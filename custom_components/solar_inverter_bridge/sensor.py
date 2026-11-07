"""Per-device telemetry. Missing data is unavailable, never zero."""

from time import monotonic

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import DOMAIN
from .core.catalogue import descriptors
from .websocket_api import SIGNAL
from .device_management import cleanup_removed_devices


PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    """Add one entity set for each saved inverter. A later enrollment adds the rest."""
    added = set()

    async def sync_devices():
        runtime = entry.runtime_data
        if runtime is None:
            return
        devices = await hass.async_add_executor_job(runtime["storage"].list_devices)
        removed_ids = await hass.async_add_executor_job(runtime["storage"].removed_device_ids)
        if entry.runtime_data is not runtime:
            return
        active_ids = {device["device_id"] for device in devices}
        cleanup_removed_devices(hass, entry, removed_ids)
        added.intersection_update({item for item in added if item[0] in active_ids})
        fresh = []
        for device in devices:
            entry.runtime_data["service"].collection_enabled[device["device_id"]] = device["enabled"]
            for descriptor in descriptors(device["profile_id"]):
                key=(device["device_id"],descriptor["key"])
                if key in added:continue
                added.add(key)
                fresh.append(BridgeSensor(entry,device,descriptor))
        if fresh:
            async_add_entities(fresh)

    await sync_devices()

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL, sync_devices))


class BridgeSensor(SensorEntity):
    """One observed measurement for one saved inverter."""

    def __init__(self, entry, device, descriptor):
        self._entry = entry
        self._device_id = device["device_id"]
        self._key = descriptor["key"]
        self._attr_unique_id = f"{device['device_id']}_{descriptor['key']}"
        self._attr_has_entity_name = True
        self._attr_name = descriptor["name"]
        self._attr_native_unit_of_measurement = descriptor["unit"]
        self._attr_device_class = SensorDeviceClass(descriptor["device_class"]) if descriptor["device_class"] else None
        self._attr_state_class = SensorStateClass(descriptor["state_class"]) if descriptor["state_class"] else None
        self._attr_options = descriptor["options"]
        self._attr_extra_state_attributes = descriptor.get("attributes")
        self._attr_entity_category = EntityCategory.DIAGNOSTIC if descriptor["key"].endswith("temperature") else None
        self._attr_should_poll = False
        self._attr_available = False
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device["device_id"])},
            name=device["name"],
            manufacturer="Solar Inverter Cloud Bridge",
        )

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL, self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self):
        if self._entry.runtime_data is None:
            return
        service = self._entry.runtime_data["service"]
        observation = service.observations.get(self._device_id)
        if not service.collection_enabled.get(self._device_id, True) or observation is None or not observation.available(monotonic()):
            self._attr_available = False
            self._attr_native_value = None
        else:
            self._attr_available = observation.values.get(self._key, {}).get("value") is not None
            self._attr_native_value = observation.values.get(self._key, {}).get("value")
        if self.hass is not None:
            self.async_write_ha_state()
