"""HA 2026.10.4 lifecycle, actual states, config flow, and service authorization."""

import asyncio
from time import monotonic
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_inverter_bridge.core.observations import Observation
from custom_components.solar_inverter_bridge.core.telemetry import decode, required_addresses

DOMAIN = "solar_inverter_bridge"


@pytest.fixture
async def entry(hass, loopback_listeners):
    assert await async_setup_component(hass, "http", {})
    item = MockConfigEntry(domain=DOMAIN, title="Solar Inverter Bridge", data={},
                           options={"allowed_sources": ["127.0.0.1/32"]})
    item.add_to_hass(hass)
    assert await hass.config_entries.async_setup(item.entry_id)
    await hass.async_block_till_done()
    assert item.title == "Solar Inverter Cloud Bridge"
    return item


async def test_brand_rename_preserves_custom_config_entry_title(hass,entry):
    hass.config_entries.async_update_entry(entry,title="My inverter collection")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.title=="My inverter collection"
    assert entry.domain==DOMAIN


async def test_native_controls_share_executor_and_never_set_optimistic_values(hass, entry, hass_admin_user, monkeypatch):
    from unittest.mock import ANY
    from homeassistant.helpers import entity_registry as er
    runtime = entry.runtime_data
    storage, service = runtime["storage"], runtime["service"]
    identifier = await hass.async_add_executor_job(storage.enroll, "native-control", "Native", "modbus_protocol_4")
    await hass.async_add_executor_job(storage.set_mode, identifier, "advanced")
    service.settings[identifier] = {"primary_output_priority": "sub", "maximum_charging_current": 12.4,
                                    "secondary_charging_start": "07:00:00", "battery_recovery_voltage_ac": "full_recovery"}
    service._settings_observed[identifier] = monotonic()
    monkeypatch.setattr(service, "_connected", lambda holder: True)
    monkeypatch.setattr(service, "transport_capabilities", lambda device: {"inverter_write": True})
    service._notify()
    await hass.async_block_till_done()
    entities = er.async_get(hass)
    def entity_id(domain, key):
        return entities.async_get_entity_id(domain, DOMAIN, f"{identifier}_setting_{key}")
    assert entity_id("select", "current_output_priority") is None
    assert entity_id("select", "current_charging_priority") is None
    assert hass.states.get(entity_id("number", "battery_recovery_voltage_ac")).state == "0"
    number_id = entity_id("number", "maximum_charging_current")
    assert hass.states.get(number_id).attributes["step"] == 0.1
    assert "limits_warning" in hass.states.get(number_id).attributes
    admin = Context(user_id=hass_admin_user.id)
    apply = AsyncMock(return_value={"outcome": "confirmed", "unresolved": False})
    monkeypatch.setattr(service, "apply", apply)
    cases = [("number", "set_value", "maximum_charging_current", "value", 12.5, 12.4),
             ("select", "select_option", "primary_output_priority", "option", "sbu", "sub"),
             ("time", "set_value", "secondary_charging_start", "time", "08:00:00", "07:00:00"),
             ("number", "set_value", "battery_recovery_voltage_ac", "value", 0, "full_recovery")]
    for domain, action, key, value_key, value, baseline in cases:
        await hass.services.async_call(domain, action, {"entity_id": entity_id(domain, key), value_key: value}, blocking=True, context=admin)
        expected = "full_recovery" if key == "battery_recovery_voltage_ac" else value
        apply.assert_awaited_with(identifier, key, expected, ANY, expected_value=baseline, actor_name=hass_admin_user.name)
    assert len({call.args[3] for call in apply.await_args_list}) == 4
    assert hass.states.get(number_id).state == "12.4"
    apply.return_value = {"outcome": "uncertain", "unresolved": True}
    with pytest.raises(ServiceValidationError, match="Change not confirmed"):
        await hass.services.async_call("number", "set_value", {"entity_id": number_id, "value": 12.5}, blocking=True, context=admin)
    assert hass.states.get(number_id).state == "12.4"
    service._settings_observed[identifier] -= 1000
    service._notify()
    await hass.async_block_till_done()
    assert hass.states.get(number_id).state == "unavailable"


