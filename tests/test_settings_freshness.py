"""Session-bound settings and readback freshness, without HA or live devices."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from custom_components.solar_inverter_bridge.core.observations import Observation
from custom_components.solar_inverter_bridge.core.parameters import FIELDS
from custom_components.solar_inverter_bridge.core.session import CollectorService
import test_clock_execution as clock_fixture


class SettingsFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.service = CollectorService([], None)
        self.device = {"device_id": "device", "collector_sha256": "collector", "enabled": True, "poll_interval": 10}
        self.holder = {"identity_sha256": "collector", "closed": asyncio.Event(), "profile_verified": True,
                       "writer": SimpleNamespace(is_closing=lambda: False),
                       "reader": SimpleNamespace(at_eof=lambda: False)}
        self.service.connections["collector"] = self.holder
        self.service._settings_sessions["device"] = self.holder
        self.service._settings_observed["device"] = 1000
        self.service.settings["device"] = {"primary_output_priority": "sub"}

    def test_current_session_is_required_independently_of_age(self):
        self.assertTrue(self.service.settings_freshness(self.device, now=1001)["available"])
        self.holder["closed"].set()
        view = self.service.settings_freshness(self.device, now=1001)
        self.assertFalse(view["current_session"])
        self.assertEqual(view["blocked_reason"], "collector_not_connected")
        self.service.connections["collector"] = {**self.holder, "closed": asyncio.Event()}
        view = self.service.settings_freshness(self.device, now=1001)
        self.assertFalse(view["available"])
        self.assertEqual(view["blocked_reason"], "settings_session_changed")

    def test_paused_unverified_missing_and_expired_readings(self):
        self.assertEqual(self.service.settings_freshness({**self.device, "enabled": False}, now=1001)["blocked_reason"], "device_disabled")
        self.holder["profile_verified"] = False
        self.assertEqual(self.service.settings_freshness(self.device, now=1001)["blocked_reason"], "profile_not_verified")
        self.holder["profile_verified"] = True
        self.assertEqual(self.service.settings_freshness(self.device, "not_observed", now=1001)["blocked_reason"], "parameter_not_observed")
        for pause in (1, 10, 60, 300):
            with self.subTest(pause=pause):
                device = {**self.device, "poll_interval": pause}
                ttl = max(90, 5 * pause)
                self.assertTrue(self.service.settings_freshness(device, now=1000 + ttl)["available"])
                self.assertFalse(self.service.settings_freshness(device, now=1000 + ttl + .001)["available"])

    def test_settings_expire_after_telemetry_without_repeated_notifications(self):
        self.service.observations["device"] = Observation({}, 800)
        self.service.on_update = Mock()
        with patch("custom_components.solar_inverter_bridge.core.session.monotonic", return_value=1000) as clock:
            self.service._expire_observations()
            self.service.on_update.reset_mock()
            clock.return_value = 1090
            self.service._expire_observations()
            self.service.on_update.assert_not_called()
            clock.return_value = 1091
            self.service._expire_observations()
            self.service.on_update.assert_called_once()
            clock.return_value = 1100
            self.service._expire_observations()
            self.service.on_update.assert_called_once()

    def test_readback_only_refreshes_its_field_and_retains_session(self):
        field = next(field for field in FIELDS if field.key == "primary_output_priority")
        with patch("custom_components.solar_inverter_bridge.core.session.monotonic", return_value=1100):
            self.service._remember_parameter("device", field, (2,), holder=self.holder)
        self.assertEqual(self.service._settings_observed["device"], 1000)
        self.assertFalse(self.service.settings_freshness(self.device, now=1100)["available"])
        view = self.service.settings_freshness(self.device, field.key, now=1100)
        self.assertTrue(view["available"])
        self.assertEqual(view["source"], "parameter_readback")
        self.assertFalse(self.service.settings_freshness(self.device, field.key, now=1191)["available"])
        self.service.connections["collector"] = {**self.holder, "closed": asyncio.Event()}
        self.assertFalse(self.service.settings_freshness(self.device, field.key, now=1101)["current_session"])


class SettingsPollingTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = clock_fixture.BinaryClockExecutionTests.asyncSetUp

    async def test_real_write_readback_does_not_refresh_group_or_cached_clock(self):
        from unittest.mock import AsyncMock
        device = self.storage.device(self.device_id)
        stamp = self.service._settings_observed[self.device_id]
        self.peer.registers[679] = 0
        result = await self.service.apply(self.device_id, "lcd_backlight", "always_on", "display")
        self.assertEqual(result["outcome"], "confirmed")
        self.assertEqual(self.service._settings_observed[self.device_id], stamp)
        self.assertFalse(self.service.settings_freshness(device)["available"])
        self.assertTrue(self.service.settings_freshness(device, "lcd_backlight")["available"])
        with patch.object(self.service, "_maybe_clock", new_callable=AsyncMock) as clock:
            await self.service.poll_once(self.device_id)
            self.assertTrue(self.service.settings_freshness(device)["available"])
            self.assertNotIn(self.device_id, self.service._parameter_observations)
            fresh_stamp = self.service._settings_observed[self.device_id]
            await self.service.poll_once(self.device_id)
            self.assertEqual(self.service._settings_observed[self.device_id], fresh_stamp)
            self.assertEqual(clock.await_count, 1)
