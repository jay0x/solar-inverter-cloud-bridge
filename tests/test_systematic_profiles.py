"""Independent primary-document specimens and executable protocol boundaries."""

import asyncio
from pathlib import Path
import re
import tempfile
import unittest
import uuid

from custom_components.solar_inverter_bridge.core.ascii_settings import prepare
from custom_components.solar_inverter_bridge.core.ascii_telemetry import decode_group
from custom_components.solar_inverter_bridge.core.catalogue import MAPS, decode_map
from custom_components.solar_inverter_bridge.core.drivers import snapshot, fields_for, settings, ascii_exchange
from custom_components.solar_inverter_bridge.core.exchange import response_frame
from custom_components.solar_inverter_bridge.core.framing import crc16
from custom_components.solar_inverter_bridge.core.parameters import Parameter, encode_value, decode_observed, merge_masked_value
from custom_components.solar_inverter_bridge.core.profile_catalog import catalogue_view
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage
from custom_components.solar_inverter_bridge.core.transport import ATTransport
from custom_components.solar_inverter_bridge.core.compatibility import CompatibilityCapture, package_report, validate_package, replay
from test_profiles import SPECIMENS, ascii_reply


PI30_LIVE="230.0 50.0 230.0 50.0 5000 1200 24 400 48.0 10 60 30 6 250 48.0 0 00000000 0 0 1500 000"
PI18_LIVE="2300,500,2300,500,5000,1200,24,480,480,480,0,10,60,30,31,32,1500,0,2500,0,0,0,0,1,0,0,0,0"
G_LIVE="0 4 0 0 0 230 50 230 50 230 50 5 48 10 24 5000 1200 60 250 6 1500 30"


