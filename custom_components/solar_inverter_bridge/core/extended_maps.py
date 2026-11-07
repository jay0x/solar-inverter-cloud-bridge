"""Reviewed runtime register facts; optional blocks never establish identity.

Sources: pinned ha-eybond-local 6ca2b23 register schemas; MUST 1.4.15 workbook
and SRNE 1.96 document (see docs/development/sources.md). No vendor code is loaded.
"""

from dataclasses import replace


def extend_maps(maps, m):
    def add(profile, fields):
        existing=maps[profile]
        keys={f.key for f in existing.fields}
        maps[profile]=replace(existing,fields=existing.fields+tuple(replace(f,optional=True) for f in fields if f.key not in keys))

    add("must_pv_ph18", (
        m("pv1_current",15207,"A",10),m("mppt_temperature",15209,"°C"),
        # High part is 1000 kWh, low part 0.1 kWh, NOT a binary u32.
        m("pv_energy_total",15217,"kWh",10,words=2,word_order="decimal10000"),
        m("pv_operating_days",15219,"d"),m("inverter_bus_voltage",25208,"V",10),
        m("ac_output_current",25211,"A",10),m("inverter_load_current",25212,"A",10),
        m("inverter_power",25213,"W",signed=True),m("grid_power",25214,"W",signed=True),
        m("transformer_temperature",25234,"°C"),m("battery_power",25273,"W",signed=True),
        m("battery_current",25274,"A",signed=True),
    ))
    for key in ("must_pv3300","must_pv3900"):
        previous=maps[key]
        common=maps["must_pv_ph18"].fields
        maps[key]=replace(previous,fields=tuple(replace(f,divisor=1) if key=="must_pv3300" and f.key=="load_percent" else f for f in common))
        add(key,(m("bms_voltage",109,"V",10),m("bms_current",110,"A",10,True),
                 m("bms_temperature",111,"°C"),m("battery_soc",113,"%",signed=True)))

    # Protocol 1.96 uses unsigned voltages/frequencies/PV/load power. Keep the
    # existing battery-current sign; expose direction rather than rewriting history.
    srne=maps["srne_modbus"]
    maps["srne_modbus"]=replace(srne,name="SRNE Modbus — v1.96-compatible map",
        source="https://github.com/syssi/esphome-smg-ii/blob/b0ff1caec3ce395d774fcf496fcc03a75f925ca2/docs/SRNE.Solar.Charge.Inverter.MODBUS.Protocol1.96.pdf",
        fields=tuple(replace(f,signed=False) if f.key!="battery_current" else f for f in srne.fields))
    add("srne_modbus", (
        m("rated_battery_voltage",0xE003,"V"),
        m("battery_temperature",259,"°C",10,True),m("pv1_current",264,"A",10),
        m("pv_power",266,"W"),m("pv2_voltage",271,"V",10),m("pv2_current",272,"A",10),m("pv2_power",273,"W"),
        m("grid_current",532,"A",10),m("output_current",537,"A",10),m("output_apparent_power",540,"VA"),
        m("ac_charging_current",542,"A",10),m("dcdc_temperature",544,"°C",10,True),m("inverter_temperature",545,"°C",10,True),
        m("grid_voltage_l2",554,"V",10),m("grid_voltage_l3",555,"V",10),
        m("output_voltage_l2",556,"V",10),m("output_voltage_l3",557,"V",10),
        m("output_current_l2",560,"A",10),m("output_current_l3",561,"A",10),
        m("output_power_l2",562,"W"),m("output_power_l3",563,"W"),
        m("output_apparent_power_l2",564,"VA"),m("output_apparent_power_l3",565,"VA"),
        m("load_percent_l2",566,"%"),m("load_percent_l3",567,"%"),
    ))
    add("growatt_spf", (
        m("pv1_voltage",1,"V",10),m("pv2_voltage",2,"V",10),m("pv2_power",5,"W",10,words=2),
        m("output_apparent_power",11,"VA",10,words=2),m("inverter_charging_power",13,"W",10,words=2),
        m("bus_voltage",19,"V",10),m("dcdc_temperature",26,"°C",10,True),
        m("buck1_temperature",32,"°C",10,True),m("buck2_temperature",33,"°C",10,True),
        m("output_current",34,"A",10),m("grid_input_power",36,"W",10,words=2),
        *(m(key,address,"kWh",10,words=2) for key,address in (
            ("pv1_energy_today",48),("pv1_energy_total",50),("pv2_energy_today",52),("pv2_energy_total",54),
            ("ac_charge_energy_today",56),("ac_charge_energy_total",58),("battery_discharge_energy_today",60),
            ("battery_discharge_energy_total",62),("load_energy_today",64),("load_energy_total",66))),
        m("ac_charging_current",68,"A",10),m("battery_power",77,"W",-10,True,2),
        m("mppt_fan_speed",81,"%"),m("inverter_fan_speed",82,"%"),m("bms_soc",93,"%"),
    ))
    add("deye_lv", (
        *(m(key,address,"kWh",10) for key,address in (("battery_charge_energy_today",70),("battery_discharge_energy_today",71),
            ("grid_import_energy_today",76),("grid_export_energy_today",77),("load_energy_today",84),("pv_energy_today",108))),
        *(m(key,address,"kWh",10,words=2,word_order="low_first") for key,address in (
            ("battery_charge_energy_total",72),("battery_discharge_energy_total",74),("grid_export_energy_total",81),
            ("load_energy_total",85),("pv_energy_total",96))),
        m("transformer_temperature",90,"°C",10,offset=-1000),m("inverter_temperature",91,"°C",10,offset=-1000),
        m("pv1_voltage",109,"V",10),m("pv1_current",110,"A",10),m("pv2_voltage",111,"V",10),m("pv2_current",112,"A",10),
        m("grid_current",160,"A",100,True),m("generator_power",166,"W",signed=True),m("grid_power",169,"W",signed=True),
        m("external_ct_power",172,"W",signed=True),m("inverter_power",175,"W",signed=True),
        m("battery_temperature",182,"°C",10,offset=-1000),m("pv2_power",187,"W"),m("pv3_power",188,"W"),m("pv4_power",189,"W"),
        m("battery_power",190,"W",-1,True),m("bms_soc",316,"%"),m("bms_voltage",317,"V",100),
        m("bms_temperature",319,"°C",10,offset=-1000),m("bms_max_charging_current",320,"A"),m("bms_max_discharge_current",321,"A"),
    ))
    add("deye_3ph_high_80kw", (
        *(m(key,address,"kWh",10) for key,address in (("battery_charge_energy_today",514),("battery_discharge_energy_today",515),
            ("grid_import_energy_today",520),("grid_export_energy_today",521),("load_energy_today",526),("pv_energy_today",529))),
        *(m(key,address,"kWh",10,words=2,word_order="low_first") for key,address in (("battery_charge_energy_total",516),
            ("battery_discharge_energy_total",518),("grid_import_energy_total",522),("grid_export_energy_total",524),
            ("load_energy_total",527),("pv_energy_total",534))),
        m("inverter_temperature",541,"°C",10,offset=-1000),m("battery_temperature",586,"°C",10),m("battery_current",591,"A",100,True),
        *(m("grid_current_l"+str(i+1),610+i,"A",100,True) for i in range(3)),
        *(m("external_grid_power_l"+str(i+1),616+i,"W",signed=True) for i in range(3)),
        m("external_grid_power",619,"W",signed=True),
        *(m("grid_power_l"+str(i+1),622+i,"W",signed=True) for i in range(3)),
        *(m("load_power_l"+str(i+1),650+i,"W",signed=True) for i in range(3)),
        m("load_total_power_raw",653,None,signed=True),
        *(m("generator_voltage_l"+str(i+1),661+i,"V",10) for i in range(3)),
        *(m("generator_power_l"+str(i+1),664+i,"W",signed=True) for i in range(3)),m("generator_power",667,"W",signed=True),
        m("pv3_power",674,"W"),m("pv4_power",675,"W"),m("pv1_current",677,"A",10),m("pv2_current",679,"A",10),
        m("pv3_voltage",680,"V",10),m("pv3_current",681,"A",10),m("pv4_voltage",682,"V",10),m("pv4_current",683,"A",10),
    ))
    add("aohai_fsa", (
        m("output_current",5,"A",10,True),m("bus_voltage",8,"V",10),m("boost_temperature",11,"°C",10,True),
        m("llc_temperature",12,"°C",10,True),m("external_ntc_temperature",13,"°C",10,True),m("grid_current",43,"A",10,True),
        m("eps_voltage",55,"V",10),m("eps_current",56,"A",10),m("pv1_voltage",64,"V",10),m("pv1_current",65,"A",10),
        m("generator_voltage",96,"V",10),m("generator_current",97,"A",10),m("battery_temperature",142,"°C",10,True),
        m("bms_max_charging_current",143,"A",10),m("bms_max_discharge_current",144,"A",10),m("battery_soh",152,"%"),
        m("inverter_apparent_power",284,"VA",10,words=2),m("inverter_power",286,"W",-10,True,2),
        m("reactive_power",288,"var",10,True,2),m("power_to_user",320,"W",10,words=2),m("output_power",330,"W",10,words=2),
        *(m(key,address,"kWh",10,words=2) for key,address in (("pv_energy_today",379),("pv_energy_total",381),
            ("battery_charge_energy_today",383),("battery_charge_energy_total",385),("battery_discharge_energy_today",387),("battery_discharge_energy_total",389))),
    ))
    add("solis_esinv", (
        m("pv1_voltage",33049,"V",10),m("pv1_current",33050,"A",10),m("pv2_voltage",33051,"V",10),m("pv2_current",33052,"A",10),
        m("pv_power",33057,"W",words=2),m("bus_voltage",33071,"V",10),m("grid_current",33076,"A",10),
        m("inverter_power",33079,"W",signed=True,words=2),m("backup_voltage",33137,"V",10),m("battery_soh",33140,"%"),
        m("bms_max_charging_current",33143,"A",10),m("bms_max_discharge_current",33144,"A",10),
        m("output_power",33147,"W"),m("backup_load_power",33148,"W"),m("battery_power_raw",33149,"W",signed=True,words=2),
        m("grid_power",33151,"W",signed=True,words=2),
        *(m(key,address,"kWh",10) for key,address in (("pv_energy_today",33035),("battery_charge_energy_today",33163),
            ("battery_discharge_energy_today",33167),("grid_import_energy_today",33171),("grid_export_energy_today",33175),("load_energy_today",33179))),
        *(m(key,address,"kWh",words=2) for key,address in (("pv_energy_total",33029),("battery_charge_energy_total",33161),
            ("battery_discharge_energy_total",33165),("grid_import_energy_total",33169),("grid_export_energy_total",33173),("load_energy_total",33177))),
    ))
    add("hopewind_0237", (
        *(m("pv"+str(i+1)+"_voltage",40500+i,"V",10,True) for i in range(8)),
        *(m("pv"+str(i+1)+"_power",40524+i,"W",.1) for i in range(8)),
        *(m("pv_string_"+str(i+1)+"_current",40508+i,"A",100,True) for i in range(16)),
        *(m("pv_string_"+str(i+17)+"_current",40588+i,"A",100,True) for i in range(4)),
        *(m("grid_current_l"+str(i+1),40535+i,"A",10,True) for i in range(3)),
        m("inverter_generation_power",40539,"W",.1,True),m("reactive_power",40540,"var",.1,True),m("pv_power",40541,"W",.1,True),
        m("inverter_efficiency",40542,"%",100),m("insulation_resistance",40545,"kΩ",10),
        m("pv_energy_today",40548,"kWh",100,words=2,word_order="low_first"),m("pv_energy_total",40550,"kWh",100,words=2,word_order="low_first"),
        m("co2_reduction",40552,"kg",100,words=2,word_order="low_first"),m("running_time_today",40554,"h",100),
        m("running_time_total",40555,"h",100,words=2,word_order="low_first"),m("bus_voltage",40586,"V",10),m("positive_bus_voltage",40587,"V",10),
        m("inverter_apparent_power",40594,"VA",.1,True),m("rated_power",40646,"W",.001),m("rated_voltage",40647,"V"),
    ))
