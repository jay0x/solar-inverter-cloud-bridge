"""Independent, bounded measurement maps from pinned protocol facts.

Sources: groove-max/ha-eybond-local 6ca2b23 protocol_catalogs/register_schemas
and payload codecs (MPL-2.0 reference, no implementation copied). See
docs/PROFILE_EXPANSION.md for exact source paths and evidence limitations.
"""

from dataclasses import dataclass, replace
import math

from .smg import SMG_VARIANTS


@dataclass(frozen=True)
class Measurement:
    key: str
    address: int
    unit: str | None
    divisor: int = 1
    signed: bool = False
    words: int = 1
    word_order: str = "high_first"
    offset: float = 0
    optional: bool = False


def m(key, address, unit, divisor=1, signed=False, words=1, *, word_order="high_first", offset=0, optional=False):
    return Measurement(key, address, unit, divisor, signed, words, word_order, offset, optional)


def address_blocks(fields):
    addresses = sorted({a for f in fields for a in range(f.address,f.address+f.words)})
    blocks=[]
    for address in addresses:
        if blocks and address-(blocks[-1][0]+blocks[-1][1])<=2 and address-blocks[-1][0]<32:
            blocks[-1]=(blocks[-1][0],address-blocks[-1][0]+1)
        else:
            blocks.append((address,1))
    return tuple(blocks)


@dataclass(frozen=True)
class Map:
    profile_id: str
    name: str
    fields: tuple
    protocol_number: int | None = None
    model_codes: tuple = ()
    function: int = 3
    slave: int = 1
    payload: str = "modbus"
    source: str = ""
    anchors: tuple = ()

    @property
    def telemetry_blocks(self):
        if self.profile_id == "smg_4":
            from .profiles import PROTOCOL4
            return PROTOCOL4.telemetry_blocks
        return address_blocks(f for f in self.fields if not f.optional)

    @property
    def optional_blocks(self):
        return address_blocks(f for f in self.fields if f.optional)


SMG_MODES = {0:"power_on",1:"standby",2:"mains",3:"off_grid",4:"bypass",5:"charging",6:"fault"}
SMG_LOW = (m("operating_mode",201,None),m("grid_voltage",202,"V",10),m("grid_frequency",203,"Hz",100),
           m("output_voltage",210,"V",10),m("output_frequency",212,"Hz",100),m("output_power",213,"W",signed=True),
           m("battery_voltage",215,"V",10),m("pv1_voltage",219,"V",10),m("pv_power",223,"W",signed=True),
           m("load_percent",225,"%"),m("inverter_temperature",227,"°C",signed=True),m("battery_soc",229,"%"),m("battery_current",232,"A",10,True))
SMG_HIGH = (m("operating_mode",201,None),m("grid_frequency",203,"Hz",100,True),m("inverter_temperature",231,"°C",signed=True),
            m("output_frequency",253,"Hz",100,True),m("battery_voltage",277,"V",10,True),m("battery_soc",280,"%"),
            m("pv_power",302,"W",signed=True),m("grid_voltage",338,"V",10,True),m("output_voltage",346,"V",10,True),
            m("pv1_voltage",351,"V",10,True),m("pv1_power",353,"W",signed=True))

MAPS = {}
for key, variant in SMG_VARIANTS.items():
    fields = SMG_LOW if variant.layout == "low" else SMG_HIGH + (
        m("output_power",variant.output_power_address,"W",signed=True),
        m("load_percent",variant.load_percent_address,"%"),
    )
    fields = tuple(field for field in fields if field.key not in variant.omitted_measurements)
    number = variant.protocol_number
    name = "Legacy SMG / ANENJI 4–6.2 kW common map" if number is None else f"SMG / Communication Protocol {number}"
    source = "modbus_smg/base.json" if number is None else f"modbus_smg/protocols/communication_protocol_{number}.json"
    MAPS[key] = Map(key, name, fields, number, variant.model_codes, source=source)

