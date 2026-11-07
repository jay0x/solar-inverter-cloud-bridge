"""User-facing families and canonical names, independent of saved enrollment IDs."""

from .catalogue import MAPS, descriptors


def canonical_id(profile_id):
    if profile_id in ("must_pv3300","must_pv3900"):
        return "must_pv_ph18"
    return "smg_4" if profile_id == "modbus_protocol_4" else profile_id


def profile_name(profile_id):
    key = canonical_id(profile_id)
    if key == "smg_legacy":
        return "SMG Classic — variant not identified"
    if key=="must_pv_ph18":
        return "MUST PV/PH18 — automatic model variant"
    return MAPS[key].name if key in MAPS else profile_id


def family_info(profile_id):
    key = canonical_id(profile_id)
    if key in ("pi30","pi30_max"):
        return {"family_id":"pi30","family_name":"PI30 family","variant":"MAX 2021 write dialect" if key=="pi30_max" else "Standard 2015 write dialect"}
    if key in ("smg_legacy", "smg_1", "smg_2", "smg_11"):
        return {"family_id":"smg_classic", "family_name":"SMG · Classic", "variant":"Unidentified variant" if key=="smg_legacy" else "Protocol "+key[4:]}
    if key.startswith("smg_"):
        return {"family_id":"smg_2024", "family_name":"SMG · 2024 map", "variant":"Protocol "+key[4:]}
    if key.startswith("smartess_"):
        return {"family_id":"smartess", "family_name":"SmartESS protocol assets", "variant":"Asset "+key[9:]}
    if key.startswith("must_"):
        return {"family_id":"must", "family_name":"MUST Modbus", "variant":profile_name(key)}
    if key.startswith("deye_"):
        return {"family_id":"deye", "family_name":"Deye Modbus", "variant":profile_name(key)}
    return {"family_id":key, "family_name":profile_name(key), "variant":"Common profile"}


def catalogue_view():
    from .drivers import fields_for
    from .parameters import execution_ready
    from .profile_layers import describe_profile
    return [{"profile_id":key, "name":profile_name(key), "payload":profile.payload,
             **family_info(key), "measurements":len(descriptors(key)),
             "controls":sum(execution_ready(field) for field in fields_for(key)),
             "evidence":"Reference readings on 4/32771; other variants require acceptance" if key=="smg_4" else "Source-derived; explicit acceptance required",
             "source":profile.source, "profile_layers":describe_profile(key)} for key,profile in MAPS.items() if canonical_id(key)==key]
