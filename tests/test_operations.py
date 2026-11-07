"""Operation failure boundaries exercised over a real loopback TCP stream."""

import asyncio
from datetime import datetime
from pathlib import Path
import tempfile
import threading
from time import monotonic
import unittest

from custom_components.solar_inverter_bridge.core.exchange import response_frame
from custom_components.solar_inverter_bridge.core.framing import crc16
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage, StorageError
from custom_components.solar_inverter_bridge.core.telemetry import required_addresses


class OperationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "bridge.sqlite3"
        self.storage = Storage(self.path)
        self.service = CollectorService(["127.0.0.1"], self.storage,
                                        now=lambda: datetime(2026, 11, 2, 12, 0, 0))
        self.port = (await self.service.start())[0][1]
        self.registers = {address: 0 for address in required_addresses()}
        self.registers.update({171: 32771, 184: 4, 201: 2, 277: 480, 280: 50,
                               601: 1, 632: 1, 636: 2, 647: 20, 648: 80,
                               696: 2026, 697: 11, 698: 2, 699: 11, 700: 59, 701: 0})
        self.writes = []
        self.write_seen = asyncio.Event()
        self.release_ack = asyncio.Event()
        self.release_ack.set()
        self.drop_ack = False
        self.client_tasks = []
        self.commands = []
        await self.connect()
        await self.service.verify(self.sha)
        self.device_id = await self.service.enroll(self.sha, "Test inverter")
        # Explicit transactions only: the autonomous polling loop is tested separately.
        self.service._polled[self.device_id] = monotonic() + 3600
        self.storage.set_mode(self.device_id, "control")

    async def asyncTearDown(self):
        self.release_ack.set()
        for task in self.commands:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.commands, return_exceptions=True)
        await self.service.close()
        for task in self.client_tasks:
            task.cancel()
        await asyncio.gather(*self.client_tasks, return_exceptions=True)
        await asyncio.to_thread(self.storage.close)
        self.directory.cleanup()

    async def connect(self):
        task = asyncio.create_task(self.collector())
        self.client_tasks.append(task)
        async with asyncio.timeout(2):
            while not self.service.connections:
                await asyncio.sleep(0)
        self.sha = next(iter(self.service.connections))
        self.holder = self.service.connections[self.sha]

    async def collector(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        try:
            await reader.readuntil(b"\n")
            writer.write(b"AT+DTUPN:OPERATIONS\r\n")
            await writer.drain()
            while True:
                header = await reader.readexactly(2)
                if header[1] == 3:
                    rest = await reader.readexactly(6)
                    request = header + rest
                    if crc16(request[:-2]) != int.from_bytes(request[-2:], "little"):
                        raise AssertionError("bad read request CRC")
                    address, count = int.from_bytes(rest[:2], "big"), int.from_bytes(rest[2:4], "big")
                    writer.write(response_frame(tuple(self.registers.get(address + i, 0) for i in range(count))))
                elif header[1] == 16:
                    meta = await reader.readexactly(5)
                    address, count = int.from_bytes(meta[:2], "big"), int.from_bytes(meta[2:4], "big")
                    payload = await reader.readexactly(meta[4] + 2)
                    request = header + meta + payload
                    if crc16(request[:-2]) != int.from_bytes(request[-2:], "little"):
                        raise AssertionError("bad write request CRC")
                    words = tuple(int.from_bytes(payload[i:i + 2], "big") for i in range(0, 2 * count, 2))
                    self.writes.append((address, words))
                    self.registers.update({address + i: word for i, word in enumerate(words)})
                    self.write_seen.set()
                    await self.release_ack.wait()
                    if self.drop_ack:
                        return
                    ack = header + meta[:4]
                    writer.write(ack + crc16(ack).to_bytes(2, "little"))
                else:
                    raise AssertionError("unexpected request function")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    def apply(self, operation_id, value="sbu", key="primary_output_priority"):
        task = asyncio.create_task(self.service.apply(self.device_id, key, value, operation_id))
        self.commands.append(task)
        return task

    async def wait_write(self):
        await asyncio.wait_for(self.write_seen.wait(), 2)

    async def reconnect(self):
        async with asyncio.timeout(2):
            while self.service.connections:
                await asyncio.sleep(0.01)
        self.drop_ack = False
        await self.connect()

    async def test_same_id_concurrent_and_offline_retry_sends_once(self):
        self.release_ack.clear()
        first = self.apply("one")
        await self.wait_write()
        second = self.apply("one")
        self.release_ack.set()
        a, b = await asyncio.gather(first, second)
        self.assertEqual(a, b)
        self.assertEqual(a["outcome"], "confirmed")
        self.assertEqual(self.service.settings_registers[self.device_id][601], 2)
        self.assertEqual(self.service.parameter_readbacks[self.device_id]["primary_output_priority"]["value"], "sbu")
        self.assertNotIn(self.device_id, self.service._settings_observed)
        self.service._disconnect(self.holder)
        self.storage.set_mode(self.device_id, "monitoring")
        self.assertEqual(await self.apply("one"), a)
        self.assertEqual(self.writes, [(601, (2,))])

    async def test_uuid_cannot_target_another_device(self):
        await self.apply("one")
        other = self.storage.enroll("b" * 64, "Other", "modbus_protocol_4")
        with self.assertRaisesRegex(StorageError, "operation_id_conflict"):
            await self.service.apply(other, "primary_output_priority", "sbu", "one")
        with self.assertRaisesRegex(StorageError, "operation_id_conflict"):
            self.storage.accept_operation(other, "one", {"key": "primary_output_priority", "value": "sbu", "clock_sync": False})
        self.assertEqual(len(self.writes), 1)

    async def test_accepted_job_already_blocks_second_admission(self):
        self.storage.accept_operation(self.device_id, "first", {"value": 1})
        with self.assertRaisesRegex(StorageError, "device_busy_or_unresolved"):
            self.storage.accept_operation(self.device_id, "second", {"value": 2})
        self.assertEqual(self.writes, [])

    async def test_collection_pause_while_waiting_for_transport_prevents_send(self):
        await self.holder["lock"].acquire()
        try:
            task = self.apply("queued")
            async with asyncio.timeout(2):
                while not self.service._command_lock(self.device_id).locked():
                    await asyncio.sleep(0)
            await asyncio.to_thread(self.storage.set_collection, self.device_id, False, 10)
        finally:
            self.holder["lock"].release()
        with self.assertRaisesRegex(ValueError, "device_disabled"):
            await task
        self.assertEqual(self.writes, [])

    async def test_lost_ack_blocks_next_write_and_reconcile_preserves_outcome(self):
        self.drop_ack = True
        with self.assertRaises(ConnectionError):
            await self.apply("lost")
        record = self.storage.operation("lost")
        self.assertEqual(record["outcome"], "uncertain")
        self.assertTrue(record["unresolved"])
        await self.reconnect()
        with self.assertRaisesRegex(StorageError, "device_busy_or_unresolved"):
            await self.apply("second", "suf")
        self.assertEqual(await self.service.reconcile(self.device_id), ["lost"])
        resolved = self.storage.operation("lost")
        self.assertEqual(resolved["outcome"], "uncertain")
        self.assertEqual(resolved["resolution"], "readback_matched")
        self.assertFalse(resolved["unresolved"])
        self.assertEqual(await self.apply("lost"), resolved)
        self.assertEqual(len(self.writes), 1)

    async def test_cancel_after_send_retains_barrier(self):
        self.release_ack.clear()
        task = self.apply("cancelled")
        await self.wait_write()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        record = self.storage.operation("cancelled")
        self.assertTrue(record["unresolved"])
        self.assertEqual(record["outcome"], "uncertain")
        self.assertEqual(record["write_attempts"], 1)
        self.assertEqual(await self.apply("cancelled"), record)
        self.assertEqual(len(self.writes), 1)

    async def test_admin_can_keep_a_fresh_different_value_without_resending(self):
        self.drop_ack = True
        with self.assertRaises(ConnectionError):
            await self.apply("keep-current")
        self.registers[601] = 1
        await self.reconnect()
        self.assertEqual(await self.service.reconcile(self.device_id), [])
        record = self.storage.operation("keep-current")
        self.assertEqual(record["last_observed_value"], "sub")
        self.storage.set_mode(self.device_id, "monitoring")
        with self.assertRaisesRegex(ValueError, "observed_value_changed"):
            await self.service.accept_current_value(self.device_id, "keep-current", "suf", "admin")
        self.assertTrue(self.storage.has_unresolved(self.device_id))
        resolved = await self.service.accept_current_value(self.device_id, "keep-current", "sub", "admin")
        self.assertEqual(resolved["outcome"], "uncertain")
        self.assertEqual(resolved["resolution"], "accepted_current_value")
        self.assertEqual(resolved["resolved_by"], "admin")
        self.assertEqual(resolved["request"]["value"], "sbu")
        self.assertFalse(self.storage.has_unresolved(self.device_id))
        self.assertEqual(len(self.writes), 1)

    async def test_clock_can_be_explicitly_resolved_using_its_observed_time(self):
        request = {"key": "inverter_datetime", "value": "2026-11-02T12:00:00", "clock_sync": True}
        self.storage.accept_operation(self.device_id, "clock-uncertain", request)
        self.storage.claim_send("clock-uncertain")
        self.storage.finish_operation("clock-uncertain", state="reconciling", outcome="uncertain", unresolved=True, reason="lost_ack")
        self.assertEqual(await self.service.reconcile(self.device_id), [])
        record = self.storage.operation("clock-uncertain")
        self.storage.set_mode(self.device_id, "monitoring")
        with self.assertRaisesRegex(ValueError, "observed_value_changed"):
            await self.service.accept_current_value(self.device_id, "clock-uncertain", record["last_observed_value"], "admin")
        resolved = await self.service.accept_current_value(self.device_id, "clock-uncertain", record["last_observed_value"], "admin", record["last_observed_at"])
        self.assertEqual(resolved["resolution"], "accepted_current_value")
        self.assertEqual(self.writes, [])

    async def test_cancel_during_late_admission_finishes_without_send(self):
        entered, release = threading.Event(), threading.Event()
        original = self.storage.accept_operation

        def delayed(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError("test did not release admission")
            return original(*args, **kwargs)

        self.storage.accept_operation = delayed
        task = self.apply("late")
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            task.cancel()
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.storage.accept_operation = original
        record = self.storage.operation("late")
        self.assertEqual(record["outcome"], "not_sent")
        self.assertEqual(record["write_attempts"], 0)
        self.assertFalse(record["unresolved"])
        self.assertEqual(self.writes, [])

    async def test_cancel_during_late_claim_does_not_send_or_replay(self):
        entered, release = threading.Event(), threading.Event()
        original = self.storage.claim_send

        def delayed(*args):
            entered.set()
            if not release.wait(3):
                raise AssertionError("test did not release claim")
            return original(*args)

        self.storage.claim_send = delayed
        task = self.apply("late-claim")
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            task.cancel()
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        record = self.storage.operation("late-claim")
        self.assertEqual(record["outcome"], "not_sent")
        self.assertFalse(record["unresolved"])
        self.assertEqual(await self.apply("late-claim"), record)
        self.assertEqual(self.writes, [])

    async def test_reconcile_cannot_clear_inflight_command(self):
        self.release_ack.clear()
        first = self.apply("inflight")
        await self.wait_write()
        reconcile = asyncio.create_task(self.service.reconcile(self.device_id))
        self.commands.append(reconcile)
        second = self.apply("next", "suf")
        await asyncio.sleep(0.02)
        self.assertFalse(reconcile.done())
        self.assertEqual(len(self.writes), 1)
        self.assertTrue(self.storage.has_unresolved(self.device_id))
        self.release_ack.set()
        a, resolved, b = await asyncio.gather(first, reconcile, second)
        self.assertEqual(resolved, [])
        self.assertEqual((a["outcome"], b["outcome"]), ("confirmed", "confirmed"))
        self.assertEqual(self.writes, [(601, (2,)), (601, (3,))])

    async def test_clock_limit_uses_fresh_registers_not_cached_time(self):
        self.storage.set_clock_sync(self.device_id, True)
        self.service.settings[self.device_id] = {"inverter_datetime": "2026-11-02T11:59:00"}
        self.registers[699] = 8
        with self.assertRaisesRegex(ValueError, "clock_correction_too_large"):
            await self.service.apply(self.device_id, "inverter_datetime", "2026-11-02T12:00:00",
                                     "clock", clock_sync=True)
        self.assertEqual(self.writes, [])

    async def test_clock_target_is_computed_after_preflight(self):
        from unittest.mock import patch
        from custom_components.solar_inverter_bridge.core import exchange
        self.storage.set_clock_sync(self.device_id, True)
        original = exchange.read_settings

        async def delayed_preflight(*args, **kwargs):
            result = await original(*args, **kwargs)
            self.service.now = lambda: datetime(2026, 11, 2, 12, 0, 30)
            return result

        with patch.object(exchange, "read_settings", delayed_preflight):
            result = await self.service.apply(self.device_id, "inverter_datetime", "2026-11-02T12:00:00", "fresh-clock", clock_sync=True)
        self.assertEqual(result["outcome"], "confirmed")
        self.assertEqual(result["request"]["value"], "2026-11-02T12:00:00")
        self.assertEqual(result["send_value"], "2026-11-02T12:00:30")
        self.assertIn((696, (2026, 11, 2, 12, 0, 30)), self.writes)
        again = await self.service.apply(self.device_id, "inverter_datetime", "2026-11-02T12:00:00", "fresh-clock", clock_sync=True)
        self.assertEqual(again, result)
        self.assertEqual(len(self.writes), 1)

    async def test_six_advanced_decimal_settings_write_and_read_back_on_simulator(self):
        cases = [("maximum_charging_current", 640, 12.5, 125),
                 ("maximum_ac_charging_current", 641, 8.2, 82),
                 ("equalization_voltage", 652, 57.6, 576),
                 ("battery_protection_voltage_ac", 644, 46.8, 468),
                 ("op1_protection_voltage_offgrid", 645, 44.4, 444),
                 ("battery_protection_voltage_offgrid", 646, 42.1, 421)]
        self.assertEqual(self.storage.device(self.device_id)["control_mode"], "full")
        for key, address, value, raw in cases:
            with self.subTest(key=key):
                self.registers[address] = raw - 1
                result = await self.service.apply(self.device_id, key, value, "advanced-" + key, expected_value=(raw - 1) / 10)
                self.assertEqual(result["outcome"], "confirmed")
                self.assertEqual(self.writes[-1], (address, (raw,)))
                self.assertEqual(self.service.settings[self.device_id][key], value)
        self.assertEqual(len(self.writes), 6)
        with self.assertRaisesRegex(ValueError, "value_outside_register_step"):
            await self.service.apply(self.device_id, cases[0][0], 12.55, "bad-decimal")
        self.assertEqual(len(self.writes), 6)

    async def test_duplicate_connection_does_not_steal_active_owner(self):
        other = asyncio.create_task(self.collector())
        self.client_tasks.append(other)
        await asyncio.sleep(0.1)
        self.assertFalse(other.done())
        self.assertIs(self.service.connections[self.sha], self.holder)
        await self.apply("still-owned")
        self.assertEqual(len(self.writes), 1)

    async def test_native_signature_and_dependent_limits_are_checked(self):
        with self.assertRaisesRegex(ValueError, "soc_recovery_must_exceed_protection"):
            await self.apply("bad-soc", 90, "battery_protection_soc_ac")
        with self.assertRaisesRegex(ValueError, "ambiguous_schedule_window"):
            await self.apply("bad-window", "snu", "secondary_charging_priority")
        self.registers[171] = 999
        with self.assertRaisesRegex(ValueError, "unsupported_or_unconfirmed_identity"):
            await self.apply("wrong-inverter")
        self.assertEqual(self.writes, [])

    async def test_editor_baseline_conflict_preserves_inverter_value(self):
        with self.assertRaisesRegex(ValueError, "baseline_conflict"):
            await self.service.apply(self.device_id, "primary_output_priority", "sbu", "stale-draft", expected_value="suf")
        self.assertEqual(self.writes, [])
        self.assertEqual(self.registers[601], 1)
        result = await self.service.apply(self.device_id, "primary_output_priority", "sbu", "fresh-draft", expected_value="sub")
        self.assertEqual(result["outcome"], "confirmed")

    async def test_collection_roundtrip_changes_epoch_and_cancels_waiting_intent(self):
        await self.holder["lock"].acquire()
        try:
            task = self.apply("old-permission")
            async with asyncio.timeout(2):
                while not self.service._command_lock(self.device_id).locked():
                    await asyncio.sleep(0)
            self.storage.set_collection(self.device_id, False, 10)
            self.storage.set_collection(self.device_id, True, 10)
        finally:
            self.holder["lock"].release()
        with self.assertRaisesRegex(ValueError, "permissions_changed"):
            await task
        self.assertEqual(self.writes, [])

    async def test_expiry_publishes_without_any_successful_poll(self):
        from custom_components.solar_inverter_bridge.core.observations import Observation
        updates = []
        self.service.on_update = lambda: updates.append(True)
        self.service.observations[self.device_id] = Observation({"pv_power": {"value": 1}}, monotonic())
        self.service._expire_observations()
        self.assertEqual(len(updates), 1)
        self.service.observations[self.device_id].observed_monotonic -= 61
        self.service._expire_observations()
        self.assertEqual(len(updates), 2)
        self.service._expire_observations()
        self.assertEqual(len(updates), 2)

    async def test_collection_options_validate_and_persist(self):
        self.storage.set_collection(self.device_id, False, 20)
        saved = self.storage.device(self.device_id)
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["poll_interval"], 20)
        for interval in (0, 4, 301, True):
            with self.assertRaises(ValueError):
                self.storage.set_collection(self.device_id, True, interval)
        with self.assertRaisesRegex(ValueError, "device_disabled"):
            await self.apply("paused")
        self.assertEqual(self.writes, [])

    async def test_expired_verification_cannot_be_reused_for_enrollment(self):
        self.holder["verified_at"] -= 91
        with self.assertRaisesRegex(ValueError, "verification_required"):
            await self.service.enroll(self.sha, "Again")
        await self.service.verify(self.sha)
        self.assertEqual(await self.service.enroll(self.sha, "Again"), self.device_id)
        self.assertEqual(self.writes, [])

    async def test_removal_retains_ledger_and_requires_new_verification(self):
        await self.apply("retained-command")
        writes_before = list(self.writes)
        old_id = self.device_id
        await self.service.remove_device(old_id)
        self.assertIsNone(self.storage.device(old_id))
        self.assertIn(old_id, self.storage.removed_device_ids())
        self.assertEqual(self.storage.operation("retained-command")["outcome"], "confirmed")
        with self.assertRaisesRegex(ValueError, "verification_required"):
            await self.service.enroll(self.sha, "Added again")
        await self.service.verify(self.sha)
        new_id = await self.service.enroll(self.sha, "Added again")
        self.assertNotEqual(old_id, new_id)
        self.assertEqual(self.storage.device(new_id)["control_mode"], "full")
        with self.assertRaisesRegex(StorageError, "operation_id_conflict"):
            await self.service.apply(new_id, "primary_output_priority", "sbu", "retained-command")
        self.assertEqual(self.writes, writes_before)

    async def test_removal_cannot_bypass_an_unresolved_write(self):
        self.drop_ack = True
        with self.assertRaises(ConnectionError):
            await self.apply("unresolved-before-remove")
        with self.assertRaisesRegex(StorageError, "device_busy_or_unresolved"):
            await self.service.remove_device(self.device_id)
        self.assertIsNotNone(self.storage.device(self.device_id))
        self.assertNotIn(self.device_id, self.storage.removed_device_ids())

    async def test_removal_is_refused_while_a_command_is_active(self):
        self.release_ack.clear()
        command = self.apply("active-before-remove")
        await self.wait_write()
        with self.assertRaisesRegex(ValueError, "device_busy_or_unresolved"):
            await self.service.remove_device(self.device_id)
        self.release_ack.set()
        await command
        self.assertIsNotNone(self.storage.device(self.device_id))

    async def test_readonly_database_never_sends_a_write(self):
        await asyncio.to_thread(self.storage.call, lambda: self.storage.db.execute("PRAGMA query_only=ON"))
        with self.assertRaisesRegex(StorageError, "storage_unavailable"):
            await self.apply("readonly")
        self.assertEqual(self.writes, [])
        self.assertIsNone(self.storage.operation("readonly"))

    async def test_transaction_abort_before_accept_never_sends(self):
        def fail_inserts():
            self.storage.db.execute("CREATE TRIGGER reject_operation BEFORE INSERT ON operations BEGIN SELECT RAISE(ABORT, 'test failure'); END")
            self.storage.db.commit()
        await asyncio.to_thread(self.storage.call, fail_inserts)
        with self.assertRaisesRegex(StorageError, "storage_unavailable"):
            await self.apply("aborted")
        self.assertEqual(self.writes, [])
        self.assertIsNone(self.storage.operation("aborted"))

    async def test_shutdown_cancels_command_and_restart_never_replays(self):
        self.release_ack.clear()
        task = self.apply("shutdown")
        await self.wait_write()
        await asyncio.wait_for(self.service.close(), 2)
        self.assertTrue(task.cancelled())
        await asyncio.to_thread(self.storage.close)
        self.storage = Storage(self.path)
        record = self.storage.operation("shutdown")
        self.assertTrue(record["unresolved"])
        self.assertEqual(record["write_attempts"], 1)
        self.service.storage = self.storage
        self.assertEqual(await self.apply("shutdown"), record)
        self.assertEqual(len(self.writes), 1)
