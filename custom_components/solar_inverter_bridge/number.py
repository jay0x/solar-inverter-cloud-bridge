"""Native numeric settings; values come only from inverter readback."""

from homeassistant.components.number import NumberEntity, NumberMode
from .control_entity import BridgeControl, setup_controls
from .core.parameters import FIELDS, execution_ready
from .core.drivers import fields_for

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_controls(hass, entry, async_add_entities, lambda item, device: (
        BridgeNumber(item, device, field) for field in fields_for(device["profile_id"]) if field.kind == "number" and execution_ready(field)))


class BridgeNumber(BridgeControl, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, entry, device, field):
        super().__init__(entry, device, field.key, field.name, field)
        self._attr_native_min_value, self._attr_native_max_value = field.bounds or (0, field.wire_max / field.divisor)
        self._attr_native_step = 1 / field.divisor
        self._attr_native_unit_of_measurement = field.unit

    @property
    def native_value(self):
        value = self.observed_value
        return 0 if self._field.zero_value and value == self._field.zero_value else value

    async def async_set_native_value(self, value):
        await self.write_value(self._field.zero_value if self._field.zero_value and value == 0 else value)
