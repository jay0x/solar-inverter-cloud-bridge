"""Solar Inverter Cloud Bridge setup. HA imports stay inside setup functions."""

import asyncio
import logging
from pathlib import Path

from .const import DOMAIN, NAME, PORTS

_LOGGER = logging.getLogger(__name__)
try:
    import voluptuous as vol
    CONFIG_SCHEMA = vol.Schema({
        vol.Optional(DOMAIN): vol.Schema({
            vol.Optional("setup_local", default=False): bool,
            vol.Optional("allowed_sources", default=list): [str],
        })
    }, extra=vol.ALLOW_EXTRA)
except ImportError:
    CONFIG_SCHEMA = None


async def async_setup(hass, config):
    """Import one local entry when explicitly requested. This is not automatic discovery."""
    domain_config = config.get(DOMAIN) or {}
    from .websocket_api import async_register
    if not hass.data.get(DOMAIN, {}).get("websocket_registered"):
        async_register(hass)
        hass.data.setdefault(DOMAIN, {})["websocket_registered"] = True
    if domain_config.get("setup_local"):
        hass.data.setdefault(DOMAIN, {})["import_options"] = {
            "allowed_sources": list(domain_config.get("allowed_sources") or [])
        }
        hass.async_create_task(hass.config_entries.flow.async_init(DOMAIN, context={"source": "import"}))
    return True


async def async_setup_entry(hass, entry):
    """Start one local bridge. An offline collector does not fail setup."""
    if entry.title == "Solar Inverter Bridge":
        hass.config_entries.async_update_entry(entry, title=NAME)
    from homeassistant.config_entries import ConfigEntryNotReady
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform

    from functools import partial

    from .core.session import CollectorService
    from .core.storage import Storage

    path = Path(hass.config.path(DOMAIN))
    await hass.async_add_executor_job(partial(path.mkdir, parents=True, exist_ok=True))
    creation = hass.async_add_executor_job(Storage, path / "bridge.sqlite3")
    try:
        storage = await asyncio.shield(creation)
    except asyncio.CancelledError:
        storage = await creation
        await hass.async_add_executor_job(storage.close)
        raise
    from homeassistant.util import dt as dt_util
    service = CollectorService(
        entry.options.get("allowed_sources", []),
        storage,
        now=lambda: dt_util.now().replace(tzinfo=None, microsecond=0),
        bootstrap_preference=entry.options.get("bootstrap_preference", "auto"),
    )
    try:
        service.restore_issues(await hass.async_add_executor_job(storage.recent_diagnostics))
        await service.start(host="0.0.0.0", ports=PORTS)
        hass.data.setdefault(DOMAIN, {}).pop("failed_listeners", None)
    except OSError as err:
        hass.data.setdefault(DOMAIN, {})["failed_listeners"] = list(service.listeners)
        await service.close()
        await hass.async_add_executor_job(storage.close)
        raise ConfigEntryNotReady("collector_port_unavailable") from err
    except BaseException:
        await service.close()
        await hass.async_add_executor_job(storage.close)
        raise
    entry.runtime_data = {"storage": storage, "service": service}

    def _publish():
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        hass.loop.call_soon_threadsafe(async_dispatcher_send, hass, "solar_inverter_bridge_update")

    service.on_update = _publish

    async def update_options(hass, updated_entry):
        from .core.identity import normalize_sources
        if updated_entry.runtime_data is not None:
            updated_entry.runtime_data["service"].sources = tuple(normalize_sources(updated_entry.options.get("allowed_sources", [])))
            updated_entry.runtime_data["service"].set_bootstrap_preference(updated_entry.options.get("bootstrap_preference", "auto"))

    entry.async_on_unload(entry.add_update_listener(update_options))
    from .services import async_register as register_services
    from .websocket_api import async_register
    try:
        register_services(hass)
        if not hass.data.get(DOMAIN, {}).get("websocket_registered"):
            async_register(hass)
            hass.data.setdefault(DOMAIN, {})["websocket_registered"] = True
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR, Platform.NUMBER, Platform.SELECT, Platform.TIME, Platform.SWITCH])
        await _register_panel(hass)
    except BaseException:
        await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR, Platform.NUMBER, Platform.SELECT, Platform.TIME, Platform.SWITCH])
        service.on_update = None
        await service.close()
        await hass.async_add_executor_job(storage.close)
        entry.runtime_data = None
        raise

    async def stop(_event):
        await _close_runtime(hass, entry)

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    _LOGGER.info("%s listener state: %s", NAME, service.listeners)
    return True