# The former reference profile is an enrollment alias of this same documented map.
from .telemetry import FIELDS as PROTOCOL4_FIELDS
MAPS["smg_4"] = replace(MAPS["smg_4"], fields=(m("operating_mode",201,None),m("battery_soc",280,"%")) +
    tuple(m(key,address,unit,divisor,signed=True) for key,address,divisor,unit in PROTOCOL4_FIELDS) +
    (m("pv_energy_today",702,"kWh",100),m("pv_energy_total",703,"kWh",100,words=2)))


def add(key, name, fields, function=3, slave=1):
    MAPS[key] = Map(key, name, tuple(fields), function=function, slave=slave, source=key + "/base.json")


add("must_pv_ph18", "MUST PV/PH18", [m("pv1_voltage",15205,"V",10),m("pv_charging_power",15208,"W"),
    m("battery_voltage",25205,"V",10),m("output_voltage",25206,"V",10),m("grid_voltage",25207,"V",10),
    m("output_current",25210,"A",10),m("output_power",25215,"W",signed=True),m("load_percent",25216,"%",100),
    m("output_frequency",25225,"Hz",100),m("grid_frequency",25226,"Hz",100),m("inverter_temperature",25233,"°C")], slave=4)
MAPS["must_pv3300"] = replace(MAPS["must_pv_ph18"],profile_id="must_pv3300",name="MUST-compatible PV3300 (whole-percent load)",
    fields=tuple(replace(field,divisor=1) if field.key=="load_percent" else field for field in MAPS["must_pv_ph18"].fields),
    anchors=((20000,0x5056),(20001,3300)),source="must_pv_ph18/pv3300.json")
MAPS["must_pv3900"] = replace(MAPS["must_pv_ph18"],profile_id="must_pv3900",name="MUST PV3900 common telemetry",
    anchors=((20000,0x5056),(20001,3900)),source="must_pv_ph18/pv3900.json")
add("srne_modbus", "SRNE Modbus", [m("battery_soc",256,"%"),m("battery_voltage",257,"V",10,True),m("battery_current",258,"A",10,True),
    m("pv1_voltage",263,"V",10,True),m("pv1_power",265,"W",signed=True),m("grid_voltage",531,"V",10,True),m("grid_frequency",533,"Hz",100,True),
    m("output_voltage",534,"V",10,True),m("output_frequency",536,"Hz",100,True),m("output_power",539,"W",signed=True),m("load_percent",543,"%")])
add("growatt_spf", "Growatt SPF input-register map", [m("pv1_power",3,"W",10,words=2),m("output_power",9,"W",10,words=2),
    m("battery_voltage",17,"V",100),m("battery_soc",18,"%"),m("grid_voltage",20,"V",10),m("grid_frequency",21,"Hz",100),
    m("output_voltage",22,"V",10),m("output_frequency",23,"Hz",100),m("inverter_temperature",25,"°C",10,True),m("load_percent",27,"%",10)],function=4)
add("deye_lv", "Deye low-voltage map", [m("grid_frequency",79,"Hz",100),m("grid_voltage",150,"V",10),m("output_voltage",154,"V",10),
    m("output_power",178,"W",signed=True),m("battery_voltage",183,"V",100),m("battery_soc",184,"%"),m("pv1_power",186,"W"),
    m("battery_current",191,"A",100,True),m("output_frequency",192,"Hz",100)])
add("sumry_ges_7530", "Sumry GES 7530", [m("battery_voltage",30000,"V",10),m("battery_current",30001,"A",10,True),m("battery_soc",30002,"%"),
    m("output_voltage",30024,"V",10),m("output_current",30025,"A",10,True),m("output_frequency",30026,"Hz",100),
    m("grid_voltage",30058,"V",10),m("grid_current",30059,"A",10,True),m("grid_frequency",30060,"Hz",100)])
add("aohai_fsa", "Aohai FSA input-register map", [m("output_voltage",2,"V",10),m("inverter_temperature",10,"°C",10,True),
    m("grid_voltage",42,"V",10),m("grid_frequency",51,"Hz",100),m("battery_voltage",127,"V",10),m("battery_soc",128,"%"),m("battery_current",141,"A",100,True)],function=4)
add("solis_esinv", "Solis ESINV input-register map", [m("grid_voltage",33073,"V",10),m("inverter_temperature",33093,"°C",10,True),
    m("grid_frequency",33094,"Hz",100),m("battery_voltage",33133,"V",10),m("battery_current",33134,"A",10,True),m("battery_soc",33139,"%")],function=4)