async def test_binary_capabilities_override_saved_advanced_mode_in_native_entities(hass, entry, monkeypatch):
    import asyncio
    from homeassistant.helpers import entity_registry as er
    from custom_components.solar_inverter_bridge.core.transport import BINARY_CAPABILITIES
    storage, service = entry.runtime_data["storage"], entry.runtime_data["service"]
    identifier = await hass.async_add_executor_job(storage.enroll, "binary-policy", "Binary", "modbus_protocol_4")
    await hass.async_add_executor_job(storage.set_mode, identifier, "advanced")
    service.connections["binary-policy"] = {"capabilities": BINARY_CAPABILITIES, "closed": asyncio.Event(), "lock":asyncio.Lock()}
    service.settings[identifier] = {"primary_output_priority": "sub"}
    service._settings_observed[identifier] = monotonic()
    monkeypatch.setattr(service, "_connected", lambda holder: True)
    service._notify()
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    priority = registry.async_get_entity_id("select", DOMAIN, f"{identifier}_setting_primary_output_priority")
    assert hass.states.get(priority).state == "unavailable"
    assert not service.transport_capabilities(await hass.async_add_executor_job(storage.device, identifier))["inverter_write"]
    assert (await hass.async_add_executor_job(storage.device, identifier))["control_mode"] == "full"
    with pytest.raises(ValueError, match="transport_write_unsupported"):
        await service.apply(identifier, "primary_output_priority", "sbu", "binary-blocked")
    with pytest.raises(ValueError, match="transport_reset_unsupported"):
        await service.reset_collector(identifier)
    assert service.transmitted == 0


async def test_compatibility_workflow_before_enrollment_is_admin_only(hass, entry, hass_ws_client, hass_read_only_access_token):
    import base64
    from custom_components.solar_inverter_bridge.core.compatibility import validate_package, replay
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": DOMAIN + "/compatibility", "action": "start", "metadata": {"inverter_model": "Unknown model"}})
    started = (await client.receive_json())["result"]
    assert started["active"] and started["report_id"]
    service = entry.runtime_data["service"]
    service.compatibility.emit("wire", session="unidentified", direction="rx", data=b"PRIVATE-PN")
    for include_raw in (False, True):
        await client.send_json_auto_id({"type": DOMAIN + "/compatibility", "action": "download", "include_raw": include_raw})
        response = await client.receive_json()
        assert response["success"]
        report = validate_package(base64.b64decode(response["result"]["base64"]))
        assert report["raw_protocol_included"] is include_raw
        assert report["build"]["sha256"]
        assert replay(report)["analysis"]["coverage"]["full_identity"] == "missing"
        assert "wire_hex" in str(report) if include_raw else "wire_hex" not in str(report)
    await client.send_json_auto_id({"type": DOMAIN + "/compatibility", "action": "stop"})
    assert not (await client.receive_json())["result"]["active"]
    reader = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await reader.send_json_auto_id({"type": DOMAIN + "/compatibility", "action": "start"})
    assert not (await reader.receive_json())["success"]


