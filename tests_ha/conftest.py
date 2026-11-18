"""Real HA fixtures with isolated config and loopback-only ephemeral ports."""

import pytest


@pytest.fixture
def observed_settings_session():
    """Connected, owned session evidence without bypassing runtime freshness checks."""
    import asyncio
    from time import monotonic
    from types import SimpleNamespace
    from custom_components.solar_inverter_bridge.core.transport import AT_CAPABILITIES, BINARY_CAPABILITIES

    def create(service, device_id, collector, *, dialect="at", verified=True):
        holder = {"identity_sha256": collector, "device_id": device_id, "dialect": dialect,
                  "closed": asyncio.Event(), "lock": asyncio.Lock(), "profile_verified": verified,
                  "listener_port": 18899, "capabilities": AT_CAPABILITIES if dialect == "at" else BINARY_CAPABILITIES,
                  "writer": SimpleNamespace(is_closing=lambda: False, close=lambda: None),
                  "reader": SimpleNamespace(at_eof=lambda: False, setting_choices={}, route=(1, 1),
                                            slave=1, route_qualified=verified, counters={})}
        service.connections[collector] = holder
        service._settings_sessions[device_id] = holder
        service._settings_observed[device_id] = monotonic()
        service._next_poll[device_id] = float("inf")
        return holder

    return create


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
