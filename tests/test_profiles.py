"""Independent protocol examples and explicit candidate/control acceptance tests."""

import asyncio
import binascii
from hashlib import sha256
from pathlib import Path
import struct
import tempfile
from time import monotonic
import unittest
import uuid

from custom_components.solar_inverter_bridge.core.catalogue import MAPS, decode_map, descriptors
from custom_components.solar_inverter_bridge.core.drivers import fields_for, parse_ascii, snapshot
from custom_components.solar_inverter_bridge.core.discovery import new_search
from custom_components.solar_inverter_bridge.core.exchange import response_frame
from custom_components.solar_inverter_bridge.core.framing import crc16, read_request, parse_read
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage
from custom_components.solar_inverter_bridge.core.transport import ATTransport


# Explicit register specimens, independently transcribed from the pinned schema
# facts. Synthetic operating values, not copied hardware captures.
SPECIMENS = {
 "smg_legacy":{202:2300,203:5000,210:2300,212:5000,213:1200,215:480,219:2500,223:1600,225:20,227:30,229:60,232:65526},
 "smg_1":{202:2300,203:5000,210:2300,212:5000,213:1200,215:480,219:2500,223:1600,225:20,227:30,229:60,232:65526},
 "smg_2":{202:2300,203:5000,210:2300,212:5000,213:1200,215:480,219:2500,223:1600,225:20,227:30,229:60,232:65526},
 "smg_11":{202:2300,203:5000,210:2300,212:5000,213:1200,215:480,219:2500,223:1600,225:20,227:30,229:60,232:65526},
 "smg_3":{203:5000,231:30,253:5000,277:480,280:60,302:1600,338:2300,346:2300,351:2500,353:1600,348:1200,350:20},
 "smg_4":{203:5000,231:30,253:5000,277:480,280:60,302:1600,338:2300,346:2300,351:2500,353:1600,254:1200,256:20},
 "smg_5":{203:5000,231:30,253:5000,277:480,280:60,302:1600,338:2300,346:2300,351:2500,353:1600,348:1200,350:20},
 "smg_6":{203:5000,231:30,253:5000,277:480,280:60,302:1600,338:2300,346:2300,351:2500,353:1600,254:1200,256:20},
 "must_pv_ph18":{15205:2500,15208:1600,25205:480,25206:2300,25207:2300,25210:50,25215:1200,25216:2000,25225:5000,25226:5000,25233:30},
 "srne_modbus":{256:60,257:480,258:65526,263:2500,265:1600,531:2300,533:5000,534:2300,536:5000,539:1200,543:20},
 "growatt_spf":{3:0,4:16000,9:0,10:12000,17:4800,18:60,20:2300,21:5000,22:2300,23:5000,25:300,27:200},
 "deye_lv":{79:5000,150:2300,154:2300,178:1200,183:4800,184:60,186:1600,191:65436,192:5000},
 "sumry_ges_7530":{30000:480,30001:65526,30002:60,30024:2300,30025:50,30026:5000,30058:2300,30059:50,30060:5000},
 "aohai_fsa":{2:2300,10:300,42:2300,51:5000,127:480,128:60,141:65436},
 "solis_esinv":{33073:2300,33093:300,33094:5000,33133:480,33134:65526,33139:60},
 "deye_3ph_high_80kw":{587:4800,588:60,590:1200,598:2300,599:2300,600:2300,609:5000,625:1200,644:2300,645:2300,646:2300,655:5000,672:1600,673:0,676:2500,678:0},
 "hopewind_0237":{40500:2500,40501:0,40532:4000,40533:4000,40534:4000,40538:5000,40544:300},
 "smartess_0912":{0:1200,1:480,2:65526,3:6000,53:2300,54:2300,55:2300,59:5000,83:2300,89:5000},
 "smartess_0921":{36:2300,37:50,38:5000,43:2300,44:50,50:5000,54:2500,55:60,65:480,66:10},
}
for key in ("smg_legacy","smg_1","smg_2","smg_3","smg_4","smg_5","smg_6","smg_11"):
    SPECIMENS[key][201]=2
