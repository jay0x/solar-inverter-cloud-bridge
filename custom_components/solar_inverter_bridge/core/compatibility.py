"""Bounded pre-enrollment evidence, deterministic analysis, and data-only replay."""

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from time import monotonic
import uuid
from zipfile import ZIP_DEFLATED, ZipFile, BadZipFile

SCHEMA = 1
ANALYZER_VERSION = 2
MAX_EVENTS = 4096
MAX_WIRE = 4 * 1024 * 1024
MAX_ARCHIVE = 24 * 1024 * 1024
PROBES = {"version": 2, "binary_identity": ["FC1 0/1", "FC2 1/1 parameter 2"],
          "native_routes": [[1, 1, 1], [1, 255, 1], [1, 255, 5], [1, 1, 5]],
          "signature_registers": [184, 171], "admission_deadline_seconds": 15,
          "route_deadline_seconds": 15, "verification_deadline_seconds": 90,
          "maximum_verification_read_requests": 34,
          "writes": False}
PROBES["profile_discovery"] = {"catalogue_version":2,"requests_per_pass":64,"seconds_per_pass":75,
    "expiry_seconds":600,"reconnect_limit":32,"user_acceptance_required":True,
    "experimental_controls_require_separate_acknowledgement":True}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class CompatibilityCapture:
    def __init__(self):
        self.recent = deque(maxlen=256)
        self.events = deque()
        self.started = None
        self.finished = None
        self.report_id = None
        self.metadata = {}
        self.byte_count = 0
        self.dropped = 0
        self._sequence = 0
        self._expiry = 0
        self.duration = 120

    def _expire(self):
        if self.started is not None and self.finished is None and monotonic() - self.started >= self.duration:
            self.stop("deadline")
        if self.finished is not None and monotonic() >= self._expiry:
            self.events.clear()
            self.started = self.finished = self.report_id = None
            self.metadata = {}

    def start(self, metadata=None, duration=120):
        self._expire()
        if self.started is not None and self.finished is None:
            raise ValueError("compatibility_collection_busy")
        self.events = deque({**event, "before_collection": True} for event in self.recent)
        self.started = monotonic()
        self.finished = None
        self.report_id = str(uuid.uuid4())
        self.metadata = {str(key): str(value)[:500] for key, value in (metadata or {}).items()
                         if key in ("inverter_model", "collector_model", "firmware", "original_endpoint", "symptom", "network_setup", "reference_readings")}
        self.byte_count = self.dropped = 0
        self.duration = min(120, max(1, duration))
        self.emit("collection_started")
        return self.view()

    def stop(self, reason="completed"):
        if self.started is not None and self.finished is None:
            self.finished = monotonic()
            self._expiry = monotonic() + 900
            self.emit("collection_finished", reason=reason)
        return self.view(expire=False)

    def emit(self, kind, **fields):
        self._expire()
        self._sequence += 1
        raw = fields.pop("data", None)
        event = {"id": self._sequence, "kind": kind, "time": utcnow(), "monotonic": round(monotonic(), 6), **deepcopy(fields)}
        if raw is not None:
            event["byte_count"] = len(raw)
        # Operational ring never holds wire payload or unredacted addresses/PNs.
        self.recent.append(event)
        if self.started is None or (self.finished is not None and kind != "collection_finished"):
            return
        event = dict(event)
        if raw is not None:
            event["wire_hex"] = raw.hex()
            self.byte_count += len(raw)
        self.events.append(event)
        # Preserve the beginning and a bounded tail. Drop from the middle.
        while len(self.events) > MAX_EVENTS or self.byte_count > MAX_WIRE:
            index = min(512, len(self.events) - 1)
            old = self.events[index]
            del self.events[index]
            self.byte_count -= len(old.get("wire_hex", "")) // 2
            self.dropped += 1

    def view(self, expire=True):
        if expire:
            self._expire()
        return {"report_id": self.report_id, "active": self.started is not None and self.finished is None,
                "events": len(self.events), "wire_bytes": self.byte_count, "dropped_events": self.dropped,
                "remaining_seconds": max(0, round(self.duration - (monotonic() - self.started))) if self.started and self.finished is None else 0,
                "retention_seconds_after_finish": 900}

    def snapshot(self, listeners, *, raw=False, build=None, context=None):
        self._expire()
        selected = self.events if self.report_id else self.recent
        events = [{key: value for key, value in event.items() if raw or key != "wire_hex"} for event in selected]
        return {"schema": SCHEMA, "analyzer_version": ANALYZER_VERSION, "probe_catalogue": PROBES,
                "report_id": self.report_id or str(uuid.uuid4()), "captured_at": utcnow(),
                "build": build or {}, "description": dict(self.metadata), "listeners": [dict(item) for item in listeners],
                "context": context or {}, "collection": self.view(), "events": events,
                "raw_protocol_included": raw,
                "redaction": "PNs and household addresses are replaced by report references. User-entered description is included. Original wire bytes, when opted in, may identify hardware or network settings."}


