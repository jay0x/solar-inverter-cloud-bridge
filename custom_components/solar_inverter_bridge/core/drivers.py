"""Profile-aware payload exchange. No arbitrary command or register write API."""

import asyncio
import binascii
from dataclasses import asdict
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from .framing import FrameError

from .catalogue import MAPS, decode_map, resolve_map, validate_measurements
from .parameters import FIELDS, Parameter
from .smg import SMG_VARIANTS
from .modbus_settings import MUST, GROWATT, SRNE, DEYE_HIGH
from .ascii_settings import SPECS as ASCII_SETTINGS

BASELINE = "modbus_protocol_4"
READ_PLANS = {"pi30": ("QPIGS", "QMOD"), "pi18": ("^P005GS", "^P006MOD"),
              "g_ascii": ("GPDAT0", "GMOD"), "eybond_09c1": ("Q1", "QF", "PV?", "F")}
# Virtual addresses are internal executor slots, never Modbus probe registers.
PI30_SETTINGS = {
    9000: (16, "POP", 1), 9001: (17, "PCP", 1), 9002: (15, "PGR", 1),
    9003: (8, "PBCV", 10), 9004: (9, "PSDV", 10),
    9005: (10, "PCVV", 10), 9006: (11, "PBFT", 10), 9007: (22, "PBDV", 10),
}


def fields_for(profile_id):
    if profile_id in (BASELINE, "smg_4"):
        return FIELDS
    if profile_id in SMG_VARIANTS:
        return SMG_VARIANTS[profile_id].controls
    if profile_id=="srne_modbus":
        return SRNE
    if profile_id in ASCII_SETTINGS:
        return tuple(spec.field for spec in ASCII_SETTINGS[profile_id])
    if profile_id in ("must_pv_ph18","must_pv3300","must_pv3900"):
        return MUST
    if profile_id == "growatt_spf":
        return GROWATT
    if profile_id == "deye_lv":
        return (Parameter("remote_switch",43,"Inverter power","select",options={0:"off",1:"on"}),
                Parameter("energy_management_mode",243,"Energy management","select",options={0:"battery_first",1:"load_first"}),
                Parameter("solar_sell",247,"Solar export","select",options={0:"disabled",1:"enabled"}),
                Parameter("grid_charge",232,"Grid charging","select",options={0:"disabled",1:"enabled"}),
                Parameter("generator_charge",231,"Generator charging","select",options={0:"disabled",1:"enabled"}),
                Parameter("export_power_limit",245,"Export power limit",unit="W"),
                Parameter("maximum_charging_current",210,"Maximum battery charging current",unit="A"),
                Parameter("maximum_discharge_current",211,"Maximum battery discharge current",unit="A"))
    if profile_id == "deye_3ph_high_80kw":
        return DEYE_HIGH
    if profile_id == "hopewind_0237":
        return (Parameter("active_power_regulation_mode",40011,"Active power regulation (uses existing setpoint)","select",options={0:"none",1:"power_value",2:"power_ratio"}),
                Parameter("active_power_regulation_ratio",40013,"Active power regulation ratio",unit="%",divisor=100,bounds=(0,100)),
                Parameter("reactive_power_regulation_mode",40002,"Reactive power regulation (uses existing setpoint)","select",options={0:"none",1:"power_factor",2:"power_value",3:"power_ratio"}))
    return ()


def write_function(profile_id):
    return 6 if profile_id in ("must_pv_ph18","must_pv3300","must_pv3900","growatt_spf","hopewind_0237") else 16


def definition_hash(profile_id, effective_profile_id=None):
    profile = MAPS[effective_profile_id or profile_id]
    definition={"map":asdict(profile),"controls":[asdict(field) for field in fields_for(profile_id)],"write_function":write_function(profile_id)}
    if profile_id in ASCII_SETTINGS:
        from .ascii_settings import definitions
        definition["ascii_settings"]=definitions(profile_id)
    if profile.payload!="modbus":
        from .ascii_telemetry import definition as telemetry_definition
        definition["ascii_telemetry"]=telemetry_definition(profile_id)
    for field in definition["map"]["fields"]:
        for key,default in (("word_order","high_first"),("offset",0),("optional",False)):
            if field.get(key)==default:
                field.pop(key,None)
    for field in definition["controls"]:
        for key,default in (("read_only",False),("mask",None),("group",None),("wire_max",65535)):
            if field.get(key)==default:
                field.pop(key,None)
    return hashlib.sha256(json.dumps(definition,sort_keys=True).encode()).hexdigest()


