"""Persistent opt-in maintenance features, shared with the panel."""

from homeassistant.components.switch import SwitchEntity
from .control_entity import BridgeControl, setup_controls

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_controls(hass, entry, async_add_entities, lambda item, device: (
        BridgeSwitch(item, device, key, name) for key, name in (
            ("clock_sync", "Automatic clock sync"), ("auto_reset", "Automatic Wi-Fi recovery"))))


class BridgeSwitch(BridgeControl, SwitchEntity):
    @property
    def is_on(self):
        return bool(self.observed_value)

    async def async_turn_on(self, **kwargs):
        await self.write_value(True)

    async def async_turn_off(self, **kwargs):
        await self.write_value(False)
