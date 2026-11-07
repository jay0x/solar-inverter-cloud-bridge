"""Native enumerated inverter settings; no separate control-mode selector."""

from homeassistant.components.select import SelectEntity
from homeassistant.helpers import entity_registry as er
from .control_entity import BridgeControl, setup_controls
from .core.parameters import FIELDS, execution_ready
from .core.drivers import fields_for

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.platform == "solar_inverter_bridge" and entity.unique_id.endswith("_setting_control_mode"):
            registry.async_remove(entity.entity_id)
    def factory(item, device):
        for field in fields_for(device["profile_id"]):
            if field.options is not None and execution_ready(field):
                yield BridgeSelect(item, device, field)
    await setup_controls(hass, entry, async_add_entities, factory)


class BridgeSelect(BridgeControl, SelectEntity):
    def __init__(self, entry, device, field):
        super().__init__(entry, device, field.key, field.name, field)
        self._attr_options = list(field.options.values())

    @property
    def current_option(self):
        value = self.observed_value
        return value if value in self.options else None

    async def async_select_option(self, option):
        await self.write_value(option)