def analyze(report):
    events = report["events"]
    kinds = {event["kind"] for event in events}
    findings = []

    def add(code, layer, action, refs=(), severity="warning", facts=None, missing=None):
        hypotheses = {
            "no_incoming_connection": ["No new session, DNS/routing error, or an offline collector; HA cannot distinguish these without arrivals."],
            "wrong_route": ["A firmware-specific header rewrite or a reply for another route; no rewrite is automatically trusted."],
            "admission_failed": ["The selected bootstrap dialect or full-PN query is not supported by this session."],
            "payload_rejected": ["An incorrect route/slave, invalid RTU payload, or an unsupported inner protocol."],
            "reference_difference": ["Sampling/display precision differences, scaling differences, or a model-specific map variant."],
        }
        findings.append({"code": code, "layer": layer, "severity": severity,
                         "evidence_refs": list(refs), "observed_facts": facts or {},
                         "candidate_explanations": hypotheses.get(code, []), "confidence_basis": "recorded_events",
                         "next_action": action, "missing_evidence": missing or []})

    for listener in report.get("listeners", []):
        if not listener.get("bound"):
            add("listener_unavailable", "network", "Resolve the reported bind error; DNS cannot change the destination port.",
                facts=listener)
    if "tcp_received" not in kinds:
        add("no_incoming_connection", "network", "Check collector DNS/routing and create a new TCP session; HA cannot observe the collector's resolver.",
            missing=["startup_connection"])
    rules = {
        "source_rejected": ("network", "Correct the allowed source rules, then reconnect. No rejected payload was read."),
        "bootstrap_exhausted": ("session", "Select the observed dialect in Advanced or isolate silent collectors sharing a NAT source, then reconnect."),
        "wrong_route": ("session", "Review request and response route evidence; do not ignore route matching globally."),
        "payload_rejected": ("payload", "Review the inner protocol/CRC and the tested route/slave; include original wire exchange for parser work."),
        "native_signature_rejected": ("map", "Provide the exact model and reference readings; the native signature is not admitted automatically."),
        "admission_failed": ("identity", "Review full-PN and dialect evidence. Include startup exchange if identity could not be established."),
        "binary_reader_failed": ("session", "Review original chunks for invalid length, partial frame, EOF or deadline failure."),
        "query_rejected": ("identity", "Review the echoed FC2 parameter and status; a prefix/empty heartbeat does not establish a full PN."),
        "unexpected_function": ("session", "Inspect interleaved function/correlation evidence; a heartbeat cannot complete an inverter request."),
        "probe_busy": ("collection", "Wait for the current operation or poll; diagnostics do not interrupt commands."),
        "probe_failed": ("inverter", "Review the last completed block and original request/reply; the report does not substitute missing parameter data."),
        "exchange_failed": ("session", "Review the failed transaction duration and received-byte count; a stream timeout does not identify a network or firmware root cause."),
        "unsolicited_data_before_request": ("session", "Queued raw bytes arrived before a new request. The session is retired rather than accepting a late or unsolicited reply as fresh data."),
        "setting_read_unsupported": ("map", "This field returned a validated illegal-address response. Other supported settings remain readable; attach the report to refine the model profile."),
        "planned_tid_rotation": ("session", "Wait for the collector to reconnect; TIDs are not reused in a session."),
    }
    for kind, (layer, action) in rules.items():
        matched = [event for event in events if event["kind"] == kind]
        if matched:
            add(kind, layer, action, [event["id"] for event in matched[:16]], facts=matched[-1])
    suggestions=[event for event in events if event["kind"]=="profile_suggested"]
    if suggestions:
        add("experimental_profile_available","map","Review the suggested profile and compare its readings. You may explicitly accept it and optionally permit source-defined controls after the warning. Share this report to add your exact device.",
            refs=[event["id"] for event in suggestions],facts={"profiles":[event.get("profile_id") for event in suggestions]})
    if "profile_probe_failed" in kinds and not suggestions:
        add("no_profile_confirmed","map","Complete the bounded search or reconnect if requested. Include original exchange, exact model and display readings in a support report; no profile will be selected silently.")
    ascii_events = [event for event in events if event["kind"] == "inner_payload_rejected" and event.get("payload_kind") == "ascii_candidate"]
    if ascii_events:
        add("unsupported_ascii_payload", "payload", "The FC4 payload looks like ASCII. Include original exchange and identify its payload family; do not apply the Protocol 4 register decoder.",
            refs=[event["id"] for event in ascii_events[:16]], missing=["qualified_ascii_driver"])
    if "identity_confirmed" in kinds and "route_qualified" not in kinds and "snapshot_complete" not in kinds:
        add("collector_only", "inverter", "Collector identity/liveness does not prove inverter communication. Run verification while collecting.", missing=["inverter_reply"])
    if not report.get("raw_protocol_included"):
        add("original_wire_excluded", "collection", "Include raw protocol exchange before download if an unknown parser or identity format needs investigation.",
            severity="info", missing=["original_chunks"])
    if not any(event["kind"] == "tcp_received" and not event.get("before_collection") for event in events):
        add("startup_not_captured", "collection", "Reconnect the collector during this run to capture original startup; prior operational summaries cannot replay it.", missing=["original_startup"])
    if report.get("collection", {}).get("dropped_events"):
        add("capture_truncated", "collection", "Use the retained startup and tail; repeat a shorter targeted run if the missing middle is relevant.")
    if report.get("context", {}).get("recorder_available") is False:
        add("recorder_unavailable", "publication", "Enable Recorder for HA history; transport reads do not require it.", severity="info")
    for device in report.get("context", {}).get("devices", []):
        if device.get("capability_reason"):
            add("control_capability_unavailable", "publication", device["capability_reason"], severity="info",
                facts={"device_ref": device.get("reference"), "control_mode": device.get("configuration", {}).get("control_mode")})
    comparisons = []
    reference_text = report.get("description", {}).get("reference_readings", "")
    if reference_text:
        try:
            references = json.loads(reference_text)
            if not isinstance(references, dict) or len(references) > 10:
                raise ValueError("invalid_reference_readings")
            snapshots = [event for event in events if event["kind"] == "snapshot_complete" and event.get("values")]
            for key, reference in references.items():
                if not isinstance(reference, dict) or not {"value", "unit", "time"}.issubset(reference):
                    raise ValueError("invalid_reference_readings")
                when = datetime.fromisoformat(reference["time"])
                if when.tzinfo is None or type(reference["value"]) not in (int, float) or not math.isfinite(reference["value"]):
                    raise ValueError("invalid_reference_readings")
                candidates = [event for event in snapshots if key in event["values"]
                              and event["values"][key].get("unit") == reference["unit"]
                              and isinstance(event["values"][key].get("value"), (int, float))
                              and abs((datetime.fromisoformat(event["time"]) - when).total_seconds()) <= 30]
                if candidates:
                    snapshot = min(candidates, key=lambda event: abs((datetime.fromisoformat(event["time"]) - when).total_seconds()))
                    observed = snapshot["values"][key]["value"]
                    comparison = {"key": key, "reference": reference, "observed": observed,
                                  "difference": round(observed - reference["value"], 6), "evidence_ref": snapshot["id"]}
                    comparisons.append(comparison)
                    if comparison["difference"]:
                        add("reference_difference", "measurements", "Review sampling time, display precision and model variant before inferring a scale change.",
                            refs=[snapshot["id"]], facts=comparison, severity="info")
            if not comparisons:
                add("reference_not_comparable", "measurements", "Supply a matching sensor key/unit and an ISO timestamp with timezone within 30 seconds of a collected snapshot.", missing=["contemporaneous_reference"])
        except (ValueError, TypeError, KeyError, OverflowError):
            add("reference_text_only", "measurements", "Reference text is retained. For automatic comparison use JSON: {\"battery_voltage\":{\"value\":48.1,\"unit\":\"V\",\"time\":\"2026-11-05T12:00:00+00:00\"}}.", severity="info")
    coverage = {"network": "observed" if "tcp_received" in kinds else "missing",
                "transport": "identified" if "dialect_selected" in kinds and "identity_confirmed" in kinds else "candidate" if "dialect_selected" in kinds else "missing",
                "full_identity": "confirmed" if "identity_confirmed" in kinds else "missing",
                "inverter_map": "qualified" if "route_qualified" in kinds or "snapshot_complete" in kinds else "missing",
                "telemetry": "complete" if "snapshot_complete" in kinds else "missing",
                "parameters": "complete" if "settings_complete" in kinds else "missing",
                "writes": "not_qualified_by_diagnostics",
                "reference_comparison": "compared" if comparisons else "not_available",
                "original_wire": "included" if report.get("raw_protocol_included") else "excluded"}
    return {"schema": 1, "analyzer_version": ANALYZER_VERSION, "findings": findings, "coverage": coverage, "reference_comparisons": comparisons,
            "issue_summary": "Solar Inverter Cloud Bridge compatibility report " + report["report_id"] + "\n" +
            "Build: " + str(report.get("build", {}).get("version", "unknown")) + " / " + str(report.get("build", {}).get("sha256", "unknown")) + "\n" +
            "\n".join(f"- {item['code']}: {item['next_action']}" for item in findings)}