add("deye_3ph_high_80kw", "Deye three-phase high-register map", [m("battery_voltage",587,"V",100),m("battery_soc",588,"%"),
    m("battery_power",590,"W",signed=True),m("grid_voltage",598,"V",10),m("grid_voltage_l2",599,"V",10),m("grid_voltage_l3",600,"V",10),
    m("grid_frequency",609,"Hz",100),m("grid_power",625,"W",signed=True),m("output_voltage",644,"V",10),
    m("output_voltage_l2",645,"V",10),m("output_voltage_l3",646,"V",10),m("output_frequency",655,"Hz",100),
    m("pv1_power",672,"W"),m("pv2_power",673,"W"),m("pv1_voltage",676,"V",10),m("pv2_voltage",678,"V",10)])
add("hopewind_0237", "Hopewind 0237", [m("pv1_voltage",40500,"V",10,True),m("pv2_voltage",40501,"V",10,True),
    m("grid_voltage",40532,"V",10,True),m("grid_voltage_bc",40533,"V",10,True),m("grid_voltage_ca",40534,"V",10,True),
    m("grid_frequency",40538,"Hz",100,True),m("inverter_temperature",40544,"°C",10,True)])
add("smartess_0912", "SmartESS 0912 telemetry map", [m("battery_power",0,"W",signed=True),m("battery_voltage",1,"V",10),
    m("battery_current",2,"A",10,True),m("battery_soc",3,"%",100),m("grid_voltage",53,"V",10),m("grid_voltage_l2",54,"V",10),
    m("grid_voltage_l3",55,"V",10),m("grid_frequency",59,"Hz",100),m("output_voltage",83,"V",10),m("output_frequency",89,"Hz",100)],function=4,slave=4)
add("smartess_0921", "SmartESS 0921 telemetry map", [m("grid_voltage",36,"V",10),m("grid_current",37,"A",10),m("grid_frequency",38,"Hz",100),
    m("output_voltage",43,"V",10),m("output_current",44,"A",10),m("inverter_frequency",50,"Hz",100),m("pv1_voltage",54,"V",10),
    m("pv1_current",55,"A",10),m("battery_voltage",65,"V",10),m("battery_current",66,"A",10)])

# ASCII addresses below are field positions, not Modbus register numbers.
PI30 = (m("grid_voltage",0,"V"),m("grid_frequency",1,"Hz"),m("output_voltage",2,"V"),m("output_frequency",3,"Hz"),
        m("output_apparent_power",4,"VA"),m("output_power",5,"W"),m("load_percent",6,"%"),m("battery_voltage",8,"V"),
        m("battery_charging_current",9,"A"),m("battery_soc",10,"%"),m("inverter_temperature",11,"°C"),
        m("pv1_current",12,"A"),m("pv1_voltage",13,"V"),m("battery_discharge_current",15,"A"))
PI18 = (m("grid_voltage",0,"V",10),m("grid_frequency",1,"Hz",10),m("output_voltage",2,"V",10),m("output_frequency",3,"Hz",10),
        m("output_apparent_power",4,"VA"),m("output_power",5,"W"),m("load_percent",6,"%"),m("battery_voltage",7,"V",10),
        m("battery_discharge_current",10,"A"),m("battery_charging_current",11,"A"),m("battery_soc",12,"%"),
        m("inverter_temperature",13,"°C"),m("pv1_power",16,"W"),m("pv2_power",17,"W"),m("pv1_voltage",18,"V",10),m("pv2_voltage",19,"V",10))
G_ASCII = (m("grid_voltage",7,"V"),m("grid_frequency",8,"Hz"),m("output_voltage",9,"V"),m("output_frequency",10,"Hz"),
           m("output_current",11,"A"),m("battery_voltage",12,"V"),m("battery_current",13,"A"),m("load_percent",14,"%"),
           m("output_apparent_power",15,"VA"),m("output_power",16,"W"),m("battery_soc",17,"%"),m("pv1_voltage",18,"V"),
           m("pv_charging_current",19,"A"),m("pv_power",20,"W"),m("inverter_temperature",21,"°C"))