def crc_ascii(body, family):
    raw = binascii.crc_hqx(body,0).to_bytes(2,"big")
    return bytes(byte+1 if byte in (0x28,0x0d,0x0a) else byte for byte in raw) if family == "pi30" else raw


def ascii_request(command, family):
    body = command.encode("ascii")
    return body + (b"" if family in ("g_ascii","eybond_09c1") else crc_ascii(body,family)) + b"\r"


def identify_ascii_request(profile_id,data):
    from .ascii_settings import read_commands,command_allowed
    from .ascii_telemetry import read_command_allowed
    family=MAPS[profile_id].payload
    if family not in READ_PLANS or not data.endswith(b"\r"):return None
    try:command=data[:-1 if family in ("g_ascii","eybond_09c1") else -3].decode("ascii")
    except UnicodeDecodeError:return None
    if ascii_request(command,family)!=data:return None
    known=set(READ_PLANS[family])|read_commands(profile_id)|({"QPI"} if family=="pi30" else {"^P005PI"} if family=="pi18" else set())
    if command in known or read_command_allowed(profile_id,command):return (command,False)
    if command_allowed(profile_id,command):return (command,True)
    return None


def parse_ascii(data, family):
    if len(data) < 2 or len(data) > 1024 or not data.endswith(b"\r"):
        raise ValueError("invalid_ascii_frame")
    if family in ("g_ascii","eybond_09c1"):
        body = data[:-1]
    else:
        body = data[:-3]
        if data[-3:-1] != crc_ascii(body,family):
            raise ValueError("ascii_crc_mismatch")
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("invalid_ascii_encoding") from error
    if family == "pi18":
        if text in ("^0","^1"):
            return "ACK" if text=="^1" else "NAK"
        if not re.match(r"\^D\d{3}",text):
            raise ValueError("pi18_response_prefix")
        # PI18 length includes the two CRC bytes and final CR.
        if int(text[2:5]) != len(body)-5+3:
            raise ValueError("pi18_response_length")
        text = text[5:]
    else:
        if family == "pi30" and not text.startswith("("):
            raise ValueError("pi30_response_prefix")
        text = text.removeprefix("(")
    if text in ("NAK","NOA","ERCRC"):
        raise ValueError("ascii_query_rejected")
    return text


async def ascii_exchange(adapter, command, family, timeout=3, *, write=False, profile_id=None):
    from .transport import BinaryTransport
    from .ascii_settings import read_commands,command_allowed
    from .ascii_telemetry import read_command_allowed
    setting_profile=(getattr(adapter,"profile_id",None) or family) if write else (profile_id or getattr(adapter,"profile_id",None) or family)
    reads = {**READ_PLANS,"pi30":("QPI","QPIGS","QMOD","QPIRI"),"pi18":("^P005PI","^P005GS","^P006MOD")}
    if write:
        if not getattr(adapter,"write_authorized",False) or not command_allowed(setting_profile,command):
            raise ValueError("unreviewed_ascii_write")
    elif command not in set(reads[family])|read_commands(setting_profile) and not read_command_allowed(setting_profile,command):
        raise ValueError("unreviewed_ascii_query")
    request = ascii_request(command,family)
    budget=getattr(adapter,"probe_budget",None)
    if budget is not None:
        if budget<=0:
            raise ValueError("profile_probe_budget_exhausted")
        adapter.probe_budget-=1
    async with asyncio.timeout(timeout):
        if isinstance(adapter,BinaryTransport):
            data = await adapter.request(4,request,timeout=timeout)
        else:
            await adapter.send(request)
            if family == "pi18":
                header = await adapter.readexactly(5)
                if header[:2] in (b"^0",b"^1"):
                    data=header
                elif not re.fullmatch(rb"\^D\d{3}",header) or not 3 <= int(header[2:]) <= 1019:
                    raise ValueError("pi18_response_prefix")
                else:
                    data = header + await adapter.readexactly(int(header[2:]))
            else:
                data = await adapter.readuntil(b"\r")
    parsed = parse_ascii(data,family)
    if not write and parsed in ("ACK","NAK"):
        raise ValueError("ascii_query_rejected" if parsed=="NAK" else "unexpected_ascii_ack")
    if family=="eybond_09c1":
        from .eybond_09c1 import parse_reply
        parse_reply("PV?" if command in ("PV1","PV2") else command,data)
    adapter.emit("ascii_validated",family=family,command=command if not write else command[:3],length=len(data),write=write)
    return parsed


