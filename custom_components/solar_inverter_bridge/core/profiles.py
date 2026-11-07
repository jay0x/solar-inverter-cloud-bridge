"""Protocol maps. Brand names never select a profile by themselves."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    profile_id: str
    name: str
    protocol_number: int | None
    model_codes: tuple[int, ...]
    slave: int
    telemetry_blocks: tuple[tuple[int, int], ...]
    identity_basis: str
    experimental: bool
    evidence: str


PROTOCOL4 = Profile(
    "modbus_protocol_4", "Modbus RTU — Protocol 4", 4, (32771, 32768, 33793), 1,
    ((201, 7), (227, 5), (252, 5), (277, 5), (302, 4), (338, 16), (384, 8), (702, 3)),
    "native_inverter", False, "documented_map_with_32771_hardware_reads_in_predecessor",
)
PROFILES = {PROTOCOL4.profile_id: PROTOCOL4}


def experimental_signature(profile: Profile, model_code: int | None) -> bool:
    return profile.experimental or (profile.profile_id == PROTOCOL4.profile_id and model_code not in (None, 32771))


def match_signature(protocol_number, model_code):
    if type(protocol_number) is not int or type(model_code) is not int:
        return {"result": "unsupported", "reason": "invalid_signature"}
    for profile in PROFILES.values():
        if profile.identity_basis == "native_inverter" and protocol_number == profile.protocol_number and model_code in profile.model_codes:
            experimental = experimental_signature(profile, model_code)
            return {
                "result": "known_unverified" if experimental else "verified",
                "profile_id": profile.profile_id, "profile_name": profile.name,
                "protocol_number": protocol_number, "model_code": model_code, "experimental": experimental,
            }
    return {"result": "unsupported", "reason": "no_known_profile", "protocol_number": protocol_number, "model_code": model_code}


def auto_profile(protocol_number, model_code):
    match = match_signature(protocol_number, model_code)
    if match.get("result") == "verified":
        return PROFILES[match["profile_id"]]
    return None
