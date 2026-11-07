"""Whitelisted ASCII setting grammars and independent readback projections.

Facts: PI30 20150924 protocol, mpp-solar eafdd432 PI18, and JSD/G-ASCII
settings documented in ha-eybond-local 6ca2b23. Virtual slots are not registers.
"""

from dataclasses import dataclass, asdict, replace
from decimal import Decimal, InvalidOperation
import re

from .parameters import Parameter


@dataclass(frozen=True)
class Setting:
    field: Parameter
    query: str
    index: int | str
    command: str
    encoding: str
    partner: int | None = None
    unit_zero: bool = False


def enum(key,slot,label,index,command,options,*,family="pi30",encoding="d2",unit_zero=False):
    return Setting(Parameter(key,slot,label,"select",options=options),"QPIRI" if family=="pi30" else "^P007PIRI",index,command,encoding,unit_zero=unit_zero)


def voltage(key,slot,label,index,command,*,family="pi30",partner=None):
    return Setting(Parameter(key,slot,label,unit="V",divisor=10,wire_max=65535 if family=="pi30" else 999),
        "QPIRI" if family=="pi30" else "^P007PIRI",index,command,"decimal1" if family=="pi30" else "d3",partner)


PI30=(
    enum("primary_output_priority",9000,"Output source priority",16,"POP",{0:"utility_first",1:"solar_first",2:"sbu"}),
    enum("primary_charging_priority",9001,"Charging source priority",17,"PCP",{0:"utility_first",1:"solar_first",2:"solar_and_utility",3:"solar_only"}),
    enum("input_mode",9002,"AC input range",15,"PGR",{0:"appliance",1:"ups"}),
    voltage("battery_recovery_voltage_ac",9003,"Back-to-grid voltage",8,"PBCV"),
    voltage("battery_protection_voltage_offgrid",9004,"Battery cutoff voltage",9,"PSDV"),
    voltage("bulk_charging_voltage",9005,"Bulk charging voltage",10,"PCVV"),
    voltage("float_charging_voltage",9006,"Float charging voltage",11,"PBFT"),
    voltage("battery_return_voltage",9007,"Back-to-battery voltage",22,"PBDV"),
    enum("pi30_battery_type",9008,"Battery type",12,"PBT",{0:"agm",1:"flooded",2:"user"}),
    Setting(Parameter("maximum_charging_current",9009,"Maximum charging current",unit="A",wire_max=999),"QPIRI",14,"MCHGC","d3"),
    Setting(Parameter("maximum_ac_charging_current",9010,"Maximum AC charging current",unit="A",wire_max=999),"QPIRI",13,"MUCHGC","d3"),
) + tuple(Setting(Parameter(key,9020+i,label,"select",options={0:"disabled",1:"enabled"}),"QFLAG",flag,flag,"flag")
    for i,(key,label,flag) in enumerate((
        ("buzzer_mode","Buzzer","A"),("overload_bypass","Overload bypass","B"),("energy_saving","Energy saving","J"),
        ("lcd_return_home","Display return to home","K"),("overload_restart","Overload restart","U"),
        ("overtemperature_restart","Overtemperature restart","V"),("lcd_backlight","Display backlight","X"),
        ("source_interrupt_alarm","Source interruption alarm","Y"),("fault_recording","Fault recording","Z"))))

