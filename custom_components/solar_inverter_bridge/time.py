"""Native time controls for documented schedule boundaries."""

from datetime import time
from homeassistant.components.time import TimeEntity
from .control_entity import BridgeControl, setup_controls
from .core.parameters import FIELDS, execution_ready
from .core.drivers import fields_for

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_controls(hass, entry, async_add_entities, lambda item, device: (
        BridgeTime(item, device, field.key, field.name, field) for field in fields_for(device["profile_id"]) if field.kind == "time" and execution_ready(field)))


class BridgeTime(BridgeControl, TimeEntity):
    @property
    def native_value(self):
        value = self.observed_value
        return time.fromisoformat(value) if value is not None else None

    async def async_set_value(self, value):
        await self.write_value(value.isoformat())