async def test_inferred_profile_has_its_own_entities_inventory_and_explicit_control_permission(hass,entry,hass_ws_client,hass_read_only_access_token):
    from homeassistant.helpers import entity_registry as er
    from custom_components.solar_inverter_bridge.core.drivers import fields_for
    storage,service=entry.runtime_data["storage"],entry.runtime_data["service"]
    identifier=await hass.async_add_executor_job(storage.enroll,"inferred-pn","Inferred","pi30")
    record={"profile_id":"pi30","fingerprint":"f"*64,"binding":{"transport":"at","slave":0,"route":[],"signature":["pi30",17],"profile_revision":1,"profile_id":"pi30"},"allow_control":False,"warning_version":1}
    await hass.async_add_executor_job(storage.accept_profile,identifier,record)
    service._notify()
    await hass.async_block_till_done()
    registry=er.async_get(hass)
    managed=[e for e in registry.entities.values() if e.unique_id.startswith(identifier+"_")]
    assert sum(e.domain=="sensor" for e in managed)==17
    assert sum(e.domain=="select" for e in managed)==13
    assert sum(e.domain=="number" for e in managed)==7
    assert not any(e.domain=="time" for e in managed)
    client=await hass_ws_client(hass)
    await client.send_json_auto_id({"type":DOMAIN+"/status"})
    state=(await client.receive_json())["result"]
    device=next(d for d in state["devices"] if d["device_id"]==identifier)
    assert {p["key"] for p in device["parameters"]}=={f.key for f in fields_for("pi30")}
    assert len(state["profile_catalogue"])==24
    assert not any(p["profile_id"]=="modbus_protocol_4" for p in state["profile_catalogue"])
    permission={"type":DOMAIN+"/profile","action":"control","device_id":identifier,"fingerprint":"f"*64,"allow_control":True}
    await client.send_json_auto_id(permission)
    assert not (await client.receive_json())["success"]
    await client.send_json_auto_id({**permission,"acknowledged":True})
    assert not (await client.receive_json())["success"]
    assert (await hass.async_add_executor_job(storage.profile_acceptance,identifier))["allow_control"]
    assert service.transmitted==0
    reader=await hass_ws_client(hass,access_token=hass_read_only_access_token)
    await reader.send_json_auto_id({**permission,"acknowledged":True})
    assert not (await reader.receive_json())["success"]


async def test_pi18_supported_values_use_engineering_units(hass,entry,monkeypatch):
    from types import SimpleNamespace
    from homeassistant.helpers import entity_registry as er
    storage,service=entry.runtime_data["storage"],entry.runtime_data["service"]
    identifier=await hass.async_add_executor_job(storage.enroll,"pi18-choices","Choices","pi18")
    service.connections["pi18-choices"]={"reader":SimpleNamespace(setting_choices={"9110":[440,450,460]}),"closed":asyncio.Event()}
    service.settings[identifier]={"battery_recovery_voltage_ac":46}
    service._settings_observed[identifier]=monotonic()
    monkeypatch.setattr(service,"_connected",lambda holder:True)
    monkeypatch.setattr(service,"transport_capabilities",lambda device:{"inverter_write":True})
    service._notify();await hass.async_block_till_done()
    entity_id=er.async_get(hass).async_get_entity_id("number",DOMAIN,f"{identifier}_setting_battery_recovery_voltage_ac")
    assert hass.states.get(entity_id).attributes["supported_values"]==[44,45,46]
    service.connections.clear()


async def test_pi30_variant_renewal_preserves_registry_and_refreshes_capabilities(hass,entry):
    from functools import partial
    from homeassistant.helpers import entity_registry as er
    storage,service=entry.runtime_data["storage"],entry.runtime_data["service"]
    identifier=await hass.async_add_executor_job(storage.enroll,"variant","Variant","pi30")
    service._notify();await hass.async_block_till_done()
    registry=er.async_get(hass)
    before={e.unique_id:e.entity_id for e in registry.entities.values() if e.unique_id.startswith(identifier+"_")}
    battery=registry.async_get_entity_id("select",DOMAIN,f"{identifier}_setting_pi30_battery_type")
    assert "pylontech" not in hass.states.get(battery).attributes["options"]
    record={"profile_id":"pi30_max","fingerprint":"f"*64,"binding":{"profile_id":"pi30_max","transport":"at"}}
    await hass.async_add_executor_job(partial(storage.accept_profile,identifier,record,previous_profile_id="pi30"))
    service._notify();await hass.async_block_till_done()
    after={e.unique_id:e.entity_id for e in registry.entities.values() if e.unique_id.startswith(identifier+"_")}
    assert before.items()<=after.items()
    assert "pylontech" in hass.states.get(battery).attributes["options"]
    assert registry.async_get_entity_id("sensor",DOMAIN,f"{identifier}_pv_energy_total")
    assert (await hass.async_add_executor_job(storage.device,identifier))["profile_id"]=="pi30_max"
    assert service.transmitted==0