PI18=(
    enum("primary_output_priority",9100,"Output source priority",17,"POP",{0:"sub",1:"sbu"},family="pi18",encoding="d1"),
    enum("primary_charging_priority",9101,"Charging source priority",18,"PCP",{0:"solar_first",1:"solar_and_utility",2:"solar_only"},family="pi18",encoding="d1",unit_zero=True),
    enum("solar_power_priority",9102,"Solar power priority",23,"PSP",{0:"battery_load_utility",1:"load_battery_utility"},family="pi18",encoding="d1"),
    enum("machine_type",9103,"Machine type",20,"PEI",{0:"off_grid",1:"grid_tie"},family="pi18",encoding="grid_tie"),
    enum("pi18_battery_type",9104,"Battery type",13,"PBT",{0:"agm",1:"flooded",2:"user"},family="pi18",encoding="d1"),
    Setting(Parameter("maximum_charging_current",9105,"Maximum charging current",unit="A",wire_max=999),"^P007PIRI",15,"MCHGC","d3",unit_zero=True),
    Setting(Parameter("maximum_ac_charging_current",9106,"Maximum AC charging current",unit="A",wire_max=999),"^P007PIRI",14,"MUCHGC","d3",unit_zero=True),
    voltage("bulk_charging_voltage",9107,"Bulk charging voltage",11,"MCHGV",family="pi18",partner=9108),
    voltage("float_charging_voltage",9108,"Float charging voltage",12,"MCHGV",family="pi18",partner=9107),
    voltage("battery_protection_voltage_offgrid",9109,"Battery cutoff voltage",10,"PSDV",family="pi18"),
    voltage("battery_recovery_voltage_ac",9110,"Back-to-grid voltage",8,"BUCD",family="pi18",partner=9111),
    Setting(Parameter("battery_return_voltage",9111,"Back-to-battery voltage (0: full)",unit="V",divisor=10,zero_value="full_recovery",wire_max=999),"^P007PIRI",9,"BUCD","d3",partner=9110),
    enum("input_mode",9112,"AC input range",16,"PGR",{0:"appliance",1:"ups"},family="pi18",encoding="d1"),
    enum("output_frequency_setting",9113,"Output frequency",3,"F",{500:"50 Hz",600:"60 Hz"},family="pi18",encoding="frequency"),
    enum("output_voltage_setting",9114,"Output voltage",2,"V",{2020:"202 V",2080:"208 V",2200:"220 V",2300:"230 V",2400:"240 V"},family="pi18",encoding="d4"),
) + tuple(Setting(Parameter(key,9120+i,label,"select",options={0:"disabled",1:"enabled"}),"^P007FLAG",i,flag,"flag")
    for i,(key,label,flag) in enumerate((("buzzer_mode","Buzzer","A"),("overload_bypass","Overload bypass","B"),
        ("lcd_return_home","Display return to home","C"),("overload_restart","Overload restart","D"),
        ("overtemperature_restart","Overtemperature restart","E"),("lcd_backlight","Display backlight","F"),
        ("source_interrupt_alarm","Source interruption alarm","G"),("fault_recording","Fault recording","H"))))

PI30_MAX=tuple(replace(spec,command=spec.command.lower()) if spec.encoding=="flag" else
    replace(spec,command="MNCHGC",encoding="max_current",unit_zero=True) if spec.field.address==9009 else
    replace(spec,encoding="max_utility",unit_zero=True) if spec.field.address==9010 else
    replace(spec,field=replace(spec.field,options={0:"agm",1:"flooded",2:"user",3:"pylontech",4:"shinheung",5:"weco",6:"soltaro",7:"bak",8:"lib",9:"lic"})) if spec.field.address==9008 else spec for spec in PI30)

# Voltage limits from a 24 V example are deliberately not inherited by 48 V
# devices. Decimal wire width and exact step still apply to those fields.
_G_FACTS=(
    ("maximum_charging_current","CHGC","A",1,3,None,"Charging"),
    ("maximum_ac_charging_current","GCC","A",1,3,None,"Charging"),
    ("charging_method","CST",None,1,2,None,"Charging"),
    ("bulk_charging_voltage","TCCV","V",10,4,None,"Battery"),
    ("float_charging_voltage","TCFV","V",10,4,None,"Battery"),
    ("equalization_voltage","TCQV","V",10,4,None,"Battery"),
    ("constant_voltage_time","TCVT","min",1,4,(1,720),"Charging"),
    ("equalization_duration","TCQT","min",1,4,(5,900),"Battery"),
    ("equalization_timeout","TCQO","min",1,4,(5,900),"Battery"),
    ("equalization_interval","TCQI","h",1,4,(24,2160),"Battery"),
    ("battery_cutoff_voltage","EOD","V",10,4,None,"Battery"),
    ("battery_alarm_voltage","TBLV","V",10,4,None,"Battery"),
    ("low_power_discharge_time","LWDT","min",1,4,(60,480),"Battery"),
    ("battery_to_grid_voltage","BTG","V",10,4,None,"Battery"),
    ("grid_to_battery_voltage","BTB","V",10,4,None,"Battery"),
    ("battery_overvoltage","BTO","V",10,4,None,"Battery"),
    ("grid_overvoltage","OVP","V",1,3,None,"Grid"),
    ("grid_undervoltage","LVP","V",1,3,None,"Grid"),
    ("constant_current_max_time","CI1","h",1,2,(1,99),"Charging"),
    ("bms_shutdown_soc","BSOCU","%",1,3,(0,50),"Battery"),
    ("bms_switch_to_grid_soc","BSOCG","%",1,3,(0,90),"Battery"),
    ("bms_switch_to_battery_soc","BSOCB","%",1,3,(0,100),"Battery"),
)
G_ASCII=tuple(Setting(Parameter(key,10000+i,key.replace("_"," ").capitalize(),
    "select" if key=="charging_method" else "number",unit=unit,
    options={0:"auto",1:"two_stage",2:"three_stage"} if key=="charging_method" else None,
    divisor=div,bounds=bounds,group=group,wire_max=999 if div==10 else min(65535,10**width-1)),
    prefix+"?"*width,0,prefix,"decimal1" if div==10 else "d"+str(width))
    for i,(key,prefix,unit,div,width,bounds,group) in enumerate(_G_FACTS))
