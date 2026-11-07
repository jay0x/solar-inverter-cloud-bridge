"""One local config entry. No endpoint or API key."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, NAME
from .core.identity import normalize_sources
from .network_hints import async_network_hints


class SolarInverterBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create the single local bridge."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SolarInverterBridgeOptionsFlow()

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        default = user_input.get("allowed_sources", "") if user_input is not None else (await async_network_hints(self.hass))["subnet"]
        if user_input is not None:
            try:
                sources = normalize_sources(user_input.get("allowed_sources", ""))
            except ValueError:
                errors["allowed_sources"] = "invalid_allowed_sources"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=NAME, data={}, options={"allowed_sources": sources})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({vol.Optional("allowed_sources", default=default): str}), errors=errors)

    async def async_step_import(self, user_input=None):
        """Create the single entry from an explicit local bootstrap."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        options = self.hass.data.get(DOMAIN, {}).get("import_options", {})
        return self.async_create_entry(
            title=NAME,
            data={},
            options={"allowed_sources": normalize_sources(options.get("allowed_sources") or [])},
        )


class SolarInverterBridgeOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                sources = normalize_sources(user_input.get("allowed_sources", ""))
            except ValueError:
                errors["allowed_sources"] = "invalid_allowed_sources"
            else:
                return self.async_create_entry(title="", data={"allowed_sources": sources,
                    "bootstrap_preference": user_input.get("bootstrap_preference", "auto")})
        default = ", ".join(self.config_entry.options.get("allowed_sources", []))
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Optional("allowed_sources", default=default): str,
            vol.Optional("bootstrap_preference", default=self.config_entry.options.get("bootstrap_preference", "auto")): vol.In(["auto", "at", "binary"]),
        }), errors=errors)
