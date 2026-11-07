"""Bounded source-derived profile search; suggestions never become enrollment."""

import asyncio
from time import monotonic

from .catalogue import MAPS
from .drivers import snapshot
from .profile_layers import describe_profile
from .profile_catalog import profile_name, canonical_id

WARNING = ("This profile is inferred from protocol responses or external sources and has not been verified on your device. "
           "Measurements, settings and limits may differ. Compare readings with the inverter before relying on them. "
           "Acceptance enables implemented controls, which can change electrical behavior; incorrect mappings may cause damage.")


def new_search(dialect, profile_id=None):
    plans = []
    first = ["smg_4","pi30","pi18","g_ascii","eybond_09c1","must_pv_ph18"]
    ordered = [profile_id] if profile_id else first + [key for key in MAPS if key not in first and canonical_id(key)==key]
    for key in ordered:
        profile = MAPS[key]
        routes = [(1,1)] if dialect == "at" else [(1,1),(1,255)]
        if dialect == "binary" and key == "g_ascii":
            routes.append((0x0994,255))
        if dialect == "binary" and key in ("pi30","pi18"):
            routes.extend(((0x0994,255),(0x0994,1),(0x0102,255)))
        for route in routes:
            plans.append((key,route,profile.slave))
    # One alternate RTU slave seen in factory-cloud examples, not a sweep.
    if dialect == "binary":
        plans.extend((key,(1,255),5) for key in ordered if MAPS[key].payload == "modbus")
    return {"plans":plans,"index":0,"candidates":[],"expires":monotonic()+600,"state":"searching","attempts":[],"connections":0}


async def search(holder, state):
    adapter,writer = holder["reader"],holder["writer"]
    adapter.profile_id = None
    adapter.probe_budget = 64
    wire = getattr(adapter,"wire",adapter)
    wire.origin = "profile_discovery"
    state["connections"] += 1
    if state["connections"] > 32 or monotonic() > state["expires"]:
        state["state"] = "expired"
        return
    try:
        async with asyncio.timeout(75):
            if holder["dialect"] == "binary" and not getattr(adapter,"descriptor_checked",False):
                adapter.descriptor_checked = True
                try:
                    async with asyncio.timeout(3):
                        raw = await adapter.query(14)
                    asset = raw.decode("ascii").strip("\x00 \r\n").split("#",1)[0].split(",",1)[0]
                    if asset in ("0912","0921"):
                        state["descriptor_hint"] = asset
                        remaining = state["plans"][state["index"]:]
                        remaining.sort(key=lambda plan: plan[0] != "smartess_"+asset)
                        state["plans"][state["index"]:] = remaining
                        holder["emit"]("protocol_descriptor_hint",asset=asset)
                except (ValueError,TimeoutError,ConnectionError,asyncio.IncompleteReadError):
                    holder["emit"]("protocol_descriptor_unavailable")
                if writer.is_closing() or adapter.at_eof():
                    state["state"] = "waiting_for_reconnect"
                    return
            while state["index"] < len(state["plans"]):
                key,route,slave = state["plans"][state["index"]]
                state["index"] += 1
                adapter.slave = slave
                if holder["dialect"] == "binary":
                    adapter.route = route
                try:
                    first = await snapshot(adapter,writer,key,timeout=3)
                    second = await snapshot(adapter,writer,key,timeout=3)
                    if first["fingerprint"] != second["fingerprint"]:
                        raise ValueError("profile_identity_unstable")
                    profile = MAPS[second["binding"].get("effective_profile_id", key)]
                    known = second["model_code"] in profile.model_codes if profile.model_codes else False
                    item = {"profile_id":key,"name":profile_name(key),"fingerprint":second["fingerprint"],"binding":second["binding"],
                            "basis":"source_identity_anchors_and_two_snapshots" if profile.anchors else "source_catalog_signature_and_two_snapshots" if known else "family_shape_and_two_snapshots",
                              "hardware_verified":False,"values":second["values"],"warning":WARNING,"source":profile.source}
                    item["descriptor_hint"] = state.get("descriptor_hint")
                    item["profile_layers"] = describe_profile(key, binding=second["binding"], identity=second,
                                                              basis=item["basis"], evidence="proposal")
                    if not any(old["fingerprint"]==item["fingerprint"] for old in state["candidates"]):
                        state["candidates"].append(item)
                    state["state"]="candidates_available"
                    # Let the user inspect evidence before probing another route
                    # which might represent a different inverter in a topology.
                    holder["emit"]("profile_suggested",profile_id=key,basis=item["basis"],fingerprint=item["fingerprint"],
                                   binding=item["binding"],values=item["values"],source=item["source"])
                    return
                except (ValueError,TimeoutError,ConnectionError,asyncio.IncompleteReadError) as error:
                    code = str(error) if isinstance(error,ValueError) else type(error).__name__
                    state["attempts"].append({"profile_id":key,"route":list(route),"slave":slave,"outcome":code})
                    holder["emit"]("profile_probe_failed",profile_id=key,code=code)
                    if code=="profile_native_protocol_mismatch":
                        preferred=f"smg_{getattr(error,'protocol_number',None)}"
                        for index in range(state["index"],len(state["plans"])):
                            candidate_plan=state["plans"][index]
                            if candidate_plan==(preferred,route,slave):
                                state["plans"].insert(state["index"],state["plans"].pop(index))
                                break
                    if code == "profile_probe_budget_exhausted":
                        state["index"] -= 1
                        state["state"] = "more_probes_available"
                        return
                    # Raw payloads have no transaction IDs. Never let late bytes
                    # from one family answer a probe for another on this socket.
                    if holder["dialect"] == "at" and (not isinstance(error,ValueError) or code in ("crc_mismatch","unexpected_slave_or_transport","unexpected_function_or_transport","ascii_crc_mismatch","invalid_ascii_frame","pi30_response_prefix","pi18_response_prefix")):
                        state["state"] = "waiting_for_reconnect"
                        writer.close()
                        return
                    if writer.is_closing() or adapter.at_eof():
                        state["state"] = "waiting_for_reconnect"
                        return
            state["state"] = "complete"
    except TimeoutError:
        state["state"] = "waiting_for_reconnect"
        writer.close()
    finally:
        adapter.probe_budget = None
        adapter.profile_id = None
        holder["ready"] = False
        if holder["dialect"] == "binary":
            adapter.route_qualified = False


async def confirm(holder, candidate):
    adapter = holder["reader"]
    binding = candidate["binding"]
    adapter.slave = binding["slave"]
    if holder["dialect"] == "binary":
        adapter.route = tuple(binding["route"])
    adapter.profile_id = None
    async with asyncio.timeout(45):
        first = await snapshot(adapter,holder["writer"],candidate["profile_id"])
        second = await snapshot(adapter,holder["writer"],candidate["profile_id"])
    if first["fingerprint"] != candidate["fingerprint"] or second["fingerprint"] != candidate["fingerprint"]:
        raise ValueError("profile_evidence_changed")
    adapter.profile_id = candidate["profile_id"]
    adapter.accepted_fingerprint = candidate["fingerprint"]
    return second