def _json(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True).encode()


def package_report(report):
    analysis = analyze(report)
    events = report["events"]
    structured = [{k: v for k, v in event.items() if k != "wire_hex"} for event in events]
    public = {**report, "events": structured}
    files = {"report.json": _json(public), "analysis.json": _json(analysis),
             "timeline.jsonl": b"\n".join(_json(event).replace(b"\n", b"") for event in structured),
             "observations.json": _json([event for event in structured if event["kind"] in ("register_read", "snapshot_complete", "settings_complete")]),
             "README.txt": (analysis["issue_summary"] + "\n\n" + report["redaction"]).encode()}
    if report["raw_protocol_included"]:
        files["protocol/original-wire.json"] = _json(events)
    files["manifest.json"] = _json({"schema": 1, "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
                                    "raw_protocol_included": report["raw_protocol_included"], "dropped_events": report["collection"]["dropped_events"]})
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue(), analysis


def validate_package(data):
    try:
        return _validate_package(data)
    except (BadZipFile, KeyError, TypeError, AttributeError, UnicodeError, RecursionError, NotImplementedError, RuntimeError) as error:
        raise ValueError("invalid_report_archive") from error


def _validate_package(data):
    """Read only known bounded archive members; never extract or execute input."""
    if len(data) > MAX_ARCHIVE:
        raise ValueError("report_archive_too_large")
    allowed = {"report.json", "analysis.json", "timeline.jsonl", "observations.json", "README.txt", "manifest.json", "protocol/original-wire.json"}
    with ZipFile(io.BytesIO(data)) as archive:
        info = archive.infolist()
        names = [item.filename for item in info]
        if len(names) != len(set(names)) or set(names) - allowed or sum(item.file_size for item in info) > MAX_ARCHIVE:
            raise ValueError("invalid_report_archive")
        if not {"manifest.json", "report.json", "analysis.json"}.issubset(names):
            raise ValueError("incomplete_report_archive")
        files = {item.filename: archive.read(item) for item in info}
    manifest = json.loads(files["manifest.json"])
    if manifest.get("schema") != SCHEMA or set(manifest["files"]) != set(files) - {"manifest.json"}:
        raise ValueError("invalid_report_manifest")
    if any(hashlib.sha256(files[name]).hexdigest() != digest for name, digest in manifest["files"].items()):
        raise ValueError("report_hash_mismatch")
    report = json.loads(files["report.json"])
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or not isinstance(report.get("report_id"), str) or len(report["report_id"]) > 80
            or not isinstance(report.get("collection"), dict)
            or not isinstance(report.get("context"), dict)
            or not isinstance(report.get("listeners"), list)
            or len(report["listeners"]) > 16
            or any(not isinstance(listener, dict) for listener in report["listeners"])
            or not isinstance(report.get("events"), list) or len(report["events"]) > MAX_EVENTS):
        raise ValueError("invalid_report_schema")
    devices = report["context"].get("devices", [])
    if not isinstance(devices, list) or len(devices) > 16 or any(not isinstance(device, dict) for device in devices):
        raise ValueError("invalid_device_context")
    if "protocol/original-wire.json" in files:
        wire = json.loads(files["protocol/original-wire.json"])
        if (not report.get("raw_protocol_included") or not isinstance(wire, list) or len(wire) > MAX_EVENTS
                or any(not isinstance(event, dict) for event in wire)
                or sum(len(event.get("wire_hex", "")) for event in wire) > MAX_WIRE * 2):
            raise ValueError("invalid_wire_evidence")
        report["events"] = wire
        if [{key: value for key, value in event.items() if key != "wire_hex"} for event in wire] != json.loads(files["report.json"])["events"]:
            raise ValueError("wire_summary_mismatch")
    elif report.get("raw_protocol_included"):
        raise ValueError("original_wire_missing")
    for event in report["events"]:
        if not isinstance(event, dict) or not isinstance(event.get("kind"), str) or not isinstance(event.get("id"), int):
            raise ValueError("invalid_report_event")
        if "wire_hex" in event:
            bytes.fromhex(event["wire_hex"])
            if event.get("direction") not in ("tx", "rx") or not isinstance(event.get("session"), str):
                raise ValueError("invalid_wire_event")
    analyze(report)
    return report