async def test_native_control_permissions_and_recovery_preference_persist(hass, entry, hass_admin_user, hass_read_only_user, monkeypatch):
    from homeassistant.helpers import entity_registry as er
    storage, service = entry.runtime_data["storage"], entry.runtime_data["service"]
    identifier = await hass.async_add_executor_job(storage.enroll, "native-policy", "Policy", "modbus_protocol_4")
    service.settings[identifier] = {"primary_output_priority": "sub"}
    service._settings_observed[identifier] = monotonic()
    monkeypatch.setattr(service, "_connected", lambda holder: True)
    monkeypatch.setattr(service, "transport_capabilities", lambda device: {"inverter_write": True})
    service._notify()
    await hass.async_block_till_done()
    entities = er.async_get(hass)
    recovery = entities.async_get_entity_id("switch", DOMAIN, f"{identifier}_setting_auto_reset")
    priority = entities.async_get_entity_id("select", DOMAIN, f"{identifier}_setting_primary_output_priority")
    assert hass.states.get(recovery).state == "off"
    assert hass.states.get(priority).state == "sub"
    for context in (Context(), Context(user_id=hass_read_only_user.id)):
        with pytest.raises(Unauthorized):
            await hass.services.async_call("switch", "turn_on", {"entity_id": recovery}, blocking=True, context=context)
    admin = Context(user_id=hass_admin_user.id)
    assert entities.async_get_entity_id("select", DOMAIN, f"{identifier}_setting_control_mode") is None
    await hass.services.async_call("switch", "turn_on", {"entity_id": recovery}, blocking=True, context=admin)
    assert (await hass.async_add_executor_job(storage.device, identifier))["auto_reset"]
    assert service.transmitted == 0
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(recovery).state == "on"
    assert (await hass.async_add_executor_job(entry.runtime_data["storage"].device, identifier))["control_mode"] == "full"


