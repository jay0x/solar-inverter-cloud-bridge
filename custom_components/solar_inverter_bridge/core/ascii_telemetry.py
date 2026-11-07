"""Optional ASCII groups with explicit units, layouts and availability.

PI30 MAX 20210217: QET/QLT are Wh and QPIGS2 is PV2, not PI41 L2.
PI18 20170926: total ET is kWh (daily ED is Wh). JSD G-ASCII counters
are high-word-first /100. These distinctions override incompatible library labels.
"""

import math
import re
from datetime import datetime

# (key, field index or high/low indices, unit, divisor)
GROUPS={
    "pi30":{"QPIWS":()},
    "pi30_max":{"QPIWS":(),"QET":(("pv_energy_total",0,"kWh",1000),),
        "QLT":(("load_energy_total",0,"kWh",1000),),
        "QPIGS2":(("pv2_current",0,"A",1),("pv2_voltage",1,"V",1),("pv2_charging_power",2,"W",1))},
    "pi18":{"^P005ET":(("pv_energy_total",0,"kWh",1),),"^P005FWS":(("inverter_fault_code",0,None,1),)},
    "g_ascii":{
        "GPV":(("pv_current",3,"A",1),("pv_energy_today",20,"kWh",100),("pv_energy_total",(21,22),"kWh",100)),
        "GBAT":(("battery_cell_count",2,None,1),("battery_cutoff_voltage_reading",3,"V",1),("battery_alarm_voltage_reading",4,"V",1)),
        "GTMP":(("pv_side_temperature",0,"°C",1),("charger_temperature",1,"°C",1),("ambient_temperature",2,"°C",1),
            ("mppt1_temperature",3,"°C",1),("mppt2_temperature",4,"°C",1)),
        "GLINE":(("grid_energy_today",10,"kWh",100),("grid_energy_total",(11,12),"kWh",100)),
        "GBUS":(("bus_voltage",0,"V",1),("bus_start_voltage",1,"V",1),("bus_reference_voltage",2,"V",1)),
        "GOP":(("output_energy_today",12,"kWh",100),("output_energy_total",(13,14),"kWh",100)),
        "GINV":(("inverter_voltage",0,"V",1),("inverter_frequency",1,"Hz",1),("inverter_current",2,"A",1)),
        "GWS":(("inverter_fault_code",0,None,1),("warning_code_1",1,None,1),("warning_code_2",2,None,1)),
        "F":(("rated_output_voltage",0,"V",1),("rated_output_current",1,"A",1),("rated_battery_voltage",2,"V",1),("rated_frequency",3,"Hz",1)),
        "GBMS":(("bms_voltage",2,"V",10),("bms_current",3,"A",100),("bms_temperature",4,"°C",10),
            ("bms_remaining_capacity",6,"Ah",10),("bms_rated_capacity",7,"Ah",10),
            ("bms_max_charging_current",10,"A",100),("bms_constant_voltage",11,"V",10)),
    },
    "eybond_09c1":{"PV1":(("pv1_voltage",0,"V",10),("pv1_current",1,"A",10)),
        "PV2":(("pv2_voltage",0,"V",10),("pv2_current",1,"A",10))},
}
CORE_EXTRAS={
    "pi30":(("pv1_charging_power",19,"W",1),),
    "pi30_max":(("pv1_charging_power",19,"W",1),),
    "pi18":(("battery_scc1_voltage",8,"V",10),("battery_scc2_voltage",9,"V",10),
        ("mppt1_temperature",14,"°C",1),("mppt2_temperature",15,"°C",1)),
}
FLAGS_09C1=(("grid_available",0,True,"absent","present"),("battery_low",1,False,"clear","active"),
    ("inverter_fault",3,False,"clear","active"),("ac_charger_enabled",2,False,"disabled","enabled"),
    ("buzzer_enabled",7,False,"disabled","enabled"))


def commands(profile):
    return set(GROUPS.get(profile,{}))|({"QT"} if profile=="pi30_max" else {"^P004T"} if profile=="pi18" else set())


def read_command_allowed(profile,command):
    if command in commands(profile):return True
    pattern=r"Q[EL]D(\d{8})" if profile=="pi30_max" else r"\^P013ED(\d{8})" if profile=="pi18" else "never"
    match=re.fullmatch(pattern,command)
    if not match:return False
    try:datetime.strptime(match[1],"%Y%m%d")
    except ValueError:return False
    return 2000<=int(match[1][:4])<=2099


def dated_queries(profile,clock):
    if not re.fullmatch(r"20\d{12}",clock):raise ValueError("invalid_inverter_clock")
    try:datetime.strptime(clock,"%Y%m%d%H%M%S")
    except ValueError as error:raise ValueError("invalid_inverter_clock") from error
    date=clock[:8]
    return (("QED"+date,"QLD"+date) if profile=="pi30_max" else ("^P013ED"+date,))