class AsciiPeer:
    """Synthetic peer with source-literal command forms, not production codecs."""
    def __init__(self, profile):
        self.profile=profile;self.family="pi30" if profile=="pi30_max" else profile
        self.reader=asyncio.StreamReader();self.closed=False;self.sent=[];self.writes=[]
        self.ignore_write=False;self.change_companion=False
        self.flags={c:False for c in ("ABCDEFGH" if profile=="pi18" else "ABJKUVXYZ")}
        self.g={"CHGC???":"050","GCC???":"020","CST??":"00","TCCV????":"56.0","TCFV????":"54.0"}
        self.piri=["0"]*28
        if self.family=="pi18":
            self.piri[:25]="2300,100,2300,500,200,5000,5000,480,460,520,440,560,540,0,20,60,1,0,1,1,0,0,0,0,2".split(",")
        else:
            self.piri[:23]="230.0 10.0 230.0 50.0 20.0 5000 5000 48.0 46.0 44.0 56.0 54.0 0 20 60 1 0 2 1 0 0 0 52.0".split()

    def write(self,data):
        command=data[:-(1 if self.family=="g_ascii" else 3)].decode("ascii")
        self.sent.append(command)
        queries={"QPI":"PI30","^P005PI":"18","QPIGS":PI30_LIVE,"^P005GS":PI18_LIVE,
                 "QMOD":"L","^P006MOD":"03","GPDAT0":G_LIVE,"GMOD":"L",
                 "QET":"00123456","QLT":"00001234","^P005ET":"1234",
                 "QT":"20261107120102","^P004T":"20261107120102",
                 "QED20261107":"1500","QLD20261107":"2300","^P013ED20261107":"1500",
                 "QPIGS2":"3.2 250.0 700","QPIWS":"0"*32,"^P005FWS":"00,"+",".join(["0"]*17)}
        if command in ("QPIRI","^P007PIRI"):
            text=("," if self.family=="pi18" else " ").join(self.piri)
        elif command=="QFLAG":
            letter=(lambda c:c.lower()) if self.profile=="pi30_max" else (lambda c:c)
            text="E"+"".join(letter(c) for c,v in self.flags.items() if v)+"D"+"".join(letter(c) for c,v in self.flags.items() if not v)
        elif command=="^P007FLAG":text=",".join([str(int(v)) for v in self.flags.values()]+["0"])
        elif command in ("QMCHGCR","QMUCHGCR","^P009MCHGCR","^P010MUCHGCR"):
            text=("," if self.family=="pi18" else " ").join(["010","020","030","060","080","120"])
        elif command in self.g and self.family=="g_ascii":text=self.g[command]
        elif command in queries:text=queries[command]
        elif command.startswith(("Q","^P")) or command.endswith("?") or command in ("GPV","GBAT","GTMP","GLINE","GBUS","GOP","GINV","GWS","F","GBMS"):
            text="NAK"
        else:
            body=command[5:] if command.startswith("^S") else command
            if self.family=="pi18":
                assert command.startswith("^S") and int(command[2:5])==len(body)+3
            self.writes.append(command)
            if not self.ignore_write:
                if body.startswith("MCHGV"):
                    self.piri[11],self.piri[12]=body[5:].split(",")
                    if self.change_companion:self.piri[12]=str(int(self.piri[12])+1)
                elif body.startswith("BUCD"):self.piri[8],self.piri[9]=body[4:].split(",")
                elif re.fullmatch(r"P[ED][A-Za-z]",body):
                    if self.family=="pi30":assert body[2].islower() if self.profile=="pi30_max" else body[2].isupper()
                    if body[2]=="I" and self.family=="pi18":self.piri[20]=str(int(body[1]=="E"))
                    else:self.flags[body[2].upper()]=body[1]=="E"
                elif body.startswith("MNCHGC0"):self.piri[14]=str(int(body[7:]))
                elif body.startswith("MUCHGC"):
                    value=body[6:]
                    if self.family=="pi18":assert value.startswith("0,");value=value[2:]
                    elif self.profile=="pi30_max":assert value.startswith("0");value=value[1:]
                    self.piri[14 if self.family=="pi18" else 13]=str(int(value))
                elif body.startswith("MCHGC"):
                    value=body[5:]
                    if self.family=="pi18":assert value.startswith("0,");value=value[2:]
                    self.piri[15 if self.family=="pi18" else 14]=str(int(value))
                elif self.family=="g_ascii" and re.fullmatch(r"(?:CHGC|TCCV)\d+(?:\.\d)?",body):
                    prefix="CHGC" if body.startswith("CHGC") else "TCCV"
                    self.g[prefix+("???" if prefix=="CHGC" else "????")]=body[len(prefix):]
                else:raise AssertionError("Unmodeled setting: "+body)
            text="ACK"
        if self.family=="pi18" and text in ("ACK","NAK"):
            reply=b"^1\x0b\xc2\r" if text=="ACK" else b"^0\x1b\xe3\r"
        else:reply=ascii_reply(text,self.family)
        self.reader.feed_data(reply[:3]);self.reader.feed_data(reply[3:])

    async def drain(self):pass
    def close(self):self.closed=True
    async def wait_closed(self):pass
    def is_closing(self):return self.closed