def replay(report):
    """Reassemble original binary chunks and rerun inner validation offline.

    Returns decoder outcomes and the recorded session timeline, including timings
    and correlation evidence. No network, writes, dynamic imports or archive code.
    """
    from .binary import decode_frame
    from .framing import parse_read, read_request
    from .profiles import auto_profile, match_signature
    from .telemetry import decode, required_addresses
    from .catalogue import MAPS, decode_map, required_measurement_addresses
    from .drivers import parse_ascii, ascii_request, decode_ascii_cycle, READ_PLANS, identify_ascii_request
    sessions = {}
    requests = {}
    failed_requests = set()
    completed_requests = set()
    native_reads = {}
    seen_tids = {}
    outcomes = []
    frame_budget_hit = False
    telemetry_addresses = required_addresses()
    active_profiles = {}
    request_profiles = {}
    profile_caches = {}
    profile_outcomes = []
    dialects = {event.get("session"): event.get("dialect") for event in report["events"] if event["kind"] == "dialect_selected"}
    for event in report["events"]:
        session = event.get("session")
        if event["kind"]=="profile_read_started" and event.get("profile_id") in MAPS:
            scope=(session,event["id"])
            active_profiles[session]=scope
            profile_caches[scope]={"profile_id":event["profile_id"],"registers":{},"ascii":{}}
        if event["kind"] == "transaction_failed":
            failed_requests.add((session, event.get("tid")))
        if event["kind"] != "wire" or "wire_hex" not in event or dialects.get(session) != "binary":
            continue
        key = (session, event["direction"])
        buffer = sessions.setdefault(key, bytearray())
        buffer.extend(bytes.fromhex(event["wire_hex"]))
        try:
            while buffer:
                parsed = decode_frame(buffer)
                if parsed is None:
                    break
                frame, size = parsed
                del buffer[:size]
                if len(outcomes) >= MAX_EVENTS:
                    frame_budget_hit = True
                    break
                result = {"session": session, "event": event["id"], "direction": event["direction"],
                          "tid": frame.tid, "function": frame.function, "route": [frame.code, frame.address], "validation": "outer_valid"}
                if event["direction"] == "tx":
                    if frame.tid in seen_tids.setdefault(session, set()):
                        result["correlation"] = "repeated_outgoing_tid_or_unsolicited_ack"
                    seen_tids[session].add(frame.tid)
                    requests[(session, frame.tid)] = frame
                    request_profiles[(session,frame.tid)]=active_profiles.get(session)
                else:
                    request = requests.get((session, frame.tid))
                    result["correlation"] = "unsolicited_or_missing_request"
                    if request is not None:
                        result["correlation"] = ("late_after_failure" if (session, frame.tid) in failed_requests else
                                                 "late_after_completion" if (session, frame.tid) in completed_requests else
                                                 "wrong_function" if frame.function != request.function else
                                                 "wrong_route" if (frame.code, frame.address) != (request.code, request.address) else "matched")
                        if result["correlation"] == "matched":
                            completed_requests.add((session, frame.tid))
                        if result["correlation"] == "matched" and frame.function == 2:
                            if len(frame.payload) < 2 or frame.payload[1:2] != request.payload:
                                result["correlation"] = "wrong_parameter"
                            elif frame.payload[0] != 0:
                                result["validation"] = "query_rejected"
                if frame.function == 4 and event["direction"] == "rx":
                    if len(frame.payload) >= 3 and frame.payload[1] in (3,4,0x83,0x84):
                        try:
                            expected = requests.get((session, frame.tid))
                            if expected and expected.function == 4 and len(expected.payload) == 8:
                                count = int.from_bytes(expected.payload[4:6], "big")
                                slave = expected.payload[0]
                            else:
                                count = frame.payload[2] // 2 if frame.payload[1] in (3,4) else 1
                                slave = frame.payload[0]
                            function=expected.payload[1] if expected and len(expected.payload)==8 and expected.payload[1] in (3,4) else frame.payload[1]&0x7f
                            inner = parse_read(frame.payload, count, slave,function)
                            result["validation"] = "inner_valid" if inner and inner[1] == len(frame.payload) else "inner_incomplete"
                            if (result["validation"] == "inner_valid" and result.get("correlation") == "matched"
                                    and expected and expected.function == 4 and len(expected.payload) == 8 and expected.payload[1] in (3,4)):
                                address = int.from_bytes(expected.payload[2:4], "big")
                                if read_request(address, count, slave,function) != expected.payload:
                                    result["validation"] = "invalid_original_read_request"
                                    outcomes.append(result)
                                    continue
                                result.update(register_address=address, words=list(inner[0]))
                                scoped=profile_caches.get(request_profiles.get((session,frame.tid)))
                                if scoped:
                                    profile=MAPS[scoped["profile_id"]]
                                    if profile.payload=="modbus" and (function==profile.function or address in (184,171)):
                                        scoped["registers"].update({address+i:word for i,word in enumerate(inner[0])})
                                        needed=required_measurement_addresses(profile)
                                        all_addresses={a for f in profile.fields for a in range(f.address,f.address+f.words)}
                                        signature_ok=(profile.protocol_number is None or scoped["registers"].get(184)==profile.protocol_number) and all(scoped["registers"].get(a)==v for a,v in profile.anchors)
                                        if signature_ok and needed.issubset(scoped["registers"]) and all_addresses.intersection(range(address,address+count)):
                                            profile_outcomes.append({"profile_id":profile.profile_id,"session":session,"event":event["id"],
                                                "evidence":"original_correlated_binary_reads","values":decode_map(profile,scoped["registers"])})
                                route_key = (session, frame.code, frame.address, slave)
                                if address == 184:
                                    native_reads[route_key] = {}
                                cache = native_reads.setdefault(route_key, {})
                                for offset, word in enumerate(inner[0]):
                                    if address + offset in (184, 171) or address + offset in telemetry_addresses:
                                        cache[address + offset] = word
                                if 184 in cache and 171 in cache:
                                    result["native_signature"] = match_signature(cache[184], cache[171])
                                    profile = auto_profile(cache[184], cache[171])
                                    result["native_admission"] = "accepted" if profile else "unsupported_or_unconfirmed_identity"
                                    if profile and telemetry_addresses.issubset(cache):
                                        result["decoded_values"] = decode(cache)
                        except ValueError as error:
                            result["validation"] = str(error)
                            if isinstance(getattr(error, "exception_code", None), int):
                                result["exception_code"] = error.exception_code
                    else:
                        result["validation"] = "unsupported_inner_protocol"
                        scoped=profile_caches.get(request_profiles.get((session,frame.tid)))
                        expected=requests.get((session,frame.tid))
                        if scoped and result.get("correlation")=="matched" and MAPS[scoped["profile_id"]].payload in READ_PLANS:
                            family=MAPS[scoped["profile_id"]].payload
                            commands=READ_PLANS[family]
                            try:
                                identified=identify_ascii_request(scoped["profile_id"],expected.payload)
                                if identified:
                                    command,is_write=identified
                                    text=parse_ascii(frame.payload,family)
                                    if is_write:
                                        result["validation"]="write_ack_valid_not_physical_proof" if text=="ACK" else "ascii_write_rejected"
                                    elif text in ("ACK","NAK"):
                                        result["validation"]="ascii_query_rejected"
                                    else:
                                        scoped["ascii"][command]=text
                                        result["validation"]="ascii_valid"
                                    if not is_write and text not in ("ACK","NAK") and all(c in scoped["ascii"] for c in commands):
                                        values,_=decode_ascii_cycle(family,scoped["ascii"],scoped["profile_id"])
                                        profile_outcomes.append({"profile_id":scoped["profile_id"],"session":session,"event":event["id"],
                                            "evidence":"original_correlated_binary_ascii","values":values})
                            except ValueError as error:
                                result["validation"]=str(error)
                outcomes.append(result)
            if frame_budget_hit:
                break
        except ValueError as error:
            outcomes.append({"session": session, "event": event["id"], "validation": str(error)})
            sessions[key] = bytearray()
    for (session, direction), buffer in sessions.items():
        if frame_budget_hit:
            break
        if buffer:
            outcomes.append({"session": session, "direction": direction, "validation": "incomplete_frame", "bytes": len(buffer)})
    at_results,at_profiles,at_limited = replay_at(report["events"],dialects,MAX_EVENTS-len(outcomes))
    outcomes.extend(at_results)
    profile_outcomes.extend(at_profiles)
    frame_budget_hit=frame_budget_hit or at_limited
    return {"schema": 1, "fidelity": "original_wire" if report.get("raw_protocol_included") else "semantic_only",
            "frame_budget_hit": frame_budget_hit, "maximum_decoded_frames": MAX_EVENTS,
            "analysis": analyze(report), "decoder_outcomes": outcomes,
            "profile_decodes": profile_outcomes,
            "timeline": [{k: v for k, v in event.items() if k != "wire_hex"} for event in report["events"]]}


