"""Source-defined Modbus settings, with explicit fields rather than address classes.

Facts: MUST 1.4.15, SRNE 1.96, Growatt V0.11 and the pinned Deye high-map
catalog. Model-dependent electrical limits are not generalized from an 8 kW unit.
"""

from .parameters import Parameter

BOOL={0:"disabled",1:"enabled"}


def n(key,address,unit=None,divisor=1,bounds=None,group="System",name=None):
    return Parameter(key,address,name or key.replace("_"," ").capitalize(),unit=unit,divisor=divisor,bounds=bounds,group=group)


def s(key,address,options,group="System",mask=None,name=None):
    return Parameter(key,address,name or key.replace("_"," ").capitalize(),"select",options=options,group=group,mask=mask)


def b(key,address,group="System",mask=None):
    return s(key,address,BOOL,group,mask)


MUST=(
    b("offgrid_output_enable",20101,"Output"),b("energy_saving",20104,"Output"),b("grid_charge",20106,"Charging"),
    s("primary_charging_priority",20143,{0:"solar_first",2:"solar_and_utility",3:"solar_only"},"Charging"),
    n("maximum_ac_charging_current",20125,"A",10,(1,80),"Charging"),
    n("maximum_charging_current",20132,"A",10,(1,140),"Charging"),
    n("output_voltage_setting",20102,"V",10,group="Output"),s("output_frequency_setting",20103,{5000:"50",6000:"60"},"Output"),
    n("maximum_pv_charging_current",10108,"A",10,(0,200),"Charging"),
    n("float_charging_voltage",10103,"V",10,group="Battery"),n("bulk_charging_voltage",10104,"V",10,group="Battery"),
    s("must_battery_type",10110,{0:"not_selected",1:"user",2:"lithium",3:"sealed_lead",4:"agm",5:"gel",6:"flooded"},"Battery"),
    n("battery_stop_charge_voltage",20119,"V",10,group="Battery"),n("battery_stop_discharge_voltage",20118,"V",10,group="Battery"),
    n("battery_low_voltage",20127,"V",10,group="Battery"),n("battery_high_voltage",20128,"V",10,group="Battery"),
    n("maximum_discharge_current",20113,"A",10,(0,200),"Battery"),
    s("energy_use_mode",20109,{1:"sbu",2:"sub",3:"utility_first",4:"solar_first"},"Grid"),
    s("grid_protection_standard",20111,{0:"vde4105",1:"ups",2:"home",3:"generator"},"Grid"),
    s("solar_use_priority",20112,{0:"load_battery_utility",1:"battery_load_utility"},"Grid"),b("solar_sell",20108,"Grid"),
    b("battery_equalization_enable",10118,"Battery"),n("battery_equalization_voltage",10119,"V",10,group="Battery"),
    n("battery_capacity",10111,"Ah",bounds=(0,2000),group="Battery"),
    n("battery_equalization_duration",10121,"min",bounds=(0,900),group="Battery"),
    n("battery_equalization_timeout",10122,"min",bounds=(0,900),group="Battery"),
    n("battery_equalization_interval",10123,"d",bounds=(0,90),group="Battery"),
)
GROWATT=(s("primary_output_priority",1,{0:"battery_first",1:"solar_first",2:"utility_first"},"Output"),
    s("primary_charging_priority",2,{0:"solar_first",1:"solar_and_utility",2:"solar_only"},"Charging"),
    s("input_mode",8,{0:"appliance",1:"ups"},"Grid"),
    s("overload_restart",20,{0:"restart",1:"no_restart",2:"switch_to_utility"},"Protection"),
    s("overtemperature_restart",21,{0:"restart",1:"no_restart"},"Protection"),b("buzzer_mode",22),
    n("maximum_charging_current",34,"A",bounds=(10,130),group="Charging"))