async def snapshot(adapter, writer, profile_id, timeout=3):
    from .exchange import read_words
    profile = MAPS[profile_id]
    adapter.emit("profile_read_started",profile_id=profile_id,function=profile.function,payload=profile.payload)
    signature = None
    if profile.payload == "modbus":
        if profile_id == "smg_legacy":
            try:
                protocol,_,_ = await read_words(adapter,writer,184,1,timeout=timeout)
            except FrameError as error:
                if error.exception_code != 2:
                    raise
            else:
                if f"smg_{protocol[0]}" in SMG_VARIANTS:
                    error = ValueError("profile_native_protocol_mismatch")
                    error.protocol_number, error.model_code = protocol[0], None
                    raise error
        if profile_id == "must_pv_ph18":
            # Known markers compose the mandatory model variant onto the common
            # map. Keeping the selected ID allows an existing common-map device
            # to renew its changed definition binding without losing HA history.
            try:
                marker,_,_ = await read_words(adapter,writer,20000,2,timeout=timeout)
            except FrameError as error:
                if error.exception_code != 2:
                    raise
            else:
                profile = resolve_map(profile, {20000:marker[0],20001:marker[1]})
                signature = [[20000,marker[0]],[20001,marker[1]]]
        if profile.anchors and signature is None:
            signature=[]
            for address,expected in profile.anchors:
                words,_,_=await read_words(adapter,writer,address,1,timeout=timeout)
                signature.append([address,words[0]])
                if words[0]!=expected:
                    raise ValueError("profile_identity_anchor_mismatch")
        if profile.protocol_number is not None:
            protocol,_,_ = await read_words(adapter,writer,184,1,timeout=timeout)
            model,_,_ = await read_words(adapter,writer,171,1,timeout=timeout)
            signature = [protocol[0],model[0]]
            if protocol[0] != profile.protocol_number:
                error=ValueError("profile_native_protocol_mismatch")
                error.protocol_number=protocol[0]
                error.model_code=model[0]
                raise error
        registers = {}
        if profile_id == "smg_4":
            from .telemetry import read_registers
            registers = await read_registers(adapter,writer,timeout)
        else:
            for address,count in profile.telemetry_blocks:
                words,_,_ = await read_words(adapter,writer,address,count,timeout=timeout,function=profile.function)
                registers.update({address+i:word for i,word in enumerate(words)})
            wire=getattr(adapter,"wire",adapter)
            if getattr(adapter,"probe_budget",None) is None and getattr(wire,"origin",None)=="normal_poll":
                for address,count in profile.optional_blocks:
                    try:
                        words,_,_=await read_words(adapter,writer,address,count,timeout=timeout,function=profile.function)
                    except FrameError as error:
                        if error.exception_code!=2:
                            raise
                        adapter.emit("optional_read_unsupported",address=address,count=count,profile_id=profile_id)
                    else:
                        registers.update({address+i:word for i,word in enumerate(words)})
        values = decode_map(profile,registers)
    else:
        family = profile.payload
        native_protocol=None
        if family in ("pi30","pi18"):
            query="QPI" if family=="pi30" else "^P005PI"
            try:native_protocol=await ascii_exchange(adapter,query,family,timeout,profile_id=profile_id)
            except ValueError as error:
                if str(error)!="ascii_query_rejected":raise
            if native_protocol not in (None,"PI30" if family=="pi30" else "18"):
                raise ValueError("ascii_protocol_mismatch:"+native_protocol)
        responses = {command: await ascii_exchange(adapter,command,family,timeout,profile_id=profile_id) for command in READ_PLANS[family]}
        values, signature = decode_ascii_cycle(family,responses,profile_id)
        if family in ("pi30","pi18"):signature.append(native_protocol)
        from .ascii_telemetry import core_values,commands,decode_group,dated_queries
        values.update(core_values(profile_id,responses))
        wire=getattr(adapter,"wire",adapter)
        if getattr(adapter,"probe_budget",None) is None and getattr(wire,"origin",None)=="normal_poll":
            # A verified negative reply is absence of this query, not an error in
            # the required group. Never reuse a previous cycle's optional values.
            for command in sorted(commands(profile_id)):
                try:text=await ascii_exchange(adapter,command,family,timeout,profile_id=profile_id)
                except ValueError as error:
                    if str(error)!="ascii_query_rejected":raise
                    adapter.emit("optional_query_unsupported",command=command)
                    continue
                if command in ("QT","^P004T"):
                    for dated in dated_queries(profile_id,text):
                        try:reply=await ascii_exchange(adapter,dated,family,timeout,profile_id=profile_id)
                        except ValueError as error:
                            if str(error)!="ascii_query_rejected":raise
                            continue
                        values.update(decode_group(profile_id,dated,reply))
                        values["energy_date"]={"value":f"{text[:4]}-{text[4:6]}-{text[6:8]}","unit":None}
                else:
                    values.update(decode_group(profile_id,command,text))
    definition_sha256=definition_hash(profile_id,profile.profile_id)
    binding = {"profile_id":profile_id,"profile_revision":1,"definition_sha256":definition_sha256,"transport":adapter.dialect,"signature":signature,"slave":getattr(adapter,"slave",1),
               "route":list(getattr(adapter,"route",()))}
    if profile.profile_id != profile_id:
        binding["effective_profile_id"] = profile.profile_id
    return {"profile_id":profile_id,"protocol_number":signature[0] if profile.protocol_number else None,
            "model_code":signature[1] if profile.protocol_number else None,"values":values,
            "binding":binding,"fingerprint":hashlib.sha256(json.dumps(binding,sort_keys=True).encode()).hexdigest()}


