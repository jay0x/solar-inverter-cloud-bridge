"""Service adapter contract tests, not a substitute for a real HA lifecycle suite."""

import asyncio
from enum import Enum
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

try:
    import voluptuous as vol
except ImportError:
    vol = None


class ServiceValidationError(Exception):
    pass


class Unauthorized(Exception):
    def __init__(self, *, context=None):
        super().__init__("Unauthorized")
        self.context = context


class SupportsResponse(Enum):
    OPTIONAL = 1
    ONLY = 2


@unittest.skipIf(vol is None, "install tests/requirements.txt for HA adapter contracts")
class ServiceAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # ServiceCall deliberately has no hass attribute. The handler must capture HA.
        core, exceptions = ModuleType("homeassistant.core"), ModuleType("homeassistant.exceptions")
        core.SupportsResponse = SupportsResponse
        exceptions.ServiceValidationError = ServiceValidationError
        exceptions.Unauthorized = Unauthorized
        modules = {"homeassistant": ModuleType("homeassistant"), "homeassistant.core": core,
                   "homeassistant.exceptions": exceptions}
        path = Path(__file__).parents[1] / "custom_components/solar_inverter_bridge/services.py"
        spec = importlib.util.spec_from_file_location("custom_components.solar_inverter_bridge._services_test", path)
        self.adapter = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(self.adapter)
        self.record = {"operation_id": "caller-id", "device_id": "device-a", "state": "completed",
                       "outcome": "confirmed", "unresolved": False, "write_attempts": 1,
                       "request": {"key": "primary_output_priority", "value": "sub"}}
        self.storage = SimpleNamespace(set_mode=Mock(), set_clock_sync=Mock(),
                                       operation=Mock(return_value=self.record))
        self.service = SimpleNamespace(apply=AsyncMock(return_value=self.record), _notify=Mock())
        self.entry = SimpleNamespace(runtime_data={"storage": self.storage, "service": self.service})
        self.handlers = {}

        def register(domain, name, handler, **options):
            self.handlers[name] = (handler, options)

        async def execute(function, *args):
            return await asyncio.to_thread(function, *args)

        self.hass = SimpleNamespace(
            data={}, services=SimpleNamespace(async_register=register),
            config_entries=SimpleNamespace(async_entries=Mock(return_value=[self.entry])),
            auth=SimpleNamespace(async_get_user=AsyncMock(return_value=SimpleNamespace(is_admin=True, is_active=True, name="Test administrator"))),
            async_add_executor_job=execute,
        )
        self.adapter.async_register(self.hass)

    async def call(self, name, data, user_id="admin"):
        handler, options = self.handlers[name]
        call = SimpleNamespace(data=options["schema"](data), context=SimpleNamespace(user_id=user_id))
        return await handler(call)

    async def test_registered_handlers_capture_hass_and_forward_caller_id(self):
        self.assertNotIn("set_mode", self.handlers)
        await self.call("set_clock_sync", {"device_id": "device-a", "enabled": False})
        self.storage.set_clock_sync.assert_called_once_with("device-a", False)
        result = await self.call("apply_parameter", {
            "device_id": "device-a", "key": "primary_output_priority", "value": "sub", "operation_id": "caller-id",
        })
        self.service.apply.assert_awaited_once_with("device-a", "primary_output_priority", "sub", "caller-id", actor_name="Test administrator")
        self.assertEqual(result["outcome"], "confirmed")
        self.assertNotIn("request", result)

    async def test_missing_context_nonadmin_and_inactive_are_rejected(self):
        data = {"device_id": "device-a", "enabled": True}
        with self.assertRaises(Unauthorized):
            await self.call("set_clock_sync", data, None)
        self.hass.auth.async_get_user.assert_not_awaited()
        for user in (None, SimpleNamespace(is_admin=False, is_active=True),
                     SimpleNamespace(is_admin=True, is_active=False)):
            self.hass.auth.async_get_user.return_value = user
            with self.assertRaises(Unauthorized):
                await self.call("set_clock_sync", data)
        self.storage.set_clock_sync.assert_not_called()

    async def test_service_accepts_decimal_value_and_baseline(self):
        await self.call("apply_parameter", {"device_id": "device-a", "key": "maximum_charging_current",
                                            "value": 12.5, "expected_value": 12.4, "operation_id": "decimal"})
        self.service.apply.assert_awaited_once_with("device-a", "maximum_charging_current", 12.5, "decimal", expected_value=12.4, actor_name="Test administrator")

    async def test_apply_requires_bounded_caller_id(self):
        data = {"device_id": "device-a", "key": "primary_output_priority", "value": "sub"}
        for extension in ({}, {"operation_id": ""}, {"operation_id": "x" * 129}):
            with self.assertRaises(vol.Invalid):
                await self.call("apply_parameter", {**data, **extension})
        self.service.apply.assert_not_awaited()

    async def test_result_lookup_is_read_only_and_device_scoped(self):
        result = await self.call("get_operation", {"device_id": "device-a", "operation_id": "caller-id"})
        self.assertEqual(result["operation_id"], "caller-id")
        self.service.apply.assert_not_awaited()
        with self.assertRaisesRegex(ServiceValidationError, "operation_not_found"):
            await self.call("get_operation", {"device_id": "other-device", "operation_id": "caller-id"})

    async def test_unloaded_bridge_and_storage_failure_are_reported(self):
        from custom_components.solar_inverter_bridge.core.storage import StorageError
        self.storage.set_clock_sync.side_effect = StorageError("device_missing")
        with self.assertRaisesRegex(ServiceValidationError, "device_missing"):
            await self.call("set_clock_sync", {"device_id": "device-a", "enabled": True})
        self.entry.runtime_data = None
        with self.assertRaisesRegex(ServiceValidationError, "bridge_not_loaded"):
            await self.call("get_operation", {"device_id": "device-a", "operation_id": "caller-id"})

    async def test_registration_is_idempotent(self):
        before = dict(self.handlers)
        self.adapter.async_register(self.hass)
        self.assertEqual(self.handlers, before)
        self.assertEqual(set(before), {"set_clock_sync", "apply_parameter", "get_operation", "export_journal", "read_module_info", "reset_collector"})
