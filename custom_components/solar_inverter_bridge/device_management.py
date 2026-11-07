"""Remove only bridge-owned registry entries after enrollment deletion."""

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN


def bridge_device_id(device):
    identifiers = [value for domain, value in device.identifiers if domain == DOMAIN]
    return identifiers[0] if len(identifiers) == 1 else None


@callback
def display_names(hass, entry):
    """User-facing names come from the device registry, never a second stored name."""
    registry = dr.async_get(hass)
    names = {}
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        identifier = bridge_device_id(device)
        if identifier is not None:
            names[identifier] = device.name_by_user or device.name
    return names


@callback
def native_device_ids(hass, entry):
    """Map bridge identities to this entry's actual HA registry device IDs."""
    registry = dr.async_get(hass)
    return {identifier: device.id
            for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
            if (identifier := bridge_device_id(device)) is not None}


@callback
def native_sensors(hass, entry, device_ids):
    """Read HA's actual entity IDs, names and states, including registry overrides."""
    registry = er.async_get(hass)
    result = {}
    for bridge_id, native_id in device_ids.items():
        sensors = []
        for entity in er.async_entries_for_device(registry, native_id, include_disabled_entities=True):
            if entity.config_entry_id != entry.entry_id or entity.platform != DOMAIN or entity.domain != "sensor":
                continue
            state = hass.states.get(entity.entity_id)
            sensors.append({
                "entity_id": entity.entity_id,
                "name": entity.name or entity.original_name or entity.entity_id,
                "state": state.state if state else "unavailable",
                "unit": state.attributes.get("unit_of_measurement") if state else None,
                "has_state": state is not None,
                "disabled": entity.disabled_by is not None,
            })
        result[bridge_id] = sorted(sensors, key=lambda sensor: (sensor["name"].casefold(), sensor["entity_id"]))
    return result


@callback
def cleanup_removed_devices(hass, entry, removed_ids):
    devices, entities = dr.async_get(hass), er.async_get(hass)
    for device in list(dr.async_entries_for_config_entry(devices, entry.entry_id)):
        identifier = bridge_device_id(device)
        # Missing data is not deletion intent: a missing/replaced DB must never
        # silently remove a user's registered devices and entities.
        if identifier is None or identifier not in removed_ids:
            continue
        for entity in list(er.async_entries_for_device(entities, device.id, include_disabled_entities=True)):
            if entity.config_entry_id == entry.entry_id and entity.platform == DOMAIN:
                entities.async_remove(entity.entity_id)
        # A user may have associated other integration entities with this device.
        # Leave those entries and their device association intact.
        if not er.async_entries_for_device(entities, device.id, include_disabled_entities=True):
            devices.async_remove_device(device.id)