SPECS={"pi30":PI30,"pi30_max":PI30_MAX,"pi18":PI18,"g_ascii":G_ASCII}
CHOICE_QUERIES={"pi30":{9009:"QMCHGCR",9010:"QMUCHGCR"},"pi18":{9105:"^P009MCHGCR",9106:"^P010MUCHGCR"}}
CHOICE_QUERIES["pi30_max"]=CHOICE_QUERIES["pi30"]
PI18_VOLTAGE_CHOICES={
    120:{9110:(110,113,115,118,120,123,125,128),9111:(0,120,123,125,128,130,133,135,138,140,143,145)},
    240:{9110:tuple(range(220,256,5)),9111:(0,*range(240,291,5))},
    480:{9110:tuple(range(440,511,10)),9111:(0,*range(480,581,10))},
}


def wire_family(profile_id):
    return "pi30" if profile_id=="pi30_max" else profile_id


def definitions(family):
    return {"settings":[asdict(spec) for spec in SPECS.get(family,())],
        "voltage_choices":PI18_VOLTAGE_CHOICES if family=="pi18" else None,
        "nominal_battery_query_index":7 if family=="pi18" else None}


def voltage_choices(family,registers):
    return {str(slot):list(values) for slot,values in PI18_VOLTAGE_CHOICES.get(registers.get(9199),{}).items()} if family=="pi18" else {}


def read_commands(family):
    return {s.query for s in SPECS.get(family,())}|set(CHOICE_QUERIES.get(family,{}).values())


def raw_number(text,field,*,observed=False):
    if not re.fullmatch(r"\d+(?:\.\d+)?",text):raise ValueError("invalid_ascii_setting_value")
    try:raw=Decimal(text)*Decimal(str(field.divisor))
    except InvalidOperation as error:raise ValueError("invalid_ascii_setting_value") from error
    if not raw.is_finite() or raw!=raw.to_integral_value() or not 0<=raw<=(65535 if observed else field.wire_max):
        raise ValueError("invalid_ascii_setting_value")
    return int(raw)


def project(family,responses):
    result={}
    for spec in SPECS[family]:
        text=responses.get(spec.query)
        if text is None:continue
        if spec.query=="QFLAG":
            if not re.fullmatch(r"E[a-zA-Z]*(?:D[a-zA-Z]*)?",text):raise ValueError("invalid_qflag")
            enabled,_,disabled=text[1:].partition("D")
            flag=str(spec.index).lower()
            if flag in enabled.lower():result[spec.field.address]=1
            elif flag in disabled.lower():result[spec.field.address]=0
            continue
        parts=text.split(",") if family=="pi18" else text.split()
        if int(spec.index)>=len(parts):continue
        value=parts[int(spec.index)].strip()
        if family=="pi18":
            if not re.fullmatch(r"\d+",value) or int(value)>65535:raise ValueError("invalid_ascii_setting_value")
            result[spec.field.address]=int(value)
        else:
            result[spec.field.address]=raw_number(value,spec.field,observed=True)
    # PI18 unit-addressed setters are only qualified for a single-module target.
    if family=="pi18" and "^P007PIRI" in responses:
        parts=responses["^P007PIRI"].split(",")
        if len(parts)>7 and re.fullmatch(r"\d{1,4}",parts[7].strip()):result[9199]=int(parts[7])
        if len(parts)<=22 or parts[22].strip()!="0":
            for spec in SPECS[family]:
                if spec.unit_zero:result.pop(spec.field.address,None)
    if family=="pi30_max" and "QPIRI" in responses:
        parts=responses["QPIRI"].split()
        if len(parts)<=21 or parts[21]!="0":
            for spec in SPECS[family]:
                if spec.unit_zero:result.pop(spec.field.address,None)
    return result