async def test_native_controls_default_full_and_legacy_selector_is_retired(hass, entry, hass_admin_user, hass_ws_client, monkeypatch):
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers.entity import EntityCategory
    runtime = entry.runtime_data
    storage, service = runtime["storage"], runtime["service"]
    identifier = await hass.async_add_executor_job(storage.enroll, "mode-visibility", "Modes", "modbus_protocol_4")
    service.settings[identifier] = {"primary_output_priority": "sub", "maximum_charging_current": 12.4, "secondary_charging_start": "07:00:00"}
    service._settings_observed[identifier] = monotonic()
    monkeypatch.setattr(service, "_connected", lambda holder: True)
    monkeypatch.setattr(service, "transport_capabilities", lambda device: {"inverter_write": True})
    service._notify()
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    def entity_id(domain, key):
        return registry.async_get_entity_id(domain, DOMAIN, f"{identifier}_setting_{key}")
    priority = entity_id("select", "primary_output_priority")
    current = entity_id("number", "maximum_charging_current")
    schedule = entity_id("time", "secondary_charging_start")
    mode = entity_id("select", "control_mode")
    assert mode is None
    admin = Context(user_id=hass_admin_user.id)
    for key, domain in [("clock_sync", "switch"), ("auto_reset", "switch")]:
        assert registry.async_get(entity_id(domain, key)).entity_category == EntityCategory.CONFIG
        assert hass.states.get(entity_id(domain, key)).state != "unavailable"
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": DOMAIN + "/set_mode", "device_id": identifier, "mode": "control"})
    assert not (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert hass.states.get(priority).state == "sub"
    assert hass.states.get(schedule).state == "07:00:00"
    assert hass.states.get(current).state == "12.4"
    obsolete = registry.async_get_or_create("select", DOMAIN, f"{identifier}_setting_control_mode", config_entry=entry)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(obsolete.entity_id) is None
    assert entity_id("select", "primary_output_priority") == priority
    assert entity_id("number", "maximum_charging_current") == current
    assert entity_id("time", "secondary_charging_start") == schedule
    assert not hass.services.has_service(DOMAIN, "set_mode")
    assert service.transmitted == 0


async def test_one_hundred_reload_cycles_release_workers_and_listeners(hass, entry):
    for _ in range(100):
        previous = entry.runtime_data
        service = previous["service"]
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert not previous["storage"].thread.is_alive()
        assert service.servers == []
        assert all(task.done() for task in service.tasks)
        assert entry.state is ConfigEntryState.LOADED
        assert len(entry.runtime_data["service"].servers) == 3
    assert hass.services.has_service(DOMAIN, "get_operation")


async def test_actual_ha_state_expires_without_next_poll(hass, entry):
    runtime = entry.runtime_data
    device = await hass.async_add_executor_job(runtime["storage"].enroll, "a" * 64, "Unit", "modbus_protocol_4")
    values = decode({address: 0 for address in required_addresses()} | {201: 2, 277: 480, 280: 55, 302: 1234})
    runtime["service"].observations[device] = Observation(values, monotonic())
    runtime["service"]._notify()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.unit_pv_power")
    assert state is not None and state.state == "1234"
    assert state.attributes["device_class"] == "power"
    assert state.attributes["state_class"] == "measurement"
    energy = hass.states.get("sensor.unit_pv_energy_total")
    assert energy.attributes["device_class"] == "energy"
    assert energy.attributes["state_class"] == "total_increasing"
    runtime["service"].observations[device].observed_monotonic -= 61
    runtime["service"]._expire_observations()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.unit_pv_power").state == "unavailable"


async def test_real_service_context_authorization_and_read_only_result(hass, entry, hass_admin_user, hass_read_only_user):
    storage = entry.runtime_data["storage"]
    device = await hass.async_add_executor_job(storage.enroll, "a" * 64, "Unit", "modbus_protocol_4")
    payload = {"device_id": device, "enabled": True}
    for context in (Context(), Context(user_id=hass_read_only_user.id)):
        with pytest.raises(Unauthorized):
            await hass.services.async_call(DOMAIN, "set_clock_sync", payload, blocking=True, context=context)
    admin = Context(user_id=hass_admin_user.id)
    await hass.services.async_call(DOMAIN, "set_clock_sync", payload, blocking=True, context=admin)
    assert (await hass.async_add_executor_job(storage.device, device))["clock_sync"]
    with pytest.raises(ServiceValidationError, match="device_or_parameter_missing"):
        await hass.services.async_call(DOMAIN, "apply_parameter", {
            "device_id": device, "operation_id": "invalid-field", "key": "unknown", "value": 0,
        }, blocking=True, context=admin, return_response=True)
    assert await hass.async_add_executor_job(storage.operation, "invalid-field") is None
    with pytest.raises(ServiceValidationError, match="operation_not_found"):
        await hass.services.async_call(DOMAIN, "get_operation", {
            "device_id": device, "operation_id": "invalid-field",
        }, blocking=True, context=admin, return_response=True)


async def test_config_flow_validates_network_without_yaml(hass, loopback_listeners, monkeypatch):
    from homeassistant.components import network
    monkeypatch.setattr(network, "async_get_adapters", AsyncMock(return_value=[
        {"enabled": True, "default": True, "ipv4": [{"address": "192.168.10.77", "network_prefix": 23}]},
    ]))
    assert await async_setup_component(hass, "http", {})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"]({})["allowed_sources"] == "192.168.10.0/23"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"allowed_sources": "0.0.0.0/0"})
    assert result["errors"] == {"allowed_sources": "invalid_allowed_sources"}
    assert result["data_schema"]({})["allowed_sources"] == "0.0.0.0/0"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"allowed_sources": "192.168.10.1"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["allowed_sources"] == ["192.168.10.1/32"]
    await hass.async_block_till_done()


async def test_config_flow_does_not_guess_ambiguous_subnet_and_allows_clearing(hass, loopback_listeners, monkeypatch):
    from homeassistant.components import network
    monkeypatch.setattr(network, "async_get_adapters", AsyncMock(return_value=[
        {"enabled": True, "ipv4": [{"address": "10.1.2.3", "network_prefix": 24}]},
        {"enabled": True, "ipv4": [{"address": "192.168.10.77", "network_prefix": 24}]},
    ]))
    assert await async_setup_component(hass, "http", {})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["data_schema"]({})["allowed_sources"] == ""
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"allowed_sources": ""})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["allowed_sources"] == []
    await hass.async_block_till_done()


async def test_options_update_network_without_restarting_listeners(hass, entry):
    service = entry.runtime_data["service"]
    servers = list(service.servers)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"allowed_sources": "192.168.20.1"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert service.sources == ("192.168.20.1/32",)
    assert service.servers == servers


