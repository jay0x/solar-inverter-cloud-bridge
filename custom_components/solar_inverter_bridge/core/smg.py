"""Shared SMG families and explicit protocol deltas, not retail-brand maps.

Protocol facts: groove-max/ha-eybond-local 6ca2b23, modbus_smg catalogs.
See docs/PROFILE_EXPANSION.md for provenance and qualification boundaries.
"""

from dataclasses import dataclass, replace

from .parameters import FIELDS, Parameter


LOW_FIELDS = (
    Parameter("buzzer_mode",303,"Buzzer mode","select",options={0:"silent",1:"enabled",2:"mute_source_change",3:"fault_only"}),
    Parameter("lcd_backlight",305,"Display backlight","select",options={0:"timed_off",1:"always_on"}),
    Parameter("primary_output_priority",301,"Output source priority","select",options={0:"utility_first",1:"solar_first",2:"sbu",3:"sub"}),
    Parameter("primary_charging_priority",331,"Charging source priority","select",options={0:"utility_first",1:"solar_first",2:"solar_and_utility",3:"solar_only"}),
    Parameter("bulk_charging_voltage",324,"Bulk charging voltage",unit="V",divisor=10),
    Parameter("float_charging_voltage",325,"Float charging voltage",unit="V",divisor=10),
    Parameter("battery_recovery_voltage_ac",326,"Battery recovery voltage",unit="V",divisor=10),
    Parameter("battery_protection_voltage_ac",327,"Battery protection voltage",unit="V",divisor=10),
    Parameter("battery_protection_voltage_offgrid",329,"Off-grid battery protection voltage",unit="V",divisor=10),
    Parameter("maximum_charging_current",332,"Maximum charging current",unit="A",divisor=10),
    Parameter("maximum_ac_charging_current",333,"Maximum AC charging current",unit="A",divisor=10),
)

# Only the source-confirmed common subset inherits reference Protocol 4 fields.
# Model-specific controls such as output topology do not follow automatically.
HIGH_KEYS = {
    "buzzer_mode", "lcd_backlight", "lcd_return_home", "energy_saving",
    "overload_restart", "overtemperature_restart", "overload_bypass",
    "primary_output_priority", "primary_charging_priority", "secondary_output_priority",
    "secondary_output_start", "secondary_output_stop", "secondary_charging_priority",
    "secondary_charging_start", "secondary_charging_stop", "bulk_charging_voltage",
    "float_charging_voltage", "maximum_charging_current", "maximum_ac_charging_current",
    "battery_recovery_voltage_ac", "battery_protection_voltage_ac",
    "battery_protection_voltage_offgrid", "battery_protection_soc_ac", "battery_recovery_soc_ac",
}
HIGH_FIELDS = tuple(field for field in FIELDS if field.key in HIGH_KEYS)


def _low_variant(**options):
    return tuple(replace(field, options=options[field.key]) if field.key in options else field
                 for field in LOW_FIELDS)


@dataclass(frozen=True)
class SMGVariant:
    protocol_number: int | None
    layout: str
    controls: tuple[Parameter, ...]
    model_codes: tuple[int, ...] = ()  # Evidence hints, not an acceptance allowlist.
    output_power_address: int | None = None
    load_percent_address: int | None = None
    omitted_measurements: tuple[str, ...] = ()


# An unlisted protocol does not inherit a high-map control set by default.
# Retail aliases and model-specific qualification belong in DEVICE_COMPATIBILITY.md.
SMG_VARIANTS = {
    "smg_legacy": SMGVariant(None, "low", LOW_FIELDS),
    "smg_1": SMGVariant(1, "low", LOW_FIELDS),
    "smg_2": SMGVariant(2, "low", _low_variant(
        primary_output_priority={1:"sub",2:"sbu",3:"suf_grid_export",4:"zec_requires_ct"},
        primary_charging_priority={1:"solar_first",2:"solar_and_utility",3:"solar_only",4:"solar_with_load_reserve"},
    ), model_codes=(8960,)),
    "smg_3": SMGVariant(3, "high", HIGH_FIELDS, (29440,), 348, 350),
    "smg_4": SMGVariant(4, "high", FIELDS, (32771,32768,33793), 254, 256),
    "smg_5": SMGVariant(5, "high", HIGH_FIELDS, (), 348, 350, ("pv_power",)),
    "smg_6": SMGVariant(6, "high", HIGH_FIELDS, (), 254, 256, ("pv_power",)),
    "smg_11": SMGVariant(11, "low", _low_variant(
        primary_charging_priority={1:"solar_first",2:"solar_and_utility",3:"solar_only"},
    ), model_codes=(30979,)),
}
