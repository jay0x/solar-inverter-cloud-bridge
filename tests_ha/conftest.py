"""Real HA fixtures with isolated config and loopback-only ephemeral ports."""

import pytest


@pytest.fixture
def hass_config_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations, socket_enabled):
    pass


@pytest.fixture
def loopback_listeners(monkeypatch):
    from custom_components.solar_inverter_bridge.core.session import CollectorService
    start = CollectorService.start

    async def isolated(self, host=None, ports=None):
        return await start(self, host="127.0.0.1", ports=(0, 0, 0))

    monkeypatch.setattr(CollectorService, "start", isolated)