SPECIMENS["smg_4"]={a:0 for start,count in ((201,7),(227,5),(252,5),(277,5),(302,4),(338,16),(384,8),(702,3)) for a in range(start,start+count)}|SPECIMENS["smg_4"]
SPECIMENS["must_pv3300"]=SPECIMENS["must_pv_ph18"]|{20000:0x5056,20001:3300,25216:20}
SPECIMENS["must_pv3900"]=SPECIMENS["must_pv_ph18"]|{20000:0x5056,20001:3900}


class MapTests(unittest.TestCase):
    def test_all_maps_have_independent_measurements_and_no_placeholder_entities(self):
        self.assertEqual(len(MAPS),26)
        for key,registers in SPECIMENS.items():
            with self.subTest(profile=key):
                values=decode_map(MAPS[key],registers)
                self.assertEqual(values["grid_frequency"]["value"],50)
                if key!="hopewind_0237":self.assertEqual(values["battery_voltage"]["value"],48)
                self.assertTrue(set(values)<={d["key"] for d in descriptors(key)})
                for field in MAPS[key].fields:
                    if field.optional and any(a not in registers for a in range(field.address,field.address+field.words)):
                        self.assertNotIn(field.key,values)
                if key!="smg_4":self.assertNotIn("pv_energy_total",values)
                with self.assertRaises(ValueError):decode_map(MAPS[key],dict.fromkeys(registers,0))
        self.assertEqual(decode_map(MAPS["srne_modbus"],SPECIMENS["srne_modbus"])["battery_current"]["value"],-1)
        self.assertEqual(decode_map(MAPS["growatt_spf"],SPECIMENS["growatt_spf"])["output_power"]["value"],1200)

    def test_input_register_function_is_not_confused_with_outer_fc4(self):
        request=read_request(17,1,1,function=4)
        self.assertEqual(request[:6],bytes.fromhex("010400110001"))
        body=bytes.fromhex("01040212c0")
        reply=body+crc16(body).to_bytes(2,"little")
        self.assertEqual(parse_read(reply,1,function=4)[0],(4800,))
        with self.assertRaises(ValueError):parse_read(reply,1,function=3)


def ascii_reply(text,family):
    if family=="g_ascii":return b"("+text.encode()+b"\r"
    body=("("+text).encode() if family=="pi30" else f"^D{len(text)+3:03d}{text}".encode()
    checksum=binascii.crc_hqx(body,0).to_bytes(2,"big")
    if family=="pi30":checksum=bytes(x+1 if x in (13,10,40) else x for x in checksum)
    return body+checksum+b"\r"


