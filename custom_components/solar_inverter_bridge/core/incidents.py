"""Passive, bounded local incident recorder. No device I/O or automatic alarms.

Call observe/record_issue/recovered/tick on the owning event loop. Call start
before use and close before closing Storage. A missing optional store is a usable
memory-only mode. The ring contains ORIGINAL chunks, never reconstructed frames.
It is not persisted on each event: a fault saves its prelude immediately and its
ten-second tail later. Interrupted tails remain explicitly incomplete on restart.

Exports reuse compatibility's validated data-only ZIP/replay schema. Only known
event fields are exported; identity/session references are remapped per report.
Original wire bytes (which can contain PN/IP/address data) require include_raw.
Firmware, collector model and numeric model code are included as report metadata.
Explicit user description/feedback strings are included verbatim, bounded, and
labeled as user input: they cannot be guaranteed anonymous. No URL is opened here.
"""

import asyncio
from bisect import bisect_right
from collections import OrderedDict, deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
from itertools import islice
import json
import math
import re
from time import monotonic
from urllib.parse import urlencode
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from . import compatibility
from .incident_store import INCIDENT_SCHEMA, MAX_INCIDENTS, MAX_SAMPLE_BYTES, MAX_WATCHES
from .storage import StorageError

FINGERPRINT_REVISION = 1
RING_SECONDS = 60
TAIL_SECONDS = 10
RING_BYTES = 512 * 1024
RING_EVENTS = 2048
SAMPLE_BYTES = 768 * 1024
SAMPLE_EVENTS = 3072
MAX_SAMPLES = 3
SESSION_METADATA_COUNT = 64
SESSION_METADATA_BYTES = 64 * 1024
EXPORT_EVENT_BYTES = 2 * 1024 * 1024
RETRY_SECONDS = 1
COMMUNICATION_STAGES = frozenset({"poll", "settings_read", "callback", "transport", "admission",
                                  "verification", "profile_discovery"})
LIMITS = {"ring_seconds": RING_SECONDS, "tail_seconds": TAIL_SECONDS,
          "ring_bytes": RING_BYTES, "ring_events": RING_EVENTS,
          "fingerprints": MAX_INCIDENTS, "samples_per_problem": MAX_SAMPLES,
          "serialized_sample_bytes": MAX_SAMPLE_BYTES, "pending_writes": 1,
          "inflight_writes": 1, "watch_hours": [1, 24],
          "session_metadata_count": SESSION_METADATA_COUNT, "session_metadata_bytes": SESSION_METADATA_BYTES}

# Strings are protocol identifiers, not arbitrary exception/user text. Never copy
# free-form error/reason/message, values, PN, host, address strings or payload_hex.
TAG_FIELDS = {"kind", "stage", "code", "profile_id", "transport", "dialect", "origin",
              "payload_kind", "validation", "classification"}
NUMBER_FIELDS = {"tid", "function", "register_address", "register_count", "exception_code",
                 "payload_length", "expected_length", "byte_count", "elapsed_ms", "received_bytes",
                 "listener_port", "attempt", "address", "inner_slave", "outer_code", "outer_address"}
ROUTE_FIELDS = {"request_route", "response_route", "expected_route", "observed_route"}
PRIVATE_FIELDS = {"device_id", "session", "source_ref"}


def _now():
    return datetime.now(timezone.utc)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _tag(value, default=None):
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]{0,95}", value):
        return value
    return default


def _ref(value):
    return value[:160] if isinstance(value, str) else ""


def _build_ref(build):
    """Copy only bounded public build identifiers, never arbitrary build metadata."""
    if not isinstance(build, dict):
        return {}
    return {key: build[key][:160] for key in ("version", "sha256")
            if isinstance(build.get(key), str) and build[key]}