# SRNE battery setting voltages are explicitly expressed per 12 V, independent
# of the actual battery bank. The rated-voltage row is marked read-only in text.
SRNE=(
    n("maximum_pv_charging_current",0xE001,"A",10,(0,150),"Charging"),n("battery_capacity",0xE002,"Ah",bounds=(0,400),group="Battery"),
    s("srne_battery_type",0xE004,{0:"user",1:"sealed_lead",2:"flooded",3:"gel",4:"lfp_14s",5:"lfp_15s",6:"lfp_16s",7:"lfp_7s",8:"lfp_8s",9:"lfp_9s",10:"lithium_7s",11:"lithium_8s",12:"lithium_13s",13:"lithium_14s"},"Battery"),
    *(n(key+"_per_12v",address,"V",10,(9,15.5),"Battery",name=label+" (12 V reference)") for key,address,label in (
        ("battery_overvoltage",0xE005,"Battery overvoltage"),("charging_limit_voltage",0xE006,"Charging limit voltage"),
        ("equalization_voltage",0xE007,"Equalization voltage"),("bulk_charging_voltage",0xE008,"Bulk charging voltage"),
        ("float_charging_voltage",0xE009,"Float charging voltage"),("boost_recovery_voltage",0xE00A,"Boost recovery voltage"),
        ("discharge_recovery_voltage",0xE00B,"Discharge recovery voltage"),("low_voltage_alarm",0xE00C,"Low voltage alarm"),
        ("discharge_cutoff_voltage",0xE00D,"Discharge cutoff voltage"),("discharge_limit_voltage",0xE00E,"Discharge limit voltage"),
        ("grid_switch_voltage",0xE01B,"Grid switch voltage"))),
    n("battery_cutoff_soc",0xE00F,"%",bounds=(0,100),group="Battery"),
    n("overdischarge_delay",0xE010,"s",bounds=(0,120),group="Battery"),
    n("equalization_duration",0xE011,"min",bounds=(0,900),group="Battery"),
    n("boost_duration",0xE012,"min",bounds=(10,900),group="Battery"),n("equalization_interval",0xE013,"d",bounds=(0,255),group="Battery"),
    n("charging_stop_current",0xE01C,"A",10,(0,10),"Charging"),n("charging_stop_soc",0xE01D,"%",bounds=(0,100),group="Charging"),
    n("battery_low_soc_alarm",0xE01E,"%",bounds=(0,100),group="Battery"),n("grid_switch_soc",0xE01F,"%",bounds=(0,100),group="Battery"),
    s("primary_output_priority",0xE204,{0:"solar_first",1:"utility_first",2:"sbu"},"Output"),
    n("maximum_ac_charging_current",0xE205,"A",10,(0,200),"Charging"),b("battery_equalization_enable",0xE206,"Battery"),
    b("neutral_ground_bond",0xE207,"Output"),n("output_voltage_setting",0xE208,"V",10,(100,264),"Output"),
    n("output_frequency_setting",0xE209,"Hz",100,(45,65),"Output"),n("maximum_charging_current",0xE20A,"A",10,(0,200),"Charging"),
    s("input_mode",0xE20B,{0:"appliance",1:"ups"},"Grid"),b("energy_saving",0xE20C,"Output"),
    b("overload_restart",0xE20D,"Protection"),b("overtemperature_restart",0xE20E,"Protection"),
    s("primary_charging_priority",0xE20F,{0:"solar_first",1:"utility_first",2:"solar_and_utility",3:"solar_only"},"Charging"),b("alarm_enabled",0xE210),
)