async def test_websocket_readonly_user_cannot_use_admin_commands(hass, entry, hass_ws_client, hass_read_only_access_token):
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    commands = [
        {"type": DOMAIN + "/status"},
        {"type": DOMAIN + "/network_hints"},
        {"type": DOMAIN + "/configure_network", "allowed_sources": []},
        {"type": DOMAIN + "/set_clock_sync", "device_id": "missing", "enabled": True},
        {"type": DOMAIN + "/apply", "device_id": "missing", "key": "primary_output_priority", "value": "sbu", "operation_id": "no-send"},
        {"type": DOMAIN + "/get_operation", "device_id": "missing", "operation_id": "no-send"},
        {"type": DOMAIN + "/accept_current_value", "device_id": "missing", "operation_id": "no-send", "expected_value": "sub"},
        {"type": DOMAIN + "/remove_device", "device_id": "missing"},
        {"type": DOMAIN + "/check_operation", "device_id": "missing", "operation_id": "no-send"},
        {"type": DOMAIN + "/diagnostics"},
    ]
    for command in commands:
        await client.send_json_auto_id(command)
        response = await client.receive_json()
        assert response["success"] is False
        assert response["error"]["code"] == "unauthorized"
    assert entry.runtime_data["service"].transmitted == 0


async def test_network_hints_are_read_only_and_do_not_guess_gateway(hass, entry, hass_ws_client, monkeypatch):
    from homeassistant.components import network
    monkeypatch.setattr(network, "async_get_adapters", AsyncMock(return_value=[
        {"enabled": True, "default": True, "ipv4": [{"address": "192.168.10.77", "network_prefix": 23}]},
    ]))
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": DOMAIN + "/network_hints"})
    response = await client.receive_json()
    assert response["success"]
    assert response["result"]["ha_ip"] == "192.168.10.77"
    assert response["result"]["subnet"] == "192.168.10.0/23"
    assert response["result"]["router_ip"] == ""
    assert entry.runtime_data["service"].transmitted == 0


async def test_websocket_validation_errors_do_not_create_commands(hass, entry, hass_ws_client):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": DOMAIN + "/set_clock_sync", "device_id": "missing", "enabled": True})
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["message"] == "device_missing"
    await client.send_json_auto_id({"type": DOMAIN + "/apply", "device_id": "missing", "key": "no-such-field", "value": 0, "operation_id": "no-send"})
    response = await client.receive_json()
    assert response["error"]["code"] == "request_rejected"
    assert await hass.async_add_executor_job(entry.runtime_data["storage"].operation, "no-send") is None
    await client.send_json_auto_id({"type": DOMAIN + "/configure_network", "allowed_sources": ["0.0.0.0/0"]})
    response = await client.receive_json()
    assert response["success"] is False
    assert entry.options["allowed_sources"] == ["127.0.0.1/32"]


async def test_websocket_forwards_decimal_value_and_baseline(hass, entry, hass_ws_client, monkeypatch, hass_admin_user):
    apply = AsyncMock(return_value={"operation_id": "decimal", "device_id": "device-a", "state": "completed", "outcome": "confirmed"})
    monkeypatch.setattr(entry.runtime_data["service"], "apply", apply)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": DOMAIN + "/apply", "device_id": "device-a", "key": "maximum_charging_current",
                                    "value": 12.5, "expected_value": 12.4, "operation_id": "decimal"})
    response = await client.receive_json()
    assert response["success"] is True
    apply.assert_awaited_once_with("device-a", "maximum_charging_current", 12.5, "decimal", expected_value=12.4, actor_name=hass_admin_user.name)


async def test_refused_platform_unload_keeps_runtime_usable(hass, entry, monkeypatch):
    from custom_components.solar_inverter_bridge import async_unload_entry
    runtime = entry.runtime_data
    with monkeypatch.context() as patcher:
        patcher.setattr(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=False))
        assert not await async_unload_entry(hass, entry)
    assert entry.runtime_data is runtime
    assert runtime["storage"].thread.is_alive()
    assert len(runtime["service"].servers) == 3


