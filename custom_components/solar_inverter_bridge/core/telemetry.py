"""Protocol 4 measurements adapted from the predecessor's documented decoder."""

from .framing import FrameError
from .profiles import PROTOCOL4

FIELDS = (
    ("grid_frequency", 203, 100, "Hz"), ("ac_charging_power", 206, 1, "W"),
    ("inverter_frequency", 227, 100, "Hz"), ("inverter_temperature", 231, 1, "°C"),
    ("output_current", 252, 10, "A"), ("output_frequency", 253, 100, "Hz"),
    ("output_power", 254, 1, "W"), ("output_apparent_power", 255, 1, "VA"), ("load_percent", 256, 1, "%"),
    ("battery_voltage", 277, 10, "V"), ("battery_current", 278, 10, "A"), ("battery_power", 279, 1, "W"),
    ("dc_temperature", 281, 1, "°C"), ("pv_power", 302, 1, "W"), ("pv_charging_power", 303, 1, "W"),
    ("pv_charging_current", 304, 10, "A"), ("pv_temperature", 305, 1, "°C"),
    ("grid_voltage", 338, 10, "V"), ("grid_power", 340, 1, "W"), ("inverter_voltage", 342, 10, "V"),
    ("inverter_current", 343, 10, "A"), ("output_voltage", 346, 10, "V"),
    ("pv1_voltage", 351, 10, "V"), ("pv1_current", 352, 10, "A"), ("pv1_power", 353, 1, "W"),
    ("second_output_voltage", 384, 10, "V"), ("pv2_voltage", 389, 10, "V"), ("pv2_current", 390, 10, "A"),
    ("pv2_power", 391, 1, "W"),
)
MODES = {0: "power_on", 1: "standby", 2: "mains", 3: "off_grid", 4: "bypass", 5: "charging", 6: "fault"}
COMMON_ADDRESSES = frozenset((201,203,231,253,254,256,277,280,302,338,346,351,353))


def required_addresses():
    return {address for start, count in PROTOCOL4.telemetry_blocks for address in range(start, start + count)}


def decode(registers: dict[int, int], *, require_full=True) -> dict:
    required = required_addresses() if require_full else COMMON_ADDRESSES
    if not required.issubset(registers):
        raise FrameError("incomplete_telemetry")
    if any(type(value) is not int or not 0 <= value <= 65535 for value in registers.values()):
        raise FrameError("invalid_register_word")
    if registers[201] not in MODES or not 0 <= registers[280] <= 100:
        raise FrameError("invalid_mode_or_soc")
    values = {
        "operating_mode": {"value": MODES[registers[201]], "unit": None},
        "battery_soc": {"value": registers[280], "unit": "%"},
    }
    for key, address, divisor, unit in FIELDS:
        if address not in registers:
            continue
        raw = registers[address]
        signed = raw - 65536 if raw >= 32768 else raw
        values[key] = {"value": signed if divisor == 1 else round(signed / divisor, 2), "unit": unit}
    if not any(0 < values[key]["value"] < limit for key, limit in (("battery_voltage", 1000), ("grid_voltage", 300), ("output_voltage", 300))):
        raise FrameError("implausible_voltage_snapshot")
    if any(not 0 <= values[key]["value"] <= 70 for key in ("grid_frequency", "output_frequency", "inverter_frequency") if key in values):
        raise FrameError("invalid_frequency")
    if not 0 <= values["load_percent"]["value"] <= 300:
        raise FrameError("implausible_load_percent")
    if "battery_current" in values:
        values["battery_charging_current"] = {"value": max(0, values["battery_current"]["value"]), "unit": "A"}
        values["battery_discharge_current"] = {"value": max(0, -values["battery_current"]["value"]), "unit": "A"}
    if 702 in registers:
        values["pv_energy_today"] = {"value": registers[702] / 100, "unit": "kWh"}
    if 703 in registers and 704 in registers:
        values["pv_energy_total"] = {"value": ((registers[703] << 16) | registers[704]) / 100, "unit": "kWh"}
    return values


async def read_registers(reader, writer, timeout=5):
    """One Protocol 4 plan for reference and accepted-family devices.

An illegal-address exception permits only the documented common addresses to be
retried within that block. Other errors remain failures; no register sweep occurs.
"""
    from .exchange import read_words
    registers = {}
    for address, count in PROTOCOL4.telemetry_blocks:
        try:
            words, _, _ = await read_words(reader, writer, address, count, timeout=timeout)
        except FrameError as error:
            if error.exception_code != 2:
                raise
            for required in sorted(COMMON_ADDRESSES.intersection(range(address,address+count))):
                words, _, _ = await read_words(reader, writer, required, 1, timeout=timeout)
                registers[required] = words[0]
        else:
            registers.update({address+i:word for i,word in enumerate(words)})
    return registers


def sensor_descriptors():
    sample = decode({address: 0 for address in required_addresses()} | {201: 2, 277: 480, 280: 50, 338: 2300, 346: 2300})
    classes = {"W": "power", "VA": "apparent_power", "V": "voltage", "A": "current", "Hz": "frequency", "°C": "temperature", "kWh": "energy"}
    return tuple({
        "key": key, "name": key.replace("_", " ").title(), "unit": value["unit"],
        "device_class": "battery" if key == "battery_soc" else "enum" if key == "operating_mode" else classes.get(value["unit"]),
        "state_class": "total_increasing" if value["unit"] == "kWh" else "measurement" if value["unit"] is not None else None,
        "options": list(MODES.values()) if key == "operating_mode" else None,
    } for key, value in sample.items())