def prepare(family,address,words,baseline,choices=None):
    spec=next((s for s in SPECS.get(family,()) if s.field.address==address),None)
    if spec is None or len(words)!=1:raise ValueError("unsupported_ascii_setting")
    if spec.unit_zero and address not in baseline:raise ValueError("unqualified_parallel_target")
    raw=words[0]
    if not 0<=raw<=spec.field.wire_max:raise ValueError("ascii_setting_width")
    if spec.field.options is not None and raw not in spec.field.options:raise ValueError("invalid_enum")
    allowed={**voltage_choices(family,baseline),**(choices or {})}
    if str(address) in allowed and raw not in allowed[str(address)]:raise ValueError("unsupported_setting_choice")
    if family=="pi18" and baseline.get(9199)==480:
        limits={9107:(480,584),9108:(480,584),9109:(400,480)}.get(address)
        if limits is not None and not limits[0]<=raw<=limits[1]:raise ValueError("value_outside_documented_bounds")
    expected={str(address):raw}
    if family=="pi18" and spec.query=="^P007PIRI" and 9199 in baseline:expected["9199"]=baseline[9199]
    if spec.partner is not None:
        other=baseline.get(spec.partner)
        if type(other) is not int or not 0<=other<=999:raise ValueError("dependent_parameter_not_observed")
        expected[str(spec.partner)]=other
        pair=(raw,other) if address<spec.partner else (other,raw)
        body=spec.command+f"{pair[0]:03d},{pair[1]:03d}"
    elif spec.encoding=="flag":body=("PE" if raw else "PD")+spec.command
    elif spec.encoding=="grid_tie":body="PEI" if raw else "PDI"
    elif spec.encoding=="frequency":body=spec.command+str(raw//10)
    elif spec.encoding in ("max_current","max_utility"):
        body=spec.command+"0"+f"{raw:0{3 if spec.encoding=='max_current' else 2}d}"
    else:
        value=f"{raw//10}.{raw%10}" if spec.encoding=="decimal1" else f"{raw:0{int(spec.encoding[1:])}d}"
        if spec.encoding.startswith("d") and spec.encoding!="decimal1" and len(value)!=int(spec.encoding[1:]):raise ValueError("ascii_setting_width")
        body=spec.command+("0," if spec.unit_zero else "")+value
    if family=="pi18":body=f"^S{len(body)+3:03d}"+body
    return {"family":family,"address":address,"target_words":list(words),"command":body,"expected":expected}


def command_allowed(family,command):
    if family=="pi18":
        if not re.match(r"\^S\d{3}",command) or int(command[2:5])!=len(command[5:])+3:return False
        command=command[5:]
    for spec in SPECS.get(family,()):
        if spec.partner is not None:pattern=re.escape(spec.command)+r"\d{3},\d{3}"
        elif spec.encoding=="flag":pattern="P[ED]"+spec.command
        elif spec.encoding=="grid_tie":pattern="P[ED]I"
        elif spec.encoding=="frequency":pattern="F(?:50|60)"
        elif spec.encoding=="max_current":pattern="MNCHGC0\\d{3}"
        elif spec.encoding=="max_utility":pattern="MUCHGC0\\d{2,3}"
        else:
            suffix=r"\d{1,4}\.\d" if spec.encoding=="decimal1" else r"\d{"+spec.encoding[1:]+"}"
            pattern=re.escape(spec.command)+(r"0," if spec.unit_zero else "")+suffix
        if re.fullmatch(pattern,command):
            if spec.partner is not None or spec.encoding in ("flag","grid_tie","frequency","max_current","max_utility"):
                return True
            text=command[len(spec.command)+(2 if spec.unit_zero else 0):]
            try:raw=raw_number(text,spec.field) if spec.encoding=="decimal1" else int(text)
            except ValueError:return False
            if not 0<=raw<=spec.field.wire_max:return False
            if spec.field.options is not None:return raw in spec.field.options
            value=raw/spec.field.divisor
            return spec.field.bounds is None or spec.field.bounds[0]<=value<=spec.field.bounds[1]
    return False


def readback_matches(plan,registers):
    return all(registers.get(int(address))==value for address,value in plan["expected"].items())