def _time(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def _sample_size(sample):
    # Conservatively reserve space for bounded sample metadata, separators and
    # changing counters. This avoids serializing megabytes on the polling loop.
    return sample["event_bytes"] + len(sample["events"]) + 4096


def _shape(value, depth=0):
    """Type/arity only: never hash measured values, arbitrary keys or identifiers."""
    if depth >= 4:
        return "nested"
    if isinstance(value, dict):
        return sorted((_shape(item, depth + 1) for item in islice(value.values(), 32)), key=str)
    if isinstance(value, (list, tuple)):
        return [_shape(item, depth + 1) for item in value[:32]]
    if isinstance(value, str):
        return "text"
    if isinstance(value, (bytes, bytearray)):
        return "bytes"
    if type(value) in (int, float):
        return "number"
    return "bool" if isinstance(value, bool) else "null"


def fingerprint(record, context=None):
    """Public identity excludes device, PN/IP/TID/time and all measured values."""
    context = context or {}
    identity = {"schema": INCIDENT_SCHEMA, "revision": FINGERPRINT_REVISION}
    for key in ("code", "stage", "profile_id", "transport"):
        identity[key] = _tag(record.get(key, context.get(key)), "unknown")
    for key in ("function", "register_address", "register_count", "exception_code"):
        value = record.get(key)
        identity[key] = value if type(value) is int else None
    for key in ("payload_length", "expected_length"):
        value = record.get(key)
        # Size class, rather than incidental numeric/identity text widths.
        if type(value) is int and 0 <= value <= RING_BYTES:
            identity[key] = 0 if not value else 1 << (value - 1).bit_length()
    if "shape" in record:
        identity["shape"] = _shape(record["shape"])
    if _tag(record.get("payload_kind")):
        identity["payload_kind"] = record["payload_kind"]
    return "sib-inc-v1-" + hashlib.sha256(_json(identity)).hexdigest()[:24]


def search_url(value, code):
    return "https://github.com/jay0x/solar-inverter-cloud-bridge/issues?" + urlencode(
        {"q": f'is:issue "{value}" "{code}"'})


def _known(code):
    if code in ("binary_empty_inverter_reply", "empty_inverter_reply", "handled_empty_reply"):
        return {"title": "Empty inverter reply", "status": "known_behavior",
                "advice": "An empty reply was observed. For communication incidents, a later full poll confirms recovery, not a firmware fix."}
    if code in ("TimeoutError", "timeout", "poll_timeout", "read_timeout", "exchange_timeout"):
        return {"title": "Communication timeout", "status": "known_symptom",
                "advice": "A timeout does not identify a network or firmware root cause. Review the retained exchange if it persists."}
    return {"title": "Unclassified protocol or runtime incident", "status": "unknown",
            "advice": "Review this local report and share it with support if needed. Unknown hardware alone is not an alarm."}


def _summary(item):
    known = _known(item["code"])
    recovered = item["count"] == item["recovered_count"]
    result = {key: item.get(key) for key in ("fingerprint", "code", "stage", "profile_id", "transport",
                                            "first_seen", "last_seen", "count", "recovered_count")}
    hardware = item.get("hardware", {})
    result.update(firmware=_ref(hardware.get("firmware")) or None,
                  collector_model=_ref(hardware.get("collector_model")) or None,
                  model_code=hardware.get("model_code") if type(hardware.get("model_code")) is int else None)
    result.update(status="recovered" if recovered else "unrecovered",
                  needs_attention=not recovered or known["status"] == "unknown",
                  sample_count=len(item["samples"]), known_issue=known,
                  support_prompt=known["status"] == "unknown", notification="none",
                  search_url=search_url(item["fingerprint"], item["code"]))
    return result


class IncidentRecorder:
    def __init__(self, storage, on_update=None, build=None):
        self.storage = storage
        self.on_update = on_update
        self.build = _build_ref(build)
        self.enabled = True
        self._records = {}
        self._watches = {}
        self._ring = deque()
        self._ring_bytes = 0
        # Original dialect-selection metadata survives a long-lived connection,
        # but only while that session is active within the ring's 60-second TTL.
        # This is not a fabricated handshake or reconstructed wire event.
        self._session_metadata = OrderedDict()
        self._metadata_bytes = 0
        self._sequence = 0
        self._capture_id = uuid4().hex
        self._predecessors = OrderedDict()
        self._pending = {}  # (device, fingerprint, sample role) -> monotonic deadline
        self._sample_bytes = 0
        self.dropped_events = 0
        self.evicted_incidents = 0
        self._revision = self._saved_revision = self._attempts = 0
        self._error = None
        self._wake = asyncio.Event()
        self._progress = asyncio.Event()
        self._task = None
        self._started = self._closed = self._stopping = False
        self._loaded = False
        self._enabled_changed = False
        self._watch_changes = set()
        self._recoveries_during_load = {}
        self._persistence = all(callable(getattr(storage, method, None))
                                for method in ("incident_load", "incident_save"))

    async def start(self):
        if self._started or self._closed:
            return
        self._started = True
        self._progress = asyncio.Event()
        if self._persistence:
            try:
                self._restore(await self.storage.incident_load())
                self._loaded = True
                self._error = None
            except asyncio.CancelledError:
                # There is no writer yet. Permit an explicit start retry, but
                # cleanup must neither restart the blocked load nor await a
                # progress notification that no task can ever produce.
                self._started = False
                self._error = "incident_start_cancelled"
                self._progress.set()
                raise
            except StorageError:
                self._error = "storage_unavailable"
            except ValueError:
                self._persistence = False
                self._error = "unsupported_incident_schema"
            if self._persistence:
                self._task = asyncio.create_task(self._writer(), name="solar-inverter-incidents")
                self._task.add_done_callback(self._writer_done)
                if not self._loaded:
                    self._wake.set()
        self.tick()

    def _writer_done(self, task):
        error = None if task.cancelled() else task.exception()
        if not self._stopping and self._persistence and (task.cancelled() or error is not None):
            self._error = "incident_writer_unavailable"
        self._progress.set()

    def _changed(self, immediate=False):
        self._revision += 1
        if immediate:
            self._wake.set()
        self._notify()

    def _notify(self):
        if self.on_update:
            # UI notification must never break polling, and is not an alarm.
            try:
                self.on_update()
            except Exception:
                pass

    def _snapshot(self):
        # Event dictionaries are immutable after admission. Copy only containers
        # mutated on the loop; the worker can serialize this stable snapshot.
        return {"schema": INCIDENT_SCHEMA, "enabled": self.enabled,
                "watches": {key: dict(value) for key, value in self._watches.items()},
                "dropped_events": self.dropped_events, "evicted_incidents": self.evicted_incidents,
                "incidents": [{**item, "samples": [{**sample, "events": list(sample["events"])}
                                                    for sample in item["samples"]]}
                              for item in self._records.values()]}

    def _restore(self, snapshot):
        if not snapshot:
            self._recoveries_during_load.clear()
            return
        if snapshot.get("schema") != INCIDENT_SCHEMA:
            raise ValueError("unsupported_incident_schema")
        if not self._enabled_changed:
            self.enabled = bool(snapshot.get("enabled", True))
        for key, value in snapshot.get("watches", {}).items():
            if key not in self._watch_changes and len(self._watches) < MAX_WATCHES:
                self._watches[key] = value
        self.dropped_events += snapshot.get("dropped_events", 0)
        self.evicted_incidents += snapshot.get("evicted_incidents", 0)
        for item in snapshot.get("incidents", [])[:MAX_INCIDENTS]:
            key = (item["device_id"], item["fingerprint"])
            recovery = self._recoveries_during_load.get(item["device_id"])
            if recovery and item.get("stage") in COMMUNICATION_STAGES and (_time(item["last_seen"]) or recovery) <= recovery:
                item["recovered_count"] = item["count"]
            for sample in item["samples"]:
                if not sample["complete"]:
                    sample["interrupted"] = True
            current = self._records.get(key)
            if current:
                current["count"] += item["count"]
                current["recovered_count"] += item["recovered_count"]
                current["first_seen"] = min(current["first_seen"], item["first_seen"])
                # Preserve first/recovered and reserve one replaceable auxiliary
                # slot. A newer explicit watch takes priority over distinct shape.
                saved = {sample["role"]: sample for sample in item["samples"]}
                live = {sample["role"]: sample for sample in current["samples"]}
                selected = {role: saved.get(role, live.get(role)) for role in ("first", "recovered")}
                watched = [samples["watched"] for samples in (live, saved) if "watched" in samples]
                if watched:
                    selected["watched"] = max(watched, key=lambda sample: sample["captured_at"])
                else:
                    selected["distinct_structure"] = saved.get("distinct_structure", live.get("distinct_structure"))
                current["samples"] = [sample for sample in selected.values() if sample is not None]
                for role, sample in live.items():
                    if selected.get(role) is not sample:
                        self._pending.pop((*key, role), None)
            else:
                self._records[key] = item
        self._recount()
        self._enforce_limits()
        self._watch_changes.clear()
        self._recoveries_during_load.clear()

    async def _writer(self):
        retry = False
        while not self._stopping:
            await self._wake.wait()
            self._wake.clear()
            if self._stopping:
                break
            if retry:
                await asyncio.sleep(RETRY_SECONDS)
            revision = self._revision
            previous_error = self._error
            try:
                if not self._loaded:
                    self._restore(await self.storage.incident_load())
                    self._loaded = True
                    revision = self._revision
                await self.storage.incident_save(self._snapshot())
                self._saved_revision = revision
                self._error = None
                retry = False
            except StorageError:
                self._error = "storage_unavailable"
                retry = True
            except ValueError:
                self._error = "unsupported_incident_schema"
                self._persistence = False
            self._attempts += 1
            self._progress.set()
            self._progress = asyncio.Event()
            if previous_error != self._error:
                self._notify()
            if not self._persistence:
                break
            if retry or self._revision != revision:
                self._wake.set()

    async def _flush(self):
        if not self._persistence:
            return
        revision, attempts = self._revision, self._attempts
        if self._task is None or self._task.done():
            if self._saved_revision >= revision:
                return
            raise StorageError("incident_writer_unavailable")
        self._wake.set()
        while self._saved_revision < revision or not self._loaded:
            progress = self._progress
            if self._task is None or self._task.done():
                raise StorageError("incident_writer_unavailable")
            if self._attempts > attempts and self._error:
                raise StorageError(self._error)
            await progress.wait()

    def _trim_ring(self):
        cutoff = monotonic() - RING_SECONDS
        while self._ring and (self._ring[0][0] < cutoff or len(self._ring) > RING_EVENTS or self._ring_bytes > RING_BYTES):
            when, event, size = self._ring.popleft()
            self._ring_bytes -= size
            if when >= cutoff:
                self.dropped_events += 1
        for session, (when, _, size) in list(self._session_metadata.items()):
            if when < cutoff:
                del self._session_metadata[session]
                self._metadata_bytes -= size
        for session, (when, _) in list(self._predecessors.items()):
            if when < cutoff:
                del self._predecessors[session]

    def _remember_session(self, event, size):
        session = event.get("session")
        if not session:
            return
        previous = self._session_metadata.pop(session, None)
        if previous:
            self._metadata_bytes -= previous[2]
        if event["kind"] == "dialect_selected" and event.get("dialect") in ("at", "binary") and "wire_hex" not in event:
            previous = (monotonic(), event, size)
        if previous:
            self._session_metadata[session] = (monotonic(), previous[1], previous[2])
            self._metadata_bytes += previous[2]
        while len(self._session_metadata) > SESSION_METADATA_COUNT or self._metadata_bytes > SESSION_METADATA_BYTES:
            _, (_, _, removed) = self._session_metadata.popitem(last=False)
            self._metadata_bytes -= removed

    def _watch_active(self, device_id=None):
        now = _now()
        return any(value["status"] == "armed" and (_time(value["expires_at"]) or now) > now
                   for key, value in self._watches.items() if device_id is None or key == device_id)

    def observe(self, kind, **fields):
        if self._closed or not (self.enabled or self._watch_active() or self._pending):
            self._predecessors.clear()
            return
        self._trim_ring()
        self._sequence += 1
        session = _ref(fields.get("session"))
        previous = self._predecessors.pop(session, None)
        # Advance even for an oversized/dropped event. A later retained event
        # then points at missing evidence instead of silently bridging the gap.
        self._predecessors[session] = (monotonic(), self._sequence)
        while len(self._predecessors) > SESSION_METADATA_COUNT:
            self._predecessors.popitem(last=False)
        event = {"id": self._sequence, "kind": _tag(kind, "unknown"),
                 "time": (_time(fields.get("time")) or _now()).isoformat(), "monotonic": monotonic(),
                 "capture_id": self._capture_id, "previous_event_id": previous[1] if previous else None}
        for key in TAG_FIELDS - {"kind"}:
            if _tag(fields.get(key)):
                event[key] = fields[key]
        for key in NUMBER_FIELDS | {"code"}:
            value = fields.get(key)
            if type(value) in (int, float) and abs(value) <= 2**53 and math.isfinite(value):
                event[key] = value
        for key in PRIVATE_FIELDS:
            if _ref(fields.get(key)):
                event[key] = _ref(fields[key])
        for key in ROUTE_FIELDS:
            value = fields.get(key)
            if isinstance(value, (list, tuple)) and len(value) <= 4 and all(type(v) is int and 0 <= v <= 65535 for v in value):
                event[key] = list(value)
        if fields.get("direction") in ("tx", "rx"):
            event["direction"] = fields["direction"]
        raw = fields.get("data")
        if isinstance(raw, (bytes, bytearray, memoryview)):
            if len(raw) * 2 > RING_BYTES:
                self.dropped_events += 1
                return
            event.update(byte_count=len(raw), wire_hex=raw.hex())
        size = len(_json(event))
        if size > RING_BYTES:
            self.dropped_events += 1
            return
        self._trim_ring()
        self._remember_session(event, size)
        self._ring.append((monotonic(), event, size))
        self._ring_bytes += size
        self._trim_ring()
        for key, deadline in list(self._pending.items()):
            if monotonic() > deadline:
                continue
            item = self._records.get(key[:2])
            if not item:
                continue
            sample = next((s for s in item["samples"] if s["role"] == key[2]), None)
            if sample is not None and self._matches(event, item["device_id"], sample["session"]):
                if sample["event_bytes"] + size <= SAMPLE_BYTES and len(sample["events"]) < SAMPLE_EVENTS:
                    sample["events"].append(event)
                    sample["event_bytes"] += size
                    self._sample_bytes += size + 1
                else:
                    sample["dropped_events"] += 1
                    self.dropped_events += 1
        self._enforce_limits()

    @staticmethod
    def _matches(event, device_id, session):
        # A known different device is never included, even if session labels clash.
        if event.get("device_id") and event["device_id"] != device_id:
            return False
        return bool((session and event.get("session") == session)
                    or (device_id and event.get("device_id") == device_id))

    def _events(self, device_id, session):
        self._trim_ring()
        entries = [(event, size) for _, event, size in self._ring if self._matches(event, device_id, session)]
        ids = {event["id"] for event, _ in entries}
        sessions = {event.get("session") for event, _ in entries}
        context = [(event, size) for key, (_, event, size) in self._session_metadata.items()
                   if key in sessions and event["id"] not in ids and self._matches(event, device_id, session)]
        return context + entries

    def _add_sample(self, item, role, session, *, complete=False, structure=None):
        if role == "watched":
            # Catch next failure means THIS occurrence, even for a saturated
            # fingerprint. Keep first/recovered; replace the auxiliary slot and
            # its old deadline, then capture a fresh prelude and ten-second tail.
            for sample in item["samples"]:
                if sample["role"] not in ("first", "recovered"):
                    self._pending.pop((item["device_id"], item["fingerprint"], sample["role"]), None)
            item["samples"] = [sample for sample in item["samples"] if sample["role"] in ("first", "recovered")]
        elif role == "distinct_structure" and any(sample["role"] == "watched" for sample in item["samples"]):
            return
        if len(item["samples"]) >= MAX_SAMPLES or any(s["role"] == role for s in item["samples"]):
            return
        entries = self._events(item["device_id"], session)
        events = [event for event, _ in entries]
        sample = {"role": role, "captured_at": _now().isoformat(), "session": session,
                  # Frozen provenance of this sample, independent of later
                  # exporter builds, recovery samples, or recorder.build updates.
                  "capture_build": _build_ref(self.build),
                  "complete": complete, "interrupted": False, "events": events,
                  "event_bytes": sum(size for _, size in entries), "dropped_events": 0,
                  "structure": structure}
        item["samples"].append(sample)
        if not complete:
            self._pending[(item["device_id"], item["fingerprint"], role)] = monotonic() + TAIL_SECONDS
        self._recount()

    def record_issue(self, record, context):
        if self._closed:
            return
        context = context or {}
        device = _ref(context.get("device_id") or record.get("device_id"))
        if not (self.enabled or self._watch_active(device)):
            return
        merged = {**record, **{key: context[key] for key in ("profile_id", "transport") if context.get(key)}}
        value = fingerprint(merged)
        key = (device, value)
        now = _now().isoformat()
        session = _ref(context.get("session"))
        # Exact structural fields select the third sample within a normalized
        # fingerprint's size class; arbitrary payload values are never compared.
        structure = hashlib.sha256(_json({key: merged.get(key) for key in
            ("payload_length", "expected_length", "payload_kind") if type(merged.get(key)) in (int, str)})).hexdigest()
        item = self._records.get(key)
        existing = item is not None
        immediate = item is None
        if item is None:
            item = {"device_id": device, "fingerprint": value, "schema": INCIDENT_SCHEMA,
                    "fingerprint_revision": FINGERPRINT_REVISION,
                    "code": _tag(record.get("code"), "unknown_payload"), "stage": _tag(record.get("stage"), "unknown"),
                    "profile_id": _tag(merged.get("profile_id")), "transport": _tag(merged.get("transport")),
                    "first_seen": now, "last_seen": now, "count": 0, "recovered_count": 0, "samples": []}
            self._records[key] = item
            self._add_sample(item, "first", session, structure=structure)
        elif item["samples"] and structure != item["samples"][0]["structure"]:
            before = len(item["samples"])
            self._add_sample(item, "distinct_structure", session, structure=structure)
            immediate = len(item["samples"]) != before
        item["count"] += 1
        item["last_seen"] = now
        # Bounded last-session context only, not a growing session registry.
        item["session"] = session
        item["hardware"] = {name: _ref(context.get(name)) for name in ("firmware", "collector_model")}
        if type(context.get("model_code")) is int:
            item["hardware"]["model_code"] = context["model_code"]
        watch = self._watches.get(device)
        if watch and self._watch_active(device):
            if existing:
                self._add_sample(item, "watched", session, structure=structure)
            watch.update(status="captured", fingerprint=value, captured_at=now)
            immediate = True
        self._enforce_limits()
        self._changed(immediate=immediate)

    def recovered(self, device_id):
        """A successful full poll recovers communication incidents only.

        Readings do not resolve uncertain/rejected commands, clock operations,
        or reconciliation outcomes. Apply the same stage filter after a delayed
        initial persistence load so a backup freeze cannot bypass this boundary.
        """
        if self._closed:
            return
        changed = False
        if self._persistence and not self._loaded:
            if device_id not in self._recoveries_during_load and len(self._recoveries_during_load) >= MAX_INCIDENTS:
                del self._recoveries_during_load[next(iter(self._recoveries_during_load))]
            self._recoveries_during_load[device_id] = _now()
            changed = True
        for item in list(self._records.values()):
            if (item["device_id"] == device_id and item.get("stage") in COMMUNICATION_STAGES
                    and item["count"] > item["recovered_count"]):
                item["recovered_count"] = item["count"]
                self._add_sample(item, "recovered", item.get("session", ""), complete=True)
                changed = True
        if changed:
            self._enforce_limits()
            self._changed(immediate=True)

    def _recount(self):
        self._sample_bytes = sum(_sample_size(sample) for item in self._records.values() for sample in item["samples"])

    def _evict(self, key):
        item = self._records.pop(key)
        self._sample_bytes -= sum(_sample_size(sample) for sample in item["samples"])
        for pending in list(self._pending):
            if pending[:2] == key:
                del self._pending[pending]

    def _enforce_limits(self):
        while self._records and (len(self._records) > MAX_INCIDENTS or self._sample_bytes > MAX_SAMPLE_BYTES):
            # Prefer retaining unrecovered faults over old recovered examples.
            key = min(self._records, key=lambda key: (
                self._records[key]["count"] != self._records[key]["recovered_count"],
                self._records[key]["last_seen"]))
            self._evict(key)
            self.evicted_incidents += 1
            self._changed(immediate=True)

    def tick(self):
        if self._closed:
            return
        self._trim_ring()
        changed = False
        for key, deadline in list(self._pending.items()):
            if monotonic() >= deadline:
                item = self._records.get(key[:2])
                if item:
                    for sample in item["samples"]:
                        if sample["role"] == key[2]:
                            sample["complete"] = True
                del self._pending[key]
                changed = True
        now = _now()
        for watch in self._watches.values():
            if watch["status"] == "armed" and (_time(watch["expires_at"]) or now) <= now:
                watch["status"] = "expired"
                changed = True
        if changed:
            self._changed()
        if self._revision > self._saved_revision:
            self._wake.set()

    async def configure(self, enabled):
        await self._ready()
        if type(enabled) is not bool:
            raise ValueError("invalid_incident_enabled")
        self.enabled = enabled
        if not enabled:
            self._predecessors.clear()
        self._enabled_changed = True
        if not enabled and not self._watch_active() and not self._pending:
            self._ring.clear()
            self._ring_bytes = 0
            self._session_metadata.clear()
            self._metadata_bytes = 0
        self._changed(immediate=True)
        await self._flush()
        return self.view()

    async def arm(self, device_id, hours):
        await self._ready()
        if (not _ref(device_id) or len(device_id) > 160 or type(hours) not in (int, float)
                or not math.isfinite(hours) or not 1 <= hours <= 24):
            raise ValueError("invalid_incident_watch")
        if device_id not in self._watches and len(self._watches) >= MAX_WATCHES:
            inactive = next((key for key in self._watches if not self._watch_active(key)), None)
            if inactive is None:
                raise ValueError("incident_watch_limit")
            del self._watches[inactive]
            self._watch_changes.discard(inactive)
        if not self._loaded:
            self._watch_changes.add(device_id)
        now = _now()
        self._watches[device_id] = {"status": "armed", "armed_at": now.isoformat(),
                                    "expires_at": (now + timedelta(hours=hours)).isoformat()}
        self._changed(immediate=True)
        await self._flush()
        return self.view(device_id)["watch"]

    async def cancel_watch(self, device_id):
        await self._ready()
        if device_id in self._watches:
            self._watches[device_id]["status"] = "cancelled"
            if not self._loaded:
                self._watch_changes.add(device_id)
            self._changed(immediate=True)
        await self._flush()
        return self.view(device_id)["watch"]

    async def delete(self, fingerprint, device_id=None):
        await self._ready()
        for key in list(self._records):
            if key[1] == fingerprint and (device_id is None or key[0] == device_id):
                self._evict(key)
                self._changed(immediate=True)
        await self._flush()
        return self.view(device_id)

    async def _ready(self):
        if self._closed:
            raise ValueError("incident_recorder_closed")
        if not self._started:
            await self.start()
        if self._persistence and not self._loaded:
            await self._flush()

    def view(self, device_id=None):
        watches = [{"device_id": key, **value, "active": self._watch_active(key)}
                   for key, value in self._watches.items() if device_id is None or key == device_id]
        watch = watches[0] if len(watches) == 1 else {"active": any(w["active"] for w in watches),
                                                    "expires_at": None, "items": watches}
        return {"enabled": self.enabled, "limits": deepcopy(LIMITS), "watch": deepcopy(watch),
                "incidents": [{**_summary(item), "device_id": item["device_id"]}
                              for item in self._records.values() if device_id is None or item["device_id"] == device_id],
                "dropped_events": self.dropped_events, "evicted_incidents": self.evicted_incidents,
                "serialized_sample_bytes": self._sample_bytes, "ring_events": len(self._ring),
                "sample_bytes_accounting": "conservative_serialized_upper_bound",
                "ring_bytes": self._ring_bytes, "pending_tails": len(self._pending),
                "session_metadata_count": len(self._session_metadata), "session_metadata_bytes": self._metadata_bytes,
                "persistence": "enabled" if self._persistence else "memory_only",
                "persistence_error": self._error, "pending_write": self._revision > self._saved_revision and self._persistence}

    async def close(self):
        if self._closed:
            return
        self.tick()
        # Shutdown must not claim that a full ten-second tail was observed.
        for key in self._pending:
            for sample in self._records[key[:2]]["samples"]:
                if sample["role"] == key[2]:
                    sample["interrupted"] = True
        if self._pending:
            self._changed(immediate=True)
        self._pending.clear()
        try:
            await self._flush()
        finally:
            self._closed = self._stopping = True
            self._wake.set()
            if self._task:
                # _flush reports a failed writer as StorageError. Do not mask
                # it with the task's original exception/cancellation on cleanup.
                await asyncio.gather(self._task, return_exceptions=True)
            self._ring.clear()
            self._ring_bytes = 0
            self._session_metadata.clear()
            self._metadata_bytes = 0
            self._predecessors.clear()

    async def export(self, fingerprint, device_id=None, include_raw=False, metadata=None):
        if type(include_raw) is not bool:
            raise ValueError("invalid_include_raw")
        items = [item for item in self._records.values()
                 if item["fingerprint"] == fingerprint and (device_id is None or item["device_id"] == device_id)]
        if not items:
            raise ValueError("incident_not_found")
        # ZIP/analysis work is off-loop. Copy mutable containers before yielding.
        selected = [{**item, "samples": [{**sample, "events": list(sample["events"])}
                                         for sample in item["samples"]]} for item in items]
        return await asyncio.to_thread(_export, selected, include_raw, _description(metadata), dict(self.build), self.dropped_events)


def _description(metadata):
    # These are explicit user-entered strings, not automatically collected fields.
    return {key: value[:2000] for key, value in (metadata or {}).items()
            if key in ("inverter_model", "collector_model", "firmware", "symptom", "network_setup", "reference_readings")
            and isinstance(value, str)}


def _export_events(samples, raw):
    """Export only proven contiguous runs under independent replay session aliases.

    Capture predecessor links advance before any admission/drop decision, are
    scoped by a per-recorder capture ID, and survive sample persistence. Missing
    links (including export clipping) break BOTH directions and all correlation.
    Old saved events without these links cannot prove continuity: isolate them.
    Metadata copies are labeled context, not invented handshakes or wire bytes.
    """
    refs, seen, selected, metadata, epochs = {}, set(), [], {}, {}
    dropped = 0

    def public(original):
        event = {key: value for key, value in original.items()
                 if key in TAG_FIELDS | NUMBER_FIELDS | ROUTE_FIELDS | {"time", "monotonic", "direction"}}
        for key in ("session", "source_ref"):
            ref = (key, original.get(key, ""))
            event[key] = refs.setdefault(ref, f"{key}-{len(refs) + 1}")
        if raw and "wire_hex" in original and event.get("direction") in ("tx", "rx"):
            event["wire_hex"] = original["wire_hex"]
        event["original_event_id"] = original["id"]
        return event

    budget = compatibility.MAX_EVENTS // max(1, len(samples))
    byte_budget = EXPORT_EVENT_BYTES // max(1, len(samples))
    for index, sample in enumerate(samples):
        sample_bytes = 0
        entries = sample["events"]

        def scope_of(original):
            epoch = original.get("capture_id") or ("legacy", index)
            epochs.setdefault(epoch, len(epochs))
            return epoch, original.get("session", "")

        for original in entries:
            scope = scope_of(original)
            if (original["kind"] == "dialect_selected" and original.get("dialect") in ("at", "binary")
                    and "wire_hex" not in original):
                metadata.setdefault(scope, {})[original["id"]] = original
        if len(entries) > budget:
            dropped += len(entries) - budget
            entries = entries[:budget // 2] + entries[-(budget - budget // 2):]
        for original in entries:
            scope = scope_of(original)
            identity = (scope, original["id"])
            if identity in seen:
                continue
            event = public(original)
            size = len(_json(event))
            if sample_bytes + size > byte_budget:
                dropped += 1
                continue
            sample_bytes += size
            seen.add(identity)
            selected.append((scope, original, event))

    # Wall-clock adjustments must not reorder bytes within a capture. Different
    # capture epochs never share a parser/correlation scope, including restart.
    selected.sort(key=lambda entry: (epochs[entry[0][0]], entry[1]["id"]))
    metadata_ids = {scope: sorted(values) for scope, values in metadata.items()}
    events, last, parent_last = [], {}, {}
    event_bytes = segments = gaps = legacy_events = 0
    for scope, original, event in selected:
        previous = last.get(scope)
        proven = bool(original.get("capture_id") and original.get("session")) and "previous_event_id" in original
        contiguous = proven and previous is not None and original["previous_event_id"] == previous[0]
        parent = event["session"]
        epoch_changed = previous is None and parent in parent_last
        alias = previous[1] if contiguous else f"{parent}-segment-{segments + 1}"
        event.update(session=alias, source_session=parent)
        chunk = []
        has_gap = not contiguous and (previous is not None or epoch_changed or not proven or original.get("previous_event_id") is not None)
        if has_gap:
            chunk.append({"kind": "capture_gap", "time": original["time"], "session": alias,
                          "source_session": parent, "origin": "incident_export",
                          "directions": ["tx", "rx"],
                          "reason": (("capture_epoch_changed" if epoch_changed else "noncontiguous_capture")
                                     if proven else "capture_continuity_unproven"),
                          "previous_session": previous[1] if previous else parent_last.get(parent)})
        if not contiguous and original["kind"] != "dialect_selected":
            ids = metadata_ids.get(scope, [])
            position = bisect_right(ids, original["id"]) - 1
            if position >= 0:
                context = public(metadata[scope][ids[position]])
                context.update(session=alias, source_session=parent, context_only=True,
                               original_origin=context.get("origin"), origin="incident_export_context")
                chunk.append(context)
        chunk.append(event)
        for offset, entry in enumerate(chunk, len(events) + 1):
            entry["id"] = offset
        size = sum(len(_json(entry)) for entry in chunk)
        if len(events) + len(chunk) > compatibility.MAX_EVENTS or event_bytes + size > EXPORT_EVENT_BYTES:
            dropped += 1
            # Leave last untouched: any later retained event must prove its
            # predecessor is still present, or begin another isolated segment.
            continue
        events.extend(chunk)
        event_bytes += size
        segments += not contiguous
        gaps += has_gap
        legacy_events += not proven
        last[scope] = (original["id"], alias)
        parent_last[parent] = alias
    for index, event in enumerate(events, 1):
        event["id"] = index
    continuity = {"revision": 1, "policy": "segment_scoped_replay", "segments": segments, "gaps": gaps,
                  "legacy_events": legacy_events,
                  "explanation": "Session aliases identify contiguous capture segments, not new physical connections. "
                                 "At gaps both directions, partial frames, request correlation and profile caches are isolated. "
                                 "Repeated dialect metadata is labeled context_only and contains no invented wire bytes. "
                                 "A missing request is missing capture evidence, not proof of a device fault."}
    return events, dropped, continuity


def _export(items, raw, description, build, dropped_events):
    build = _build_ref(build)
    samples = [sample for item in items for sample in item["samples"]]
    events, export_dropped, continuity = _export_events(samples, raw)
    dropped = dropped_events + export_dropped
    summary = _summary(max(items, key=lambda item: item["last_seen"]))
    summary["count"] = sum(item["count"] for item in items)
    summary["recovered_count"] = sum(item["recovered_count"] for item in items)
    summary["first_seen"] = min(item["first_seen"] for item in items)
    summary["last_seen"] = max(item["last_seen"] for item in items)
    summary["sample_count"] = len(samples)
    summary["status"] = "recovered" if summary["count"] == summary["recovered_count"] else "unrecovered"
    summary["needs_attention"] = summary["status"] != "recovered" or summary["known_issue"]["status"] == "unknown"
    report = {"schema": compatibility.SCHEMA, "report_id": items[0]["fingerprint"],
              "analyzer_version": compatibility.ANALYZER_VERSION, "captured_at": _now().isoformat(),
              "build": build, "description": description, "listeners": [],
              "context": {"incident": summary, "incident_schema": INCIDENT_SCHEMA,
                          "build_role": "exporter", "exporter_build": build,
                          "fingerprint_revision": FINGERPRINT_REVISION,
                          "capture_continuity": continuity,
                          "samples": [{**{key: sample[key] for key in ("role", "captured_at", "complete", "interrupted", "dropped_events")},
                                       "capture_build": _build_ref(sample.get("capture_build"))}
                                      for sample in samples]},
              "collection": {"dropped_events": dropped, "drop_counter_scope": "recorder_global_plus_export",
                             "limits": LIMITS}, "events": events,
              "raw_protocol_included": raw,
              "redaction": "Only whitelisted event fields are included. Session/source references are report-local. "
                           "Explicit user description and feedback strings are included verbatim; review before sharing. "
                           "Opt-in original wire bytes can contain PN, addresses and other private data. "
                           "Original dialect-selection metadata can predate the rolling wire window. "
                           "Top-level build identifies the exporter, not the capture version. Each sample has its own "
                           "capture_build; an empty object means unknown, including older saved samples. "
                           + continuity["explanation"] + " " +
                           "Missing startup or truncated samples cannot establish complete protocol replay."}
    if raw:
        report["context"]["hardware"] = [item.get("hardware", {}) for item in items]
    return _package(report, summary)


def _package(report, summary):
    data, analysis = compatibility.package_report(report)
    if summary:
        # A rolling incident window need not contain startup/admission. Absence
        # here cannot establish that no collector connected or no route qualified.
        analysis["findings"] = [finding for finding in analysis["findings"]
                                if finding["code"] not in ("no_incoming_connection", "collector_only")]
        analysis["capture_continuity"] = report["context"]["capture_continuity"]
        analysis.update(build_role="exporter", exporter_build=dict(report["build"]))
        analysis.update(incident=summary, search_url=summary["search_url"],
                        issue_summary=f"Incident {summary['fingerprint']}\nCode: {summary['code']}\n"
                                      f"Status: {summary['status']}; occurrences: {summary['count']}\n"
                                      + summary["known_issue"]["advice"])
    else:
        analysis = {"schema": compatibility.SCHEMA, "report_type": "compatibility_feedback", "findings": [],
                    "coverage": {"evidence": "user_reported"},
                    "issue_summary": "User-reported compatibility feedback\n" + "\n".join(
                        f"- {entry['feature']}: {entry['result']}"
                        for entry in report["context"]["compatibility_feedback"])}
    # Keep the existing strict archive member list and regenerate hashes after
    # adding incident-specific analysis. validate_package/replay remain compatible.
    with ZipFile(io.BytesIO(data)) as archive:
        files = {name: archive.read(name) for name in archive.namelist() if name != "manifest.json"}
    files["analysis.json"] = _json(analysis)
    files["README.txt"] = (analysis["issue_summary"] + "\n\n" + report["redaction"]).encode()
    files["manifest.json"] = _json({"schema": compatibility.SCHEMA,
        "files": {name: hashlib.sha256(value).hexdigest() for name, value in files.items()},
        "raw_protocol_included": report["raw_protocol_included"],
        "dropped_events": report["collection"]["dropped_events"]})
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue(), analysis


async def export_compatibility_feedback(feedback, *, metadata=None, build=None):
    """Separate explicit per-feature user feedback, not an automatically raised incident.

    feature is a stable UI feature ID; result is working/not_working/unknown.
    comment is explicit user text (potentially identifying), not auto-redacted.
    """
    if not isinstance(feedback, list) or len(feedback) > 64:
        raise ValueError("invalid_compatibility_feedback")
    entries = []
    for item in feedback:
        if (not isinstance(item, dict) or not _tag(item.get("feature"))
                or item.get("result") not in ("working", "not_working", "unknown")):
            raise ValueError("invalid_compatibility_feedback")
        entries.append({"feature": item["feature"], "result": item["result"],
                        "comment": str(item.get("comment", ""))[:2000]})
    report = {"schema": compatibility.SCHEMA, "report_id": "compatibility-feedback",
              "build": {key: _ref(value) for key, value in (build or {}).items() if key in ("version", "sha256")},
              "description": _description(metadata), "listeners": [], "events": [],
              "context": {"compatibility_feedback": entries, "evidence": "user_reported"},
              "collection": {"dropped_events": 0}, "raw_protocol_included": False,
              "redaction": "Separate user-reported compatibility feedback; no incident or device commands. "
                           "User comments and descriptions are included verbatim and may identify you."}
    return await asyncio.to_thread(_package, report, None)
