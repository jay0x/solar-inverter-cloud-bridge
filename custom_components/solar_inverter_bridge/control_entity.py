"""Native HA controls using the same durable executor as the panel."""

from types import SimpleNamespace
from time import monotonic
import uuid

from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity, EntityCategory

from .const import DOMAIN, NAME
from .core.parameters import execution_ready
from .core.storage import StorageError
from .services import _admin, _actor_name
from .websocket_api import SIGNAL


async def setup_controls(hass, entry, async_add_entities, factory):
    entities = {}

    async def sync():
        runtime = entry.runtime_data
        if runtime is None:
            return
        devices = await hass.async_add_executor_job(runtime["storage"].list_devices)
        if entry.runtime_data is not runtime:
            return
        active = {device["device_id"] for device in devices}
        for key in list(entities):
            if key not in active:
                entities.pop(key)
        fresh = []
        for device in devices:
            from .core.drivers import fields_for
            current_fields={field.key:field for field in fields_for(device["profile_id"])}
            identifier = device["device_id"]
            if identifier not in entities:
                entities[identifier] = list(factory(entry, device))
                fresh.extend(entities[identifier])
            for entity in entities[identifier]:
                entity._device = device
                if entity._field is not None and entity._key in current_fields:
                    entity._field=current_fields[entity._key]
                    if entity._field.options is not None:
                        entity._attr_options=list(entity._field.options.values())
                    if entity._field.kind=="number":
                        entity._attr_native_min_value,entity._attr_native_max_value=entity._field.bounds or (0,entity._field.wire_max/entity._field.divisor)
                        entity._attr_native_step=1/entity._field.divisor
                if entity.hass is not None and entity.entity_id is not None:
                    entity.async_write_ha_state()
        if fresh:
            async_add_entities(fresh)

    await sync()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL, sync))


class BridgeControl(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry, device, key, name, field=None):
        self._entry = entry
        self._device = device
        self._device_id = device["device_id"]
        self._key = key
        self._field = field
        self._last_operation = None
        self._attr_unique_id = f"{self._device_id}_setting_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._device_id)}, name=device["name"], manufacturer=NAME)

    @property
    def available(self):
        runtime = self._entry.runtime_data
        if runtime is None:
            return False
        if self._field is None:
            return True
        if not execution_ready(self._field):
            return False
        service = runtime["service"]
        if not service.transport_capabilities(self._device)["inverter_write"]:
            return False
        stamp = service._settings_observed.get(self._device_id)
        return (self._device["enabled"] and stamp is not None
                and monotonic() - stamp <= max(90, 5 * self._device["poll_interval"])
                and service._connected(service.connections.get(self._device["collector_sha256"]))
                and self.observed_value is not None)

    @property
    def observed_value(self):
        runtime = self._entry.runtime_data
        if runtime is None:
            return None
        if self._field is None:
            return self._device.get(self._key)
        return runtime["service"].settings.get(self._device_id, {}).get(self._key)

    @property
    def extra_state_attributes(self):
        attributes = {}
        runtime = self._entry.runtime_data
        if runtime is not None:
            attributes["transport_capabilities"] = runtime["service"].transport_capabilities(self._device)
        if self._field is not None:
            attributes["write_supported"] = (execution_ready(self._field)
                and runtime is not None and runtime["service"].transport_capabilities(self._device)["inverter_write"])
            if runtime is not None:
                holder=runtime["service"].connections.get(self._device["collector_sha256"])
                if holder and "reader" in holder:
                    choices=getattr(holder["reader"],"setting_choices",{}).get(str(self._field.address))
                    if choices is not None:
                        attributes["supported_values"]=[value/self._field.divisor for value in choices]
            if self._field.kind == "number" and self._field.bounds is None:
                attributes["limits_warning"] = "Manufacturer limits undocumented; displayed limits are register-format limits only."
            if self._field.zero_value:
                attributes["zero_means"] = self._field.zero_value
        if self._last_operation:
            attributes["last_operation_id"] = self._last_operation
        return attributes

    async def write_value(self, value):
        await _admin(self.hass, SimpleNamespace(context=self._context))
        runtime = self._entry.runtime_data
        if runtime is None:
            raise ServiceValidationError("bridge_not_loaded")
        try:
            if self._field is None:
                setter = {"clock_sync": "set_clock_sync", "auto_reset": "set_auto_reset"}[self._key]
                await self.hass.async_add_executor_job(getattr(runtime["storage"], setter), self._device_id, value)
                self._device = await self.hass.async_add_executor_job(runtime["storage"].device, self._device_id)
            else:
                baseline = self.observed_value
                if baseline is None:
                    raise ValueError("parameter_not_observed")
                self._last_operation = str(uuid.uuid4())
                result = await runtime["service"].apply(
                    self._device_id, self._key, value, self._last_operation,
                    expected_value=baseline, actor_name=await _actor_name(self.hass, self._context.user_id))
                if result.get("outcome") != "confirmed" or result.get("unresolved"):
                    raise ServiceValidationError(f"Change not confirmed; inspect Activity (operation {self._last_operation})")
        except (StorageError, ValueError, ConnectionError, TimeoutError) as error:
            raise ServiceValidationError(str(error)) from error
        finally:
            runtime["service"]._notify()
        self.async_write_ha_state()