def decode_ascii_values(family,text,mode):
    profile = MAPS[family]
    parts = text.split(",") if family == "pi18" else text.split()
    if len(parts) < {"pi30":17,"pi18":28,"g_ascii":22}[family]:
        raise ValueError("ascii_field_count")
    try:
        values = {field.key:{"value":float(parts[field.address])/field.divisor,"unit":field.unit} for field in profile.fields}
    except ValueError as error:
        raise ValueError("invalid_ascii_numeric_value") from error
    if (family in ("pi30","g_ascii") and mode not in ("P","S","L","B","F","D","H","X","Y")) or (family=="pi18" and not re.fullmatch(r"\d{2}",mode)):
        raise ValueError("ascii_mode_mismatch")
    validate_measurements(values)
    modes={"P":"power_on","S":"standby","L":"mains","B":"off_grid","F":"fault","D":"off","H":"power_saving","X":"test"}
    values["operating_mode"]={"value":modes.get(mode,"mode_"+mode),"unit":None}
    return values,len(parts)


def decode_ascii_cycle(family,responses,profile_id=None):
    from .ascii_telemetry import core_values,commands,decode_group,read_command_allowed
    profile_id=profile_id or family
    if family=="eybond_09c1":
        from .eybond_09c1 import decode_cycle
        values,mode,signature=decode_cycle({command:responses[command] for command in READ_PLANS[family]})
        validate_measurements(values)
        values["operating_mode"]={"value":mode,"unit":None}
    else:
        if family=="pi30" and responses.get("QPI") not in (None,"PI30"):
            raise ValueError("ascii_protocol_mismatch")
        values,count=decode_ascii_values(family,*(responses[command] for command in READ_PLANS[family]))
        signature=[family,count]
    values.update(core_values(profile_id,responses))
    for command,text in responses.items():
        if command not in ("QT","^P004T") and read_command_allowed(profile_id,command):
            values.update(decode_group(profile_id,command,text))
    return values,signature


