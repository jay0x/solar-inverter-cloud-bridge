"""Storage keeps the ledger authoritative and does not treat every event as new."""

from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path

from custom_components.solar_inverter_bridge.core.storage import Storage, StorageError


def _at(seconds):
    return (datetime(2026, 11, 3, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()


class StorageBoundaryTests(unittest.TestCase):
    def test_repeated_fault_is_coalesced_instead_of_filling_the_log(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "bridge.sqlite3")
            try:
                first = {"occurred_at": _at(0), "device_id": "device", "stage": "poll", "code": "timeout"}
                self.assertEqual(storage.record_diagnostic(first)["code"], "timeout")
                self.assertIsNone(storage.record_diagnostic({**first, "occurred_at": _at(30)}))
                updated = storage.record_diagnostic({**first, "occurred_at": _at(90)})
                self.assertEqual(updated["repeat_count"], 2)
                self.assertEqual(updated["occurred_at"], _at(0))
                self.assertEqual(updated["last_seen_at"], _at(90))
                self.assertEqual(len(storage.recent_diagnostics()), 1)
                storage.record_diagnostic({**first, "occurred_at": _at(91), "code": "crc_mismatch"})
                self.assertEqual(len(storage.recent_diagnostics()), 2)
            finally:
                storage.close()

    def test_journal_page_does_not_delete_operation_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "bridge.sqlite3")
            try:
                device = storage.enroll("a" * 64, "House name", "modbus_protocol_4")
                storage.accept_operation(device, "op-1", {"key": "output_source", "value": 1})
                page = storage.journal_page(0, 1)
                self.assertEqual(page["retained"], 1)
                self.assertEqual(page["records"][0]["operation_id"], "op-1")
                self.assertNotIn("name", page["records"][0])
                self.assertEqual(storage.operation("op-1")["state"], "accepted")
            finally:
                storage.close()

    def test_corrupt_database_is_refused_before_use(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sqlite3"
            path.write_bytes(b"not a sqlite database")
            with self.assertRaises(StorageError):
                Storage(path)
