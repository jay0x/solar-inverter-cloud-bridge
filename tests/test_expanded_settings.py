"""Source-specific enums, scale-preserving PI30 writes and missing readbacks."""

import asyncio
import unittest

from custom_components.solar_inverter_bridge.core.drivers import fields_for, settings, write_ascii_setting
from custom_components.solar_inverter_bridge.core.parameters import encode_value, decode_observed
from custom_components.solar_inverter_bridge.core.transport import ATTransport
from test_profiles import ascii_reply


class ExpandedSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_crc_and_queued_exception_tail_are_not_silently_skipped(self):
        from custom_components.solar_inverter_bridge.core.exchange import response_frame
        from custom_components.solar_inverter_bridge.core.framing import crc16
        for corrupt in (True,False):
            reader=asyncio.StreamReader();requests=[]
            class Writer:
                def write(self,data):
                    requests.append(data)
                    body=b"\x04\x83\x02"
                    frame=body+crc16(body).to_bytes(2,"little")
                    reader.feed_data(frame[:-1]+bytes([frame[-1]^1]) if corrupt else frame+response_frame((1,),4))
                async def drain(self):pass
            writer=Writer();adapter=ATTransport(reader,writer,lambda *a,**k:None)
            adapter.profile_id="must_pv_ph18";adapter.slave=4;adapter.raw_session_identified=True
            with self.assertRaisesRegex(ValueError,"crc_mismatch" if corrupt else "unsolicited_data_before_request"):
                await settings(adapter,writer)
            self.assertEqual(len(requests),1)

    def test_low_smg_model_enums_and_voltage_grade_are_not_inherited_blindly(self):
        field=lambda profile,key:next(f for f in fields_for(profile) if f.key==key)
        self.assertEqual(encode_value(field("smg_legacy","primary_output_priority"),"utility_first"),(0,))
        self.assertEqual(encode_value(field("smg_2","primary_output_priority"),"zec_requires_ct"),(4,))
        with self.assertRaises(ValueError):encode_value(field("smg_2","primary_output_priority"),"utility_first")
        with self.assertRaises(ValueError):encode_value(field("smg_11","primary_charging_priority"),"utility_first")
        self.assertEqual(encode_value(field("smg_11","bulk_charging_voltage"),27.6),(276,))
        self.assertEqual(encode_value(field("must_pv3300","maximum_ac_charging_current"),12.5),(125,))
        with self.assertRaises(ValueError):encode_value(field("must_pv3300","maximum_ac_charging_current"),80.1)
        self.assertNotIn(1,field("must_pv3300","primary_charging_priority").options)

    async def test_pi30_voltage_command_encoding_and_decimal_readback(self):
        from custom_components.solar_inverter_bridge.core.drivers import crc_ascii
        reader=asyncio.StreamReader();sent=[]
        class Writer:
            def write(self,data):
                sent.append(data)
                body=data[:-3]
                if body==b"QPIRI":
                    parts=["0"]*23
                    parts[8:12]=["46.1","44.2","56.3","54.4"]
                    parts[15:18]=["1","2","3"];parts[22]="51.5"
                    reader.feed_data(ascii_reply(" ".join(parts),"pi30"))
                elif body in (b"QFLAG",b"QMCHGCR",b"QMUCHGCR"):
                    reader.feed_data(ascii_reply("NAK","pi30"))
                else:
                    self_test.assertEqual(data[-3:-1],crc_ascii(body,"pi30"))
                    reader.feed_data(ascii_reply("ACK","pi30"))
            async def drain(self):pass
        self_test=self
        writer=Writer();adapter=ATTransport(reader,writer,lambda *a,**k:None)
        adapter.profile_id="pi30";adapter.write_authorized=True
        raw=await settings(adapter,writer)
        observed=decode_observed(raw,fields_for("pi30"))
        self.assertEqual(observed["bulk_charging_voltage"],56.3)
        self.assertEqual(observed["battery_return_voltage"],51.5)
        for slot,value,body in ((9003,461,b"PBCV46.1"),(9004,442,b"PSDV44.2"),(9005,563,b"PCVV56.3"),(9006,544,b"PBFT54.4"),(9007,515,b"PBDV51.5")):
            await write_ascii_setting(adapter,slot,(value,))
            self.assertEqual(sent[-1][:-3],body)
        adapter.write_authorized=False
        with self.assertRaises(ValueError):await write_ascii_setting(adapter,9005,(560,))
        self.assertEqual(len(sent),9)
