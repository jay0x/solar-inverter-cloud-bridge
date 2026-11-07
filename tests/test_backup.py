"""A Home Assistant backup must copy a quiescent bridge database."""

import contextlib
import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from custom_components.solar_inverter_bridge.core.storage import Storage, StorageError


class BackupFreezeTests(unittest.TestCase):
    def test_frozen_copy_excludes_later_writes_and_does_not_replay_unsent_work(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sqlite3"
            storage = Storage(path)
            try:
                device = storage.enroll("a" * 64, "Unit", "modbus_protocol_4")
                other = storage.enroll("b" * 64, "Other", "modbus_protocol_4")
                accepted = storage.accept_operation(device, "accepted-id", {"key": "output_source", "value": 1})
                self.assertEqual(accepted["state"], "accepted")
                claimed = storage.accept_operation(other, "sending-id", {"key": "output_source", "value": 2})
                self.assertEqual(claimed["state"], "accepted")
                self.assertTrue(storage.claim_send("sending-id"))
                storage.begin_backup()
                try:
                    with self.assertRaisesRegex(StorageError, "storage_backup_in_progress"):
                        storage.set_clock_sync(device, True)
                    copy = Path(directory) / "copied.sqlite3"
                    shutil.copy2(path, copy)
                    with contextlib.closing(sqlite3.connect(copy)) as db:
                        clock = db.execute("SELECT clock_sync FROM devices WHERE device_id=?", (device,)).fetchone()[0]
                        rows = {row[0]: row[1] for row in db.execute("SELECT operation_id, record FROM operations")}
                    self.assertEqual(clock, 0)
                    self.assertIn('"reason": "backup_before_send"', rows["accepted-id"])
                    self.assertIn('"state": "sending"', rows["sending-id"])
                    self.assertNotIn("advanced", rows["sending-id"])
                finally:
                    self.assertTrue(storage.end_backup())
                storage.set_clock_sync(device, True)
                with contextlib.closing(sqlite3.connect(copy)) as db:
                    self.assertEqual(db.execute("SELECT clock_sync FROM devices WHERE device_id=?", (device,)).fetchone()[0], 0)
                self.assertTrue(storage.device(device)["clock_sync"])
                self.assertFalse(storage.end_backup())
                restored = Storage(copy)
                try:
                    self.assertFalse(restored.device(device)["clock_sync"])
                    unsent = restored.operation("accepted-id")
                    possible = restored.operation("sending-id")
                    self.assertEqual(unsent["outcome"], "not_sent")
                    self.assertFalse(unsent["unresolved"])
                    self.assertEqual(possible["state"], "reconciling")
                    self.assertEqual(possible["outcome"], "uncertain")
                    self.assertTrue(possible["unresolved"])
                    self.assertEqual(possible["write_attempts"], 1)
                finally:
                    restored.close()
            finally:
                storage.close()

    def test_close_during_freeze_does_not_hang(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "bridge.sqlite3")
            storage.begin_backup()
            finished = threading.Event()

            def stop():
                storage.close()
                finished.set()

            threading.Thread(target=stop).start()
            self.assertTrue(finished.wait(5))
            self.assertFalse(storage.thread.is_alive())
