"""One SQLite connection owned by one worker thread."""

from datetime import datetime, timezone
import json
import queue
import sqlite3
import threading
import uuid

from .policy import normalize_mode


class StorageError(RuntimeError):
    pass


def _diagnostic_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _same_diagnostic(saved, record):
    keys = ("device_id", "stage", "code", "parameter", "register_address", "function", "exception_code")
    return all(saved.get(key) == record.get(key) for key in keys)


class Storage:
    def __init__(self, path, *, max_operations=100000, max_devices=16):
        self.path = str(path)
        self.max_operations = max_operations
        self.max_devices = max_devices
        self.queue = queue.Queue(maxsize=64)
        self.closed = False
        self.backup_active = False
        self._admit = threading.Lock()
        self._backup_release = None
        self._backup_finished = None
        self.thread = threading.Thread(target=self._run, name="solar-inverter-bridge-storage", daemon=True)
        self.ready = threading.Event()
        self.thread.start()
        if not self.ready.wait(5):
            raise StorageError("storage_worker_unavailable")
        if getattr(self, "startup_error", None):
            self.thread.join(5)
            raise self.startup_error

    def _run(self):
        try:
            self.db = sqlite3.connect(self.path, check_same_thread=True)
            integrity = self.db.execute("PRAGMA quick_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise StorageError("storage_corrupt")
            if self.db.execute("PRAGMA user_version").fetchone()[0] > 4:
                raise StorageError("unsupported_storage_schema")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self._schema()
            self._recover()
        except Exception as error:
            if isinstance(error, sqlite3.DatabaseError):
                error = StorageError("storage_corrupt")
            self.startup_error = error
            if hasattr(self, "db"):
                self.db.close()
            self.ready.set()
            return
        self.ready.set()
        while True:
            item = self.queue.get()
            if item is None:
                self.db.close()
                return
            function, box, done, loop, future = item
            try:
                result = function()
                if future is not None:
                    loop.call_soon_threadsafe(self._deliver, future, result, None)
                else:
                    box["result"] = result
            except Exception as error:
                try:
                    self.db.rollback()
                except sqlite3.Error:
                    pass
                if isinstance(error, sqlite3.Error):
                    error = StorageError("storage_unavailable")
                if future is not None:
                    loop.call_soon_threadsafe(self._deliver, future, None, error)
                else:
                    box["error"] = error
            finally:
                if done is not None:
                    done.set()

    @staticmethod
    def _deliver(future, result, error):
        # Cancellation of the waiter does not cancel a committed worker job.
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)

    def _schema(self):
        previous_version = self.db.execute("PRAGMA user_version").fetchone()[0]
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS installation (id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY, collector_sha256 TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL, profile_id TEXT, control_mode TEXT NOT NULL,
                clock_sync INTEGER NOT NULL, poll_interval INTEGER NOT NULL, enabled INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS operations (
                operation_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, state TEXT NOT NULL,
                unresolved INTEGER NOT NULL, record TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS operations_device ON operations(device_id);
            CREATE TABLE IF NOT EXISTS removed_devices (device_id TEXT PRIMARY KEY, removed_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS diagnostic_events (record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS collector_resets (collector_sha256 TEXT PRIMARY KEY, attempted_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS device_routes (device_id TEXT PRIMARY KEY, route TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS profile_acceptances (device_id TEXT PRIMARY KEY, record TEXT NOT NULL);
        """)
        if "policy_revision" not in {row[1] for row in self.db.execute("PRAGMA table_info(devices)")}:
            self.db.execute("ALTER TABLE devices ADD COLUMN policy_revision INTEGER NOT NULL DEFAULT 0")
            self.db.commit()
        if "auto_reset" not in {row[1] for row in self.db.execute("PRAGMA table_info(devices)")}:
            self.db.execute("ALTER TABLE devices ADD COLUMN auto_reset INTEGER NOT NULL DEFAULT 0")
            self.db.commit()
        if self.db.execute("SELECT id FROM installation").fetchone() is None:
            self.db.execute("INSERT INTO installation VALUES (?)", (str(uuid.uuid4()),))
        if previous_version < 4:
            # Retain the legacy column for old journals/tools, but retire all
            # selectable restrictions. No operation is sent by this migration.
            self.db.execute("UPDATE devices SET control_mode='full', policy_revision=policy_revision+1 WHERE control_mode != 'full'")
            for device_id, raw in self.db.execute("SELECT device_id, record FROM profile_acceptances").fetchall():
                record = json.loads(raw)
                record["allow_control"] = True
                self.db.execute("UPDATE profile_acceptances SET record=? WHERE device_id=?", (json.dumps(record), device_id))
        self.db.execute("PRAGMA user_version=4")
        self.db.commit()

    def _recover(self):
        rows = self.db.execute("SELECT operation_id, record, state FROM operations WHERE state != 'completed'").fetchall()
        for operation_id, raw, state in rows:
            record = json.loads(raw)
            if state == "accepted":
                record.update(state="completed", outcome="not_sent", reason="restart_before_send", unresolved=False)
            else:
                record.update(state="reconciling", unresolved=True, recovery_reason="restart_after_send_intent")
                if record.get("outcome") is None:
                    record.update(outcome="uncertain", reason="restart_after_send_intent")
            self._save_record(record)
        self.db.commit()

    def bind_route(self, device_id, route):
        """Persist only a qualified logical route; never a TID, socket or source IP."""
        if (not isinstance(route, dict) or set(route) != {"transport", "outer_code", "outer_address", "inner_slave"}
                or route["transport"] not in ("at", "binary") or route["inner_slave"] not in (0, 1, 4, 5)
                or (route["transport"] == "at" and (route["outer_code"] is not None or route["outer_address"] is not None))
                or (route["transport"] == "binary" and (route["outer_code"] not in (1,0x0994,0x0102) or route["outer_address"] not in (1, 255)))):
            raise ValueError("invalid_qualified_route")
        raw = json.dumps(route, sort_keys=True)

        def work():
            if self.db.execute("SELECT 1 FROM devices WHERE device_id=?", (device_id,)).fetchone() is None:
                raise StorageError("device_missing")
            row = self.db.execute("SELECT route FROM device_routes WHERE device_id=?", (device_id,)).fetchone()
            if row and row[0] == raw:
                return False
            previous = json.loads(row[0]) if row else {"transport": "at", "outer_code": None, "outer_address": None, "inner_slave": 1}
            if previous != route:
                self.db.execute("UPDATE devices SET policy_revision=policy_revision+1 WHERE device_id=?", (device_id,))
            self.db.execute("INSERT INTO device_routes VALUES (?,?) ON CONFLICT(device_id) DO UPDATE SET route=excluded.route", (device_id, raw))
            self.db.commit()
            return previous != route
        return self.call(work)

    def selected_route(self, device_id):
        def work():
            row = self.db.execute("SELECT route FROM device_routes WHERE device_id=?", (device_id,)).fetchone()
            return json.loads(row[0]) if row else None
        return self.call(work)

    def profile_acceptance(self, device_id):
        def work():
            row = self.db.execute("SELECT record FROM profile_acceptances WHERE device_id=?",(device_id,)).fetchone()
            return json.loads(row[0]) if row else None
        return self.call(work)

    def accept_profile(self, device_id, record, previous_profile_id=None):
        record = {**record, "allow_control": True}
        def work():
            row = self.db.execute("SELECT profile_id FROM devices WHERE device_id=?",(device_id,)).fetchone()
            if row is None:
                raise StorageError("profile_acceptance_mismatch")
            if row[0] != record["profile_id"]:
                if row[0]!=previous_profile_id or {row[0],record["profile_id"]}!={"pi30","pi30_max"}:
                    raise StorageError("profile_acceptance_mismatch")
                if self.db.execute("SELECT 1 FROM operations WHERE device_id=? AND unresolved=1",(device_id,)).fetchone():
                    raise StorageError("device_busy_or_unresolved")
                self.db.execute("UPDATE devices SET profile_id=? WHERE device_id=?",(record["profile_id"],device_id))
            self.db.execute("INSERT INTO profile_acceptances VALUES (?,?) ON CONFLICT(device_id) DO UPDATE SET record=excluded.record",
                            (device_id,json.dumps(record)))
            self.db.execute("UPDATE devices SET policy_revision=policy_revision+1 WHERE device_id=?",(device_id,))
            self.db.commit()
        return self.call(work)

    def set_experimental_control(self, device_id, enabled, fingerprint):
        if not enabled:
            raise ValueError("control_modes_removed")
        def work():
            row = self.db.execute("SELECT record FROM profile_acceptances WHERE device_id=?",(device_id,)).fetchone()
            if row is None:
                raise StorageError("profile_acceptance_required")
            record = json.loads(row[0])
            if record["fingerprint"] != fingerprint:
                raise StorageError("profile_evidence_changed")
            if self.db.execute("SELECT 1 FROM operations WHERE device_id=? AND unresolved=1",(device_id,)).fetchone():
                raise StorageError("device_busy_or_unresolved")
            record["allow_control"] = bool(enabled)
            self.db.execute("UPDATE profile_acceptances SET record=? WHERE device_id=?",(json.dumps(record),device_id))
            self.db.execute("UPDATE devices SET policy_revision=policy_revision+1 WHERE device_id=?",(device_id,))
            self.db.commit()
            return record
        return self.call(work)

    def _save_record(self, record):
        self.db.execute(
            "UPDATE operations SET state=?, unresolved=?, record=? WHERE operation_id=?",
            (record["state"], int(record["unresolved"]), json.dumps(record), record["operation_id"]),
        )

    def call(self, function, timeout=5):
        box, done = {}, threading.Event()
        with self._admit:
            if self.closed:
                raise StorageError("storage_closed")
            if self.backup_active:
                raise StorageError("storage_backup_in_progress")
            self.queue.put((function, box, done, None, None), timeout=timeout)
        if not done.wait(timeout):
            raise StorageError("storage_timeout")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    async def async_call(self, function):
        import asyncio
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        with self._admit:
            if self.closed:
                raise StorageError("storage_closed")
            if self.backup_active:
                raise StorageError("storage_backup_in_progress")
            try:
                self.queue.put_nowait((function, None, None, loop, future))
            except queue.Full as error:
                raise StorageError("storage_busy") from error
        return await future

    def _freeze_unsent_for_backup(self):
        rows = self.db.execute("SELECT record FROM operations WHERE state='accepted'").fetchall()
        for (raw,) in rows:
            record = json.loads(raw)
            record.update(state="completed", outcome="not_sent", unresolved=False, reason="backup_before_send")
            self._save_record(record)
        if rows:
            self.db.commit()

    def begin_backup(self, timeout=30):
        """Checkpoint WAL and hold the writer until end_backup. Runs on the DB thread."""
        if self.closed:
            raise StorageError("storage_closed")
        release = threading.Event()
        locked = threading.Event()
        finished = threading.Event()
        box = {}

        def job():
            held = False
            previous_isolation = self.db.isolation_level
            try:
                if release.is_set():
                    box["error"] = StorageError("storage_timeout")
                    return
                self._freeze_unsent_for_backup()
                self.db.commit()
                self.db.isolation_level = None
                self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self.db.execute("BEGIN IMMEDIATE")
                held = True
                locked.set()
                release.wait()
            except Exception as error:
                box["error"] = error if isinstance(error, StorageError) else StorageError("storage_unavailable")
            finally:
                locked.set()
                if held:
                    try:
                        self.db.execute("END")
                    except sqlite3.Error:
                        try:
                            self.db.rollback()
                        except sqlite3.Error:
                            pass
                self.db.isolation_level = previous_isolation
                with self._admit:
                    self.backup_active = False
                    self._backup_release = None
                    self._backup_finished = None
                finished.set()

        with self._admit:
            if self.backup_active:
                raise StorageError("backup_already_active")
            self.backup_active = True
            self._backup_release = release
            self._backup_finished = finished
            try:
                self.queue.put_nowait((job, {}, None, None, None))
            except queue.Full:
                self.backup_active = False
                self._backup_release = None
                self._backup_finished = None
                raise StorageError("storage_busy")
        if not locked.wait(timeout):
            release.set()
            finished.wait(timeout)
            raise StorageError("storage_timeout")
        if "error" in box:
            finished.wait(timeout)
            raise box["error"]

    def end_backup(self, timeout=30):
        """Release a backup freeze. Safe when no freeze is held."""
        with self._admit:
            release = self._backup_release
            finished = self._backup_finished
        if release is None or finished is None:
            return False
        release.set()
        if not finished.wait(timeout):
            raise StorageError("storage_timeout")
        return True

    def close(self):
        if not self.closed:
            self.closed = True
            with self._admit:
                release = self._backup_release
            if release is not None:
                release.set()
            self.queue.put(None)
            self.thread.join(5)

    def installation_id(self):
        return self.call(lambda: self.db.execute("SELECT id FROM installation").fetchone()[0])

    def enroll(self, collector_sha256, name, profile_id=None):
        def write():
            existing = self.db.execute("SELECT device_id FROM devices WHERE collector_sha256=?", (collector_sha256,)).fetchone()
            if existing:
                return existing[0]
            if self.db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] >= self.max_devices:
                raise StorageError("device_capacity_reached")
            device_id = str(uuid.uuid4())
            self.db.execute(
                "INSERT INTO devices (device_id, collector_sha256, name, profile_id, control_mode, clock_sync, poll_interval, enabled) VALUES (?, ?, ?, ?, 'full', 0, 10, 1)",
                (device_id, collector_sha256, name, profile_id),
            )
            self.db.commit()
            return device_id
        return self.call(write)

    def list_devices(self):
        def read():
            rows = self.db.execute("SELECT device_id, collector_sha256, name, profile_id, control_mode, clock_sync, poll_interval, enabled, policy_revision, auto_reset FROM devices").fetchall()
            return [{
                "device_id": row[0], "collector_sha256": row[1], "name": row[2], "suggested_name": row[2], "profile_id": row[3],
                "control_mode": row[4], "clock_sync": bool(row[5]), "poll_interval": row[6], "enabled": bool(row[7]),
                "policy_revision": row[8], "auto_reset": bool(row[9]),
            } for row in rows]
        return self.call(read)

    def device(self, device_id):
        def read():
            row = self.db.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
            if row is None:
                return None
            return {
                "device_id": row[0], "collector_sha256": row[1], "name": row[2], "suggested_name": row[2], "profile_id": row[3],
                "control_mode": row[4], "clock_sync": bool(row[5]), "poll_interval": row[6], "enabled": bool(row[7]),
                "policy_revision": row[8], "auto_reset": bool(row[9]),
            }
        return self.call(read)

    def set_mode(self, device_id, mode):
        mode = normalize_mode(mode)
        def write():
            cursor = self.db.execute("UPDATE devices SET policy_revision=policy_revision+(control_mode != ?), control_mode=? WHERE device_id=?", (mode, mode, device_id))
            self.db.commit()
            if cursor.rowcount != 1:
                raise StorageError("device_missing")
        self.call(write)

    def set_clock_sync(self, device_id, enabled: bool):
        def write():
            cursor = self.db.execute("UPDATE devices SET policy_revision=policy_revision+(clock_sync != ?), clock_sync=? WHERE device_id=?", (int(bool(enabled)), int(bool(enabled)), device_id))
            self.db.commit()
            if cursor.rowcount != 1:
                raise StorageError("device_missing")
        self.call(write)

    def set_collection(self, device_id, enabled, poll_interval):
        if type(enabled) is not bool or type(poll_interval) is not int or not 5 <= poll_interval <= 300:
            raise ValueError("invalid_collection_options")
        def write():
            cursor = self.db.execute("UPDATE devices SET policy_revision=policy_revision+(enabled != ?), enabled=?, poll_interval=? WHERE device_id=?",
                                     (int(enabled), int(enabled), poll_interval, device_id))
            if cursor.rowcount != 1:
                raise StorageError("device_missing")
            self.db.commit()
        self.call(write)

    def set_auto_reset(self, device_id, enabled):
        if type(enabled) is not bool:
            raise ValueError("invalid_auto_reset")
        def write():
            cursor = self.db.execute("UPDATE devices SET auto_reset=? WHERE device_id=?", (int(enabled), device_id))
            if cursor.rowcount != 1:
                raise StorageError("device_missing")
            self.db.commit()
        self.call(write)

    def reserve_collector_reset(self, device_id, *, automatic=False, now=None):
        """Commit the attempt before sending. Keep cooldown across re-enrollment/restart."""
        instant = now or datetime.now(timezone.utc)
        def write():
            row = self.db.execute("SELECT collector_sha256, auto_reset, enabled, control_mode FROM devices WHERE device_id=?", (device_id,)).fetchone()
            if row is None:
                raise StorageError("device_missing")
            if self.db.execute("SELECT 1 FROM operations WHERE device_id=? AND (state != 'completed' OR unresolved=1)", (device_id,)).fetchone():
                raise ValueError("device_busy_or_unresolved")
            if automatic:
                if not row[1] or not row[2]:
                    return False
                last = self.db.execute("SELECT attempted_at FROM collector_resets WHERE collector_sha256=?", (row[0],)).fetchone()
                if last and (instant - datetime.fromisoformat(last[0])).total_seconds() < 3600:
                    return False
            self.db.execute("INSERT OR REPLACE INTO collector_resets VALUES (?, ?)", (row[0], instant.isoformat()))
            self.db.commit()
            return True
        return self.call(write)

    def remove_device(self, device_id):
        """Remove enrollment only. Retained operation IDs must never be replayed."""
        def write():
            if self.db.execute("SELECT 1 FROM operations WHERE device_id=? AND (state != 'completed' OR unresolved=1)", (device_id,)).fetchone():
                raise StorageError("device_busy_or_unresolved")
            self.db.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
            self.db.execute("INSERT OR IGNORE INTO removed_devices VALUES (?, ?)", (device_id, datetime.now(timezone.utc).isoformat()))
            self.db.commit()
        self.call(write)

    def removed_device_ids(self):
        return self.call(lambda: {row[0] for row in self.db.execute("SELECT device_id FROM removed_devices")})

    def accept_operation(self, device_id, operation_id, request, *, send_value=None, actor_name=None, planned_words=None, write_plan=None):
        def write():
            existing = self.db.execute("SELECT record FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if existing:
                saved = json.loads(existing[0])
                if saved["device_id"] != device_id or saved["request"] != request:
                    raise StorageError("operation_id_conflict")
                return saved
            if self.db.execute("SELECT 1 FROM devices WHERE device_id=?", (device_id,)).fetchone() is None:
                raise StorageError("device_missing")
            if self.db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] >= self.max_operations:
                raise StorageError("operation_capacity_reached")
            if self.db.execute("SELECT 1 FROM operations WHERE device_id=? AND (state != 'completed' OR unresolved=1)", (device_id,)).fetchone():
                raise StorageError("device_busy_or_unresolved")
            record = {
                "operation_id": operation_id, "device_id": device_id, "request": request,
                "state": "accepted", "outcome": None, "unresolved": False, "write_attempts": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if send_value is not None:
                record["send_value"] = send_value
            if planned_words is not None:
                record["planned_words"] = list(planned_words)
            if write_plan is not None:
                record["write_plan"] = write_plan
            if actor_name:
                record["actor_name"] = str(actor_name)[:80]
            self.db.execute(
                "INSERT INTO operations VALUES (?, ?, 'accepted', 0, ?)",
                (operation_id, device_id, json.dumps(record)),
            )
            self.db.commit()
            return record
        return self.call(write)

    def claim_send(self, operation_id):
        def write():
            row = self.db.execute("SELECT record FROM operations WHERE operation_id=? AND state='accepted'", (operation_id,)).fetchone()
            if row is None:
                return False
            record = json.loads(row[0])
            if self.db.execute(
                "SELECT 1 FROM operations WHERE device_id=? AND operation_id != ? AND unresolved=1",
                (record["device_id"], operation_id),
            ).fetchone():
                raise StorageError("device_busy_or_unresolved")
            record.update(state="sending", unresolved=True, write_attempts=1,
                          send_intent_at=datetime.now(timezone.utc).isoformat())
            self.db.execute(
                "UPDATE operations SET state='sending', unresolved=1, record=? WHERE operation_id=? AND state='accepted'",
                (json.dumps(record), operation_id),
            )
            self.db.commit()
            return True
        return self.call(write)

    def has_unresolved(self, device_id):
        return self.call(lambda: self.db.execute("SELECT 1 FROM operations WHERE device_id=? AND unresolved=1", (device_id,)).fetchone() is not None)

    def unresolved(self, device_id):
        def read():
            rows = self.db.execute("SELECT record FROM operations WHERE device_id=? AND unresolved=1", (device_id,)).fetchall()
            return [json.loads(row[0]) for row in rows]
        return self.call(read)

    def recent_operations(self, device_id, limit=5):
        def read():
            rows = self.db.execute("SELECT record FROM operations WHERE device_id=? ORDER BY rowid DESC LIMIT ?", (device_id, limit)).fetchall()
            records = []
            for row in rows:
                saved = json.loads(row[0])
                request = saved.get("request") or {}
                record = {key: saved.get(key) for key in ("operation_id", "device_id", "state", "outcome", "resolution", "reason", "unresolved", "created_at", "resolved_at", "actor_name", "write_attempts", "last_observed_value", "last_observed_at")}
                record["setting_key"] = request.get("key")
                record["desired_value"] = saved.get("send_value", request.get("value"))
                record["previous_value"] = request.get("expected_value")
                records.append(record)
            return records
        return self.call(read)

    def record_diagnostic(self, record):
        """Keep one row for a repeated fault and persist it at most once a minute."""
        def write():
            latest = self.db.execute("SELECT rowid, record FROM diagnostic_events ORDER BY rowid DESC LIMIT 1").fetchone()
            if latest is not None:
                saved = json.loads(latest[1])
                if _same_diagnostic(saved, record):
                    previous = _diagnostic_time(saved.get("last_seen_at")) or _diagnostic_time(saved.get("occurred_at"))
                    current = _diagnostic_time(record.get("occurred_at"))
                    if previous is not None and current is not None and (current - previous).total_seconds() < 60:
                        return None
                    if previous is not None and current is not None:
                        saved["last_seen_at"] = record["occurred_at"]
                        saved["repeat_count"] = int(saved.get("repeat_count") or 1) + 1
                        self.db.execute("UPDATE diagnostic_events SET record=? WHERE rowid=?", (json.dumps(saved), latest[0]))
                        self.db.commit()
                        return saved
            self.db.execute("INSERT INTO diagnostic_events VALUES (?)", (json.dumps(record),))
            self.db.execute("DELETE FROM diagnostic_events WHERE rowid NOT IN (SELECT rowid FROM diagnostic_events ORDER BY rowid DESC LIMIT 32)")
            self.db.commit()
            return record
        return self.call(write)

    def journal_page(self, offset=0, limit=200):
        """Return a maintenance page. Operation IDs are retained; this does not delete them."""
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 500:
            raise ValueError("invalid_journal_page")
        def read():
            retained = self.db.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
            rows = self.db.execute("SELECT record FROM operations ORDER BY rowid LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            records = []
            for (raw,) in rows:
                saved = json.loads(raw)
                request = saved.get("request") or {}
                records.append({
                    "operation_id": saved.get("operation_id"), "device_id": saved.get("device_id"),
                    "setting_key": request.get("key"), "desired_value": saved.get("send_value", request.get("value")),
                    "state": saved.get("state"), "outcome": saved.get("outcome"), "reason": saved.get("reason"),
                    "resolution": saved.get("resolution"), "unresolved": saved.get("unresolved"),
                    "write_attempts": saved.get("write_attempts"), "created_at": saved.get("created_at"),
                    "send_intent_at": saved.get("send_intent_at"), "resolved_at": saved.get("resolved_at"),
                })
            return {"offset": offset, "limit": limit, "retained": retained, "max_operations": self.max_operations, "records": records}
        return self.call(read)

    def recent_diagnostics(self):
        return self.call(lambda: [json.loads(row[0]) for row in self.db.execute("SELECT record FROM diagnostic_events ORDER BY rowid")])

    def storage_summary(self):
        def read():
            return {"schema": self.db.execute("PRAGMA user_version").fetchone()[0],
                    "saved_devices": self.db.execute("SELECT COUNT(*) FROM devices").fetchone()[0],
                    "retained_operations": self.db.execute("SELECT COUNT(*) FROM operations").fetchone()[0],
                    "unresolved_operations": self.db.execute("SELECT COUNT(*) FROM operations WHERE unresolved=1").fetchone()[0],
                    "max_devices": self.max_devices, "max_operations": self.max_operations,
                    "worker_queue_depth": self.queue.qsize(), "worker_queue_capacity": self.queue.maxsize}
        return self.call(read)

    def finish_operation(self, operation_id, *, state, outcome, unresolved, reason):
        def write():
            row = self.db.execute("SELECT record FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                raise StorageError("operation_missing")
            record = json.loads(row[0])
            if record["state"] == "completed":
                return record
            record.update(state=state, outcome=outcome, unresolved=unresolved, reason=reason)
            self._save_record(record)
            self.db.commit()
            return record
        return self.call(write)

    def cancel_unsent(self, operation_id, device_id, request):
        """Finish a late accepted job, never clear a possible-send barrier."""
        def write():
            row = self.db.execute("SELECT record FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                return
            record = json.loads(row[0])
            if (record["device_id"] != device_id or record["request"] != request
                    or record["state"] != "accepted"):
                return
            record.update(state="completed", outcome="not_sent", unresolved=False, reason="cancelled_before_send")
            self._save_record(record)
            self.db.commit()
        self.call(write)

    def observe_operation(self, operation_id, value):
        def write():
            row = self.db.execute("SELECT record FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                raise StorageError("operation_missing")
            record = json.loads(row[0])
            record.update(last_observed_value=value, last_observed_at=datetime.now(timezone.utc).isoformat())
            self._save_record(record)
            self.db.commit()
        self.call(write)

    def resolve_operation(self, operation_id, resolution="readback_matched", actor_id=None):
        """Record a later observation without rewriting the original outcome."""
        def write():
            row = self.db.execute("SELECT record FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                raise StorageError("operation_missing")
            record = json.loads(row[0])
            if not record["unresolved"]:
                return record
            record.update(state="completed", unresolved=False, resolution=resolution,
                          resolved_at=datetime.now(timezone.utc).isoformat())
            if actor_id is not None:
                record["resolved_by"] = actor_id
            self._save_record(record)
            self.db.commit()
            return record
        return self.call(write)

    def operation(self, operation_id):
        return self.call(lambda: json.loads(self.db.execute("SELECT record FROM operations WHERE operation_id=?", (operation_id,)).fetchone()[0]) if self.db.execute("SELECT 1 FROM operations WHERE operation_id=?", (operation_id,)).fetchone() else None)