for key, title, fields in (("pi30","PI30 / PI30 MAX common telemetry",PI30),("pi18","PI18 ASCII",PI18),("g_ascii","EyeBond / JsdSolar G-ASCII",G_ASCII)):
    MAPS[key] = Map(key,title,fields,slave=0,payload=key,source="payload/"+key)

from .eybond_09c1 import MEASUREMENTS as MEASUREMENTS_09C1
MAPS["eybond_09c1"] = Map("eybond_09c1", "EyeBond 09C1 / Q1-QF-PV?-F",
    tuple(m(key,index,unit) for index,(key,unit) in enumerate(MEASUREMENTS_09C1)),
    slave=0,payload="eybond_09c1",source="payload/urtu09c1.py")

SOURCE_ROOT = "https://github.com/groove-max/ha-eybond-local/blob/6ca2b23cda042f5919e3831a907f784000d5de27/custom_components/eybond_local/"
for key, profile in tuple(MAPS.items()):
    if key == "eybond_09c1":
        source="payload/urtu09c1.py"
    elif key in ("pi30","pi18"):
        source="payload/"+key+".py"
    elif key=="g_ascii":
        source="protocol_catalogs/command_schemas/eybond_g_ascii/base.json"
    else:
        source="protocol_catalogs/register_schemas/"+("smartess_local/models/"+key[-4:]+".json" if key.startswith("smartess_") else profile.source)
    MAPS[key]=replace(profile,source=SOURCE_ROOT+source)

from .extended_maps import extend_maps
extend_maps(MAPS,m)
MAPS["pi30"]=replace(MAPS["pi30"],name="PI30 — standard 2015 command variant")
MAPS["pi30_max"]=replace(MAPS["pi30"],profile_id="pi30_max",name="PI30 MAX — 2021 command variant",
    source="https://github.com/jblance/mpp-solar/blob/eafdd4328c77f516cf82430c5bcb6fa042c45d3a/docs/protocols/PI30MAX.Communication.Protocol20210217.pdf")


def validate_measurements(values):
    """Physical consistency is family evidence, never proof of a model identity."""
    for key, reading in values.items():
        validate_reading(key,reading)
    if not any(8 <= values.get(key,{}).get("value",0) <= 1000 for key in ("battery_voltage","grid_voltage","output_voltage")):
        raise ValueError("no_positive_voltage_evidence")
    if not any(40 <= values.get(key,{}).get("value",0) <= 70 for key in ("grid_frequency","output_frequency","inverter_frequency")):
        raise ValueError("no_frequency_evidence")


def validate_reading(key,reading):
    value,unit=reading["value"],reading["unit"]
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError("invalid_numeric_measurement")
    if unit=="V" and not 0<=value<=1600:raise ValueError("implausible_voltage")
    if unit=="Hz" and not 0<=value<=70:raise ValueError("implausible_frequency")
    if key in ("battery_soc","battery_soh","bms_soc") and not 0<=value<=100:raise ValueError("implausible_soc")
    if key=="load_percent" and not 0<=value<=300:raise ValueError("implausible_load_percent")
    if unit=="°C" and not -50<=value<=180:raise ValueError("implausible_temperature")


def resolve_map(profile, registers):
    """Apply known mandatory model corrections to a selected common map."""
    if profile.profile_id == "must_pv_ph18" and registers.get(20000) == 0x5056:
        variant = {3300:"must_pv3300", 3900:"must_pv3900"}.get(registers.get(20001))
        if variant:
            return MAPS[variant]
    return profile


