"""Describe implemented profile layers without granting or changing capabilities.

The selected map and controls remain the executable, definition-bound authority.
Retail names never select an extension. Mandatory variants retain their read anchors.
"""

from .catalogue import MAPS
from .profile_catalog import canonical_id, family_info, profile_name


def describe_profile(profile_id, *, binding=None, identity=None, basis=None, evidence="catalogue"):
    binding, identity = binding or {}, identity or {}
    reference = profile_id == "modbus_protocol_4"
    if reference:
        profile_id = "smg_4"
    if profile_id == "must_pv_ph18" and binding.get("effective_profile_id") in ("must_pv3300", "must_pv3900"):
        profile_id = binding["effective_profile_id"]
    profile = MAPS.get(profile_id)
    if profile is None:
        return None
    base_id = profile_id
    extension = None
    if profile_id=="pi30_max":
        base_id="pi30"
        extension={"id":"pi30_max","kind":"command_variant","name":"PI30 MAX 2021","required":True,
            "changes":["Lowercase flag commands and indexed charging-current commands.","QPIGS2 is PV2 on this variant; energy replies are Wh, converted to kWh."]}
    if profile_id in ("must_pv3300", "must_pv3900"):
        base_id = "must_pv_ph18"
        extension = {
            "id": profile_id, "kind": "model_variant", "name": "MUST-compatible PV3300" if profile_id == "must_pv3300" else "MUST PV3900",
            "required": True,
            "changes": (["Load register 25216 is a whole percent, not divided by 100."] if profile_id == "must_pv3300" else [])
                       + ["PV/model identity markers are required on every profile check."],
        }
    protocol = identity.get("protocol_number")
    model = identity.get("model_code")
    signature = binding.get("signature")
    if profile and profile.protocol_number is not None and isinstance(signature, (list, tuple)) and len(signature) == 2:
        if all(type(value) is int for value in signature):
            protocol, model = signature
    if profile_id in ("must_pv3300", "must_pv3900") and signature:
        markers = dict(signature) if all(isinstance(pair, (list, tuple)) and len(pair) == 2 and all(type(value) is int for value in pair) for pair in signature) else {}
        if markers.get(20000) == 0x5056:
            model = markers.get(20001)
    return {
        "base_map": {"profile_id": base_id, "name": profile_name(base_id)},
        **family_info(profile_id),
        "qualification": "Reference read checks for native 4/32771" if reference and model==32771 else "Source-derived profile; model compatibility must be checked",
        "extension": extension,
        "common_only": extension is None,
        "protocol_number": protocol, "model_code": model,
        "selection_basis": basis or ("native_protocol_and_model" if reference and model is not None else "selected_profile_definition"),
        "evidence_state": evidence,
        "variants": [{"id":"pi30","name":"Standard 2015"},{"id":"pi30_max","name":"MAX 2021"}] if profile_id in ("pi30","pi30_max") else [],
        "selected_variant":profile_id,
    }
