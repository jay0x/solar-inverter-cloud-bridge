"""Administrator services for external callers. Missing user context is not authorization."""

from functools import partial

from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ServiceValidationError, Unauthorized
import voluptuous as vol

from .const import DOMAIN
from .core.storage import StorageError


OPERATION_ID = vol.All(str, vol.Length(min=1, max=128))


def async_register(hass):
    if hass.data.get(DOMAIN, {}).get("services_registered"):
        return
    hass.services.async_register(DOMAIN, "set_clock_sync", partial(_set_clock_sync, hass), schema=vol.Schema({
        vol.Required("device_id"): str,
        vol.Required("enabled"): bool,
    }))
    hass.services.async_register(DOMAIN, "apply_parameter", partial(_apply, hass), schema=vol.Schema({
        vol.Required("device_id"): str,
        vol.Required("key"): str,
        vol.Required("value"): vol.Any(str, int, float),
        vol.Required("operation_id"): OPERATION_ID,
        vol.Optional("expected_value"): vol.Any(str, int, float, None),
    }), supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "get_operation", partial(_get_operation, hass), schema=vol.Schema({
        vol.Required("device_id"): str,
        vol.Required("operation_id"): OPERATION_ID,
    }), supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, "read_module_info", partial(_read_module_info, hass), schema=vol.Schema({
        vol.Required("device_id"): str,
    }), supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, "reset_collector", partial(_reset_collector, hass), schema=vol.Schema({
        vol.Required("device_id"): str,
    }), supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "export_journal", partial(_export_journal, hass), schema=vol.Schema({
        vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0)),
        vol.Optional("limit", default=200): vol.All(int, vol.Range(min=1, max=500)),
    }), supports_response=SupportsResponse.ONLY)
    hass.data.setdefault(DOMAIN, {})["services_registered"] = True


def _entry(hass):
    entries = hass.config_entries.async_entries(DOMAIN)
    entry = next((entry for entry in entries if getattr(entry, "runtime_data", None) is not None), None)
    if entry is None:
        raise ServiceValidationError("bridge_not_loaded")
    return entry


async def _admin(hass, call):
    if call.context.user_id is None:
        raise Unauthorized(context=call.context)
    user = await hass.auth.async_get_user(call.context.user_id)
    if user is None or not user.is_admin or not user.is_active:
        raise Unauthorized(context=call.context)


async def _set_clock_sync(hass, call):
    await _admin(hass, call)
    entry = _entry(hass)
    try:
        await hass.async_add_executor_job(entry.runtime_data["storage"].set_clock_sync, call.data["device_id"], call.data["enabled"])
        entry.runtime_data["service"]._notify()
    except StorageError as error:
        raise ServiceValidationError(str(error)) from error


async def _actor_name(hass, user_id):
    user = await hass.auth.async_get_user(user_id) if user_id else None
    return user.name if user and user.name else "Administrator"


async def _apply(hass, call):
    await _admin(hass, call)
    entry = _entry(hass)
    try:
        baseline = {"expected_value": call.data["expected_value"]} if "expected_value" in call.data else {}
        result = await entry.runtime_data["service"].apply(
            call.data["device_id"], call.data["key"], call.data["value"], call.data["operation_id"],
            actor_name=await _actor_name(hass, call.context.user_id), **baseline)
    except (StorageError, ValueError, ConnectionError, TimeoutError) as error:
        # The caller already owns the ID and can query it after an ambiguous error.
        raise ServiceValidationError(str(error)) from error
    return operation_view(result)


def operation_view(record):
    request = record.get("request") or {}
    return {
        "setting_key": request.get("key") or record.get("setting_key"),
        "desired_value": record.get("send_value", request.get("value", record.get("desired_value"))),
        "previous_value": request.get("expected_value", record.get("previous_value")),
        "actor_name": record.get("actor_name"),
        **{key: record.get(key) for key in (
            "operation_id", "device_id", "state", "outcome", "reason", "resolution",
            "unresolved", "write_attempts", "created_at", "send_intent_at", "send_value",
            "resolved_at", "last_observed_value", "last_observed_at",
        )},
    }


async def _get_operation(hass, call):
    await _admin(hass, call)
    entry = _entry(hass)
    record = await hass.async_add_executor_job(entry.runtime_data["storage"].operation, call.data["operation_id"])
    if record is None or record["device_id"] != call.data["device_id"]:
        raise ServiceValidationError("operation_not_found")
    return operation_view(record)


async def _read_module_info(hass, call):
    await _admin(hass, call)
    try:
        return await _entry(hass).runtime_data["service"].read_module_info(call.data["device_id"])
    except (ConnectionError, TimeoutError, ValueError, StorageError) as error:
        raise ServiceValidationError(str(error)) from error


async def _reset_collector(hass, call):
    await _admin(hass, call)
    try:
        return await _entry(hass).runtime_data["service"].reset_collector(call.data["device_id"])
    except (ConnectionError, TimeoutError, ValueError, StorageError) as error:
        raise ServiceValidationError(str(error)) from error


async def _export_journal(hass, call):
    await _admin(hass, call)
    entry = _entry(hass)
    try:
        return await hass.async_add_executor_job(
            entry.runtime_data["storage"].journal_page, call.data["offset"], call.data["limit"])
    except ValueError as error:
        raise ServiceValidationError(str(error)) from error