async def test_cancelled_setup_closes_storage_worker(hass, monkeypatch):
    from custom_components.solar_inverter_bridge import async_setup_entry
    from custom_components.solar_inverter_bridge.core import session, storage
    created = []
    real_storage = storage.Storage

    def tracked(*args, **kwargs):
        result = real_storage(*args, **kwargs)
        created.append(result)
        return result

    monkeypatch.setattr(storage, "Storage", tracked)
    monkeypatch.setattr(session.CollectorService, "start", AsyncMock(side_effect=asyncio.CancelledError))
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    with pytest.raises(asyncio.CancelledError):
        await async_setup_entry(hass, entry)
    assert len(created) == 1
    assert not created[0].thread.is_alive()


async def test_remove_device_cleans_its_ha_entities_and_registry(hass, entry, hass_ws_client):
    from homeassistant.helpers import device_registry as dr, entity_registry as er
    runtime = entry.runtime_data
    identifier = await hass.async_add_executor_job(runtime["storage"].enroll, "collector-remove", "Removable", "modbus_protocol_4")
    runtime["service"]._notify()
    await hass.async_block_till_done()
    devices = dr.async_get(hass)
    device = devices.async_get_device_by_identifier((DOMAIN, identifier), entry.entry_id)
    assert device is not None
    assert hass.states.get("sensor.removable_pv_power") is not None
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": DOMAIN + "/remove_device", "device_id": identifier})
    result = await client.receive_json()
    assert result["success"] and result["result"]["removed"]
    await hass.async_block_till_done()
    assert devices.async_get_device_by_identifier((DOMAIN, identifier), entry.entry_id) is None
    assert er.async_get(hass).async_get("sensor.removable_pv_power") is None
    assert hass.states.get("sensor.removable_pv_power") is None
    assert await hass.async_add_executor_job(runtime["storage"].device, identifier) is None
    assert runtime["service"].transmitted == 0


async def test_missing_enrollment_does_not_imply_registry_deletion(hass, entry):
    from homeassistant.helpers import device_registry as dr, entity_registry as er
    devices, entities = dr.async_get(hass), er.async_get(hass)
    device = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, "unknown-existing-device")}, name="Existing")
    entity = entities.async_get_or_create("sensor", DOMAIN, "existing-entity", config_entry=entry, device_id=device.id)
    entry.runtime_data["service"]._notify()
    await hass.async_block_till_done()
    assert devices.async_get(device.id) is not None
    assert entities.async_get(entity.entity_id) is not None


async def test_diagnostics_contains_real_context_and_redacts_identifiers(hass, entry):
    import json
    from types import SimpleNamespace
    from custom_components.solar_inverter_bridge.diagnostics import async_get_config_entry_diagnostics
    from custom_components.solar_inverter_bridge.core.framing import FrameError
    runtime = entry.runtime_data
    service = runtime["service"]
    identifier = await hass.async_add_executor_job(runtime["storage"].enroll, "private-collector", "Private house name", "modbus_protocol_4")
    service.observations[identifier] = Observation(decode({address: 0 for address in required_addresses()} | {201: 2, 277: 480, 280: 55, 302: 1234}), monotonic())
    service.settings[identifier] = {"primary_output_priority": "sbu", "battery_protection_soc_ac": 20}
    service.settings_registers[identifier] = {601: 2, 647: 20}
    service._settings_observed[identifier] = monotonic()
    service._channels["private-collector"] = [{"source": "192.168.99.123", "primary": True, "listener_port": 18899,
        "identity_sha256": "private-collector", "writer": SimpleNamespace(is_closing=lambda: False)}]
    service._notify()
    await hass.async_block_till_done()
    error = FrameError("crc_mismatch")
    error.register_address, error.register_count, error.function = 630, 26, 3
    await service.record_issue(error, identifier, "settings_read")
    await service.record_issue(ValueError("secret_token=do-not-export-this"), identifier, "command")
    captured_at = service.last_error_at
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["schema"] == 2
    assert len(report["parameter_inventory"]) == 51
    assert report["devices"][0]["parameters"]["values"]["primary_output_priority"] == "sbu"
    assert report["devices"][0]["parameters"]["raw_register_values"]["primary_output_priority"] == [2]
    assert report["devices"][0]["telemetry"]["values"]["pv_power"]["value"] == 1234
    assert report["devices"][0]["ha_sensors"]["pv_power"]["state"] == "1234"
    assert report["recent_issues"][0]["register_address"] == 630
    assert report["recent_issues"][0]["register_count"] == 26
    assert report["recent_issues"][0]["occurred_at"]
    assert report["artifact"]["sha256"]
    encoded = json.dumps(report)
    for private in (identifier, "private-collector", "Private house name", "192.168.99.123", "do-not-export-this"):
        assert private not in encoded
    assert service.transmitted == 0
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert entry.runtime_data["service"].last_error_at == captured_at
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["recent_issues"][-1]["previous_session"] is True