def decode_map(profile, registers):
    profile = resolve_map(profile, registers)
    if profile.profile_id == "smg_4":
        from .telemetry import decode
        return decode(registers, require_full=False)
    values = {}
    for field in profile.fields:
        if field.optional and any(a not in registers for a in range(field.address,field.address+field.words)):
            continue
        raw = 0
        invalid_counter = False
        addresses=list(range(field.address,field.address+field.words))
        if field.word_order=="low_first":
            addresses.reverse()
        if field.word_order not in ("high_first","low_first","decimal10000"):
            raise ValueError("unknown_word_order")
        if field.word_order=="decimal10000" and (field.words!=2 or field.signed):
            raise ValueError("invalid_decimal_counter")
        for address in addresses:
            word = registers[address]
            if type(word) is not int or not 0 <= word <= 65535:
                raise ValueError("invalid_register_word")
            if field.word_order=="decimal10000" and address==field.address+1 and word>=10000:
                invalid_counter=True
                break
            raw = raw * (10000 if field.word_order=="decimal10000" else 65536) + word
        if invalid_counter:
            if field.optional:continue
            raise ValueError("invalid_decimal_counter_low_word")
        if field.signed and raw >= 1 << (16*field.words-1):
            raw -= 1 << (16*field.words)
        reading={"value":round((raw+field.offset)/field.divisor,3),"unit":field.unit}
        if field.optional:
            try:validate_reading(field.key,reading)
            except ValueError:continue
        values[field.key]=reading
    validate_measurements(values)
    if profile.profile_id=="srne_modbus":
        current=values["battery_current"]["value"]
        values["battery_charging_current"]={"value":max(0,-current),"unit":"A"}
        values["battery_discharge_current"]={"value":max(0,current),"unit":"A"}
    if "operating_mode" in values:
        raw=values["operating_mode"]["value"]
        if raw not in SMG_MODES:
            raise ValueError("unsupported_operating_mode")
        values["operating_mode"]={"value":SMG_MODES[raw],"unit":None}
    return values


def descriptors(profile_id):
    if profile_id in ("modbus_protocol_4", "smg_4"):
        from .telemetry import sensor_descriptors
        return sensor_descriptors()
    profile = MAPS[profile_id]
    if profile_id=="must_pv_ph18":
        # BMS fields belong to recognized variants; reserve stable entities even
        # before an optional BMS block is available on a particular device.
        profile=replace(profile,fields=MAPS["must_pv3300"].fields)
    classes = {"W":"power","VA":"apparent_power","V":"voltage","A":"current","Hz":"frequency","°C":"temperature","kWh":"energy"}
    labels = {"grid_voltage":"Grid voltage AB (line-to-line)"} if profile_id=="hopewind_0237" else {}
    if profile_id in ("deye_3ph_high_80kw","smartess_0912"):
        labels={"grid_voltage":"Grid voltage L1","output_voltage":"Output voltage L1"}
    if profile_id in ("smg_3","smg_5"):
        labels={"output_power":"Output power L1","load_percent":"Load L1"}
    if profile_id in ("srne_modbus","sumry_ges_7530"):
        labels={"output_power":"Output power phase A","output_voltage":"Output voltage phase A","grid_voltage":"Grid voltage phase A","output_current":"Output current phase A","grid_current":"Grid current phase A"}
    result = tuple({"key":f.key,"name":labels.get(f.key,f.key.replace("_"," ").title()),"unit":f.unit,
                  "device_class":"battery" if f.key=="battery_soc" else classes.get(f.unit),
                  "state_class":"total_increasing" if f.unit=="kWh" else "measurement" if f.unit else None,"options":None} for f in profile.fields)
    if profile_id=="srne_modbus":
        result=tuple({**d,"attributes":{"positive_direction":"discharging","negative_direction":"charging"}} if d["key"]=="battery_current" else d for d in result)
        result+=tuple({"key":key,"name":name,"unit":"A","device_class":"current","state_class":"measurement","options":None} for key,name in (("battery_charging_current","Battery charging current"),("battery_discharge_current","Battery discharge current")))
    if profile.payload != "modbus":
        result += ({"key":"operating_mode","name":"Operating mode" if profile.payload!="pi18" else "Operating mode code",
                     "unit":None,"device_class":None,"state_class":None,"options":None},)
        from .ascii_telemetry import descriptors as extra_descriptors
        result+=extra_descriptors(profile_id)
    return result


def required_measurement_addresses(profile):
    if profile.profile_id == "smg_4":
        from .telemetry import COMMON_ADDRESSES
        return set(COMMON_ADDRESSES)
    return {address for field in profile.fields if not field.optional for address in range(field.address,field.address+field.words)}
