"""Keep the bridge database consistent while Home Assistant copies config."""

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _storages(hass: HomeAssistant):
    return [
        entry.runtime_data["storage"]
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.runtime_data and entry.runtime_data.get("storage") is not None
    ]


async def async_pre_backup(hass: HomeAssistant) -> None:
    """Checkpoint and freeze writes before HA copies the database files."""
    locked = []
    try:
        for storage in _storages(hass):
            await hass.async_add_executor_job(storage.begin_backup)
            locked.append(storage)
    except Exception as err:
        _LOGGER.error("Bridge database could not be frozen for backup")
        for storage in reversed(locked):
            try:
                await hass.async_add_executor_job(storage.end_backup)
            except Exception:
                _LOGGER.exception("Could not release a bridge database freeze")
        raise HomeAssistantError("Bridge database could not be frozen for backup") from err


async def async_post_backup(hass: HomeAssistant) -> None:
    """Release the write freeze after HA finishes copying."""
    errors = 0
    for storage in _storages(hass):
        try:
            await hass.async_add_executor_job(storage.end_backup)
        except Exception:
            errors += 1
            _LOGGER.exception("Could not release a bridge database freeze")
    if errors:
        raise HomeAssistantError("Bridge database freeze could not be released")
