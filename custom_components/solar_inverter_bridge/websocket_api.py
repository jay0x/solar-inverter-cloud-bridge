"""Authenticated panel commands. Manual changes require an administrator."""

from homeassistant.components import websocket_api
from homeassistant.helpers.dispatcher import async_dispatcher_send
import voluptuous as vol

from .const import DOMAIN
from .device_management import display_names, native_device_ids, native_sensors
from .core.parameters import inventory
from .core.policy import clock_write_allowed
from .core.storage import StorageError
from .core.identity import normalize_sources
from .services import OPERATION_ID, operation_view

SIGNAL = "solar_inverter_bridge_update"


def async_register(hass):
    websocket_api.async_register_command(hass, ws_status)
    websocket_api.async_register_command(hass, ws_network_hints)
    websocket_api.async_register_command(hass, ws_verify)
    websocket_api.async_register_command(hass, ws_enroll)
    websocket_api.async_register_command(hass, ws_set_clock_sync)
    websocket_api.async_register_command(hass, ws_set_auto_reset)
    websocket_api.async_register_command(hass, ws_apply)
    websocket_api.async_register_command(hass, ws_get_operation)
    websocket_api.async_register_command(hass, ws_configure_network)
    websocket_api.async_register_command(hass, ws_set_collection)
    websocket_api.async_register_command(hass, ws_accept_current_value)
    websocket_api.async_register_command(hass, ws_remove_device)
    websocket_api.async_register_command(hass, ws_check_operation)
    websocket_api.async_register_command(hass, ws_diagnostics)
    websocket_api.async_register_command(hass, ws_journal)
    websocket_api.async_register_command(hass, ws_module_info)
    websocket_api.async_register_command(hass, ws_reset_collector)
    websocket_api.async_register_command(hass, ws_compatibility)
    websocket_api.async_register_command(hass, ws_profile)


def _runtime(hass):
    entries = hass.config_entries.async_entries(DOMAIN)
    return next((entry for entry in entries if getattr(entry, "runtime_data", None) is not None), None)