class AsciiTests(unittest.IsolatedAsyncioTestCase):
    async def test_pi30_control_uses_crc_ack_and_independent_qpiri_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            storage=Storage(Path(directory)/"db")
            service=CollectorService([],storage)
            reader=asyncio.StreamReader()
            priority=[0];writes=[];commands=[]
            live="230 50 230 50 1500 1200 20 400 48 10 60 30 6 250 48 0 00000000"
            class Writer:
                closed=False
                def write(self,data):
                    body=data[:-3];command=body.decode();commands.append(command)
                    checksum=binascii.crc_hqx(body,0).to_bytes(2,"big")
                    checksum=bytes(x+1 if x in (10,13,40) else x for x in checksum)
                    if checksum!=data[-3:-1]:raise AssertionError("wrong request CRC")
                    if command=="QPIGS":text=live
                    elif command=="QPI":text="PI30"
                    elif command=="QMOD":text="L"
                    elif command in ("QFLAG","QMCHGCR","QMUCHGCR"):text="NAK"
                    elif command=="QPIRI":
                        fields=["0"]*21;fields[16]=str(priority[0]);fields[17]="2";fields[15]="1";text=" ".join(fields)
                    elif command.startswith("POP"):
                        writes.append(command);priority[0]=int(command[3:]);text="ACK"
                    else:raise AssertionError(command)
                    reader.feed_data(ascii_reply(text,"pi30"))
                async def drain(self):pass
                def is_closing(self):return self.closed
                def close(self):self.closed=True
            writer=Writer();adapter=ATTransport(reader,writer,lambda *a,**k:None);adapter.slave=0
            evidence=await snapshot(adapter,writer,"pi30")
            device=storage.enroll("ascii-pn","ASCII","pi30")
            storage.accept_profile(device,{"profile_id":"pi30","fingerprint":evidence["fingerprint"],"binding":evidence["binding"],"allow_control":True})
            storage.bind_route(device,{"transport":"at","outer_code":None,"outer_address":None,"inner_slave":0})
            storage.set_mode(device,"advanced")
            service.connections["ascii-pn"]={"reader":adapter,"writer":writer,"identity_sha256":"ascii-pn","dialect":"at","closed":asyncio.Event(),"lock":asyncio.Lock(),"profile_verified":True,"capabilities":adapter.capabilities}
            try:
                result=await service.apply(device,"primary_output_priority","solar_first",str(uuid.uuid4()),expected_value="utility_first")
                self.assertEqual(result["outcome"],"confirmed")
                self.assertEqual(writes,["POP01"])
                self.assertEqual(commands[-2:],["POP01","QPIRI"])
                self.assertEqual(service.settings[device]["primary_output_priority"],"solar_first")
                with self.assertRaises(ValueError):await service.apply(device,"primary_output_priority","POP99\r",str(uuid.uuid4()))
                self.assertEqual(len(writes),1)
            finally:
                await service.close();storage.close()

    async def test_must_single_register_write_checks_exact_echo(self):
        from custom_components.solar_inverter_bridge.core.exchange import write_words
        from custom_components.solar_inverter_bridge.core.framing import write_request
        reader=asyncio.StreamReader()
        class Writer:
            def write(self,data):
                self.last=data
                reader.feed_data(data)
            async def drain(self):pass
        writer=Writer();adapter=ATTransport(reader,writer,lambda *a,**k:None)
        adapter.profile_id="must_pv_ph18";adapter.slave=4
        await write_words(adapter,writer,20104,(1,))
        self.assertEqual(writer.last[:6],bytes.fromhex("04064e880001"))
        # Wrong value with a valid checksum cannot be accepted as an ACK.
        def wrong(data):reader.feed_data(write_request(20104,(0,),4,6))
        writer.write=wrong
        with self.assertRaisesRegex(ValueError,"wrong_ack_route"):
            await write_words(adapter,writer,20104,(1,))

    async def test_three_ascii_families_with_fragmented_streams_and_checksums(self):
        samples={"pi30":"230.0 50.0 230.0 50.0 1500 1200 20 400 48.0 10 60 30 6 250 48.0 0 00000000 0 0 1500 000",
                 "pi18":"2300,500,2300,500,1500,1200,20,480,480,480,0,10,60,30,30,30,1600,0,2500,0,0,0,0,0,0,0,0,0",
                 "g_ascii":"0 4 0 0 0 230 50 230 50 230 50 5 48 10 20 1500 1200 60 250 6 1600 30"}
        for family,text in samples.items():
            from custom_components.solar_inverter_bridge.core.compatibility import CompatibilityCapture,package_report,validate_package,replay
            capture=CompatibilityCapture();capture.start();capture.emit("dialect_selected",session="synthetic-at",dialect="at")
            reader=asyncio.StreamReader()
            class Writer:
                def write(self,data):
                    if data[:-3] in (b"QPI",b"^P005PI"):
                        value="18" if family=="pi18" else "PI30"
                    else:value=("02" if family=="pi18" else "L") if (b"MOD" in data) else text
                    response=ascii_reply(value,family)
                    reader.feed_data(response[:4]);reader.feed_data(response[4:])
                async def drain(self):pass
                def is_closing(self):return False
            writer=Writer();adapter=ATTransport(reader,writer,lambda kind,**fields:capture.emit(kind,session="synthetic-at",**fields))
            result=await snapshot(adapter,writer,family)
            self.assertEqual(result["values"]["battery_voltage"]["value"],48)
            self.assertEqual(result["values"]["output_power"]["value"],1200)
            report=replay(validate_package(package_report(capture.snapshot([],raw=True))[0]))
            self.assertEqual(report["profile_decodes"][-1]["values"]["battery_voltage"]["value"],48)
            self.assertEqual(report["profile_decodes"][-1]["evidence"],"original_ordered_at_ascii")
            if family!="g_ascii":
                corrupt=bytearray(ascii_reply(text,family));corrupt[-2]^=1
                with self.assertRaises(ValueError):parse_ascii(bytes(corrupt),family)


class ProfileWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.storage=Storage(Path(self.tmp.name)/"bridge.sqlite3")
        self.service=CollectorService(["127.0.0.1"],self.storage,bootstrap_preference="binary")
        self.port=(await self.service.start())[0][1]
        self.writes=[];self.reads=[];self.lose_ack=False
        self.regs=SPECIMENS["smg_4"]|{184:4,171:33793,678:1,679:0,680:1,681:0,682:1,683:1,684:0}
        self.client=asyncio.create_task(self.collector())
        async with asyncio.timeout(3):
            while not self.service.candidates:await asyncio.sleep(.01)
        self.key=next(iter(self.service.candidates))

    async def asyncTearDown(self):
        await self.service.close();self.client.cancel()
        await asyncio.gather(self.client,return_exceptions=True)
        self.storage.close();self.tmp.cleanup()

    async def collector(self):
        reader,writer=await asyncio.open_connection("127.0.0.1",self.port)
        try:
            while True:
                h=await reader.readexactly(8)
                tid,code,length,addr,fc=struct.unpack(">HHHBB",h)
                data=await reader.readexactly(length-2)
                if fc==4 and getattr(self,"stall",None) is not None:
                    await self.stall.wait()
                if fc==1:reply=b""
                elif fc==2:
                    reply=b"\x00\x02SYNTHETIC-PROFILE" if data==b"\x02" else b"\x00\x0e"+self.descriptor if data==b"\x0e" and hasattr(self,"descriptor") else b"\x01"+data
                elif data[1] in (3,4):
                    address,count=struct.unpack(">HH",data[2:6])
                    self.reads.append((data[0],data[1],address,count))
                    registers=getattr(self,"input_regs",self.regs) if data[1]==4 else self.regs
                    unsupported=bool(set(range(address,address+count)) & getattr(self,"unsupported",set()))
                    if unsupported:
                        body=bytes([data[0],data[1]|128,2]);reply=body+crc16(body).to_bytes(2,"little")
                    else:
                        reply=response_frame(tuple(registers.get(address+i,0) for i in range(count)),data[0])
                    if data[1]==4 and not unsupported:
                        body=reply[:1]+b"\x04"+reply[2:-2];reply=body+crc16(body).to_bytes(2,"little")
                elif data[1]==16:
                    address,count=struct.unpack(">HH",data[2:6]);words=struct.unpack('>'+str(count)+'H',data[7:-2])
                    self.writes.append((address,words));self.regs.update({address+i:w for i,w in enumerate(words)})
                    if self.lose_ack:break
                    reply=data[:6]+crc16(data[:6]).to_bytes(2,"little")
                elif data[1]==6:
                    address,value=struct.unpack(">HH",data[2:6]);self.writes.append((address,(value,)));self.regs[address]=value
                    if self.lose_ack:break
                    reply=data
                else:raise AssertionError("unexpected command")
                writer.write(struct.pack(">HHHBB",tid,code,len(reply)+2,addr,fc)+reply);await writer.drain()
        except (asyncio.IncompleteReadError,ConnectionError):pass
        finally:writer.close();await writer.wait_closed()

    async def suggest(self):
        state=new_search("binary");state["plans"]=[("smg_4",(1,1),1)]
        self.service.profile_searches[self.key]=state
        result=await self.service.discover_profiles(self.key,resume=True)
        self.assertEqual(result["state"],"candidates_available")
        return result["candidates"][0]

    async def test_smartess_0912_descriptor_prioritizes_fc04_slave4_and_replays(self):
        from custom_components.solar_inverter_bridge.core.compatibility import package_report,validate_package,replay
        self.descriptor=b"0912#1.0#"
        self.input_regs=SPECIMENS["smartess_0912"]
        self.service.compatibility.start()
        self.reads.clear()
        result=await self.service.discover_profiles(self.key)
        candidate=result["candidates"][0]
        self.assertEqual(candidate["profile_id"],"smartess_0912")
        self.assertEqual(candidate["descriptor_hint"],"0912")
        self.assertEqual(candidate["values"]["battery_voltage"]["value"],48)
        expected=[(4,4,0,4),(4,4,53,3),(4,4,59,1),(4,4,83,1),(4,4,89,1)]
        self.assertEqual(self.reads,expected*2)
        capture=self.service.compatibility.snapshot([],raw=True)
        replayed=replay(validate_package(package_report(capture)[0]))
        self.assertEqual(replayed["profile_decodes"][-1]["values"]["battery_voltage"]["value"],48)
        self.assertFalse(self.writes)

    async def test_old_common_protocol4_binding_requires_explicit_renewal(self):
        import json
        candidate=await self.suggest()
        await self.service.select_profile(self.key,candidate["fingerprint"],True)
        device=await self.service.enroll(self.key,"Existing common Protocol4")
        self.service._next_poll[device]=float("inf")
        old=self.storage.profile_acceptance(device)
        old["binding"]["definition_sha256"]="7b56af71128c89ddce4b1d6595508494788a98ea9afc96113b5d154150bd87de"
        old["fingerprint"]=sha256(json.dumps(old["binding"],sort_keys=True).encode()).hexdigest()
        self.storage.accept_profile(device,old)
        self.reads.clear()
        with self.assertRaisesRegex(ValueError,"accepted_profile_fingerprint_changed"):
            await self.service.poll_once(device)
        self.assertFalse(self.reads)
        self.assertTrue(self.service.connections[self.key]["profile_change_required"])
        await self.service.recheck_profile(device)
        async with asyncio.timeout(5):
            while not self.service.profile_searches[self.key]["candidates"]:
                await asyncio.sleep(.01)
        renewed=self.service.profile_searches[self.key]["candidates"][0]
        await self.service.select_profile(self.key,renewed["fingerprint"],True)
        self.assertEqual(self.storage.list_devices()[0]["device_id"],device)
        self.assertEqual(len(fields_for("smg_4")),51)
        self.assertFalse(self.writes)

    async def test_unknown_model_acceptance_enables_implemented_control_without_mode(self):
        self.regs[171]=45678
        candidate=await self.suggest()
        self.assertEqual(candidate["basis"],"family_shape_and_two_snapshots")
        self.assertTrue(candidate["profile_layers"]["common_only"])
        self.assertIsNone(candidate["profile_layers"]["extension"])
        self.assertEqual(candidate["profile_layers"]["model_code"],45678)
        self.assertFalse(self.service.candidates[self.key]["ready"])
        with self.assertRaisesRegex(ValueError,"acknowledgement"):
            await self.service.select_profile(self.key,candidate["fingerprint"],False)
        await self.service.select_profile(self.key,candidate["fingerprint"],True)
        device=await self.service.enroll(self.key,"Unknown inverter")
        self.service._next_poll[device]=float("inf")
        self.storage.set_mode(device,"advanced")
        await self.service.poll_once(device)
        view=(await self.service.status())["devices"][0]["profile_layers"]
        self.assertTrue(view["common_only"])
        self.assertEqual(view["evidence_state"],"observed")
        self.storage.set_collection(device,False,10)
        self.assertEqual((await self.service.status())["devices"][0]["profile_layers"]["evidence_state"],"saved")
        self.storage.set_collection(device,True,10)
        self.assertTrue(self.storage.profile_acceptance(device)["allow_control"])
        operation=str(uuid.uuid4())
        result=await self.service.apply(device,"lcd_backlight","always_on",operation,expected_value="timed_off")
        self.assertEqual(result["outcome"],"confirmed")
        self.assertEqual(self.writes,[(679,(1,))])
        await self.service.apply(device,"lcd_backlight","always_on",operation,expected_value="timed_off")
        self.assertEqual(len(self.writes),1)
        with self.assertRaisesRegex(ValueError,"control_modes_removed"):
            await self.service.set_experimental_control(device,False,candidate["fingerprint"])
        self.assertEqual(len(self.writes),1)

    async def test_standard_verification_falls_back_to_suggestions_without_enrollment(self):
        with self.assertRaisesRegex(ValueError,"unsupported_or_unconfirmed_identity"):
            await self.service.verify(self.key,discover=True)
        async with asyncio.timeout(4):
            while not self.service.profile_searches[self.key]["candidates"]:
                await asyncio.sleep(.01)
        self.assertFalse(self.storage.list_devices())
        self.assertFalse(self.service.candidates[self.key]["ready"])
        self.assertFalse(self.writes)
        self.assertTrue(self.service.compatibility.view()["active"])

    async def test_cancelled_search_retires_stream_and_preserves_no_write_guarantee(self):
        self.stall=asyncio.Event()
        self.service.schedule_profile_search(self.key,resume=False)
        async with asyncio.timeout(3):
            while self.key not in self.service.profile_searches:
                await asyncio.sleep(.01)
        await self.service.cancel_profile_search(self.key)
        self.stall.set()
        self.assertEqual(self.service.profile_searches[self.key]["state"],"cancelled")
        self.assertFalse(self.writes)

    async def test_changed_signature_refuses_selected_profile_and_no_uncertain_write_replay(self):
        candidate=await self.suggest()
        await self.service.select_profile(self.key,candidate["fingerprint"],True,True)
        device=await self.service.enroll(self.key,"Candidate")
        self.service._next_poll[device]=float("inf")
        self.storage.set_mode(device,"advanced")
        self.lose_ack=True
        operation=str(uuid.uuid4())
        with self.assertRaises(ConnectionError):
            await self.service.apply(device,"lcd_backlight","always_on",operation)
        result=await self.service.apply(device,"lcd_backlight","always_on",operation)
        self.assertTrue(result["unresolved"])
        self.assertEqual(self.writes,[(679,(1,))])

    async def test_selection_rechecks_fingerprint_instead_of_trusting_old_suggestion(self):
        candidate=await self.suggest();self.regs[171]=32768
        with self.assertRaisesRegex(ValueError,"evidence_changed"):
            await self.service.select_profile(self.key,candidate["fingerprint"],True,True)
        self.assertFalse(self.storage.list_devices());self.assertFalse(self.writes)

    async def test_growatt_input_telemetry_and_holding_controls_remain_separate(self):
        self.input_regs=SPECIMENS["growatt_spf"]
        self.regs={1:2,2:0,22:1}
        state=new_search("binary");state["plans"]=[("growatt_spf",(1,1),1)]
        self.service.profile_searches[self.key]=state
        result=await self.service.discover_profiles(self.key,resume=True)
        candidate=result["candidates"][0]
        await self.service.select_profile(self.key,candidate["fingerprint"],True,True)
        device=await self.service.enroll(self.key,"Growatt candidate")
        self.storage.set_mode(device,"advanced");self.service._next_poll[device]=float("inf")
        await self.service.poll_once(device)
        self.assertEqual(self.service.observations[device].values["output_voltage"]["value"],230)
        self.assertEqual(self.service.settings[device]["buzzer_mode"],"enabled")
        result=await self.service.apply(device,"primary_output_priority","battery_first",str(uuid.uuid4()),expected_value="utility_first")
        self.assertEqual(result["outcome"],"confirmed")
        self.assertEqual(self.writes,[(1,(0,))])
        self.assertEqual(self.input_regs[22],2300)

    async def test_must_variant_uses_marker_and_whole_percent_load(self):
        self.regs=SPECIMENS["must_pv3300"]|{20104:0}
        state=new_search("binary");state["plans"]=[("must_pv3900",(1,1),4),("must_pv3300",(1,1),4)]
        self.service.profile_searches[self.key]=state
        result=await self.service.discover_profiles(self.key,resume=True)
        self.assertEqual(len(result["candidates"]),1)
        candidate=result["candidates"][0]
        self.assertEqual(candidate["profile_id"],"must_pv3300")
        self.assertEqual(candidate["values"]["load_percent"]["value"],20)
        self.assertEqual(candidate["basis"],"source_identity_anchors_and_two_snapshots")
        self.assertEqual(candidate["profile_layers"]["extension"]["id"],"must_pv3300")
        self.regs[20001]=3900
        with self.assertRaisesRegex(ValueError,"anchor_mismatch"):
            await self.service.select_profile(self.key,candidate["fingerprint"],True)

    async def test_common_must_renewal_adds_required_variant_without_new_device_id(self):
        self.regs=SPECIMENS["must_pv_ph18"]|{20000:0x5056,20001:1800,20104:0}
        state=new_search("binary");state["plans"]=[("must_pv_ph18",(1,1),4)]
        self.service.profile_searches[self.key]=state
        candidate=(await self.service.discover_profiles(self.key,resume=True))["candidates"][0]
        self.assertTrue(candidate["profile_layers"]["common_only"])
        await self.service.select_profile(self.key,candidate["fingerprint"],True,True)
        device=await self.service.enroll(self.key,"Common MUST")
        self.service._next_poll[device]=float("inf")
        self.regs.update({20001:3300,25216:20})
        # Renew through the supported same-profile path after the identity change.
        state=new_search("binary");state["plans"]=[("must_pv_ph18",(1,1),4)];state["device_id"]=device
        self.service.profile_searches[self.key]=state
        result=await self.service.discover_profiles(self.key,resume=True)
        renewed=result["candidates"][0]
        self.assertNotEqual(renewed["fingerprint"],candidate["fingerprint"])
        self.assertEqual(renewed["values"]["load_percent"]["value"],20)
        self.assertEqual(renewed["profile_layers"]["extension"]["id"],"must_pv3300")
        self.assertEqual(renewed["basis"],"source_identity_anchors_and_two_snapshots")
        await self.service.select_profile(self.key,renewed["fingerprint"],True,False)
        self.assertEqual(self.storage.list_devices()[0]["device_id"],device)
        self.assertEqual(self.storage.device(device)["profile_id"],"must_pv_ph18")
        self.assertTrue(self.storage.profile_acceptance(device)["allow_control"])
        self.assertFalse(self.writes)
        await self.service.poll_once(device)
        self.assertEqual((await self.service.status())["devices"][0]["profile_layers"]["extension"]["id"],"must_pv3300")
        restarted=CollectorService([],self.storage)
        try:
            saved=(await restarted.status())["devices"][0]["profile_layers"]
            self.assertEqual(saved["extension"]["id"],"must_pv3300")
            self.assertEqual(saved["evidence_state"],"saved")
        finally:
            await restarted.close()

    async def test_expanded_smg_voltage_and_schedule_controls_share_executor(self):
        self.regs.update({637:540,638:520,603:700,604:2200,602:1,634:800,635:2100,633:1})
        candidate=await self.suggest()
        await self.service.select_profile(self.key,candidate["fingerprint"],True,True)
        device=await self.service.enroll(self.key,"Expanded")
        self.storage.set_mode(device,"advanced");self.service._next_poll[device]=float("inf")
        for key,value,address,words in (("bulk_charging_voltage",54.1,637,(541,)),
                                        ("secondary_output_stop","23:00:00",604,(2300,))):
            result=await self.service.apply(device,key,value,str(uuid.uuid4()))
            self.assertEqual(result["outcome"],"confirmed")
            self.assertEqual(self.writes[-1],(address,words))
        with self.assertRaisesRegex(ValueError,"ambiguous_schedule_window"):
            await self.service.apply(device,"secondary_output_start","23:30:00",str(uuid.uuid4()))
        self.assertEqual(len(self.writes),2)

    async def test_unsupported_setting_address_does_not_hide_supported_controls(self):
        self.unsupported={638}
        candidate=await self.suggest()
        await self.service.select_profile(self.key,candidate["fingerprint"],True,True)
        device=await self.service.enroll(self.key,"Partial settings")
        self.storage.set_mode(device,"advanced");self.service._next_poll[device]=float("inf")
        await self.service.poll_once(device)
        self.assertNotIn("float_charging_voltage",self.service.settings[device])
        result=await self.service.apply(device,"lcd_backlight","always_on",str(uuid.uuid4()))
        self.assertEqual(result["outcome"],"confirmed")
        with self.assertRaisesRegex(ValueError,"parameter_not_observed"):
            await self.service.apply(device,"float_charging_voltage",52.5,str(uuid.uuid4()))
        self.assertEqual(self.writes,[(679,(1,))])

    async def test_reconnect_revalidates_saved_profile_before_enabling_control(self):
        candidate=await self.suggest()
        await self.service.select_profile(self.key,candidate["fingerprint"],True,True)
        device=await self.service.enroll(self.key,"Retained inferred")
        self.storage.set_mode(device,"advanced");self.service._next_poll[device]=float("inf")
        self.client.cancel();await asyncio.gather(self.client,return_exceptions=True)
        async with asyncio.timeout(3):
            while self.key in self.service.connections:await asyncio.sleep(.01)
        self.client=asyncio.create_task(self.collector())
        async with asyncio.timeout(3):
            while self.key not in self.service.connections:await asyncio.sleep(.01)
        self.assertFalse(self.service.transport_capabilities(self.storage.device(device))["inverter_write"])
        await self.service.poll_once(device)
        self.assertTrue(self.service.transport_capabilities(self.storage.device(device))["inverter_write"])
        self.regs[171]=45678
        with self.assertRaisesRegex(ValueError,"fingerprint_changed"):
            await self.service.poll_once(device)
        self.assertFalse(self.writes)
        self.assertTrue(self.service.connections[self.key]["profile_change_required"])
        await self.service.recheck_profile(device)
        async with asyncio.timeout(4):
            while not self.service.profile_searches[self.key]["candidates"]:
                await asyncio.sleep(.01)
        renewed=self.service.profile_searches[self.key]["candidates"][0]
        self.assertNotEqual(renewed["fingerprint"],candidate["fingerprint"])
        selected=await self.service.select_profile(self.key,renewed["fingerprint"],True,True)
        self.assertEqual(selected["device_id"],device)
        self.assertEqual(len(self.storage.list_devices()),1)
        await self.service.poll_once(device)
        self.assertTrue(self.service.transport_capabilities(self.storage.device(device))["inverter_write"])
        self.assertFalse(self.writes)

    async def test_profile_report_replays_inferred_map_from_original_frames(self):
        from custom_components.solar_inverter_bridge.core.compatibility import package_report,validate_package,replay
        self.service.compatibility.start()
        self.regs[171]=45678
        candidate=await self.suggest()
        await self.service.select_profile(self.key,candidate["fingerprint"],True,True)
        self.service.compatibility.stop()
        report=self.service.compatibility.snapshot(self.service.listeners,raw=True)
        # Capture began after admission: explicitly retain the known session type,
        # as normal startup operational evidence does in a complete collection.
        holder=self.service.candidates[self.key]
        report["events"].insert(0,{"id":0,"kind":"dialect_selected","session":holder["session_ref"],"dialect":"binary"})
        result=replay(validate_package(package_report(report)[0]))
        values=[item["values"] for item in result["profile_decodes"] if item["profile_id"]=="smg_4"]
        self.assertTrue(values)
        self.assertEqual(values[-1]["battery_voltage"]["value"],48)
        self.assertIn("experimental_profile_available",{item["code"] for item in result["analysis"]["findings"]})
