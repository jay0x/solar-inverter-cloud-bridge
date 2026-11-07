"""Schema 3 mode retirement preserves identity, preferences and uncertain intent."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from custom_components.solar_inverter_bridge.core.storage import Storage


class FullControlMigrationTests(unittest.TestCase):
    def test_all_legacy_modes_migrate_once_without_replaying_work(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bridge.sqlite3"
            store = Storage(path)
            ids = [store.enroll(f"collector-{i}", f"Device {i}", "smg_4") for i in range(3)]
            installation = store.installation_id()
            for i, device in enumerate(ids):
                store.set_clock_sync(device, i == 0)
                store.set_auto_reset(device, i == 1)
                store.accept_profile(device, {"profile_id":"smg_4", "fingerprint":"f"*64,
                    "binding":{"signature":[4,45678],"definition_sha256":"a"*64}, "allow_control":False})
            before = {d["device_id"]: d for d in store.list_devices()}
            store.accept_operation(ids[0], "unsent", {"key":"lcd_backlight","value":"always_on"})
            store.accept_operation(ids[1], "uncertain", {"key":"lcd_backlight","value":"always_on"})
            store.claim_send("uncertain")
            store.close()
            db = sqlite3.connect(path)
            try:
                with db:
                    db.execute("PRAGMA user_version=3")
                    for device, mode in zip(ids, ("monitoring","control","advanced")):
                        db.execute("UPDATE devices SET control_mode=? WHERE device_id=?", (mode,device))
                        record = json.loads(db.execute("SELECT record FROM profile_acceptances WHERE device_id=?",(device,)).fetchone()[0])
                        record["allow_control"] = False
                        db.execute("UPDATE profile_acceptances SET record=? WHERE device_id=?", (json.dumps(record),device))
            finally:
                db.close()
            store = Storage(path)
            try:
                self.assertEqual(store.storage_summary()["schema"], 4)
                self.assertEqual(store.installation_id(), installation)
                for device in ids:
                    after = store.device(device)
                    self.assertEqual(after["control_mode"], "full")
                    self.assertEqual(after["policy_revision"], before[device]["policy_revision"]+1)
                    for key in ("name","profile_id","collector_sha256","clock_sync","auto_reset","enabled","poll_interval"):
                        self.assertEqual(after[key], before[device][key])
                    accepted = store.profile_acceptance(device)
                    self.assertTrue(accepted["allow_control"])
                    self.assertEqual(accepted["fingerprint"], "f"*64)
                    self.assertEqual(accepted["binding"]["signature"], [4,45678])
                self.assertEqual(store.operation("unsent")["outcome"], "not_sent")
                self.assertTrue(store.operation("uncertain")["unresolved"])
                revisions = [store.device(device)["policy_revision"] for device in ids]
            finally:
                store.close()
            store = Storage(path)
            try:
                self.assertEqual([store.device(device)["policy_revision"] for device in ids], revisions)
                self.assertEqual(store.operation("uncertain")["state"], "reconciling")
            finally:
                store.close()