@websocket_api.websocket_command({vol.Required("type"): "solar_inverter_bridge/network_hints"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_network_hints(hass, connection, msg):
    from .network_hints import async_network_hints
    connection.send_result(msg["id"], await async_network_hints(hass))


@websocket_api.websocket_command({vol.Required("type"): "solar_inverter_bridge/status"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_status(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    status = await entry.runtime_data["service"].status()
    status["parameters"] = list(inventory())
    names = display_names(hass, entry)
    native_ids = native_device_ids(hass, entry)
    sensors = native_sensors(hass, entry, native_ids)
    status["recorder_available"] = "recorder" in hass.config.components
    for device in status["devices"]:
        from .core.drivers import fields_for
        device["parameters"] = list(inventory(fields_for(device["profile_id"])))
        for parameter in device["parameters"]:
            choices=device.get("setting_choices",{}).get(str(parameter["address"]))
            if choices is not None:
                field=next(f for f in fields_for(device["profile_id"]) if f.key==parameter["key"])
                parameter["allowed_values"]=[value/field.divisor for value in choices]
        from .core.catalogue import descriptors
        device["measurement_labels"]={d["key"]:d["name"] for d in descriptors(device["profile_id"])}
        device["ha_device_id"] = native_ids.get(device["device_id"])
        device["ha_sensors"] = sensors.get(device["device_id"], [])
        device["suggested_name"] = device.get("suggested_name") or device["name"]
        device["name"] = names.get(device["device_id"]) or device["suggested_name"]
        device["clock_write_allowed"] = device["capabilities"]["clock_write"] and clock_write_allowed(device["clock_sync"])
    status["last_error"] = entry.runtime_data["service"].last_error
    status["time_zone"] = hass.config.time_zone
    status["allowed_sources"] = list(entry.runtime_data["service"].sources)
    connection.send_result(msg["id"], status)


def _field(key):
    from .core.parameters import FIELDS
    return next(field for field in FIELDS if field.key == key)


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/verify",
    vol.Required("collector_sha256"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_verify(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    try:
        result = await entry.runtime_data["service"].verify(msg["collector_sha256"],discover=True)
    except (ConnectionError, ValueError, TimeoutError) as err:
        connection.send_error(msg["id"], "unknown_error", str(err))
        return
    hass.loop.call_soon_threadsafe(async_dispatcher_send, hass, SIGNAL)
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/profile",
    vol.Required("action"): vol.In(["discover","select","cancel","recheck"]),
    vol.Optional("collector_sha256"): str,
    vol.Optional("device_id"): str,
    vol.Optional("fingerprint"): str,
    vol.Optional("acknowledged",default=False): bool,
    vol.Optional("resume",default=False): bool,
    vol.Optional("variant_id"): vol.In(["pi30","pi30_max"]),
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_profile(hass,connection,msg):
    import asyncio
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"],"not_found","bridge_not_loaded")
        return
    service=entry.runtime_data["service"]
    try:
        if msg["action"]=="discover":
            key=msg["collector_sha256"]
            holder=service.connections.get(key)
            if not service._connected(holder) or holder["lock"].locked():
                raise ValueError("collector_missing_or_busy")
            service.schedule_profile_search(key,resume=msg["resume"])
            result={"started":True}
        elif msg["action"]=="cancel":
            await service.cancel_profile_search(msg["collector_sha256"])
            result={"cancelled":True}
        elif msg["action"]=="recheck":
            result=await service.recheck_profile(msg["device_id"],msg.get("variant_id"))
        elif msg["action"]=="select":
            result=await service.select_profile(msg["collector_sha256"],msg["fingerprint"],msg["acknowledged"])
    except (KeyError,ValueError,ConnectionError,TimeoutError,StorageError) as error:
        connection.send_error(msg["id"],"profile_failed",str(error))
        return
    connection.send_result(msg["id"],result)


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/enroll",
    vol.Required("collector_sha256"): str,
    vol.Required("name"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_enroll(hass, connection, msg):
    name = msg["name"].strip()
    if not name or len(name) > 80:
        connection.send_error(msg["id"], "invalid_format", "invalid_name")
        return
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    try:
        device_id = await entry.runtime_data["service"].enroll(msg["collector_sha256"], name)
    except (ValueError, StorageError) as err:
        connection.send_error(msg["id"], "unknown_error", str(err))
        return
    connection.send_result(msg["id"], {"device_id": device_id})


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/set_clock_sync",
    vol.Required("device_id"): str,
    vol.Required("enabled"): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_clock_sync(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    try:
        await hass.async_add_executor_job(entry.runtime_data["storage"].set_clock_sync, msg["device_id"], msg["enabled"])
    except StorageError as err:
        connection.send_error(msg["id"], "storage_error", str(err))
        return
    connection.send_result(msg["id"], {"enabled": msg["enabled"]})
    entry.runtime_data["service"]._notify()


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/set_auto_reset",
    vol.Required("device_id"): str,
    vol.Required("enabled"): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_auto_reset(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    try:
        await hass.async_add_executor_job(entry.runtime_data["storage"].set_auto_reset, msg["device_id"], msg["enabled"])
    except StorageError as err:
        connection.send_error(msg["id"], "storage_error", str(err))
        return
    entry.runtime_data["service"]._notify()
    connection.send_result(msg["id"], {"enabled": msg["enabled"]})


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/apply",
    vol.Required("device_id"): str,
    vol.Required("key"): str,
    vol.Required("value"): vol.Any(str, int, float),
    vol.Required("operation_id"): OPERATION_ID,
    vol.Optional("expected_value"): vol.Any(str, int, float, None),
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_apply(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    operation_id = msg["operation_id"]
    try:
        baseline = {"expected_value": msg["expected_value"]} if "expected_value" in msg else {}
        user = await hass.auth.async_get_user(connection.user.id)
        result = await entry.runtime_data["service"].apply(
            msg["device_id"], msg["key"], msg["value"], operation_id,
            actor_name=user.name if user and user.name else "Administrator", **baseline)
    except (ConnectionError, ValueError, TimeoutError, StorageError) as err:
        if str(err) == "operation_id_conflict":
            connection.send_error(msg["id"], "operation_id_conflict", str(err))
            return
        record = await hass.async_add_executor_job(entry.runtime_data["storage"].operation, operation_id)
        if record is not None and record["device_id"] == msg["device_id"]:
            connection.send_result(msg["id"], operation_view(record))
        else:
            # Storage timeouts may still commit later. Never label those unsent.
            code = "request_rejected" if isinstance(err, ValueError) else "unknown_result"
            connection.send_error(msg["id"], code, str(err))
        return
    connection.send_result(msg["id"], operation_view(result))


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/get_operation",
    vol.Required("device_id"): str,
    vol.Required("operation_id"): OPERATION_ID,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_get_operation(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    record = await hass.async_add_executor_job(entry.runtime_data["storage"].operation, msg["operation_id"])
    if record is None or record["device_id"] != msg["device_id"]:
        connection.send_error(msg["id"], "not_found", "operation_not_found")
        return
    connection.send_result(msg["id"], operation_view(record))


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/configure_network",
    vol.Required("allowed_sources"): [str],
    vol.Optional("bootstrap_preference"): vol.In(["auto", "at", "binary"]),
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_configure_network(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    try:
        sources = normalize_sources(msg["allowed_sources"])
    except ValueError as error:
        connection.send_error(msg["id"], "invalid_format", str(error))
        return
    preference = msg.get("bootstrap_preference", entry.options.get("bootstrap_preference", "auto"))
    hass.config_entries.async_update_entry(entry, options={**entry.options, "allowed_sources": sources, "bootstrap_preference": preference})
    entry.runtime_data["service"].sources = tuple(sources)
    entry.runtime_data["service"].set_bootstrap_preference(preference)
    connection.send_result(msg["id"], {"allowed_sources": sources})


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/set_collection",
    vol.Required("device_id"): str,
    vol.Required("enabled"): bool,
    vol.Required("poll_interval"): vol.All(int, vol.Range(min=5, max=300)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_collection(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    try:
        await hass.async_add_executor_job(entry.runtime_data["storage"].set_collection,
                                         msg["device_id"], msg["enabled"], msg["poll_interval"])
    except (ValueError, StorageError) as error:
        connection.send_error(msg["id"], "invalid_format", str(error))
        return
    entry.runtime_data["service"].collection_enabled[msg["device_id"]] = msg["enabled"]
    entry.runtime_data["service"]._notify()
    connection.send_result(msg["id"], {"enabled": msg["enabled"], "poll_interval": msg["poll_interval"]})


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/accept_current_value",
    vol.Required("device_id"): str,
    vol.Required("operation_id"): OPERATION_ID,
    vol.Required("expected_value"): vol.Any(str, int, float),
    vol.Optional("expected_observed_at"): vol.Any(str, None),
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_accept_current_value(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    try:
        record = await entry.runtime_data["service"].accept_current_value(
            msg["device_id"], msg["operation_id"], msg["expected_value"], connection.user.id, msg.get("expected_observed_at"),
        )
    except (ValueError, StorageError, ConnectionError, TimeoutError) as error:
        connection.send_error(msg["id"], "resolution_failed", str(error))
        return
    connection.send_result(msg["id"], operation_view(record))


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/remove_device",
    vol.Required("device_id"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_remove_device(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    try:
        await entry.runtime_data["service"].remove_device(msg["device_id"])
        from .device_management import cleanup_removed_devices
        removed_ids = await hass.async_add_executor_job(entry.runtime_data["storage"].removed_device_ids)
        cleanup_removed_devices(hass, entry, removed_ids)
    except (ValueError, StorageError) as error:
        connection.send_error(msg["id"], "remove_failed", str(error))
        return
    connection.send_result(msg["id"], {"removed": True, "device_id": msg["device_id"]})


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/check_operation",
    vol.Required("device_id"): str,
    vol.Required("operation_id"): OPERATION_ID,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_check_operation(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    record = await hass.async_add_executor_job(entry.runtime_data["storage"].operation, msg["operation_id"])
    if record is None or record["device_id"] != msg["device_id"]:
        connection.send_error(msg["id"], "not_found", "operation_not_found")
        return
    if record["unresolved"]:
        try:
            await entry.runtime_data["service"].reconcile(msg["device_id"])
        except (ValueError, StorageError, ConnectionError, TimeoutError) as error:
            connection.send_error(msg["id"], "check_failed", str(error))
            return
        record = await hass.async_add_executor_job(entry.runtime_data["storage"].operation, msg["operation_id"])
    connection.send_result(msg["id"], operation_view(record))


@websocket_api.websocket_command({vol.Required("type"): "solar_inverter_bridge/diagnostics"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_diagnostics(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    from .diagnostics import async_get_config_entry_diagnostics
    connection.send_result(msg["id"], await async_get_config_entry_diagnostics(hass, entry))


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/journal",
    vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0)),
    vol.Optional("limit", default=200): vol.All(int, vol.Range(min=1, max=500)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_journal(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    try:
        page = await hass.async_add_executor_job(entry.runtime_data["storage"].journal_page, msg["offset"], msg["limit"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], page)


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/module_info",
    vol.Required("device_id"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_module_info(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    try:
        values = await entry.runtime_data["service"].read_module_info(msg["device_id"])
    except (ConnectionError, TimeoutError, ValueError, StorageError) as err:
        connection.send_error(msg["id"], "unknown_error", str(err))
        return
    connection.send_result(msg["id"], values)


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/reset_collector",
    vol.Required("device_id"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_reset_collector(hass, connection, msg):
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    try:
        result = await entry.runtime_data["service"].reset_collector(msg["device_id"])
    except (ConnectionError, TimeoutError, ValueError, StorageError) as err:
        connection.send_error(msg["id"], "unknown_error", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({
    vol.Required("type"): "solar_inverter_bridge/compatibility",
    vol.Required("action"): vol.In(["start", "stop", "status", "download"]),
    vol.Optional("metadata", default=dict): {str: str},
    vol.Optional("include_raw", default=False): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_compatibility(hass, connection, msg):
    import base64
    import platform
    from .core.compatibility import analyze, package_report
    from .diagnostics import artifact_metadata
    from homeassistant.const import __version__ as HA_VERSION
    entry = _runtime(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "bridge_not_loaded")
        return
    service = entry.runtime_data["service"]
    capture = service.compatibility
    try:
        action = msg["action"]
        if len(msg["metadata"]) > 10 or any(len(value) > 500 for value in msg["metadata"].values()):
            raise ValueError("compatibility_description_too_large")
        if action == "start":
            capture.start(msg["metadata"])
            service.schedule_compatibility_probe()
        elif action == "stop":
            capture.stop("user_cancelled")
        if action != "start":
            capture.metadata.update({key:value for key,value in msg["metadata"].items()
                if key in ("inverter_model","collector_model","firmware","original_endpoint","symptom","network_setup","reference_readings")})
        report = capture.snapshot(service.listeners, raw=msg["include_raw"], build=await hass.async_add_executor_job(artifact_metadata), context={
            "recorder_available": "recorder" in hass.config.components,
            "home_assistant_version": HA_VERSION, "python": platform.python_version(),
            "time_zone": hass.config.time_zone, "installation_method": "unknown"})
        if action == "download":
            from .diagnostics import async_get_config_entry_diagnostics
            diagnostic = await async_get_config_entry_diagnostics(hass, entry)
            report["context"].update({key: diagnostic[key] for key in ("devices", "recent_issues", "policy","profile_discovery")})
            data, analysis = await hass.async_add_executor_job(package_report, report)
            result = {"filename": f"compatibility-{report['report_id']}.zip",
                      "base64": base64.b64encode(data).decode(), "analysis": analysis}
        else:
            result = {**capture.view(), "analysis": analyze(report)}
    except (ValueError, OSError, StorageError) as error:
        connection.send_error(msg["id"], "compatibility_failed", str(error))
        return
    connection.send_result(msg["id"], result)