async def _register_panel(hass):
    from homeassistant.components import panel_custom
    from homeassistant.components.http import StaticPathConfig

    from homeassistant.components import frontend

    panel_path = Path(__file__).parent / "frontend" / "panel.js"
    module_url = "/solar_inverter_bridge/panel.js?v=0.16.1"
    state = hass.data.setdefault(DOMAIN, {})
    if not state.get("static_registered"):
        await hass.http.async_register_static_paths([
            StaticPathConfig("/solar_inverter_bridge/panel.js", str(panel_path), False),
            StaticPathConfig("/solar_inverter_bridge/panel.css", str(panel_path.with_suffix(".css")), False),
            StaticPathConfig("/solar_inverter_bridge/routers.html", str(panel_path.parent / "routers.html"), False),
            StaticPathConfig("/solar_inverter_bridge/router-guide.js", str(panel_path.parent / "router-guide.js"), False),
            StaticPathConfig("/solar_inverter_bridge/collector-domains.json", str(panel_path.parent / "collector-domains.json"), False),
            StaticPathConfig("/solar_inverter_bridge/icon.png", str(panel_path.parent.parent / "brand/icon.png"), False),
            StaticPathConfig("/solar_inverter_bridge/icon@2x.png", str(panel_path.parent.parent / "brand/icon@2x.png"), False),
        ])
        state["static_registered"] = True
    key = "solar-inverter-bridge"
    if state.get("panel_url") != module_url:
        if state.get("panel_url"):
            frontend.async_remove_panel(hass, key)
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=key,
            webcomponent_name="solar-inverter-bridge-panel",
            sidebar_title="Inverters",
            sidebar_icon="mdi:solar-power",
            module_url=module_url,
            require_admin=True,
        )
        state["panel_url"] = module_url


async def _close_runtime(hass, entry):
    runtime = entry.runtime_data
    if runtime is None:
        return
    runtime["service"].on_update = None
    await runtime["service"].close()
    await hass.async_add_executor_job(runtime["storage"].close)
    entry.runtime_data = None


async def async_unload_entry(hass, entry):
    """Stop listeners before platform unload. Closing twice is safe."""
    from homeassistant.const import Platform
    from homeassistant.components import frontend

    if not await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR, Platform.NUMBER, Platform.SELECT, Platform.TIME, Platform.SWITCH]):
        return False
    await _close_runtime(hass, entry)
    state = hass.data.get(DOMAIN, {})
    if state.pop("panel_url", None):
        frontend.async_remove_panel(hass, "solar-inverter-bridge")
    return True


async def async_remove_config_entry_device(hass, config_entry, device_entry):
    """Apply the same pending-operation guard to removal from HA's device page."""
    from .device_management import bridge_device_id
    from .core.storage import StorageError
    from homeassistant.helpers import entity_registry as er
    identifier = bridge_device_id(device_entry)
    if identifier is None or config_entry.runtime_data is None:
        return False
    if any(entity.config_entry_id != config_entry.entry_id or entity.platform != DOMAIN
           for entity in er.async_entries_for_device(er.async_get(hass), device_entry.id, include_disabled_entities=True)):
        return False
    try:
        await config_entry.runtime_data["service"].remove_device(identifier)
    except (ValueError, StorageError):
        return False
    return True
