"""Endpoint mutation failures must not replay or escape the existing owner."""

import asyncio
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from custom_components.solar_inverter_bridge.core import collector_endpoint as endpoint
from custom_components.solar_inverter_bridge.core.binary import BinaryFrame
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage, StorageError
from custom_components.solar_inverter_bridge.core.transport import ATTransport, BinaryTransport

OLD = "dtu_ess.eybond.com,18899,TCP"
NEW = "m2m.eybond.com,18899,TCP"
PN = b"SyntheticFullCollector12345"


class Writer:
    def __init__(self):
        self.closed = False
        self.data = bytearray()

    def write(self, value):
        self.data.extend(value)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    def is_closing(self):
        return self.closed


class Collector:
    def __init__(self):
        self.endpoint = OLD
        self.pn = PN
        self.writes = []
        self.fail = False
        self.ignore = False

    def at_eof(self):
        return False

    async def query(self, parameter):
        return self.pn if parameter == 2 else self.endpoint.encode()

    async def set_collector(self, parameter, value):
        self.writes.append((parameter, value))
        if parameter == 21 and not self.ignore:
            self.endpoint = value
        if self.fail:
            raise TimeoutError()


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.folder.name) / "bridge.sqlite3")
        self.identity = sha256(PN).hexdigest()
        self.device = self.storage.enroll(self.identity, "Fixture", "modbus_protocol_4")
        self.service = CollectorService([], self.storage)
        self.reader = Collector()
        self.holder = {"identity_sha256": self.identity, "reader": self.reader,
                       "writer": Writer(), "closed": asyncio.Event(), "lock": asyncio.Lock(),
                       "dialect": "binary", "listener_port": 8899, "session_ref": "before"}
        self.service.connections[self.identity] = self.holder
        self.service.listeners = [{"bound": True, "port": 18899}]
        self.dns = patch.object(endpoint, "validate_destination", AsyncMock(return_value=["192.168.1.10"]))
        self.dns.start()

    async def asyncTearDown(self):
        self.dns.stop()
        self.storage.close()
        self.folder.cleanup()

    async def write(self, operation_id="one", **changes):
        args = dict(operation_id=operation_id, value=NEW, expected_value=OLD,
                    expected_transport="binary", expected_listener_port=8899,
                    local_addresses=["192.168.1.10"])
        args.update(changes)
        return await endpoint.execute(self.service, self.device, "write", **args)

    async def test_write_apply_are_distinct_and_duplicate_never_replays(self):
        result = await self.write()
        self.assertEqual(result["outcome"], "confirmed")
        self.assertEqual(result["write_plan"]["endpoint"], OLD)
        self.assertEqual(self.reader.writes, [(21, NEW)])
        await self.write()
        self.assertEqual(len(self.reader.writes), 1)
        with self.assertRaisesRegex(StorageError, "operation_id_conflict"):
            await self.write(value=OLD)
        applied = await endpoint.execute(self.service, self.device, "apply", operation_id="apply",
                                          value=NEW, expected_value=NEW, expected_transport="binary",
                                          expected_listener_port=8899, local_addresses=["192.168.1.10"])
        self.assertEqual(applied["reason"], "apply_acknowledged_not_reconnect_proof")
        self.assertEqual(self.reader.writes, [(21, NEW), (29, "1")])
        self.holder["closed"].set()
        self.assertEqual((await self.write())["outcome"], "confirmed")

    async def test_timeout_after_effect_blocks_other_writes_then_explicit_read_reconciles(self):
        self.reader.fail = True
        with self.assertRaises(TimeoutError):
            await self.write()
        self.assertTrue(self.storage.has_unresolved(self.device))
        self.assertEqual((await self.write())["outcome"], "uncertain")
        with self.assertRaisesRegex(ValueError, "device_busy_or_unresolved"):
            await self.write("two")
        # Restart preserves the barrier and does not reinterpret it as an inverter setting.
        self.storage.close()
        self.storage = Storage(Path(self.folder.name) / "bridge.sqlite3")
        self.service.storage = self.storage
        self.holder.update(writer=Writer(), closed=asyncio.Event(), session_ref="after")
        self.assertEqual(await self.service.reconcile(self.device), [])
        checked = await endpoint.execute(self.service, self.device, "check", operation_id="one")
        self.assertEqual(checked["operation"]["outcome"], "uncertain")
        self.assertFalse(checked["operation"]["unresolved"])
        self.assertEqual(len(self.reader.writes), 1)

    async def test_wrong_identity_baseline_route_and_dns_prevent_mutation(self):
        for changes, reason in (({"expected_value": NEW}, "baseline_changed"),
                                ({"expected_listener_port": 18899}, "route_changed")):
            with self.assertRaisesRegex(ValueError, reason):
                await self.write(**changes)
        endpoint.validate_destination.side_effect = ValueError("collector_destination_not_local")
        with self.assertRaisesRegex(ValueError, "destination_not_local"):
            await self.write()
        endpoint.validate_destination.side_effect = None
        self.reader.pn = b"OtherFullCollector"
        with self.assertRaisesRegex(ValueError, "identity_changed"):
            await self.write()
        self.assertFalse(self.reader.writes)
        self.assertIsNone(self.storage.operation("one"))

    async def test_ack_without_matching_readback_stays_unresolved(self):
        self.reader.ignore = True
        with self.assertRaisesRegex(ValueError, "readback_mismatch"):
            await self.write()
        self.assertTrue(self.storage.has_unresolved(self.device))
        self.assertEqual(self.storage.operation("one")["last_observed_value"], OLD)

    async def test_owner_replaced_while_waiting_for_lock_cannot_write(self):
        await self.holder["lock"].acquire()
        pending = asyncio.create_task(self.write())
        await asyncio.sleep(.03)
        self.service.connections[self.identity] = {**self.holder, "session_ref": "replacement"}
        self.holder["lock"].release()
        with self.assertRaisesRegex(ConnectionError, "session_changed"):
            await pending
        self.assertFalse(self.reader.writes)

    async def test_at_wire_uses_exact_setter_and_requires_status(self):
        self.holder["dialect"] = "at"
        async def exchange(reader, writer, command):
            if command == b"AT+DTUPN?\r\n":
                return b"AT+DTUPN:" + PN + b"\r\n"
            if command == b"AT+CLDSRVHOST1?\r\n":
                return b"AT+CLDSRVHOST1:" + reader.endpoint.encode() + b"\r\n"
            self.assertEqual(command, b"AT+CLDSRVHOST1=m2m.eybond.com,18899,TCP\r\n")
            reader.endpoint = NEW
            return b"AT+CLDSRVHOST1:W000\r\n"
        with patch.object(endpoint, "exchange_at", side_effect=exchange):
            result = await self.write(expected_transport="at")
        self.assertEqual(result["outcome"], "confirmed")

    async def test_prepare_is_read_only_and_return_address_survives_restart(self):
        before = await endpoint.execute(self.service, self.device, "prepare", value=NEW,
                                         local_addresses=["192.168.1.10"])
        self.assertEqual(before["endpoint"], OLD)
        self.assertEqual(before["prepared_action"], "write")
        self.assertTrue(before["destination_is_local"])
        self.assertFalse(self.reader.writes)
        self.assertEqual(self.storage.storage_summary()["retained_operations"], 0)
        await self.write()
        self.storage.close()
        self.storage = Storage(Path(self.folder.name) / "bridge.sqlite3")
        self.service.storage = self.storage
        self.assertEqual((await endpoint.execute(self.service, self.device, "state"))["saved_endpoint"], OLD)
        with self.assertRaisesRegex(ValueError, "restore_target_mismatch"):
            await endpoint.execute(self.service, self.device, "prepare_restore", value="other.example,18899,TCP")
        prepared = await endpoint.execute(self.service, self.device, "prepare_restore", value=OLD)
        self.assertEqual(prepared["prepared_action"], "restore")
        restored = await endpoint.execute(self.service, self.device, "restore", value=OLD,
            expected_value=NEW, operation_id="restore", expected_transport="binary", expected_listener_port=8899)
        self.assertEqual(restored["last_observed_value"], OLD)
        self.assertEqual(self.storage.collector_endpoint_history(self.device)["saved_endpoint"], OLD)

    async def test_uncertain_apply_requires_explicit_fresh_acceptance(self):
        await self.write()
        self.reader.fail = True
        with self.assertRaises(TimeoutError):
            await endpoint.execute(self.service, self.device, "apply", value=NEW, expected_value=NEW,
                operation_id="apply", expected_transport="binary", expected_listener_port=8899)
        self.holder.update(writer=Writer(), closed=asyncio.Event(), session_ref="after")
        checked = await endpoint.execute(self.service, self.device, "check", operation_id="apply")
        self.assertTrue(checked["operation"]["unresolved"])
        with self.assertRaisesRegex(ValueError, "observed_value_changed"):
            await endpoint.execute(self.service, self.device, "accept_current", operation_id="apply", expected_value=OLD, actor_id="admin")
        accepted = await endpoint.execute(self.service, self.device, "accept_current", operation_id="apply", expected_value=NEW, actor_id="admin")
        self.assertFalse(accepted["operation"]["unresolved"])
        self.assertEqual(accepted["operation"]["outcome"], "uncertain")
        self.assertEqual(accepted["operation"]["resolved_by"], "admin")
        self.assertEqual(self.reader.writes, [(21,NEW),(29,"1")])

    async def test_duplicate_after_removal_returns_record_without_accessing_device(self):
        await self.write()
        self.storage.remove_device(self.device)
        self.assertEqual((await self.write())["outcome"], "confirmed")
        self.assertEqual(len(self.reader.writes), 1)


