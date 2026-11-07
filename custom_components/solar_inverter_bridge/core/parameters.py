"""Documented Protocol 4 parameter inventory. Listing is not hardware qualification."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal


READ_ONLY = {605, 636}
OUTPUT = {1: "sub", 2: "sbu", 3: "suf"}
CHARGE = {1: "sof", 2: "snu", 3: "oso", 4: "sor"}
BOOL = {0: "disabled", 1: "enabled"}


@dataclass(frozen=True)
class Parameter:
    key: str
    address: int
    name: str
    kind: str = "number"
    unit: str | None = None
    options: dict | None = None
    bounds: tuple | None = None
    divisor: int = 1
    zero_value: str | None = None
    read_only: bool = False
    mask: int | None = None
    group: str | None = None
    wire_max: int = 65535


FIELDS = (
    Parameter("output_mode", 600, "Output mode", "select", options={0: "single", 1: "parallel", 2: "three_phase_p1", 3: "three_phase_p2", 4: "three_phase_p3", 5: "split_phase_p1", 6: "split_phase_p2"}),
    Parameter("primary_output_priority", 601, "Primary output priority", "select", options=OUTPUT),
    Parameter("secondary_output_priority", 602, "Secondary output priority", "select", options={0: "off", **OUTPUT}),
    Parameter("secondary_output_start", 603, "Secondary output priority start", "time"),
    Parameter("secondary_output_stop", 604, "Secondary output priority stop", "time"),
    Parameter("current_output_priority", 605, "Current output priority", "select", options=OUTPUT, read_only=True),
    Parameter("output_voltage_setting", 606, "Output voltage setting", "select", "V", options={2200: "220", 2300: "230", 2400: "240"}),
    Parameter("output_frequency_setting", 607, "Output frequency setting", "select", "Hz", options={5000: "50", 6000: "60"}),
    Parameter("secondary_output_overload_alarm", 608, "Secondary output overload threshold", unit="%", bounds=(10, 100)),
    Parameter("secondary_output_enabled", 609, "Secondary output enabled", "select", options=BOOL),
    Parameter("secondary_output_start_hour", 610, "Secondary output start hour", unit="h", bounds=(0, 23)),
    Parameter("secondary_output_stop_hour", 611, "Secondary output stop hour", unit="h", bounds=(0, 23)),
    Parameter("battery_type", 630, "Battery type", "select", options={0: "agm", 1: "fld", 2: "user", 4: "li2", 6: "li4", 8: "lib"}),
    Parameter("battery_overvoltage_protection", 631, "Battery overvoltage protection", unit="V", divisor=10),
    Parameter("primary_charging_priority", 632, "Primary charging priority", "select", options=CHARGE),
    Parameter("secondary_charging_priority", 633, "Secondary charging priority", "select", options={0: "off", **CHARGE}),
    Parameter("secondary_charging_start", 634, "Secondary charging priority start", "time"),
    Parameter("secondary_charging_stop", 635, "Secondary charging priority stop", "time"),
    Parameter("current_charging_priority", 636, "Current charging priority", "select", options=CHARGE, read_only=True),
    Parameter("bulk_charging_voltage", 637, "Bulk charging voltage", unit="V", divisor=10),
    Parameter("float_charging_voltage", 638, "Float charging voltage", unit="V", divisor=10),
    Parameter("constant_voltage_time", 639, "Constant voltage duration (0: default)", unit="min", bounds=(0, 900)),
    Parameter("maximum_charging_current", 640, "Maximum charging current", unit="A", divisor=10),
    Parameter("maximum_ac_charging_current", 641, "Maximum AC charging current", unit="A", divisor=10),
    Parameter("maximum_discharge_current", 642, "Maximum discharge current protection", unit="A", bounds=(0, 500)),
    Parameter("battery_recovery_voltage_ac", 643, "Battery recovery voltage in AC mode", unit="V", divisor=10, zero_value="full_recovery"),
    Parameter("battery_protection_voltage_ac", 644, "Battery protection voltage in AC mode", unit="V", divisor=10),
    Parameter("op1_protection_voltage_offgrid", 645, "OP1 protection voltage off-grid", unit="V", divisor=10),
    Parameter("battery_protection_voltage_offgrid", 646, "Battery protection voltage off-grid", unit="V", divisor=10),
    Parameter("battery_protection_soc_ac", 647, "Battery protection SOC in AC mode", "number", "%", bounds=(0, 100)),
    Parameter("battery_recovery_soc_ac", 648, "Battery recovery SOC in AC mode", "number", "%", bounds=(0, 100)),
    Parameter("op1_protection_soc_offgrid", 649, "OP1 protection SOC off-grid", "number", "%", bounds=(0, 100)),
    Parameter("battery_protection_soc_offgrid", 650, "Battery protection SOC off-grid", "number", "%", bounds=(0, 100)),
    Parameter("equalization_enabled", 651, "Battery equalization enabled", "select", options=BOOL),
    Parameter("equalization_voltage", 652, "Equalization voltage", unit="V", divisor=10),
    Parameter("equalization_time", 653, "Equalization duration", unit="min", bounds=(0, 900)),
    Parameter("equalization_timeout", 654, "Equalization timeout", unit="min", bounds=(0, 900)),
    Parameter("equalization_interval", 655, "Equalization interval", unit="d", bounds=(1, 90)),
    Parameter("input_mode", 677, "AC input mode", "select", options={0: "apl", 1: "ups", 2: "generator"}),
    Parameter("buzzer_mode", 678, "Buzzer mode", "select", options={0: "silent", 1: "fault_warning_source_change", 2: "fault_warning", 3: "fault"}),
    Parameter("lcd_backlight", 679, "Display backlight", "select", options={0: "timed_off", 1: "always_on"}),
    Parameter("lcd_return_home", 680, "Display return to home", "select", options=BOOL),
    Parameter("energy_saving", 681, "Energy saving", "select", options=BOOL),
    Parameter("overload_restart", 682, "Restart after overload", "select", options=BOOL),
    Parameter("overtemperature_restart", 683, "Restart after overtemperature", "select", options=BOOL),
    Parameter("overload_bypass", 684, "Bypass on overload", "select", options=BOOL),
    Parameter("dry_contact", 689, "Dry contact mode", "select", options={0: "normal", 1: "grounded_box"}),
    Parameter("automatic_mains_output", 690, "Automatic AC output", "select", options=BOOL),
    Parameter("boot_method", 693, "Startup method", "select", options={0: "local_or_remote", 1: "local_only", 2: "remote_only"}),
    Parameter("remote_switch", 694, "Remote switch", "select", options={0: "off", 1: "on"}),
    Parameter("inverter_datetime", 696, "Inverter date and time", "datetime"),
)


def access_class(field: Parameter) -> str:
    if field.read_only:
        return "read_only"
    return "writable"


SETTINGS_BLOCKS = ((600, 12), (630, 26), (677, 8), (689, 2), (693, 2), (696, 6))


def execution_ready(field: Parameter) -> bool:
    if access_class(field) == "read_only" or field.kind == "datetime":
        return False
    return field.options is not None or field.kind in ("time", "number")


def parameter_group(address: int) -> str:
    if address < 630:
        return "Output"
    if address in (*range(632, 637), 639, 640, 641, *range(651, 656)):
        return "Charging"
    if address < 677:
        return "Battery"
    if address < 689:
        return "AC input and display"
    return "Contact and clock"


def inventory(fields=None):
    return tuple({
        "key": field.key, "name": field.name, "address": field.address, "kind": field.kind,
        "unit": field.unit, "access": access_class(field), "group": field.group or parameter_group(field.address),
        "options": None if field.options is None else tuple(field.options.values()),
        "bounds": field.bounds,
        "protocol_access": "R" if field.read_only else "R/W",
        "step": 1 / field.divisor if field.kind == "number" else None,
        "wire_bounds": (0, field.wire_max / field.divisor) if field.kind == "number" else None,
        "zero_value": field.zero_value,
        "warning": "manufacturer_limits_unknown" if field.kind == "number" and field.bounds is None else None,
        "managed_by": "clock_sync" if field.kind == "datetime" else None,
        "execution_ready": execution_ready(field),
    } for field in (FIELDS if fields is None else fields))


def encode_value(field: Parameter, value):
    if field.read_only:
        raise ValueError("read_only_parameter")
    if field.kind == "datetime":
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value):
            raise ValueError("clock_requires_local_datetime_without_timezone")
        clock = datetime.fromisoformat(value)
        return (clock.year, clock.month, clock.day, clock.hour, clock.minute, clock.second)
    if field.options is not None:
        if not isinstance(value, str) or value not in field.options.values():
            raise ValueError("invalid_enum")
        return (next(raw for raw, label in field.options.items() if label == value),)
    if field.kind == "time":
        if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d:00", value):
            raise ValueError("time_requires_HH_MM_00")
        return (int(value[:2]) * 100 + int(value[3:5]),)
    if field.zero_value is not None and value == field.zero_value:
        return (0,)
    if type(value) not in (int, float):
        raise ValueError("numeric_value_required")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("finite_numeric_value_required")
    if field.bounds is not None and not Decimal(str(field.bounds[0])) <= number <= Decimal(str(field.bounds[1])):
        raise ValueError("value_outside_documented_bounds")
    raw = number * Decimal(str(field.divisor))
    if raw != raw.to_integral_value():
        raise ValueError("value_outside_register_step")
    # This is the uint16 wire format, not a claim about manufacturer-safe limits.
    if not 0 <= raw <= field.wire_max:
        raise ValueError("value_outside_register_range")
    return (int(raw),)


def validate_change(field: Parameter, value, observed):
    """Validate documented dependencies against a fresh read, not a UI cache."""
    if observed.get(field.key) is None:
        raise ValueError("parameter_not_observed")
    merged = {**observed, field.key: value}
    for prefix in ("secondary_output", "secondary_charging"):
        if field.key not in (prefix + "_priority", prefix + "_start", prefix + "_stop"):
            continue
        if field.key == prefix + "_priority" and value == "off":
            continue
        start, stop = merged.get(prefix + "_start"), merged.get(prefix + "_stop")
        if start is None or stop is None or start >= stop:
            raise ValueError("ambiguous_schedule_window")
    if field.key in ("battery_protection_soc_ac", "battery_recovery_soc_ac"):
        protection, recovery = merged.get("battery_protection_soc_ac"), merged.get("battery_recovery_soc_ac")
        if protection is None or recovery is None or protection >= recovery:
            raise ValueError("soc_recovery_must_exceed_protection")
    if field.key == "equalization_enabled" and value == "enabled" and observed.get("battery_type") not in ("agm", "fld"):
        raise ValueError("equalization_not_qualified_for_battery_type")
    if field.key == "battery_type" and value in ("li2", "li4", "lib") and observed.get("equalization_enabled") != "disabled":
        raise ValueError("disable_equalization_before_lithium_profile")


def readback_matches(field, desired_words, observed_words, record, poll_interval=10, now_utc=None):
    if field.kind != "datetime":
        return tuple(observed_words) == tuple(desired_words)
    # A running clock cannot equal an old command's literal words forever.
    # Resolve only its expected evolution from the durable send-intent timestamp.
    # Original uncertainty remains in the ledger even when this observation matches.
    if not record.get("send_intent_at"):
        return False
    try:
        sent_at = datetime.fromisoformat(record["send_intent_at"])
        elapsed = ((now_utc or datetime.now(timezone.utc)) - sent_at).total_seconds()
        if elapsed < 0:
            return False
        expected = datetime(*desired_words) + timedelta(seconds=elapsed)
        observed = datetime(*observed_words)
        return abs((observed - expected).total_seconds()) <= max(3, 3 * poll_interval)
    except (TypeError, ValueError, OverflowError):
        return False


def decode_observed(registers: dict, fields=None):
    values = {}
    for field in (FIELDS if fields is None else fields):
        if field.kind == "datetime":
            words = [registers.get(address) for address in range(696, 702)]
            if any(type(word) is not int for word in words):
                continue
            try:
                values[field.key] = datetime(*words).isoformat()
            except ValueError:
                values[field.key] = None
            continue
        raw = registers.get(field.address)
        if type(raw) is not int:
            continue
        if field.mask is not None:
            raw=(raw & field.mask)//(field.mask & -field.mask)
        if field.options is not None:
            values[field.key] = field.options.get(raw)
        elif field.kind == "time":
            values[field.key] = None if raw // 100 > 23 or raw % 100 > 59 else f"{raw // 100:02d}:{raw % 100:02d}:00"
        elif field.zero_value is not None and raw == 0:
            values[field.key] = field.zero_value
        else:
            scaled = raw if field.divisor == 1 else raw / field.divisor
            values[field.key] = scaled if field.bounds is None or field.bounds[0] <= scaled <= field.bounds[1] else None
    return values


def merge_masked_value(field, words, baseline_raw):
    if field.mask is None:
        return tuple(words)
    if type(baseline_raw) is not int or len(words)!=1 or not 0<field.mask<=65535:
        raise ValueError("masked_baseline_required")
    shifted=words[0]*(field.mask & -field.mask)
    if shifted & ~field.mask:
        raise ValueError("value_outside_bitmask")
    return ((baseline_raw & ~field.mask)|shifted,)


def editing_allowed(mode: str, field: Parameter) -> bool:
    """Legacy mode argument cannot restrict an implemented writable setting."""
    return execution_ready(field)
