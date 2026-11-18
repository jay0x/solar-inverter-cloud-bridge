"""Offline passive-recorder, persistence, privacy and replay contracts (no builds)."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from zipfile import ZipFile

from custom_components.solar_inverter_bridge.core import incidents as module
from custom_components.solar_inverter_bridge.core.binary import BinaryFrame
from custom_components.solar_inverter_bridge.core.framing import crc16, read_request
from custom_components.solar_inverter_bridge.core.compatibility import validate_package, replay
from custom_components.solar_inverter_bridge.core.incidents import IncidentRecorder, fingerprint, export_compatibility_feedback
from custom_components.solar_inverter_bridge.core.storage import Storage, StorageError


CONTEXT = {"device_id": "device-private", "session": "session-private", "profile_id": "smg_4", "transport": "binary"}
ISSUE = {"code": "binary_empty_inverter_reply", "stage": "poll", "function": 3,
         "register_address": 100, "register_count": 8, "payload_length": 0}


def wire(recorder, data=b"original-PN-PRIVATE-192.168.50.6", **fields):
    recorder.observe("wire", session=CONTEXT["session"], direction="rx", source_ref="192.168.50.6",
                     listener_port=8899, data=data, **fields)


class MemoryStore:
    def __init__(self):
        self.snapshot = None
        self.writes = 0
        self.fail = False
        self.gate = None
        self.active = self.maximum_active = 0
        self.history = []

    async def incident_load(self):
        if self.fail:
            raise StorageError("storage_backup_in_progress")
        return deepcopy(self.snapshot)

    async def incident_save(self, snapshot):
        self.active += 1
        self.maximum_active = max(self.active, self.maximum_active)
        try:
            if self.gate:
                await self.gate.wait()
            if self.fail:
                raise StorageError("storage_backup_in_progress")
            self.snapshot = deepcopy(snapshot)
            self.history.append(self.snapshot)
            self.writes += 1
        finally:
            self.active -= 1


class FingerprintTests(unittest.TestCase):
    def test_identity_and_measurements_do_not_change_fingerprint(self):
        baseline = fingerprint({**ISSUE, "shape": {"values": [12.3, 48]}}, CONTEXT)
        for key, value in {"pn": "different", "ip": "10.20.30.40", "tid": 65535,
                           "occurred_at": "2099-12-31", "payload_hex": "ffff", "values": [0, 99],
                           "device_id": "other", "parameter": "user text"}.items():
            self.assertEqual(baseline, fingerprint({**ISSUE, key: value, "shape": {"values": [0.0, 2]}},
                                                  {**CONTEXT, "device_id": "another", "session": "new"}))
        for key in ("code", "stage", "function", "register_address", "register_count", "exception_code"):
            changed = {**ISSUE, key: "different" if key in ("code", "stage") else 999}
            self.assertNotEqual(fingerprint(ISSUE, CONTEXT), fingerprint(changed, CONTEXT))
        self.assertNotEqual(fingerprint(ISSUE, CONTEXT), fingerprint(ISSUE, {**CONTEXT, "profile_id": "other"}))
        self.assertNotEqual(fingerprint(ISSUE, CONTEXT), fingerprint(ISSUE, {**CONTEXT, "transport": "at"}))


class RecorderTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_and_untrusted_sample_build_refs_are_not_inferred_or_leaked(self):
        for saved_build, expected in (
            (None, {}),
            ({"version": "old", "sha256": "a" * 64, "path": "private-build-path", "token": "private-build-token"},
             {"version": "old", "sha256": "a" * 64}),
            ({"version": {"token": "private-build-token"}, "sha256": ["private-build-path"]}, {}),
        ):
            with self.subTest(saved_build=saved_build):
                store = MemoryStore()
                recorder = IncidentRecorder(store)
                await recorder.start()
                recorder.record_issue(ISSUE, CONTEXT)
                await recorder.close()
                sample = store.snapshot["incidents"][0]["samples"][0]
                if saved_build is None:
                    del sample["capture_build"]  # pre-provenance persisted sample
                else:
                    sample["capture_build"] = saved_build
                restarted = IncidentRecorder(store, build={"version": "exporter", "sha256": "b" * 64,
                                                           "token": "private-exporter-token"})
                await restarted.start()
                value = restarted.view()["incidents"][0]["fingerprint"]
                data, analysis = await restarted.export(value)
                report = validate_package(data)
                self.assertEqual(report["context"]["samples"][0]["capture_build"], expected)
                self.assertEqual(report["build"], {"version": "exporter", "sha256": "b" * 64})
                self.assertEqual(analysis["build_role"], "exporter")
                with ZipFile(io.BytesIO(data)) as archive:
                    contents = b"".join(archive.read(name) for name in archive.namelist()).decode()
                for secret in ("private-build-path", "private-build-token", "private-exporter-token"):
                    self.assertNotIn(secret, contents)
                if saved_build is None:
                    self.assertNotIn("capture_build", next(iter(restarted._records.values()))["samples"][0])
                await restarted.close()

    async def test_cancelled_initial_load_closes_without_restarting_or_waiting_for_writer(self):
        entered, release = asyncio.Event(), asyncio.Event()
        store = MemoryStore()
        loads = []

        async def load():
            loads.append(True)
            entered.set()
            await release.wait()

        store.incident_load = load
        recorder = IncidentRecorder(store)
        start = asyncio.create_task(recorder.start())
        await entered.wait()
        start.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await start
        self.assertFalse(recorder._started)
        self.assertIsNone(recorder._task)
        await asyncio.wait_for(recorder.close(), 0.2)
        self.assertTrue(recorder._closed)
        self.assertEqual(len(loads), 1)
        self.assertEqual(store.writes, 0)
        self.assertFalse(release.is_set())

    async def test_cancelled_load_with_pending_incident_reports_missing_writer_and_can_retry_start(self):
        for retry in (False, True):
            with self.subTest(retry=retry):
                entered, release = asyncio.Event(), asyncio.Event()
                store = MemoryStore()

                async def load():
                    entered.set()
                    await release.wait()

                store.incident_load = load
                recorder = IncidentRecorder(store)
                start = asyncio.create_task(recorder.start())
                await entered.wait()
                recorder.record_issue(ISSUE, CONTEXT)
                start.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await start
                if retry:
                    release.set()
                    await asyncio.wait_for(recorder.start(), 0.2)
                    await asyncio.wait_for(recorder.close(), 0.2)
                    self.assertEqual(store.snapshot["incidents"][0]["count"], 1)
                else:
                    with self.assertRaisesRegex(StorageError, "incident_writer_unavailable"):
                        await asyncio.wait_for(recorder.close(), 0.2)
                    self.assertEqual(store.writes, 0)
                self.assertTrue(recorder._closed)

    async def test_flush_wakes_when_writer_dies_or_is_cancelled(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                entered, release = asyncio.Event(), asyncio.Event()
                store = MemoryStore()

                async def save(snapshot):
                    entered.set()
                    await release.wait()
                    raise RuntimeError("unexpected_worker_failure")

                store.incident_save = save
                recorder = IncidentRecorder(store)
                await recorder.start()
                recorder.record_issue(ISSUE, CONTEXT)
                flush = asyncio.create_task(recorder._flush())
                await entered.wait()
                if cancelled:
                    recorder._task.cancel()
                else:
                    release.set()
                with self.assertRaisesRegex(StorageError, "incident_writer_unavailable"):
                    await asyncio.wait_for(flush, 0.2)
                with self.assertRaisesRegex(StorageError, "incident_writer_unavailable"):
                    await asyncio.wait_for(recorder.close(), 0.2)
                self.assertTrue(recorder._task.done())

    async def test_full_poll_recovers_only_device_communication_stages(self):
        store = MemoryStore()
        recorder = IncidentRecorder(store)
        await recorder.start()
        communication = {"poll", "settings_read", "callback", "transport", "admission",
                         "verification", "profile_discovery"}
        for stage in communication | {"command", "reconcile_or_clock", "runtime", "unknown"}:
            codes = ("timeout", "write_rejected", "uncertain") if stage in ("command", "reconcile_or_clock") else ("timeout",)
            for code in codes:
                recorder.record_issue({"stage": stage, "code": code}, CONTEXT)
        recorder.recovered(CONTEXT["device_id"])
        recorder.recovered(CONTEXT["device_id"])
        recorder.record_issue({"stage": "poll", "code": "timeout"}, {**CONTEXT, "device_id": "other"})
        recorder.recovered(CONTEXT["device_id"])
        self.assertEqual(len(recorder.view()["incidents"]), 16)
        for item in recorder.view()["incidents"]:
            expected = item["device_id"] == CONTEXT["device_id"] and item["stage"] in communication
            self.assertEqual(item["recovered_count"], int(expected), item)
            self.assertEqual(item["status"], "recovered" if expected else "unrecovered")
            if not expected:
                self.assertTrue(item["needs_attention"])
                self.assertEqual(item["sample_count"], 1)
        await recorder.close()
        restarted = IncidentRecorder(store)
        await restarted.start()
        for item in restarted.view()["incidents"]:
            if item["stage"] in ("command", "reconcile_or_clock"):
                self.assertEqual(item["recovered_count"], 0)
        await restarted.close()

    async def test_summary_exposes_only_latest_hardware_metadata_after_restart(self):
        store = MemoryStore()
        recorder = IncidentRecorder(store)
        await recorder.start()
        recorder.record_issue(ISSUE, CONTEXT)
        value = recorder.view()["incidents"][0]["fingerprint"]
        self.assertIsNone(recorder.view()["incidents"][0]["firmware"])
        for firmware, model, code in (("8.50.12.3", "Wi-Fi.DTU", 100), ("8.50.12.4", "Wi-Fi.DTU-B", 101)):
            recorder.record_issue(ISSUE, {**CONTEXT, "firmware": firmware, "collector_model": model,
                                         "model_code": code, "pn": "private-pn", "ip": "10.20.30.40"})
        await recorder.close()
        restarted = IncidentRecorder(store)
        await restarted.start()
        summary = restarted.view()["incidents"][0]
        self.assertEqual(summary["fingerprint"], value)
        self.assertEqual((summary["firmware"], summary["collector_model"], summary["model_code"]),
                         ("8.50.12.4", "Wi-Fi.DTU-B", 101))
        self.assertNotIn("pn", summary)
        self.assertNotIn("ip", summary)
        data, analysis = await restarted.export(value)
        report = validate_package(data)
        self.assertEqual(report["context"]["incident"]["firmware"], "8.50.12.4")
        self.assertEqual(analysis["incident"]["model_code"], 101)
        self.assertNotIn("private-pn", json.dumps(report))
        self.assertNotIn("10.20.30.40", json.dumps(report))
        await restarted.close()

    async def test_first_sample_immediate_repeat_counter_tail_and_recovery(self):
        store = MemoryStore()
        recorder = IncidentRecorder(store)
        clock = [100.0]
        with patch.object(module, "monotonic", side_effect=lambda: clock[0]):
            await recorder.start()
            wire(recorder, b"before", tid=12)
            recorder.record_issue(ISSUE, CONTEXT)
            await recorder._flush()
            first = store.snapshot["incidents"][0]["samples"][0]
            self.assertEqual(bytes.fromhex(first["events"][0]["wire_hex"]), b"before")
            self.assertFalse(first["complete"])
            self.assertEqual(first["events"][0]["tid"], 12)
            clock[0] += 1
            wire(recorder, b"tail")
            for _ in range(100):
                recorder.record_issue(ISSUE, CONTEXT)
            self.assertEqual(len(recorder._records), 1)
            self.assertEqual(recorder.view()["incidents"][0]["sample_count"], 1)
            # No new archive for each repeat; only a coalesced counter snapshot.
            recorder.tick()
            await recorder._flush()
            self.assertLessEqual(store.writes, 2)
            clock[0] = 110.0
            recorder.tick()
            wire(recorder, b"after-tail")
            recorder.recovered(CONTEXT["device_id"])
            summary = recorder.view()["incidents"][0]
            self.assertEqual(summary["count"], 101)
            self.assertEqual(summary["recovered_count"], 101)
            self.assertFalse(summary["needs_attention"])
            self.assertEqual(summary["status"], "recovered")
            await recorder.close()
            samples = store.snapshot["incidents"][0]["samples"]
            self.assertTrue(samples[0]["complete"])
            self.assertEqual([bytes.fromhex(e["wire_hex"]) for e in samples[0]["events"]], [b"before", b"tail"])
            self.assertEqual([s["role"] for s in samples], ["first", "recovered"])

    async def test_sample_roles_are_bounded_and_repeated_recovery_is_idempotent(self):
        recorder = IncidentRecorder(None)
        await recorder.start()
        first = {**ISSUE, "payload_length": 9}
        changed = {**ISSUE, "payload_length": 10}
        self.assertEqual(fingerprint(first, CONTEXT), fingerprint(changed, CONTEXT))
        wire(recorder)
        recorder.record_issue(first, CONTEXT)
        recorder.recovered(CONTEXT["device_id"])
        for _ in range(40):
            recorder.record_issue(changed, CONTEXT)
            recorder.recovered(CONTEXT["device_id"])
            recorder.recovered(CONTEXT["device_id"])
        summary = recorder.view()["incidents"][0]
        self.assertEqual(summary["sample_count"], 3)
        self.assertEqual(summary["count"], summary["recovered_count"])
        self.assertEqual(len(recorder._pending), 2)
        await recorder.close()

    async def test_memory_mock_missing_methods_and_no_shared_view_objects(self):
        for storage in (None, SimpleNamespace()):
            recorder = IncidentRecorder(storage)
            await recorder.start()
            recorder.record_issue({"code": "unknown_payload"}, CONTEXT)
            recorder.recovered(CONTEXT["device_id"])
            view = recorder.view()
            self.assertEqual(view["persistence"], "memory_only")
            self.assertTrue(view["incidents"][0]["needs_attention"])
            self.assertTrue(view["incidents"][0]["support_prompt"])
            self.assertEqual(view["incidents"][0]["notification"], "none")
            view["limits"]["watch_hours"].clear()
            self.assertEqual(recorder.view()["limits"]["watch_hours"], [1, 24])
            await recorder.close()

    async def test_ring_time_size_event_limits_and_oversized_original_chunk(self):
        recorder = IncidentRecorder(None)
        clock = [100.0]
        with patch.object(module, "monotonic", side_effect=lambda: clock[0]):
            for _ in range(2200):
                wire(recorder, b"a")
            self.assertLessEqual(recorder.view()["ring_events"], 2048)
            self.assertLessEqual(recorder.view()["ring_bytes"], 512 * 1024)
            self.assertGreater(recorder.dropped_events, 0)
            clock[0] += 61
            recorder.tick()
            self.assertEqual(recorder.view()["ring_events"], 0)
            wire(recorder, b"x" * 300000)
            self.assertEqual(recorder.view()["ring_events"], 0)
            wire(recorder, b"x" * 120000)
            wire(recorder, b"y" * 120000)
            wire(recorder, b"z" * 120000)
            self.assertLessEqual(recorder.view()["ring_bytes"], 512 * 1024)
            recorder.record_issue(ISSUE, CONTEXT)
            sample = next(iter(recorder._records.values()))["samples"][0]
            self.assertTrue(all(len(bytes.fromhex(event["wire_hex"])) == 120000 for event in sample["events"]))
        await recorder.close()

    async def test_global_fingerprint_and_serialized_data_limits(self):
        recorder = IncidentRecorder(None)
        for index in range(50):
            recorder.record_issue({**ISSUE, "register_address": index}, CONTEXT)
        self.assertEqual(len(recorder._records), 32)
        self.assertEqual(recorder.view()["evicted_incidents"], 18)
        await recorder.close()
        recorder = IncidentRecorder(None)
        # Large original chunks fill both prelude and tail for many problems.
        for index in range(32):
            wire(recorder, bytes([index]) * 120000)
            recorder.record_issue({**ISSUE, "register_address": index}, CONTEXT)
            wire(recorder, bytes([index]) * 120000)
            recorder.recovered(CONTEXT["device_id"])
        actual = sum(len(module._json(item["samples"])) for item in recorder._records.values())
        self.assertLessEqual(actual, 16 * 1024 * 1024)
        self.assertGreaterEqual(recorder.view()["serialized_sample_bytes"], actual)
        self.assertLessEqual(recorder.view()["serialized_sample_bytes"], 16 * 1024 * 1024)
        self.assertGreater(recorder.view()["evicted_incidents"], 0)
        self.assertLessEqual(len(recorder._pending), 96)
        await recorder.close()

    async def test_device_and_session_scoping_delete_does_not_resurrect(self):
        store = MemoryStore()
        recorder = IncidentRecorder(store)
        await recorder.start()
        wire(recorder, b"one")
        recorder.observe("wire", session="other-session", device_id="other-device", direction="rx", data=b"two")
        recorder.record_issue(ISSUE, CONTEXT)
        recorder.record_issue(ISSUE, {**CONTEXT, "device_id": "other-device", "session": "other-session"})
        value = recorder.view()["incidents"][0]["fingerprint"]
        self.assertEqual(len(recorder.view()["incidents"]), 2)
        data, _ = await recorder.export(value, CONTEXT["device_id"], include_raw=True)
        report = validate_package(data)
        self.assertEqual([bytes.fromhex(e["wire_hex"]) for e in report["events"]], [b"one"])
        await recorder.delete(value, CONTEXT["device_id"])
        wire(recorder, b"later")
        recorder.tick()
        await recorder.close()
        restarted = IncidentRecorder(store)
        await restarted.start()
        self.assertEqual([i["device_id"] for i in restarted.view()["incidents"]], ["other-device"])
        await restarted.delete(value)
        self.assertEqual(restarted.view()["incidents"], [])
        await restarted.close()

    async def test_private_fields_never_escape_default_export_and_raw_is_explicit(self):
        recorder = IncidentRecorder(None, build={"version": "test", "secret": "do-not-export"})
        wire(recorder, pn="PN-PRIVATE", ip="192.168.50.6", reason="secret-reason", values={"secret": 1},
             payload_hex="deadbeef", variable="secret-variable", description="secret-description")
        recorder.record_issue(ISSUE, {**CONTEXT, "firmware": "8.50.12.3"})
        value = recorder.view()["incidents"][0]["fingerprint"]
        default, analysis = await recorder.export(value)
        report = validate_package(default)
        self.assertFalse(report["raw_protocol_included"])
        replay(report)
        with ZipFile(io.BytesIO(default)) as archive:
            self.assertNotIn("protocol/original-wire.json", archive.namelist())
            exported = b"".join(archive.read(name) for name in archive.namelist()).decode()
            for secret in ("PN-PRIVATE", "192.168.50.6", "device-private", "session-private", "secret-reason",
                           "secret-variable", "secret-description", "deadbeef", "do-not-export"):
                self.assertNotIn(secret, exported)
            packaged_analysis = json.loads(archive.read("analysis.json"))
            self.assertEqual(packaged_analysis, analysis)
            self.assertIn(value, archive.read("README.txt").decode())
        self.assertEqual(parse_qs(urlparse(analysis["search_url"]).query)["q"],
                         [f'is:issue "{value}" "{ISSUE["code"]}"'])
        raw, _ = await recorder.export(value, include_raw=True, metadata={"symptom": "explicit user comment"})
        raw_report = validate_package(raw)
        self.assertEqual(bytes.fromhex(raw_report["events"][0]["wire_hex"]), b"original-PN-PRIVATE-192.168.50.6")
        self.assertEqual(raw_report["description"]["symptom"], "explicit user comment")
        self.assertIn("verbatim", raw_report["redaction"])
        await recorder.close()

    async def test_original_binary_frame_replays_and_export_cap_validates(self):
        recorder = IncidentRecorder(None)
        recorder.observe("dialect_selected", session=CONTEXT["session"], dialect="binary")
        encoded = BinaryFrame(2, 1, 0, 1, b"").encode()
        recorder.observe("wire", session=CONTEXT["session"], direction="tx", data=encoded)
        recorder.record_issue(ISSUE, CONTEXT)
        value = recorder.view()["incidents"][0]["fingerprint"]
        raw, _ = await recorder.export(value, include_raw=True)
        report = validate_package(raw)
        result = replay(report)
        self.assertIn("outer_valid", json.dumps(result))
        # Small export budgets simulate aggregate export pressure without large ZIPs.
        for _ in range(30):
            wire(recorder, b"x" * 100)
        with patch.object(module, "EXPORT_EVENT_BYTES", 1200):
            raw, _ = await recorder.export(value, include_raw=True)
        self.assertGreater(validate_package(raw)["collection"]["dropped_events"], 0)
        await recorder.close()

    async def test_long_lived_session_replay_preserves_original_bounded_metadata(self):
        recorder = IncidentRecorder(None)
        clock = [100.0]
        with patch.object(module, "monotonic", side_effect=lambda: clock[0]):
            recorder.observe("dialect_selected", session=CONTEXT["session"], dialect="binary")
            original = recorder._ring[0][1]
            for moment in (140.0, 180.0):
                clock[0] = moment
                wire(recorder, BinaryFrame(3, 1, 1, 1, b"").encode())
            self.assertNotIn(original, [entry[1] for entry in recorder._ring])
            recorder.record_issue(ISSUE, CONTEXT)
            value = recorder.view()["incidents"][0]["fingerprint"]
            archive, _ = await recorder.export(value, include_raw=True)
            report = validate_package(archive)
            dialect = next(e for e in report["events"] if e["kind"] == "dialect_selected")
            self.assertEqual(dialect["time"], original["time"])
            self.assertEqual(dialect["monotonic"], original["monotonic"])
            self.assertIn("outer_valid", json.dumps(replay(report)))
            for index in range(100):
                recorder.observe("dialect_selected", session=f"session-{index}", dialect="binary")
            self.assertLessEqual(recorder.view()["session_metadata_count"], 64)
            self.assertLessEqual(recorder.view()["session_metadata_bytes"], 64 * 1024)
            clock[0] += 61
            recorder.tick()
            self.assertEqual(recorder.view()["session_metadata_count"], 0)
        await recorder.close()

    async def test_disabled_watch_utc_restart_capture_and_expiry(self):
        store = MemoryStore()
        now = datetime(2026, 11, 17, tzinfo=timezone.utc)
        with patch.object(module, "_now", return_value=now):
            recorder = IncidentRecorder(store)
            await recorder.start()
            await recorder.configure(False)
            wire(recorder)
            recorder.record_issue(ISSUE, CONTEXT)
            self.assertEqual(recorder.view()["ring_events"], 0)
            self.assertEqual(recorder.view()["incidents"], [])
            watch = await recorder.arm(CONTEXT["device_id"], 2)
            self.assertTrue(watch["active"])
            self.assertEqual(watch["expires_at"], (now + timedelta(hours=2)).isoformat())
            await recorder.close()
        recorder = IncidentRecorder(store)
        with patch.object(module, "_now", return_value=now + timedelta(hours=1)):
            await recorder.start()
            self.assertFalse(recorder.enabled)
            self.assertTrue(recorder.view(CONTEXT["device_id"])["watch"]["active"])
            wire(recorder, b"watched")
            recorder.record_issue(ISSUE, CONTEXT)
            recorder.record_issue(ISSUE, CONTEXT)
            self.assertEqual(recorder.view()["incidents"][0]["count"], 1)
            self.assertEqual(recorder.view(CONTEXT["device_id"])["watch"]["status"], "captured")
            wire(recorder, b"watched-tail")
            await recorder.arm("expires", 1)
            await recorder.arm("cancelled", 24)
            await recorder.cancel_watch("cancelled")
            self.assertFalse(recorder.view("cancelled")["watch"]["active"])
        with patch.object(module, "_now", return_value=now + timedelta(hours=3)):
            recorder.tick()
            self.assertEqual(recorder.view("expires")["watch"]["status"], "expired")
            await recorder.close()
        for hours in (0, 25, float("nan"), float("inf"), True, "2"):
            fresh = IncidentRecorder(None)
            with self.assertRaises(ValueError):
                await fresh.arm("device", hours)
            await fresh.close()

    async def test_slow_writer_queue_is_coalesced_and_snapshot_is_immutable(self):
        store = MemoryStore()
        store.gate = asyncio.Event()
        recorder = IncidentRecorder(store)
        await recorder.start()
        wire(recorder, b"first")
        recorder.record_issue(ISSUE, CONTEXT)
        await asyncio.sleep(0)
        self.assertEqual(store.active, 1)
        for _ in range(2000):
            recorder.record_issue(ISSUE, CONTEXT)
        wire(recorder, b"new-tail")
        recorder.tick()
        self.assertEqual(store.maximum_active, 1)
        self.assertEqual(recorder.view()["limits"]["pending_writes"], 1)
        store.gate.set()
        await recorder._flush()
        self.assertEqual(store.snapshot["incidents"][0]["count"], 2001)
        self.assertEqual(store.history[0]["incidents"][0]["count"], 1)
        self.assertEqual(len(store.history[0]["incidents"][0]["samples"][0]["events"]), 1)
        self.assertLessEqual(store.writes, 2)
        await recorder.close()

    async def test_backup_refusal_retries_without_diagnostic_recursion(self):
        store = MemoryStore()
        updates = []
        recorder = IncidentRecorder(store, on_update=lambda: updates.append(True))
        with patch.object(module, "RETRY_SECONDS", 0.001):
            await recorder.start()
            store.fail = True
            recorder.record_issue(ISSUE, CONTEXT)
            with self.assertRaises(StorageError):
                await recorder._flush()
            self.assertEqual(recorder.view()["persistence_error"], "storage_unavailable")
            self.assertEqual(recorder.view()["incidents"][0]["count"], 1)
            self.assertEqual(len(updates), 2)  # issue + persistence status, no new diagnostic
            store.fail = False
            await recorder._flush()
            self.assertIsNone(recorder.view()["persistence_error"])
            await recorder.close()

    async def test_initial_load_freeze_merges_durable_incidents_instead_of_overwriting(self):
        store = MemoryStore()
        original = IncidentRecorder(store)
        await original.start()
        original.record_issue(ISSUE, CONTEXT)
        await original.close()
        store.fail = True
        recorder = IncidentRecorder(store)
        with patch.object(module, "RETRY_SECONDS", 0.001):
            await recorder.start()
            recorder.record_issue(ISSUE, CONTEXT)
            store.fail = False
            await recorder._flush()
            self.assertEqual(recorder.view()["incidents"][0]["count"], 2)
            await recorder.close()

    async def test_shutdown_failure_is_explicit_bounded_and_leaves_no_task(self):
        store = MemoryStore()
        recorder = IncidentRecorder(store)
        await recorder.start()
        recorder.record_issue(ISSUE, CONTEXT)
        store.fail = True
        with patch.object(module, "RETRY_SECONDS", 0.001):
            with self.assertRaises(StorageError):
                await asyncio.wait_for(recorder.close(), 1)
        self.assertTrue(recorder._task.done())

    async def test_full_poll_during_initial_freeze_recovers_loaded_old_faults(self):
        store = MemoryStore()
        recorder = IncidentRecorder(store)
        await recorder.start()
        recorder.record_issue(ISSUE, CONTEXT)
        for stage in ("command", "reconcile_or_clock"):
            recorder.record_issue({"code": "uncertain", "stage": stage}, CONTEXT)
        await recorder.close()
        store.fail = True
        recorder = IncidentRecorder(store)
        with patch.object(module, "RETRY_SECONDS", 0.001):
            await recorder.start()
            recorder.recovered(CONTEXT["device_id"])
            # This subsequent failure must remain unrecovered after the merge.
            recorder.record_issue(ISSUE, CONTEXT)
            store.fail = False
            await recorder._flush()
            summaries = recorder.view()["incidents"]
            summary = next(item for item in summaries if item["stage"] == "poll")
            self.assertEqual((summary["count"], summary["recovered_count"]), (2, 1))
            self.assertEqual(summary["sample_count"], 1)
            self.assertEqual({item["stage"]: item["recovered_count"] for item in summaries if item["stage"] != "poll"},
                             {"command": 0, "reconcile_or_clock": 0})
            await recorder.close()

    async def test_user_feedback_is_separate_and_never_creates_incidents(self):
        data, _ = await export_compatibility_feedback([
            {"feature": "battery_voltage", "result": "working", "comment": "Compared with display"},
            {"feature": "clock_sync", "result": "unknown"}], metadata={"symptom": "user text"})
        report = validate_package(data)
        self.assertNotIn("incident", report["context"])
        self.assertEqual(report["context"]["evidence"], "user_reported")
        self.assertEqual(len(report["context"]["compatibility_feedback"]), 2)
        self.assertEqual(report["events"], [])
        self.assertFalse(report["raw_protocol_included"])
        with ZipFile(io.BytesIO(data)) as archive:
            analysis = json.loads(archive.read("analysis.json"))
            self.assertEqual(analysis["report_type"], "compatibility_feedback")
            self.assertEqual(analysis["findings"], [])


class IncidentReplayContinuityTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def exchange(dialect):
        request = read_request(184, 1)
        payload = b"\x01\x03\x02\x00\x04"
        response = payload + crc16(payload).to_bytes(2, "little")
        if dialect == "binary":
            request = BinaryFrame(11, 1, 1, 4, request).encode()
            response = BinaryFrame(11, 1, 1, 4, response).encode()
        prefix, suffix = response[:-2], response[-2:]
        bad_crc = bytes((suffix[0] ^ 0xff, suffix[1]))
        return request, prefix, bad_crc, suffix

    @staticmethod
    def emit(recorder, direction, data, **fields):
        recorder.observe("wire", session=CONTEXT["session"], direction=direction, data=data, **fields)

    def begin_exchange(self, recorder, dialect):
        request, prefix, bad_crc, suffix = self.exchange(dialect)
        recorder.observe("dialect_selected", session=CONTEXT["session"], dialect=dialect)
        self.emit(recorder, "tx", request)
        self.emit(recorder, "rx", prefix)
        return prefix, bad_crc, suffix

    async def report(self, recorder):
        value = recorder.view()["incidents"][0]["fingerprint"]
        archive, analysis = await recorder.export(value, include_raw=True)
        report = validate_package(archive)
        self.assertEqual(analysis["capture_continuity"], report["context"]["capture_continuity"])
        self.assertIn("not proof of a device fault", analysis["capture_continuity"]["explanation"])
        return report

    def assert_crc_splice_prevented(self, report, prefix, bad_crc, suffix):
        wires = [event for event in report["events"] if "wire_hex" in event]
        before = next(event for event in wires if event["wire_hex"] == prefix.hex())
        after = next(event for event in wires if event["wire_hex"] == suffix.hex())
        self.assertNotEqual(before["session"], after["session"])
        self.assertEqual(before["source_session"], after["source_session"])
        self.assertNotIn(bad_crc.hex(), [event["wire_hex"] for event in wires])
        self.assertTrue(any(event["kind"] == "capture_gap" for event in report["events"]))
        self.assertTrue(any(event.get("context_only") and event["origin"] == "incident_export_context"
                            for event in report["events"]))
        actual = replay(report)
        self.assertFalse(any(item.get("validation") == "inner_valid" for item in actual["decoder_outcomes"]))
        self.assertFalse(any(item.get("register_address") == 184 for item in actual["decoder_outcomes"]))
        self.assertEqual(actual["profile_decodes"], [])

        # Demonstrate the old failure, rather than merely testing alias names:
        # merging these exact retained bytes invents a valid register-184 read.
        unsafe = deepcopy(report)
        for event in unsafe["events"]:
            event["session"] = "incorrectly-joined-session"
        joined = replay(unsafe)
        self.assertTrue(any(item.get("validation") == "inner_valid" and item.get("register_address") == 184
                            for item in joined["decoder_outcomes"]), joined)
        # The real intervening corrupt CRC would have rejected that response.
        position = next(index for index, event in enumerate(unsafe["events"])
                        if event.get("wire_hex") == suffix.hex())
        unsafe["events"].insert(position, {**unsafe["events"][position], "wire_hex": bad_crc.hex()})
        self.assertFalse(any(item.get("validation") == "inner_valid" for item in replay(unsafe)["decoder_outcomes"]))

    async def test_disjoint_sample_windows_do_not_splice_response_crc(self):
        for dialect in ("binary", "at"):
            with self.subTest(dialect=dialect):
                recorder = IncidentRecorder(None)
                clock = [100.0]
                with patch.object(module, "monotonic", side_effect=lambda: clock[0]):
                    prefix, bad_crc, suffix = self.begin_exchange(recorder, dialect)
                    recorder.record_issue(ISSUE, {**CONTEXT, "transport": dialect})
                    clock[0] = 111
                    recorder.tick()
                    self.emit(recorder, "rx", bad_crc)  # after the first sample's tail
                    clock[0] = 200
                    self.emit(recorder, "rx", suffix)   # corrupt CRC has aged out of the ring
                    recorder.recovered(CONTEXT["device_id"])
                    report = await self.report(recorder)
                    self.assert_crc_splice_prevented(report, prefix, bad_crc, suffix)
                await recorder.close()

    async def test_export_middle_event_clipping_does_not_splice_response_crc(self):
        recorder = IncidentRecorder(None)
        prefix, bad_crc, suffix = self.begin_exchange(recorder, "binary")
        self.emit(recorder, "rx", bad_crc)
        recorder.observe("snapshot_complete", session=CONTEXT["session"])
        self.emit(recorder, "rx", suffix)
        recorder.observe("settings_complete", session=CONTEXT["session"])
        recorder.observe("snapshot_complete", session=CONTEXT["session"])
        recorder.record_issue(ISSUE, CONTEXT)
        with patch.object(module.compatibility, "MAX_EVENTS", 6):
            report = await self.report(recorder)
            self.assertLessEqual(len(report["events"]), 6)
            self.assertGreater(report["collection"]["dropped_events"], 0)
            self.assert_crc_splice_prevented(report, prefix, bad_crc, suffix)
        await recorder.close()

    async def test_export_byte_skip_and_oversized_capture_keep_discontinuity_after_restart(self):
        for oversized in (False, True):
            with self.subTest(oversized=oversized):
                store = MemoryStore()
                recorder = IncidentRecorder(store)
                await recorder.start()
                prefix, bad_crc, suffix = self.begin_exchange(recorder, "binary")
                self.emit(recorder, "rx", bad_crc + b"x" * (module.RING_BYTES if oversized else 5000))
                self.emit(recorder, "rx", suffix)
                recorder.record_issue(ISSUE, CONTEXT)
                await recorder.close()
                restarted = IncidentRecorder(store)
                await restarted.start()
                with patch.object(module, "EXPORT_EVENT_BYTES", 3000):
                    report = await self.report(restarted)
                    self.assertGreater(report["collection"]["dropped_events"], 0)
                    self.assert_crc_splice_prevented(report, prefix, bad_crc, suffix)
                await restarted.close()

    async def test_gap_clears_request_correlation_for_complete_response(self):
        recorder = IncidentRecorder(None)
        request, prefix, _, suffix = self.exchange("binary")
        recorder.observe("dialect_selected", session=CONTEXT["session"], dialect="binary")
        self.emit(recorder, "tx", request)
        self.emit(recorder, "rx", b"x" * module.RING_BYTES)  # missing original exchange
        self.emit(recorder, "rx", prefix + suffix)
        recorder.record_issue(ISSUE, CONTEXT)
        report = await self.report(recorder)
        response = next(item for item in replay(report)["decoder_outcomes"] if item.get("validation") == "inner_valid")
        self.assertEqual(response["correlation"], "unsolicited_or_missing_request")
        self.assertNotIn("register_address", response)
        await recorder.close()

    async def test_contiguous_fragments_survive_interleaved_sessions_and_wall_clock_changes(self):
        recorder = IncidentRecorder(None)
        _, _, suffix = self.begin_exchange(recorder, "binary")
        recorder.observe("wire", session="other-session", direction="rx", data=b"unrelated")
        self.emit(recorder, "rx", suffix, time="2020-01-01T00:00:00+00:00")
        recorder.record_issue(ISSUE, CONTEXT)
        report = await self.report(recorder)
        result = replay(report)
        self.assertTrue(any(item.get("validation") == "inner_valid" and item.get("register_address") == 184
                            for item in result["decoder_outcomes"]), result)
        self.assertEqual(report["context"]["capture_continuity"]["gaps"], 0)
        await recorder.close()

    async def test_legacy_samples_without_predecessors_are_not_assumed_contiguous(self):
        recorder = IncidentRecorder(None)
        prefix, bad_crc, suffix = self.begin_exchange(recorder, "binary")
        self.emit(recorder, "rx", suffix)
        recorder.record_issue(ISSUE, CONTEXT)
        sample = next(iter(recorder._records.values()))["samples"][0]
        sample["events"] = [{key: value for key, value in event.items() if key not in ("capture_id", "previous_event_id")}
                            for event in sample["events"]]
        report = await self.report(recorder)
        self.assertGreater(report["context"]["capture_continuity"]["legacy_events"], 0)
        self.assert_crc_splice_prevented(report, prefix, bad_crc, suffix)
        await recorder.close()

    async def test_reused_session_and_event_ids_after_restart_never_join_capture_epochs(self):
        store = MemoryStore()
        recorder = IncidentRecorder(store)
        await recorder.start()
        prefix, _, suffix = self.begin_exchange(recorder, "binary")
        recorder.record_issue(ISSUE, CONTEXT)
        await recorder.close()
        restarted = IncidentRecorder(store)
        await restarted.start()
        await restarted.arm(CONTEXT["device_id"], 1)
        restarted.observe("dialect_selected", session=CONTEXT["session"], dialect="binary")
        self.emit(restarted, "rx", suffix)
        restarted.record_issue(ISSUE, CONTEXT)
        report = await self.report(restarted)
        wires = [event for event in report["events"] if "wire_hex" in event]
        before = next(event for event in wires if event["wire_hex"] == prefix.hex())
        after = next(event for event in wires if event["wire_hex"] == suffix.hex())
        self.assertNotEqual(before["session"], after["session"])
        self.assertTrue(any(event.get("reason") == "capture_epoch_changed" for event in report["events"]))
        self.assertFalse(any(item.get("validation") == "inner_valid" for item in replay(report)["decoder_outcomes"]))
        await restarted.close()


class SQLiteRecorderTests(unittest.IsolatedAsyncioTestCase):
    async def test_sample_capture_build_survives_upgrade_and_mixed_build_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sqlite3"
            build_a = {"version": "build-A", "sha256": "a" * 64}
            build_b = {"version": "build-B", "sha256": "b" * 64}
            supplied = {**build_a, "path": "private-source-path", "token": "private-source-token"}
            storage = await asyncio.to_thread(Storage, path)
            recorder = IncidentRecorder(storage, build=supplied)
            supplied["version"] = "caller-mutated"
            try:
                await recorder.start()
                wire(recorder, b"original-from-build-A")
                recorder.record_issue(ISSUE, CONTEXT)
                # Later mutation must not relabel an already captured sample,
                # including its subsequently appended tail and persisted copy.
                recorder.build.update(version="later-recorder-build", token="private-runtime-token")
                wire(recorder, b"tail-from-build-A")
                await recorder.close()
                saved = (await storage.incident_load())["incidents"][0]["samples"][0]
                self.assertEqual(saved["capture_build"], build_a)
            finally:
                await asyncio.to_thread(storage.close)

            storage = await asyncio.to_thread(Storage, path)
            recorder = IncidentRecorder(storage, build={**build_b, "token": "private-exporter-token"})
            try:
                await recorder.start()
                value = recorder.view()["incidents"][0]["fingerprint"]
                for raw in (False, True):
                    data, analysis = await recorder.export(value, include_raw=raw)
                    report = validate_package(data)
                    self.assertEqual(report["build"], build_b)
                    self.assertEqual(report["context"]["build_role"], "exporter")
                    self.assertEqual(report["context"]["exporter_build"], build_b)
                    self.assertEqual(report["context"]["samples"][0]["capture_build"], build_a)
                    self.assertEqual(analysis["exporter_build"], build_b)
                    if raw:
                        self.assertIn(b"original-from-build-A", [bytes.fromhex(event["wire_hex"])
                                      for event in report["events"] if "wire_hex" in event])
                    with ZipFile(io.BytesIO(data)) as archive:
                        contents = b"".join(archive.read(name) for name in archive.namelist()).decode()
                    for secret in ("private-source-path", "private-source-token", "private-runtime-token", "private-exporter-token"):
                        self.assertNotIn(secret, contents)

                wire(recorder, b"recovered-under-build-B")
                recorder.recovered(CONTEXT["device_id"])
                data, _ = await recorder.export(value)
                report = validate_package(data)
                self.assertEqual({sample["role"]: sample["capture_build"] for sample in report["context"]["samples"]},
                                 {"first": build_a, "recovered": build_b})
                self.assertIn("not the capture version", report["redaction"])
                await recorder.close()
                saved = (await storage.incident_load())["incidents"][0]["samples"]
                self.assertEqual({sample["role"]: sample["capture_build"] for sample in saved},
                                 {"first": build_a, "recovered": build_b})
            finally:
                await asyncio.to_thread(storage.close)

    async def test_watch_replaces_saturated_sample_and_persists_this_failure_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sqlite3"
            clock = [100.0]
            first = {**ISSUE, "payload_length": 9}
            distinct = {**ISSUE, "payload_length": 10}
            with patch.object(module, "monotonic", side_effect=lambda: clock[0]):
                storage = await asyncio.to_thread(Storage, path)
                recorder = IncidentRecorder(storage)
                try:
                    await recorder.start()
                    wire(recorder, b"original-first")
                    recorder.record_issue(first, CONTEXT)
                    clock[0] += 10
                    recorder.tick()
                    wire(recorder, b"original-recovery")
                    recorder.recovered(CONTEXT["device_id"])
                    wire(recorder, b"old-distinct")
                    recorder.record_issue(distinct, CONTEXT)
                    clock[0] += 10
                    recorder.tick()
                    item = next(iter(recorder._records.values()))
                    preserved = deepcopy(item["samples"][:2])
                    value = item["fingerprint"]
                    self.assertEqual(len(item["samples"]), 3)
                    await recorder.arm(CONTEXT["device_id"], 1)
                    await recorder.close()
                finally:
                    await asyncio.to_thread(storage.close)

                storage = await asyncio.to_thread(Storage, path)
                recorder = IncidentRecorder(storage)
                try:
                    await recorder.start()
                    self.assertTrue(recorder.view(CONTEXT["device_id"])["watch"]["active"])
                    clock[0] = 200
                    wire(recorder, b"new-watch-failure")
                    recorder.record_issue(distinct, CONTEXT)
                    await recorder._flush()
                    persisted = (await storage.incident_load())["incidents"][0]
                    self.assertEqual(persisted["samples"][:2], preserved)
                    self.assertEqual([s["role"] for s in persisted["samples"]], ["first", "recovered", "watched"])
                    self.assertFalse(persisted["samples"][2]["complete"])
                    self.assertEqual(bytes.fromhex(persisted["samples"][2]["events"][0]["wire_hex"]), b"new-watch-failure")
                    wire(recorder, b"new-watch-tail")
                    clock[0] += 10
                    recorder.tick()
                    await recorder.close()
                finally:
                    await asyncio.to_thread(storage.close)

                storage = await asyncio.to_thread(Storage, path)
                recorder = IncidentRecorder(storage)
                try:
                    await recorder.start()
                    watch = recorder.view(CONTEXT["device_id"])["watch"]
                    self.assertEqual(watch["status"], "captured")
                    self.assertEqual(watch["fingerprint"], value)
                    self.assertFalse(watch["active"])
                    data, _ = await recorder.export(value, include_raw=True)
                    report = validate_package(data)
                    raw = [bytes.fromhex(e["wire_hex"]) for e in report["events"] if "wire_hex" in e]
                    self.assertIn(b"new-watch-failure", raw)
                    self.assertIn(b"new-watch-tail", raw)
                    self.assertTrue(next(s for s in report["context"]["samples"] if s["role"] == "watched")["complete"])

                    # Re-arming replaces the same slot/deadline, never first or
                    # recovered, even if another watch tail is still pending.
                    for moment, marker in ((300.0, b"watch-two"), (305.0, b"watch-three")):
                        clock[0] = moment
                        await recorder.arm(CONTEXT["device_id"], 1)
                        wire(recorder, marker)
                        recorder.record_issue(distinct, CONTEXT)
                    item = next(iter(recorder._records.values()))
                    self.assertEqual(item["samples"][:2], preserved)
                    self.assertEqual(len(item["samples"]), 3)
                    self.assertEqual(recorder._pending[(CONTEXT["device_id"], value, "watched")], 315.0)
                    clock[0] = 310
                    recorder.tick()
                    self.assertFalse(item["samples"][2]["complete"])
                    wire(recorder, b"latest-watch-tail")
                    clock[0] = 315
                    recorder.tick()
                    data, _ = await recorder.export(value, include_raw=True)
                    raw = [bytes.fromhex(e["wire_hex"]) for e in validate_package(data)["events"] if "wire_hex" in e]
                    self.assertIn(b"watch-three", raw)
                    self.assertIn(b"latest-watch-tail", raw)
                    self.assertLessEqual(recorder.view()["serialized_sample_bytes"], module.MAX_SAMPLE_BYTES)
                    await recorder.close()
                finally:
                    await asyncio.to_thread(storage.close)

    async def test_future_diagnostic_schema_is_not_overwritten_and_ledger_stays_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = await asyncio.to_thread(Storage, Path(directory) / "bridge.sqlite3")
            try:
                def future_schema():
                    storage.db.execute("INSERT INTO incident_state VALUES (1,99,'{}')")
                    storage.db.commit()
                await storage.async_call(future_schema)
                recorder = IncidentRecorder(storage)
                await recorder.start()
                self.assertEqual(recorder.view()["persistence"], "memory_only")
                self.assertEqual(recorder.view()["persistence_error"], "unsupported_incident_schema")
                recorder.record_issue(ISSUE, CONTEXT)
                await recorder.close()
                actual = await storage.async_call(lambda: storage.db.execute("SELECT schema, record FROM incident_state").fetchone())
                self.assertEqual(actual, (99, "{}"))
                self.assertEqual(await storage.async_call(lambda: storage.db.execute("PRAGMA user_version").fetchone()[0]), 4)
            finally:
                await asyncio.to_thread(storage.close)

    async def test_store_rejects_over_budget_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = await asyncio.to_thread(Storage, Path(directory) / "bridge.sqlite3")
            recorder = IncidentRecorder(storage)
            try:
                await recorder.start()
                wire(recorder)
                recorder.record_issue(ISSUE, CONTEXT)
                await recorder._flush()
                before = await storage.incident_load()
                invalid = deepcopy(before)
                invalid["incidents"][0]["samples"] *= 4
                with self.assertRaisesRegex(ValueError, "incident_limit_exceeded"):
                    await storage.incident_save(invalid)
                self.assertEqual(await storage.incident_load(), before)
                with patch("custom_components.solar_inverter_bridge.core.incident_store.MAX_SAMPLE_BYTES", 1):
                    with self.assertRaisesRegex(ValueError, "incident_sample_limit_exceeded"):
                        await storage.incident_save(before)
                self.assertEqual(await storage.incident_load(), before)
                await recorder.close()
            finally:
                await asyncio.to_thread(storage.close)

    async def test_restart_watch_counter_samples_and_ledger_schema_four(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sqlite3"
            storage = await asyncio.to_thread(Storage, path)
            recorder = IncidentRecorder(storage)
            try:
                await recorder.start()
                wire(recorder, b"before-restart")
                recorder.record_issue(ISSUE, CONTEXT)
                await recorder.arm(CONTEXT["device_id"], 24)
                await recorder.close()
                version = await storage.async_call(lambda: storage.db.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(version, 4)
            finally:
                await asyncio.to_thread(storage.close)
            storage = await asyncio.to_thread(Storage, path)
            recorder = IncidentRecorder(storage)
            try:
                await recorder.start()
                summary = recorder.view()["incidents"][0]
                self.assertEqual(summary["count"], 1)
                self.assertTrue(recorder.view(CONTEXT["device_id"])["watch"]["active"])
                data, _ = await recorder.export(summary["fingerprint"], include_raw=True)
                report = validate_package(data)
                self.assertTrue(report["context"]["samples"][0]["interrupted"])
                self.assertFalse(report["context"]["samples"][0]["complete"])
                self.assertEqual(bytes.fromhex(report["events"][0]["wire_hex"]), b"before-restart")
                recorder.record_issue(ISSUE, CONTEXT)
                recorder.recovered(CONTEXT["device_id"])
                self.assertEqual(recorder.view()["incidents"][0]["recovered_count"], 2)
                await recorder.close()
            finally:
                await asyncio.to_thread(storage.close)

    async def test_single_existing_worker_and_loop_remains_responsive(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = await asyncio.to_thread(Storage, Path(directory) / "bridge.sqlite3")
            recorder = IncidentRecorder(storage)
            entered, release = threading.Event(), threading.Event()
            job = None
            try:
                await recorder.start()
                def block():
                    entered.set()
                    release.wait(3)
                job = asyncio.create_task(storage.async_call(block))
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                recorder.record_issue(ISSUE, CONTEXT)
                await asyncio.sleep(0)
                # If incident_save used synchronous call, this loop checkpoint
                # would block behind the deliberately held SQLite worker.
                await asyncio.wait_for(asyncio.sleep(0), 0.1)
                self.assertEqual(storage.queue.qsize(), 1)
                release.set()
                await job
                await recorder.close()
                owner = await storage.async_call(threading.get_ident)
                self.assertEqual(owner, storage.thread.ident)
            finally:
                release.set()
                if job:
                    await job
                await asyncio.to_thread(storage.close)

    async def test_real_backup_freeze_does_not_modify_ledger_or_lose_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = await asyncio.to_thread(Storage, Path(directory) / "bridge.sqlite3")
            recorder = IncidentRecorder(storage)
            try:
                await recorder.start()
                await asyncio.to_thread(storage.begin_backup)
                with patch.object(module, "RETRY_SECONDS", 0.001):
                    recorder.record_issue(ISSUE, CONTEXT)
                    with self.assertRaises(StorageError):
                        await recorder._flush()
                    await asyncio.to_thread(storage.end_backup)
                    await recorder._flush()
                loaded = await storage.incident_load()
                self.assertEqual(loaded["incidents"][0]["count"], 1)
                operations = await storage.async_call(lambda: storage.db.execute("SELECT count(*) FROM operations").fetchone()[0])
                self.assertEqual(operations, 0)
                await recorder.close()
            finally:
                await asyncio.to_thread(storage.end_backup)
                await asyncio.to_thread(storage.close)