class WireTests(unittest.IsolatedAsyncioTestCase):
    async def test_fc3_callback_mapping_requires_confirmed_identity_and_exact_payload(self):
        for qualified in (False, True):
            reader, writer = asyncio.StreamReader(), Writer()
            adapter = BinaryTransport(ATTransport(reader, writer, lambda *a, **k: None), callback_connection=True)
            if qualified:
                adapter.callback_identity_route = (258, 255)
            task = asyncio.create_task(adapter.set_collector(21, NEW))
            try:
                async with asyncio.timeout(1):
                    while adapter._pending is None:
                        await asyncio.sleep(0)
                tid = adapter._pending[0].tid
                self.assertEqual(adapter._pending[0].payload, b"\x15" + NEW.encode())
                reader.feed_data(BinaryFrame(tid, 258, 255, 3, b"\x00\x15").encode())
                await asyncio.sleep(.01)
                if not qualified:
                    self.assertFalse(task.done())
                    reader.feed_data(BinaryFrame(tid, 1, 1, 3, b"\x00\x15").encode())
                await task
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    await adapter.set_collector(41, "not-a-wifi-api")
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await adapter.close()

    async def test_destination_rejects_mixed_or_remote_addresses(self):
        service = type("Service", (), {"listeners": [{"bound": True, "port": 18899}], "auxiliary_ports": {38899}})()
        loop = asyncio.get_running_loop()
        with patch.object(loop, "getaddrinfo", AsyncMock(return_value=[(2, 1, 6, "", ("192.168.1.10", 18899)),
                                                                      (2, 1, 6, "", ("203.0.113.1", 18899))])):
            with self.assertRaisesRegex(ValueError, "not_local"):
                await endpoint.validate_destination(service, NEW, ["192.168.1.10"])
            self.assertEqual(await endpoint.validate_destination(service, OLD, ["192.168.1.10"], restoring=True), ["192.168.1.10", "203.0.113.1"])
        for value in ("host,0,TCP", "host,18899,UDP", "host\r\nAT+RESET=S,18899,TCP", "host,018899,TCP"):
            with self.assertRaises(ValueError):
                endpoint.parse_endpoint(value)