def replay_at(events,dialects,limit):
    """Replay ordered raw-AT payloads without guessing boundaries after failure."""
    from .catalogue import MAPS,decode_map,required_measurement_addresses
    from .drivers import ascii_request,parse_ascii,decode_ascii_cycle,READ_PLANS,identify_ascii_request
    from .framing import read_request,parse_read,parse_write_ack,crc16
    active={};caches={};pending={};outcomes=[];profiles=[]
    commands=READ_PLANS
    for event in events:
        session=event.get("session")
        if dialects.get(session)!="at":
            continue
        if len(outcomes)>=limit:
            return outcomes,profiles,True
        if event["kind"]=="profile_read_started" and event.get("profile_id") in MAPS:
            active[session]=(session,event["id"])
            caches[active[session]]={"profile_id":event["profile_id"],"registers":{},"ascii":{}}
        if event["kind"]!="wire" or "wire_hex" not in event:
            continue
        data=bytes.fromhex(event["wire_hex"])
        if event["direction"]=="tx":
            if session in pending:
                previous=pending.pop(session)
                outcomes.append({"session":session,"event":event["id"],"validation":"incomplete_previous_reply" if previous["buffer"] else "previous_reply_missing"})
            scope=active.get(session);cache=caches.get(scope)
            item={"request":data,"buffer":bytearray(),"scope":scope,"kind":"unknown"}
            if data.startswith(b"AT+") and data.endswith(b"\n"):
                item["kind"]="at_line"
            elif len(data)==8 and data[1] in (3,4):
                address,count=int.from_bytes(data[2:4],"big"),int.from_bytes(data[4:6],"big")
                try:
                    if data==read_request(address,count,data[0],data[1]):
                        item.update(kind="read",address=address,count=count,slave=data[0],function=data[1])
                except ValueError:
                    pass
            elif len(data)>=8 and data[1] in (6,16) and crc16(data[:-2])==int.from_bytes(data[-2:],"little"):
                item.update(kind="write",address=int.from_bytes(data[2:4],"big"),count=1 if data[1]==6 else int.from_bytes(data[4:6],"big"),
                            slave=data[0],function=data[1],value=int.from_bytes(data[4:6],"big"))
            elif cache and MAPS[cache["profile_id"]].payload in commands:
                family=MAPS[cache["profile_id"]].payload
                identified=identify_ascii_request(cache["profile_id"],data)
                if identified:
                    command,is_write=identified
                    item.update(kind="ascii",family=family,command=command,is_write=is_write)
            pending[session]=item
            continue
        item=pending.get(session)
        if item is None:
            outcomes.append({"session":session,"event":event["id"],"validation":"unsolicited_or_missing_request"})
            continue
        item["buffer"].extend(data)
        buffer=item["buffer"]
        result={"session":session,"event":event["id"],"direction":"rx","evidence":"original_ordered_at_exchange"}
        cache=caches.get(item["scope"])
        try:
            if len(buffer)>4096:
                raise ValueError("raw_frame_too_large")
            kind=item["kind"]
            size=None
            if kind=="read":
                parsed=parse_read(buffer,item["count"],item["slave"],item["function"])
                if parsed is None:
                    continue
                words,size=parsed
                result.update(validation="inner_valid",register_address=item["address"],words=list(words),function=item["function"])
                if cache:
                    profile=MAPS[cache["profile_id"]]
                    if profile.payload=="modbus" and (item["function"]==profile.function or item["address"] in (184,171)):
                        cache["registers"].update({item["address"]+i:word for i,word in enumerate(words)})
                        needed=required_measurement_addresses(profile)
                        all_addresses={address for field in profile.fields for address in range(field.address,field.address+field.words)}
                        if (needed.issubset(cache["registers"]) and all_addresses.intersection(range(item["address"],item["address"]+item["count"]))
                                and (profile.protocol_number is None or cache["registers"].get(184)==profile.protocol_number)
                                and all(cache["registers"].get(a)==v for a,v in profile.anchors)):
                            profiles.append({"profile_id":profile.profile_id,"session":session,"event":event["id"],
                                             "evidence":"original_ordered_at_reads","values":decode_map(profile,cache["registers"])})
            elif kind=="write":
                size=parse_write_ack(buffer,item["address"],item["count"],item["slave"],item["function"],item["value"])
                if size is None:
                    continue
                result["validation"]="write_ack_valid_not_physical_proof"
            elif kind in ("ascii","at_line"):
                if kind=="ascii" and item["family"]=="pi18":
                    if len(buffer)<5:
                        continue
                    if bytes(buffer[:2]) in (b"^0",b"^1"):
                        size=5
                    elif not bytes(buffer[:5]).startswith(b"^D") or not bytes(buffer[2:5]).isdigit():
                        raise ValueError("pi18_response_prefix")
                    else:
                        size=5+int(buffer[2:5])
                    if size>1024 or size<5:
                        raise ValueError("pi18_response_length")
                    if len(buffer)<size:
                        continue
                else:
                    delimiter=b"\n" if kind=="at_line" else b"\r"
                    index=buffer.find(delimiter)
                    if index<0:
                        continue
                    size=index+1
                if kind=="at_line":
                    result["validation"]="at_line_received_not_identity_proof"
                else:
                    text=parse_ascii(bytes(buffer[:size]),item["family"])
                    result["validation"]="ascii_valid"
                    if item.get("is_write"):
                        result["validation"]="write_ack_valid_not_physical_proof" if text=="ACK" else "ascii_write_rejected"
                    elif text in ("ACK","NAK"):
                        result["validation"]="ascii_query_rejected"
                    elif cache:
                        cache["ascii"][item["command"]]=text
                        required=commands[item["family"]]
                        if all(command in cache["ascii"] for command in required):
                            values,_=decode_ascii_cycle(item["family"],cache["ascii"],cache["profile_id"])
                            profiles.append({"profile_id":cache["profile_id"],"session":session,"event":event["id"],
                                             "evidence":"original_ordered_at_ascii","values":values})
            else:
                raise ValueError("unsupported_raw_request")
            if size is not None and size<len(buffer):
                result["unassociated_tail_bytes"]=len(buffer)-size
            pending.pop(session,None)
        except ValueError as error:
            result["validation"]=str(error)
            pending.pop(session,None)
        outcomes.append(result)
    for session,item in pending.items():
        if len(outcomes)>=limit:
            return outcomes,profiles,True
        outcomes.append({"session":session,"validation":"incomplete_frame" if item["buffer"] else "reply_missing","bytes":len(item["buffer"])})
    return outcomes,profiles,False