async def test_registry_name_overrides_the_enrollment_name(hass, entry, hass_ws_client):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    storage = entry.runtime_data["storage"]
    device_id = await hass.async_add_executor_job(storage.enroll, "c" * 64, "Suggested", "modbus_protocol_4")
    entry.runtime_data["service"]._notify()
    await hass.async_block_till_done()
    registry = dr.async_get(hass)
    registered = registry.async_get_device_by_identifier((DOMAIN, device_id), entry.entry_id)
    assert registered.name == "Suggested"
    registry.async_update_device(registered.id, name_by_user="Renamed by HA")
    entities = er.async_get(hass)
    sensor_id = entities.async_get_entity_id("sensor", DOMAIN, f"{device_id}_pv_power")
    entities.async_update_entity(sensor_id, new_entity_id="sensor.renamed_roof_pv", name="Roof PV")
    await hass.async_block_till_done()
    hass.states.async_set("sensor.renamed_roof_pv", "123.4", {"unit_of_measurement": "W"})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": DOMAIN + "/status"})
    response = await client.receive_json()
    shown = next(item for item in response["result"]["devices"] if item["device_id"] == device_id)
    assert shown["name"] == "Renamed by HA"
    assert shown["ha_device_id"] == registered.id
    assert shown["ha_device_id"] != device_id
    assert len(shown["ha_sensors"]) == 35
    sensor = next(item for item in shown["ha_sensors"] if item["entity_id"] == "sensor.renamed_roof_pv")
    assert sensor == {"entity_id": "sensor.renamed_roof_pv", "name": "Roof PV", "state": "123.4", "unit": "W", "has_state": True, "disabled": False}
    assert sensor_id not in {item["entity_id"] for item in shown["ha_sensors"]}
    assert response["result"]["recorder_available"] == ("recorder" in hass.config.components)
    assert shown["suggested_name"] == "Suggested"
    assert (await hass.async_add_executor_job(storage.device, device_id))["name"] == "Suggested"
    assert "control_mode" not in entry.options


async def test_backup_platform_freezes_and_releases_the_loaded_database(hass, entry):
    from custom_components.solar_inverter_bridge.backup import async_post_backup, async_pre_backup
    from custom_components.solar_inverter_bridge.core.storage import StorageError

    storage = entry.runtime_data["storage"]
    device = await hass.async_add_executor_job(storage.enroll, "b" * 64, "Backup", "modbus_protocol_4")
    await async_pre_backup(hass)
    try:
        with pytest.raises(StorageError, match="storage_backup_in_progress"):
            await hass.async_add_executor_job(storage.set_mode, device, "control")
    finally:
        await async_post_backup(hass)
    await hass.async_add_executor_job(storage.set_mode, device, "advanced")
    saved = await hass.async_add_executor_job(storage.device, device)
    assert saved["control_mode"] == "full"


async def test_native_ha_brand_and_panel_use_the_same_mark(hass, entry, hass_client):
    from pathlib import Path
    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()
    integration_logo = await client.get("/api/brands/integration/solar_inverter_bridge/logo.png")
    panel_icon = await client.get("/solar_inverter_bridge/icon.png")
    assert integration_logo.status == panel_icon.status == 200
    assert integration_logo.content_type == "image/png"
    expected = (Path(__file__).parents[1] / "custom_components/solar_inverter_bridge/brand/icon.png").read_bytes()
    assert await integration_logo.read() == await panel_icon.read() == expected
