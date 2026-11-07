"""Clock readback evolution, storage bounds, and HA measurement metadata."""

from datetime import datetime, timedelta, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from custom_components.solar_inverter_bridge.core.parameters import FIELDS, SETTINGS_BLOCKS, access_class, decode_observed, execution_ready, readback_matches, validate_change
from custom_components.solar_inverter_bridge.core.storage import Storage, StorageError
from custom_components.solar_inverter_bridge.core.telemetry import sensor_descriptors


class ClockAndCapacityTests(unittest.TestCase):
    def test_full_inventory_and_advanced_fields_with_undocumented_limits(self):
        self.assertEqual(len(FIELDS), 51)
        addresses = {address for start, count in SETTINGS_BLOCKS for address in range(start, start + count)}
        self.assertTrue({field.address for field in FIELDS} <= addresses)
        for field in FIELDS:
            if field.kind == "number" and field.bounds is None:
                self.assertEqual(access_class(field), "writable")
                self.assertTrue(execution_ready(field))
        values = decode_observed({637: 564, 640: 125, 643: 0})
        self.assertEqual(values["bulk_charging_voltage"], 56.4)
        self.assertEqual(values["maximum_charging_current"], 12.5)
        self.assertEqual(values["battery_recovery_voltage_ac"], "full_recovery")

    def test_battery_and_equalization_guards(self):
        fields = {field.key: field for field in FIELDS}
        with self.assertRaisesRegex(ValueError, "equalization_not_qualified"):
            validate_change(fields["equalization_enabled"], "enabled", {"equalization_enabled": "disabled", "battery_type": "li2"})
        with self.assertRaisesRegex(ValueError, "disable_equalization"):
            validate_change(fields["battery_type"], "li4", {"battery_type": "agm", "equalization_enabled": "enabled"})

    def test_running_clock_can_be_reconciled_without_an_exact_old_timestamp(self):
        field = next(item for item in FIELDS if item.key == "inverter_datetime")
        sent = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        record = {"send_intent_at": sent.isoformat()}
        desired = (2026, 11, 2, 15, 0, 0)
        observed = (2026, 11, 2, 15, 2, 1)
        self.assertTrue(readback_matches(field, desired, observed, record, now_utc=sent + timedelta(minutes=2)))
        self.assertFalse(readback_matches(field, desired, observed, record, now_utc=sent + timedelta(hours=2)))
        self.assertFalse(readback_matches(field, desired, observed, {}, now_utc=sent))
        self.assertFalse(readback_matches(field, desired, observed, record, now_utc=sent - timedelta(seconds=1)))

    def test_capacity_rejects_new_work_but_keeps_idempotent_results(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "bridge.sqlite3", max_operations=1, max_devices=1)
            try:
                device = storage.enroll("a" * 64, "One")
                self.assertEqual(storage.enroll("a" * 64, "One"), device)
                with self.assertRaisesRegex(StorageError, "device_capacity_reached"):
                    storage.enroll("b" * 64, "Two")
                request = {"key": "primary_output_priority", "value": "sbu"}
                storage.accept_operation(device, "one", request)
                storage.finish_operation("one", state="completed", outcome="not_sent", unresolved=False, reason="test")
                self.assertEqual(storage.accept_operation(device, "one", request)["outcome"], "not_sent")
                with self.assertRaisesRegex(StorageError, "operation_capacity_reached"):
                    storage.accept_operation(device, "two", request)
                self.assertEqual(storage.operation("one")["outcome"], "not_sent")
            finally:
                storage.close()

    def test_existing_device_schema_gains_policy_revision_without_data_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sqlite3"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE devices (device_id TEXT PRIMARY KEY, collector_sha256 TEXT NOT NULL UNIQUE, name TEXT NOT NULL, profile_id TEXT, control_mode TEXT NOT NULL, clock_sync INTEGER NOT NULL, poll_interval INTEGER NOT NULL, enabled INTEGER NOT NULL)")
                db.execute("INSERT INTO devices VALUES ('existing', 'collector', 'House', 'modbus_protocol_4', 'advanced', 0, 10, 1)")
            storage = Storage(path)
            try:
                device = storage.device("existing")
                self.assertEqual(device["control_mode"], "full")
                self.assertEqual(device["policy_revision"], 1)
                storage.set_mode("existing", "monitoring")
                storage.set_mode("existing", "advanced")
                self.assertEqual(storage.device("existing")["policy_revision"], 1)
            finally:
                storage.close()

    def test_energy_and_measurement_metadata(self):
        fields = {field["key"]: field for field in sensor_descriptors()}
        for key in ("pv_energy_today", "pv_energy_total"):
            self.assertEqual((fields[key]["unit"], fields[key]["device_class"], fields[key]["state_class"]),
                             ("kWh", "energy", "total_increasing"))
        self.assertEqual(fields["pv_power"]["device_class"], "power")
        self.assertEqual(fields["battery_soc"]["device_class"], "battery")
        self.assertIn("mains", fields["operating_mode"]["options"])

    def test_future_schema_is_refused_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sqlite3"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("PRAGMA user_version=99")
            with self.assertRaisesRegex(StorageError, "unsupported_storage_schema"):
                Storage(path)
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 99)

    def test_diagnostic_history_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "bridge.sqlite3")
            try:
                for index in range(40):
                    storage.record_diagnostic({"occurred_at": str(index), "code": "timeout"})
                history = storage.recent_diagnostics()
                self.assertEqual(len(history), 32)
                self.assertEqual(history[0]["occurred_at"], "8")
                self.assertEqual(history[-1]["occurred_at"], "39")
            finally:
                storage.close()

    def test_abrupt_process_exit_recovers_accept_and_claim_without_replay(self):
        for phase in ("accepted", "sending"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bridge.sqlite3"
                program = """
import os,sys
from custom_components.solar_inverter_bridge.core.storage import Storage
storage=Storage(sys.argv[1])
device=storage.enroll('collector','House')
storage.accept_operation(device,'crash',{'value':2})
if sys.argv[2]=='sending': storage.claim_send('crash')
os._exit(0)
"""
                subprocess.run([sys.executable, "-c", program, str(path), phase], check=True,
                               cwd=Path(__file__).parents[1], timeout=10)
                recovered = Storage(path)
                try:
                    record = recovered.operation("crash")
                    self.assertEqual(record["unresolved"], phase == "sending")
                    self.assertEqual(record["outcome"], "uncertain" if phase == "sending" else "not_sent")
                    self.assertFalse(recovered.claim_send("crash"))
                finally:
                    recovered.close()
