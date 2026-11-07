"""Independent 09C1 fixed-column decoder from pinned public wire facts.

Reference: ha-eybond-local 6ca2b23, payload/urtu09c1.py and the documented
09C1 formats. Plain ASCII + CR; no address/checksum prefix or inferred power.
"""

import re

READ_COMMANDS = ("Q1", "QF", "PV?", "F")
MEASUREMENTS = (
    ("grid_voltage", "V"), ("last_fault_voltage", "V"), ("output_voltage", "V"),
    ("load_percent", "%"), ("grid_frequency", "Hz"), ("battery_voltage", "V"),
    ("inverter_temperature", "°C"), ("output_frequency", "Hz"),
    ("pv_voltage", "V"), ("pv_current", "A"),
    ("rated_output_voltage", "V"), ("rated_power", "W"),
    ("rated_battery_voltage", "V"), ("rated_frequency", "Hz"),
)
PATTERNS = {
    "Q1": rb"\((\d{3}\.\d) (\d{3}\.\d) (\d{3}\.\d) (\d{3}) (\d{2}\.\d) (\d{2}\.\d) ((?:\d{2}|-\d)\.\d) ([01]{8})\r",
    "QF": rb"\((\d{2}\.\d)\r",
    "PV?": rb"\((\d{4}) (\d{3}) \d \d{6}\r",
    "F": rb"\((\d{3}\.\d) (\d{2}K|\d\.\d|\d{3}) (\d{2}\.\d{2}) (\d{2}\.\d)\r",
}


def parse_reply(command, frame):
    pattern = PATTERNS.get(command)
    if pattern is None:
        raise ValueError("eybond_09c1_query_unsupported")
    match = re.fullmatch(pattern, frame)
    if match is None:
        raise ValueError("eybond_09c1_reply_shape")
    return match.groups()


def decode_cycle(responses):
    parsed = {command: parse_reply(command, b"(" + responses[command].encode("ascii") + b"\r")
              for command in READ_COMMANDS}
    q1, frequency, pv, rating = (parsed[command] for command in READ_COMMANDS)
    values = {key: {"value": float(raw), "unit": unit}
              for (key, unit), raw in zip(MEASUREMENTS[:7], q1[:7])}
    values["output_frequency"] = {"value": float(frequency[0]), "unit": "Hz"}
    values["pv_voltage"] = {"value": int(pv[0]) / 10, "unit": "V"}
    values["pv_current"] = {"value": int(pv[1]) / 10, "unit": "A"}
    raw_power = rating[1].decode("ascii")
    power = float(raw_power[:-1]) * 1000 if raw_power.endswith("K") else float(raw_power) * (1000 if "." in raw_power else 1)
    for key, value, unit in (("rated_output_voltage", float(rating[0]), "V"), ("rated_power", power, "W"),
                             ("rated_battery_voltage", float(rating[2]), "V"), ("rated_frequency", float(rating[3]), "Hz")):
        values[key] = {"value": value, "unit": unit}
    if power <= 0 or not 40 <= values["rated_frequency"]["value"] <= 70:
        raise ValueError("eybond_09c1_invalid_rating")
    flags = q1[7].decode("ascii")
    mode = {"00": "bypass", "01": "avr", "10": "battery_energy_saving", "11": "inverter_failure"}[flags[4:6]]
    # No unique inverter serial is known. Do not turn readings or configurable
    # ratings into identity; the binding identifies only this wire family.
    signature = ["eybond_09c1", 47, 6, 19, 22]
    return values, mode, signature