async def settings(adapter, writer, slave=1, addresses=None):
    from .exchange import read_words
    profile_id = getattr(adapter,"profile_id",None) or BASELINE
    fields = fields_for(profile_id)
    if profile_id in (BASELINE,"smg_4"):
        from .parameters import SETTINGS_BLOCKS
        registers = {}
        for address,count in SETTINGS_BLOCKS:
            try:
                words,_,_ = await read_words(adapter,writer,address,count,slave)
            except FrameError as error:
                if error.exception_code != 2:
                    raise
                for field in fields:
                    if not address <= field.address < address+count:
                        continue
                    try:
                        words,_,_ = await read_words(adapter,writer,field.address,6 if field.kind=="datetime" else 1,slave)
                    except FrameError as error:
                        if error.exception_code != 2:
                            raise
                        if hasattr(adapter,"emit"):
                            adapter.emit("setting_read_unsupported",parameter=field.key,address=field.address,exception_code=2)
                    else:
                        registers.update({field.address+i:word for i,word in enumerate(words)})
            else:
                registers.update({address+i:word for i,word in enumerate(words)})
        return registers
    if profile_id in ASCII_SETTINGS:
        from .ascii_settings import project,CHOICE_QUERIES,wire_family,voltage_choices
        specs=ASCII_SETTINGS[profile_id]
        queries=dict.fromkeys(s.query for s in specs if addresses is None or s.field.address in addresses)
        responses={}
        for query in queries:
            try:responses[query]=await ascii_exchange(adapter,query,wire_family(profile_id))
            except ValueError as error:
                if str(error)!="ascii_query_rejected":raise
                adapter.emit("setting_read_unsupported",query=query)
        if profile_id in ("pi30","pi30_max") and "QPIRI" in responses and len(responses["QPIRI"].split())<21:
            raise ValueError("qpiri_field_count")
        if profile_id=="pi18" and "^P007PIRI" in responses and len(responses["^P007PIRI"].split(","))<25:
            raise ValueError("piri_field_count")
        registers=project(profile_id,responses)
        adapter.latest_ascii_settings=registers
        if addresses is None:
            adapter.setting_choices=voltage_choices(profile_id,registers)
            for slot,query in CHOICE_QUERIES.get(profile_id,{}).items():
                try:reply=await ascii_exchange(adapter,query,wire_family(profile_id))
                except ValueError as error:
                    if str(error)!="ascii_query_rejected":raise
                    continue
                parts=re.split(r"[, ]+",reply.strip())
                if not parts or len(parts)>128 or any(not re.fullmatch(r"\d{1,3}",p) for p in parts):
                    raise ValueError("invalid_current_choices")
                adapter.setting_choices[str(slot)]=sorted({int(p) for p in parts})
        return registers
    registers = {}
    unsupported=set()
    for field in fields:
        if field.address in registers or field.address in unsupported:
            continue
        try:
            words,_,_ = await read_words(adapter,writer,field.address,1,slave)
        except FrameError as error:
            if error.exception_code != 2:
                raise
            unsupported.add(field.address)
            adapter.emit("setting_read_unsupported",parameter=field.key,address=field.address,exception_code=2)
            continue
        registers[field.address] = words[0]
    return registers


async def write_ascii_setting(adapter,address,words):
    from .ascii_settings import prepare,wire_family
    family=adapter.profile_id
    plan=getattr(adapter,"pending_ascii_write",None)
    if plan is None:
        plan=prepare(family,address,words,{},getattr(adapter,"setting_choices",None))
    if plan["family"]!=family or plan["address"]!=address or plan["target_words"]!=list(words):
        raise ValueError("ascii_write_plan_mismatch")
    adapter.pending_ascii_write=None
    if await ascii_exchange(adapter,plan["command"],wire_family(family),write=True) != "ACK":
        raise ValueError("ascii_write_not_acknowledged")