def definition(profile):
    return {"groups":GROUPS.get(profile,{}),"core_extras":CORE_EXTRAS.get(profile,()),
            "flags":FLAGS_09C1 if profile=="eybond_09c1" else (),
            "dated_energy":{"clock":"QT" if profile=="pi30_max" else "^P004T",
                "prefixes":["QED","QLD"] if profile=="pi30_max" else ["^P013ED"],"divisor":1000}
                if profile in ("pi30_max","pi18") else None}


def descriptors(profile):
    fields=list(CORE_EXTRAS.get(profile,()))+[f for group in GROUPS.get(profile,{}).values() for f in group]
    classes={"V":"voltage","A":"current","W":"power","°C":"temperature","Hz":"frequency","kWh":"energy"}
    result=[{"key":key,"name":key.replace("_"," ").capitalize(),"unit":unit,"device_class":classes.get(unit),
             "state_class":"total_increasing" if unit=="kWh" else "measurement" if unit else None,"options":None} for key,_,unit,_ in fields]
    if profile in ("pi30","pi30_max","pi18"):
        result.append({"key":"warning_flags_raw","name":"Warning flags (raw)","unit":None,"device_class":None,"state_class":None,"options":None})
    if profile in ("pi30_max","pi18"):
        for key in (("pv_energy_today","load_energy_today") if profile=="pi30_max" else ("pv_energy_today",)):
            result.append({"key":key,"name":key.replace("_"," ").capitalize(),"unit":"kWh","device_class":"energy","state_class":"total_increasing","options":None})
        result.append({"key":"energy_date","name":"Energy counter date (inverter)","unit":None,"device_class":None,"state_class":None,"options":None})
    if profile=="eybond_09c1":
        result.extend({"key":key,"name":key.replace("_"," ").capitalize(),"unit":None,"device_class":"enum","state_class":None,"options":[off,on]} for key,_,_,off,on in FLAGS_09C1)
    return tuple(result)


def decode_fields(text,fields,separator=None):
    from .catalogue import validate_reading
    parts=text.strip().lstrip("#").split(separator)
    result={}
    for key,index,unit,divisor in fields:
        indexes=index if isinstance(index,tuple) else (index,)
        if any(i>=len(parts) for i in indexes):continue
        try:
            if len(indexes)==2:
                words=[int(parts[i]) for i in indexes]
                if any(not 0<=w<=65535 for w in words):continue
                value=((words[0]<<16)|words[1])/divisor
            else:
                raw=parts[indexes[0]].strip()
                if not re.fullmatch(r"-?\d+(?:\.\d+)?",raw):continue
                value=float(raw)/divisor
            reading={"value":round(value,3),"unit":unit}
            validate_reading(key,reading)
        except (ValueError,OverflowError):continue
        result[key]=reading
    return result


def core_values(profile,responses):
    if profile=="eybond_09c1":
        bits=responses["Q1"].split()[-1]
        return {key:{"value":on if (bits[index]=="1")!=inverse else off,"unit":None}
                for key,index,inverse,off,on in FLAGS_09C1}
    if profile in CORE_EXTRAS:
        command="^P005GS" if profile=="pi18" else "QPIGS"
        return decode_fields(responses[command],CORE_EXTRAS[profile],"," if profile=="pi18" else None)
    return {}


def decode_group(profile,command,text):
    if command.startswith(("QED","QLD","^P013ED")):
        if not read_command_allowed(profile,command) or not re.fullmatch(r"\d{1,12}",text):raise ValueError("invalid_energy_counter")
        return {"load_energy_today" if command.startswith("QLD") else "pv_energy_today":{"value":int(text)/1000,"unit":"kWh"}}
    if command=="QPIWS":
        if not re.fullmatch(r"[01]{1,64}",text):raise ValueError("invalid_warning_flags")
        return {"warning_flags_raw":{"value":text,"unit":None}}
    if profile=="eybond_09c1":
        from .eybond_09c1 import parse_reply
        parse_reply("PV?",b"("+text.encode("ascii")+b"\r")
    if command=="QPIGS2" and len(text.split())!=3:
        raise ValueError("pi30_max_pv2_layout_mismatch")
    if command in ("QET","QLT","^P005ET") and not re.fullmatch(r"\d{1,12}",text):
        raise ValueError("invalid_energy_counter")
    if command=="GBMS":
        parts=text.split()
        # The BMS reply uses all-zero/FFFF placeholders when no BMS is attached.
        if len(parts)<12 or not any(re.fullmatch(r"\d+",v) and int(v) not in (0,65535,4294967295) for v in (parts[i] for i in (2,3,4,6,7,10,11))):return {}
        text=" ".join("missing" if v in ("65535","4294967295") else v for v in parts)
    result=decode_fields(text,GROUPS[profile][command],"," if profile=="pi18" else None)
    if command=="^P005FWS":
        parts=text.split(",")
        if len(parts)==18 and all(p in ("0","1") for p in parts[1:]):
            result["warning_flags_raw"]={"value":"".join(parts[1:]),"unit":None}
    return result
