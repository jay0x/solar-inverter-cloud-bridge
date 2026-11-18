"""Optional diagnostic tables on Storage's existing SQLite worker.

These additive, disposable tables do not change ledger schema 4 or its recovery
rules. Their independent schema is checked before reading or replacing data. All
serialization and SQL run through async_call on the existing connection; no new
connection, thread, device command, or synchronous event-loop I/O is introduced.
"""

import json

INCIDENT_SCHEMA = 1
MAX_INCIDENTS = 32
MAX_SAMPLE_BYTES = 16 * 1024 * 1024
MAX_WATCHES = 32


class IncidentStoreMixin:
    def _incident_schema(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS incident_state (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                schema INTEGER NOT NULL, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS incident_records (
                device_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                record TEXT NOT NULL, PRIMARY KEY(device_id, fingerprint));
        """)

    async def incident_load(self):
        def work():
            row = self.db.execute("SELECT schema, record FROM incident_state WHERE singleton=1").fetchone()
            if row is None:
                return None
            if row[0] != INCIDENT_SCHEMA:
                raise ValueError("unsupported_incident_schema")
            state = json.loads(row[1])
            state["incidents"] = [json.loads(raw) for (raw,) in self.db.execute(
                "SELECT record FROM incident_records ORDER BY device_id, fingerprint")]
            return state
        return await self.async_call(work)

    async def incident_save(self, snapshot):
        """Atomically replace a bounded snapshot; retries are idempotent.

        The caller owns an immutable snapshot until this await completes. A backup
        freeze/queue refusal follows StorageError semantics, without recording a
        new diagnostic about the diagnostic writer itself.
        """
        def work():
            row = self.db.execute("SELECT schema FROM incident_state WHERE singleton=1").fetchone()
            if row and row[0] != INCIDENT_SCHEMA:
                raise ValueError("unsupported_incident_schema")
            records = snapshot["incidents"]
            if (len(records) > MAX_INCIDENTS or len(snapshot["watches"]) > MAX_WATCHES
                    or any(len(item["samples"]) > 3 for item in records)):
                raise ValueError("incident_limit_exceeded")
            size = sum(len(json.dumps(item["samples"], separators=(",", ":"), ensure_ascii=True).encode())
                       for item in records)
            if size > MAX_SAMPLE_BYTES:
                raise ValueError("incident_sample_limit_exceeded")
            metadata = json.dumps({key: value for key, value in snapshot.items() if key != "incidents"})
            rows = [(item["device_id"], item["fingerprint"],
                     json.dumps(item, separators=(",", ":"), ensure_ascii=True)) for item in records]
            with self.db:
                self.db.execute("DELETE FROM incident_records")
                self.db.executemany("INSERT INTO incident_records VALUES (?,?,?)", rows)
                self.db.execute("INSERT INTO incident_state VALUES (1,?,?) "
                                "ON CONFLICT(singleton) DO UPDATE SET schema=excluded.schema, record=excluded.record",
                                (INCIDENT_SCHEMA, metadata))
        return await self.async_call(work)