def deye_high():
    fields=[s("inverter_power",60,{0:"on",2:"off"}),s("battery_control_mode",98,{0:"lead_acid",1:"lithium"},"Battery"),
        b("parallel_battery_enabled",110,"Battery"),s("battery_operation_basis",111,{0:"voltage",1:"soc",2:"no_battery"},"Battery"),
        s("output_voltage_level",138,{0:"220/380 V",1:"230/400 V",2:"277/480 V"},"Output"),
        s("grid_phase_sequence",147,{0:"abc",1:"acb"},"Grid"),s("grid_frequency_setting",183,{0:"50 Hz",1:"60 Hz"},"Grid"),
        s("grid_system_type",184,{0:"three_phase",1:"single_phase",2:"split_phase"},"Grid"),
        b("ups_delay",209),b("grid_phase_tracking",235,"Grid"),b("it_system",236,"Grid"),b("unbalanced_load",237,"Grid"),
        n("unbalanced_power_trip",238,"W",group="Grid")]
    for key,addr,unit,div in (
        ("battery_equalization_voltage",99,"V",100),("battery_absorption_voltage",100,"V",100),("battery_float_voltage",101,"V",100),
        ("battery_capacity",102,"Ah",1),("battery_equalization_cycle",105,"d",1),("battery_equalization_duration",106,"h",2),
        ("maximum_charging_current",108,"A",1),("maximum_discharge_current",109,"A",1),("battery_resistance",113,"mΩ",1),
        ("battery_charge_efficiency",114,"%",10),("battery_shutdown_soc",115,"%",1),("battery_restart_soc",116,"%",1),
        ("battery_low_soc",117,"%",1),("battery_shutdown_voltage",118,"V",100),("battery_restart_voltage",119,"V",100),("battery_low_voltage",120,"V",100)):
        limits=(0,100) if unit=="%" else (0,2000) if unit=="Ah" else (0,90) if unit=="d" else (0,10) if unit=="h" else (0,6000) if unit=="mΩ" else None
        fields.append(n(key,addr,unit,div,limits,"Battery"))
    for key,addr,unit,div,group in (
        ("generator_max_runtime",121,"h",10,"Generator"),("generator_cooldown",122,"h",10,"Generator"),
        ("generator_charge_start_voltage",123,"V",100,"Generator"),("generator_charge_start_soc",124,"%",1,"Generator"),
        ("generator_charge_current",125,"A",1,"Generator"),("grid_charge_start_voltage",126,"V",100,"Charging"),
        ("grid_charge_start_soc",127,"%",1,"Charging"),("grid_charge_current",128,"A",1,"Charging"),
        ("smart_load_off_voltage",134,"V",100,"Smart load"),("smart_load_off_soc",135,"%",1,"Smart load"),
        ("smart_load_on_voltage",136,"V",100,"Smart load"),("smart_load_on_soc",137,"%",1,"Smart load"),
        ("generator_minimum_solar_power",139,"W",1,"Generator"),("generator_peak_shaving_power",190,"W",1,"Generator"),
        ("grid_peak_shaving_power",191,"W",1,"Grid"),("maximum_sell_power",143,"W",.1,"Energy"),("maximum_solar_sell_power",340,"W",.1,"Energy")):
        fields.append(n(key,addr,unit,div,(0,100) if unit=="%" else None,group))
    fields.extend((b("generator_charge_enable",129,"Generator"),b("grid_charge_enable",130,"Charging"),
        n("ac_coupling_frequency_upper",131,"Hz",100,(50,65),"Generator"),b("force_generator_as_load",132,"Generator"),
        s("generator_port_mode",133,{0:"generator_input",1:"smart_load_output",2:"microinverter_input"},"Generator"),
        b("generator_on_grid_input",189,"Generator"),n("smart_load_open_delay",192,"min",bounds=(1,120),group="Smart load"),
        s("energy_priority",141,{2:"battery_first",3:"load_first"},"Energy",3),
        s("passive_grid_power_balance",141,{2:"disabled",3:"enabled"},"Energy",12),
        s("active_grid_power_balance",141,{2:"disabled",3:"enabled"},"Energy",48),
        s("grid_export_mode",142,{0:"selling_enabled",1:"zero_export_load",2:"zero_export_ct"},"Energy"),b("solar_sell_enable",145,"Energy"),
        n("output_power_factor",193,"%",10,(80,120),"Grid"),b("solar_arc_fault_mode",181),
        n("restore_grid_connection_time",180,"s",bounds=(10,300),group="Grid"),
        s("grid_measurement_source",344,{0:"ct",1:"meter"},"Meter"),s("meter_manufacturer",345,{1:"eastron",2:"chnt"},"Meter"),
        s("meter_limit_mode",346,{0:"average",1:"minimum"},"Meter"),n("external_ct_ratio",347,":1",bounds=(1,65535),group="Meter")))
    for key,addr,mask in (("microinverter_export_cutoff",178,3),("generator_peak_shaving_enable",178,12),("grid_peak_shaving_enable",178,48),
        ("on_grid_always_on",178,192),("external_relay_enable",178,768),("lithium_battery_loss_fault",178,3072),
        ("external_ct_auto_direction",179,3),("forced_off_grid_mode",179,12)):
        fields.append(s(key,addr,{2:"disabled",3:"enabled"},"System",mask))
    for bit,day in enumerate(("enable","monday","tuesday","wednesday","thursday","friday","saturday","sunday","spain_mode")):
        fields.append(b("time_of_use_"+day,146,"Schedules",1<<bit))
    for i in range(6):
        key="time_of_use_period_"+str(i+1)
        fields.extend((Parameter(key+"_time",148+i,f"Period {i+1} start","time",group="Schedules"),
            n(key+"_power",154+i,"W",.1,group="Schedules"),n(key+"_voltage",160+i,"V",100,group="Schedules"),
            n(key+"_soc",166+i,"%",bounds=(0,100),group="Schedules"),
            b(key+"_grid_charge",172+i,"Schedules",1),b(key+"_generator_charge",172+i,"Schedules",2)))
    return tuple(fields)


DEYE_HIGH=deye_high()
