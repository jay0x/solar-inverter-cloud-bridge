"""Independent synthetic 09C1 fixed-column examples, not hardware captures."""

import asyncio
from pathlib import Path
import struct
import tempfile
import unittest
import uuid

from custom_components.solar_inverter_bridge.core.catalogue import descriptors
from custom_components.solar_inverter_bridge.core.compatibility import package_report,validate_package,replay
from custom_components.solar_inverter_bridge.core.discovery import new_search
from custom_components.solar_inverter_bridge.core.drivers import snapshot,fields_for
from custom_components.solar_inverter_bridge.core.eybond_09c1 import parse_reply,decode_cycle
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage
from custom_components.solar_inverter_bridge.core.transport import ATTransport

FRAMES = {"Q1":b"(230.0 000.0 228.0 025 49.9 51.2 -5.0 00001001\r",
          "QF":b"(50.1\r", "PV?":b"(2500 032 1 123456\r", "F":b"(230.0 12K 48.00 50.0\r"}


class CodecTests(unittest.TestCase):
    def test_fixed_columns_input_and_output_frequency_and_no_invented_power(self):
        responses={key:value[1:-1].decode() for key,value in FRAMES.items()}
        values,mode,signature=decode_cycle(responses)
        self.assertEqual([len(frame) for frame in FRAMES.values()],[47,6,19,22])
        self.assertEqual(values["grid_frequency"]["value"],49.9)
        self.assertEqual(values["output_frequency"]["value"],50.1)
        self.assertEqual(values["inverter_temperature"]["value"],-5)
        self.assertEqual(values["pv_voltage"]["value"],250)
        self.assertEqual(values["pv_current"]["value"],3.2)
        self.assertEqual(values["rated_power"]["value"],12000)
        self.assertEqual(mode,"battery_energy_saving")
        self.assertEqual(signature,["eybond_09c1",47,6,19,22])
        self.assertTrue({"pv_power","output_power","battery_soc","pv_energy_total"}.isdisjoint(values))
        self.assertEqual(len(descriptors("eybond_09c1")),24)
        self.assertEqual(fields_for("eybond_09c1"),())

    def test_malformed_or_other_ascii_dialects_are_rejected(self):
        for frame in (FRAMES["Q1"]+b"\n",FRAMES["Q1"].replace(b"230.0",b"23.00"),
                      FRAMES["Q1"].replace(b"00001001",b"00002001"),b"01"+FRAMES["Q1"]+b"00",b"(NAK\r"):
            with self.assertRaisesRegex(ValueError,"09c1_reply_shape"):parse_reply("Q1",frame)
        with self.assertRaisesRegex(ValueError,"query_unsupported"):parse_reply("RESET",b"(ACK\r")


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_at_reads_and_replay_use_plain_cr_without_pi30_crc(self):
        from custom_components.solar_inverter_bridge.core.compatibility import CompatibilityCapture
        capture=CompatibilityCapture();capture.start();capture.emit("dialect_selected",session="at",dialect="at")
        reader=asyncio.StreamReader();sent=[]
        class Writer:
            def write(self,data):
                sent.append(data)
                frame=FRAMES[data[:-1].decode()]
                reader.feed_data(frame[:3]);reader.feed_data(frame[3:])
            async def drain(self): pass
        writer=Writer();adapter=ATTransport(reader,writer,lambda kind,**fields:capture.emit(kind,session="at",**fields))
        adapter.slave=0
        result=await snapshot(adapter,writer,"eybond_09c1")
        self.assertEqual(sent,[b"Q1\r",b"QF\r",b"PV?\r",b"F\r"])
        self.assertEqual(result["values"]["battery_voltage"]["value"],51.2)
        replayed=replay(validate_package(package_report(capture.snapshot([],raw=True))[0]))
        self.assertEqual(replayed["profile_decodes"][-1]["values"]["output_frequency"]["value"],50.1)

    async def test_binary_discovery_enrollment_and_monitoring_do_not_enable_unsourced_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            storage=Storage(Path(directory)/"bridge.sqlite3")
            service=CollectorService(["127.0.0.1"],storage,bootstrap_preference="binary")
            host,port=(await service.start())[0]
            seen=[]
            async def collector():
                reader,writer=await asyncio.open_connection(host,port)
                try:
                    while True:
                        header=await reader.readexactly(8)
                        tid,code,length,addr,fc=struct.unpack(">HHHBB",header)
                        payload=await reader.readexactly(length-2);seen.append((fc,payload))
                        if fc==1:reply=b""
                        elif fc==2:reply=b"\x00\x02SYNTHETIC-09C1"
                        else:
                            self.assertEqual((fc,code,addr),(4,1,255))
                            reply=FRAMES.get(payload[:-1].decode(),b"(NAK\r")
                        writer.write(struct.pack(">HHHBB",tid,code,len(reply)+2,addr,fc)+reply)
                        await writer.drain()
                except (asyncio.IncompleteReadError,ConnectionError):pass
                finally:writer.close();await writer.wait_closed()
            task=asyncio.create_task(collector())
            try:
                async with asyncio.timeout(3):
                    while not service.candidates:await asyncio.sleep(.01)
                key=next(iter(service.candidates))
                state=new_search("binary");state["plans"]=[("eybond_09c1",(1,255),0)]
                service.profile_searches[key]=state;service.compatibility.start()
                result=await service.discover_profiles(key,resume=True)
                candidate=result["candidates"][0]
                await service.select_profile(key,candidate["fingerprint"],True,True)
                device=await service.enroll(key,"09C1 candidate")
                storage.set_mode(device,"advanced");service._next_poll[device]=float("inf")
                await service.poll_once(device)
                self.assertFalse(service.transport_capabilities(storage.device(device))["inverter_write"])
                with self.assertRaises(ValueError):await service.apply(device,"remote_switch","on",str(uuid.uuid4()))
                report=replay(validate_package(package_report(service.compatibility.snapshot(service.listeners,raw=True))[0]))
                self.assertTrue(any(item["profile_id"]=="eybond_09c1" for item in report["profile_decodes"]))
                self.assertTrue(all(fc in (1,2) or payload in (b"Q1\r",b"QF\r",b"PV?\r",b"F\r",b"PV1\r",b"PV2\r") for fc,payload in seen))
            finally:
                await service.close();task.cancel();await asyncio.gather(task,return_exceptions=True);storage.close()
