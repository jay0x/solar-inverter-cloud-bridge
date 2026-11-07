"""Recovery cooldown, reconnect, and failure boundaries without live hardware."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from custom_components.solar_inverter_bridge.core.observations import Observation
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage, StorageError


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Backdated grace periods must not depend on the CI host's uptime.
        clock = patch("custom_components.solar_inverter_bridge.core.session.monotonic", return_value=10000.0)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "bridge.sqlite3"
        self.storage = Storage(self.path)
        self.device = self.storage.enroll("collector", "Unit", "modbus_protocol_4")
        self.service = CollectorService([], self.storage)
        self.service._started_monotonic -= 1000
        self.connect()

    def connect(self):
        holder = {"identity_sha256": "collector", "closed": asyncio.Event(), "lock": asyncio.Lock(),
                  "writer": Mock(), "reader": Mock()}
        holder["writer"].is_closing.return_value = False
        holder["reader"].at_eof.return_value = False
        self.service.connections["collector"] = holder

    async def asyncTearDown(self):
        self.storage.close()
        self.directory.cleanup()

    def enable(self):
        self.storage.set_mode(self.device, "control")
        self.storage.set_auto_reset(self.device, True)

    async def test_opt_in_collection_pause_and_fresh_reading_prevent_reset(self):
        self.assertFalse(self.storage.device(self.device)["auto_reset"])
        with patch("custom_components.solar_inverter_bridge.core.exchange.exchange_at", new_callable=AsyncMock) as send:
            self.assertEqual(await self.service.reset_collector(self.device, automatic=True), {"reset": "skipped"})
            self.storage.set_auto_reset(self.device, True)
            self.storage.set_collection(self.device, False, 10)
            self.assertEqual(await self.service.reset_collector(self.device, automatic=True), {"reset": "skipped"})
            self.storage.set_collection(self.device, True, 10)
            self.service.observations[self.device] = Observation({}, self.clock())
            self.assertEqual(await self.service.reset_collector(self.device, automatic=True), {"reset": "skipped"})
            send.assert_not_awaited()

    async def test_timeout_counts_and_restart_cannot_replay_reset(self):
        self.enable()
        with patch("custom_components.solar_inverter_bridge.core.exchange.exchange_at", new_callable=AsyncMock, side_effect=TimeoutError) as send:
            self.assertEqual(await self.service.reset_collector(self.device, automatic=True), {"reset": "uncertain"})
            self.assertEqual(send.await_count, 1)
            self.storage.close()
            self.storage = Storage(self.path)
            self.service = CollectorService([], self.storage)
            self.service._started_monotonic -= 1000
            self.connect()
            self.assertTrue(self.storage.device(self.device)["auto_reset"])
            self.assertEqual(await self.service.reset_collector(self.device, automatic=True), {"reset": "skipped"})
            self.assertEqual(send.await_count, 1)

    async def test_failed_reservation_and_pending_command_prevent_send(self):
        self.enable()
        with patch("custom_components.solar_inverter_bridge.core.exchange.exchange_at", new_callable=AsyncMock) as send:
            with patch.object(self.storage, "reserve_collector_reset", side_effect=StorageError("storage_unavailable")):
                with self.assertRaises(StorageError):
                    await self.service.reset_collector(self.device, automatic=True)
            self.storage.accept_operation(self.device, "pending", {"key": "primary_output_priority", "value": "sbu"})
            with self.assertRaisesRegex(ValueError, "device_busy_or_unresolved"):
                await self.service.reset_collector(self.device, automatic=True)
            send.assert_not_awaited()

    async def test_cooldown_boundary_clock_rollback_and_reenrollment(self):
        self.enable()
        now = datetime.now(timezone.utc)
        self.assertTrue(self.storage.reserve_collector_reset(self.device, now=now))
        self.assertFalse(self.storage.reserve_collector_reset(self.device, automatic=True, now=now - timedelta(days=1)))
        self.storage.remove_device(self.device)
        self.device = self.storage.enroll("collector", "Again", "modbus_protocol_4")
        self.enable()
        self.assertFalse(self.storage.reserve_collector_reset(self.device, automatic=True, now=now + timedelta(seconds=3599)))
        self.assertTrue(self.storage.reserve_collector_reset(self.device, automatic=True, now=now + timedelta(seconds=3600)))

    async def test_scheduler_recovers_stale_connection_but_not_disconnected_module(self):
        self.enable()
        with patch("custom_components.solar_inverter_bridge.core.exchange.exchange_at", new_callable=AsyncMock, return_value=b"AT+RESET:W000\r\n") as send:
            await self.service._poll_device(self.device)
            self.assertEqual(send.await_count, 1)
            self.assertEqual(send.await_args.args[2], b"AT+RESET=S\r\n")
            with self.assertRaisesRegex(ConnectionError, "collector_not_connected"):
                await self.service.reset_collector(self.device, automatic=True)
            self.assertEqual(send.await_count, 1)

    async def test_startup_grace_and_three_poll_intervals(self):
        self.enable()
        self.service._started_monotonic = self.clock()
        self.assertFalse(self.service._reset_due(self.storage.device(self.device)))
        self.service._started_monotonic -= 400
        self.storage.set_collection(self.device, True, 300)
        self.assertFalse(self.service._reset_due(self.storage.device(self.device)))
        self.service._started_monotonic -= 501
        self.assertTrue(self.service._reset_due(self.storage.device(self.device)))

    async def test_new_enrollment_gets_its_own_grace_after_long_runtime(self):
        holder = self.service.connections["collector"]
        holder.update(ready=True, verified_at=self.clock(), proof={"profile_id": "modbus_protocol_4"})
        self.service.candidates["collector"] = holder
        await self.service.enroll("collector", "Unit")
        self.enable()
        self.assertFalse(self.service._reset_due(self.storage.device(self.device)))