class SystematicMapTests(unittest.TestCase):
    def test_word_order_offset_and_decimal_must_counter(self):
        deye=decode_map(MAPS["deye_lv"],SPECIMENS["deye_lv"]|{72:0x1234,73:1,90:1250})
        self.assertEqual(deye["battery_charge_energy_total"]["value"],7019.6)
        self.assertEqual(deye["transformer_temperature"]["value"],25)
        must=decode_map(MAPS["must_pv_ph18"],SPECIMENS["must_pv_ph18"]|{15217:2,15218:1234,15219:17})
        self.assertEqual(must["pv_energy_total"]["value"],2123.4)
        self.assertEqual(must["pv_operating_days"]["value"],17)
        absent=decode_map(MAPS["must_pv_ph18"],SPECIMENS["must_pv_ph18"]|{15217:2,15218:65535})
        self.assertNotIn("pv_energy_total",absent)
        self.assertNotIn("transformer_temperature",decode_map(MAPS["deye_lv"],SPECIMENS["deye_lv"]|{90:0}))

    def test_srne_primary_types_sign_and_12v_setting_dimension(self):
        values=decode_map(MAPS["srne_modbus"],SPECIMENS["srne_modbus"]|{265:40000,258:65436})
        self.assertEqual(values["pv1_power"]["value"],40000)
        self.assertEqual(values["battery_current"]["value"],-10)
        self.assertEqual(values["battery_charging_current"]["value"],10)
        field=next(f for f in fields_for("srne_modbus") if f.key=="bulk_charging_voltage_per_12v")
        self.assertEqual(encode_value(field,14.4),(144,))
        with self.assertRaisesRegex(ValueError,"documented_bounds"):encode_value(field,57.6)
        self.assertEqual(encode_value(Parameter("other",605,"Unrelated writable register"),7),(7,))

    def test_mask_projection_preserves_unrelated_bits_and_full_catalogs(self):
        fields={f.key:f for f in fields_for("deye_3ph_high_80kw")}
        self.assertEqual(len(fields),118)
        field=fields["passive_grid_power_balance"]
        self.assertEqual(decode_observed({141:0xA5AA},(field,))[field.key],"disabled")
        self.assertEqual(merge_masked_value(field,encode_value(field,"enabled"),0xA5AA),(0xA5AE,))
        self.assertEqual(len(fields_for("must_pv_ph18")),27)
        self.assertEqual(len(fields_for("growatt_spf")),7)
        rows=catalogue_view();self.assertEqual(len(rows),24)
        self.assertNotIn("must_pv3300",{r["profile_id"] for r in rows})
        self.assertIn("pi30_max",{r["profile_id"] for r in rows})

    def test_primary_ascii_energy_units_and_pv2_layout(self):
        self.assertEqual(decode_group("pi30_max","QET","123456")["pv_energy_total"]["value"],123.456)
        self.assertEqual(decode_group("pi30_max","QLT","123456")["load_energy_total"]["value"],123.456)
        self.assertEqual(decode_group("pi18","^P005ET","1234")["pv_energy_total"]["value"],1234)
        self.assertEqual(decode_group("pi18","^P013ED20261107","1500")["pv_energy_today"]["value"],1.5)
        with self.assertRaisesRegex(ValueError,"layout_mismatch"):decode_group("pi30_max","QPIGS2","230 50 230 100 90 10 0")

    def test_pi18_pair_and_date_validation(self):
        from custom_components.solar_inverter_bridge.core.ascii_telemetry import dated_queries
        from custom_components.solar_inverter_bridge.core.drivers import identify_ascii_request,ascii_request
        plan=prepare("pi18",9111,(0,),{9110:460,9199:480})
        self.assertEqual(plan["command"],"^S014BUCD460,000")
        with self.assertRaisesRegex(ValueError,"unsupported_setting_choice"):
            prepare("pi18",9110,(461,),{9111:520,9199:480})
        with self.assertRaisesRegex(ValueError,"dependent_parameter_not_observed"):
            prepare("pi18",9107,(560,),{9199:480})
        self.assertEqual(dated_queries("pi30_max","20261107120102"),("QED20261107","QLD20261107"))
        with self.assertRaisesRegex(ValueError,"invalid_inverter_clock"):dated_queries("pi18","20260230120000")
        self.assertEqual(identify_ascii_request("pi18",ascii_request("^P005PI","pi18")),("^P005PI",False))


class ModbusPeer:
    def __init__(self,profile):
        self.reader=asyncio.StreamReader();self.closed=False;self.sent=[];self.writes=[]
        self.registers=dict(SPECIMENS[profile]);self.registers[141]=0xA5AA
        self.change_other_bits=False;self.reject_optional=False;self.corrupt=False

    def write(self,data):
        assert crc16(data[:-2])==int.from_bytes(data[-2:],"little")
        function=data[1];address=int.from_bytes(data[2:4],"big");count=int.from_bytes(data[4:6],"big")
        self.sent.append((function,address,count))
        if function in (3,4):
            if self.reject_optional and (address,count) in MAPS["deye_3ph_high_80kw"].optional_blocks:
                body=bytes((data[0],function|128,2));reply=body+crc16(body).to_bytes(2,"little")
                if self.corrupt:reply=reply[:-1]+bytes([reply[-1]^1])
            else:
                body=bytes((data[0],function,2*count))+b"".join(self.registers.get(address+i,0).to_bytes(2,"big") for i in range(count))
                reply=body+crc16(body).to_bytes(2,"little")
        elif function==16:
            words=tuple(int.from_bytes(data[7+i*2:9+i*2],"big") for i in range(count))
            self.writes.append((address,words));self.registers.update({address+i:w for i,w in enumerate(words)})
            if self.change_other_bits:self.registers[address]^=0x8000
            body=data[:6];reply=body+crc16(body).to_bytes(2,"little")
        else:raise AssertionError("Unexpected function")
        self.reader.feed_data(reply)

    async def drain(self):pass
    def close(self):self.closed=True
    async def wait_closed(self):pass
    def is_closing(self):return self.closed


class AsciiExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def setup_profile(self,profile,peer=None):
        self.tmp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.tmp.name)/"db")
        self.peer=peer or AsciiPeer(profile);self.service=CollectorService([],self.store)
        self.capture=CompatibilityCapture();self.capture.start();self.capture.emit("dialect_selected",session="fixture",dialect="at")
        self.adapter=ATTransport(self.peer.reader,self.peer,lambda kind,**data:self.capture.emit(kind,session="fixture",**data))
        self.adapter.minimum_gap=0;self.adapter.slave=MAPS[profile].slave
        evidence=await snapshot(self.adapter,self.peer,profile)
        self.device=self.store.enroll("fixture-pn","ASCII fixture",profile)
        self.store.accept_profile(self.device,{"profile_id":profile,"binding":evidence["binding"],"fingerprint":evidence["fingerprint"]})
        self.service.connections["fixture-pn"]={"reader":self.adapter,"writer":self.peer,"identity_sha256":"fixture-pn","dialect":"at",
            "closed":asyncio.Event(),"lock":asyncio.Lock(),"profile_verified":True,"capabilities":self.adapter.capabilities,
            "emit":lambda kind,**data:self.capture.emit(kind,session="fixture",**data)}
        await self.service._bind_holder_route(self.device,self.service.connections["fixture-pn"])

    async def asyncTearDown(self):
        if hasattr(self,"service"):await self.service.close();self.store.close();self.tmp.cleanup()

    async def test_pi18_compound_command_preserves_companion_and_requires_readback(self):
        await self.setup_profile("pi18")
        result=await self.service.apply(self.device,"float_charging_voltage",54.5,str(uuid.uuid4()),expected_value=54)
        self.assertEqual(result["outcome"],"confirmed")
        self.assertEqual(self.peer.writes,["^S015MCHGV560,545"])
        record=self.store.recent_operations(self.device)[0]
        full=self.store.operation(record["operation_id"])
        self.assertEqual(full["write_plan"]["expected"],{"9108":545,"9107":560,"9199":480})
        self.assertEqual(self.peer.sent[-1],"^P007PIRI")
        self.peer.change_companion=True
        operation=str(uuid.uuid4())
        result=await self.service.apply(self.device,"bulk_charging_voltage",56.4,operation)
        self.assertTrue(result["unresolved"])
        before=len(self.peer.writes)
        await self.service.apply(self.device,"bulk_charging_voltage",56.4,operation)
        self.assertEqual(len(self.peer.writes),before)
        self.assertEqual(await self.service.reconcile(self.device),[])
        self.peer.piri[12]="545"
        self.assertEqual(await self.service.reconcile(self.device),[operation])
        self.assertEqual(len(self.peer.writes),before)

    async def test_pi18_current_choices_and_parallel_target_are_not_guessed(self):
        await self.setup_profile("pi18")
        result=await self.service.apply(self.device,"maximum_charging_current",30,str(uuid.uuid4()))
        self.assertEqual(result["outcome"],"confirmed")
        self.assertEqual(self.peer.writes,["^S013MCHGC0,030"])
        with self.assertRaisesRegex(ValueError,"unsupported_setting_choice"):
            await self.service.apply(self.device,"maximum_charging_current",35,str(uuid.uuid4()))
        self.peer.piri[22]="1"
        with self.assertRaisesRegex(ValueError,"parameter_not_observed"):
            await self.service.apply(self.device,"maximum_charging_current",60,str(uuid.uuid4()))
        self.assertEqual(len(self.peer.writes),1)

    async def test_pi30_max_has_lowercase_flags_indexed_currents_and_wh_energy(self):
        await self.setup_profile("pi30_max")
        for key,value,command in (("buzzer_mode","enabled","PEa"),("maximum_charging_current",30,"MNCHGC0030"),
                                  ("maximum_ac_charging_current",120,"MUCHGC0120")):
            result=await self.service.apply(self.device,key,value,str(uuid.uuid4()))
            self.assertEqual(result["outcome"],"confirmed");self.assertEqual(self.peer.writes[-1],command)
        await self.service.poll_once(self.device)
        values=self.service.observations[self.device].values
        self.assertEqual(values["pv_energy_total"]["value"],123.456)
        self.assertEqual(values["pv2_charging_power"]["value"],700)
        self.assertEqual(values["load_energy_today"]["value"],2.3)
        result=replay(validate_package(package_report(self.capture.snapshot([],raw=True))[0]))
        self.assertEqual(result["profile_decodes"][-1]["values"]["pv_energy_total"]["value"],123.456)

    async def test_g_ascii_exact_plain_commands_and_independent_decimal_readback(self):
        await self.setup_profile("g_ascii")
        for key,value,command in (("maximum_charging_current",60,"CHGC060"),("bulk_charging_voltage",56.4,"TCCV56.4")):
            result=await self.service.apply(self.device,key,value,str(uuid.uuid4()))
            self.assertEqual(result["outcome"],"confirmed");self.assertEqual(self.peer.writes[-1],command)
        self.peer.ignore_write=True
        result=await self.service.apply(self.device,"maximum_charging_current",80,str(uuid.uuid4()))
        self.assertEqual(result["outcome"],"readback_mismatch")
        self.assertTrue(result["unresolved"])

    async def test_pi30_standard_flags_are_uppercase_without_case_retry(self):
        await self.setup_profile("pi30")
        result=await self.service.apply(self.device,"buzzer_mode","enabled",str(uuid.uuid4()))
        self.assertEqual(result["outcome"],"confirmed");self.assertEqual(self.peer.writes,["PEA"])
        with self.assertRaisesRegex(ValueError,"unreviewed_ascii_write"):
            await ascii_exchange(self.adapter,"PEa","pi30",write=True)
        self.assertEqual(self.peer.writes,["PEA"])

    async def test_masked_write_persists_full_word_and_reconciles_without_resending(self):
        profile="deye_3ph_high_80kw"
        await self.setup_profile(profile,ModbusPeer(profile))
        result=await self.service.apply(self.device,"passive_grid_power_balance","enabled","masked")
        self.assertEqual(result["outcome"],"confirmed")
        self.assertEqual(self.peer.writes,[(141,(0xA5AE,))])
        self.assertEqual(self.store.operation("masked")["planned_words"],[0xA5AE])
        self.peer.change_other_bits=True
        result=await self.service.apply(self.device,"passive_grid_power_balance","disabled","masked-uncertain")
        self.assertEqual(result["outcome"],"readback_mismatch")
        self.assertEqual(await self.service.reconcile(self.device),[])
        self.peer.registers[141]=0xA5AA
        self.assertEqual(await self.service.reconcile(self.device),["masked-uncertain"])
        await self.service.apply(self.device,"passive_grid_power_balance","disabled","masked-uncertain")
        self.assertEqual(len(self.peer.writes),2)

    async def test_optional_modbus_rejection_is_absence_but_crc_is_failure(self):
        profile="deye_3ph_high_80kw"
        await self.setup_profile(profile,ModbusPeer(profile))
        self.peer.reject_optional=True;self.adapter.origin="normal_poll"
        result=await snapshot(self.adapter,self.peer,profile)
        self.assertNotIn("pv_energy_total",result["values"])
        self.assertIn("battery_voltage",result["values"])
        self.assertTrue(all(count<=32 for fn,_,count in self.peer.sent if fn in (3,4)))
        self.peer.corrupt=True
        with self.assertRaisesRegex(ValueError,"crc_mismatch"):
            await snapshot(self.adapter,self.peer,profile)
