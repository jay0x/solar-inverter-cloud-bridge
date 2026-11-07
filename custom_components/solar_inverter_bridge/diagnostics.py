"""Useful cached diagnostics without credentials, raw frames, names, or addresses."""

from datetime import datetime, timezone
import platform

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .core.identity import peer_allowed
from .core.observations import TELEMETRY_TTL_SECONDS
from .core.parameters import FIELDS, inventory
from .core.policy import MAX_CLOCK_CORRECTION_SECONDS
from .core.artifact import artifact_metadata


async def async_get_config_entry_diagnostics(hass, entry):
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return {"schema": 2, "state": "not_loaded", "home_assistant_version": HA_VERSION,
                "listeners": hass.data.get(DOMAIN, {}).get("failed_listeners", [])}
    service, storage = runtime["service"], runtime["storage"]
    state = await service.status()
    references = {device["device_id"]: f"device_{index + 1}" for index, device in enumerate(state["devices"])}
    entries = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    sources = {}
    devices = []
    for device in state["devices"]:
        from .core.drivers import fields_for
        fields = fields_for(device["profile_id"])
        identifier = device["device_id"]
        observation = service.observations.get(identifier)
        registers = service.settings_registers.get(identifier, {})
        raw_values = {field.key: [registers[address] for address in range(field.address, field.address + (6 if field.kind == "datetime" else 1))]
                       for field in fields if all(address in registers for address in range(field.address, field.address + (6 if field.kind == "datetime" else 1)))}
        channels = []
        for holder in service._channels.get(device["collector_sha256"], []):
            source = sources.setdefault(holder["source"], f"source_{len(sources) + 1}")
            channels.append({"source_ref": source, "source_allowed": peer_allowed(holder["source"], service.sources),
                             "role": "primary" if holder["primary"] else "secondary_passive", "listener_port": holder["listener_port"],
                             "active_owner": service.connections.get(holder["identity_sha256"]) is holder,
                             "closing": holder["writer"].is_closing()})
        sensors = {}
        for entity in entries:
            if not entity.unique_id.startswith(identifier + "_"):
                continue
            sensor = hass.states.get(entity.entity_id)
            sensors[entity.unique_id[len(identifier) + 1:]] = {
                "state": sensor.state if sensor else None,
                "last_updated": sensor.last_updated.isoformat() if sensor else None,
                "disabled": entity.disabled_by is not None,
                "unit": sensor.attributes.get("unit_of_measurement") if sensor else None,
                "device_class": sensor.attributes.get("device_class") if sensor else None,
                "state_class": sensor.attributes.get("state_class") if sensor else None,
            }
        operations = []
        for index, public in enumerate(device["operations"]):
            record = await hass.async_add_executor_job(storage.operation, public["operation_id"])
            operations.append({"reference": f"operation_{index + 1}", "setting_key": record.get("request", {}).get("key"),
                               "desired_value": record.get("send_value", record.get("request", {}).get("value")),
                               "baseline": record.get("request", {}).get("expected_value"),
                               **{key: record.get(key) for key in ("state", "outcome", "reason", "resolution", "unresolved", "write_attempts",
                                                                 "created_at", "send_intent_at", "resolved_at", "last_observed_value", "last_observed_at")}})
        devices.append({"reference": references[identifier], "profile": device["profile_id"],
                          "profile_acceptance": device.get("profile_acceptance"),
                          "profile_layers": device.get("profile_layers"),
                        "native_identity": service.native_identity.get(identifier),
                        "configuration": {key: device[key] for key in ("control_mode", "clock_sync", "enabled", "poll_interval", "policy_revision")},
                         "connection": {"connected": device["connected"], "channels": channels,
                                        "transport": device.get("transport"), "route": device.get("route")},
                         "capabilities": device.get("capabilities"), "capability_reason": device.get("capability_reason"),
                        "telemetry": {"available": device["enabled"] and not device["stale"], "observed_at": device["observed_at"], "age_seconds": device["age_seconds"],
                                      "values": observation.values if observation else None},
                        "parameters": {"available": device["settings_available"], "observed_at": service.settings_observed_at.get(identifier), "values": device["settings"], "raw_register_values": raw_values, "individual_readbacks": service.parameter_readbacks.get(identifier, {})},
                         "polling": {"completed_snapshots": service.poll_cycles[identifier], "last_duration_ms": service.poll_duration_ms.get(identifier),
                                     "error_count_total": service.poll_errors[identifier],
                                    "failure_count": service._failures.get(identifier, 0), "backoff_seconds": device["poll_backoff_seconds"]},
                        "ha_sensors": sensors, "recent_operations": operations, "unresolved_count": device["unresolved"]})
    issues = [{**{key: value for key, value in event.items() if key not in ("device_id", "runtime_id")},
               "device_ref": references.get(event.get("device_id"), "bridge_or_removed_device"),
               "previous_session": event.get("runtime_id") != service.runtime_id} for event in service.issues]
    compatibility = service.compatibility.snapshot(service.listeners)
    compatibility["description"] = {}
    return {
        "schema": 2, "captured_at": datetime.now(timezone.utc).isoformat(),
        "home_assistant": {"version": HA_VERSION, "python": platform.python_version(), "time_zone": hass.config.time_zone},
        "artifact": await hass.async_add_executor_job(artifact_metadata),
         "runtime": {"started_at": service.started_at, "listening": state["listening"],
                     "listeners": service.listeners, "degraded": state["degraded"],
                    "active_tasks": sum(not task.done() for task in service.tasks), "queued_commands": sum(service._queued.values()),
                    "allowed_source_rules": len(service.sources), "rejected_connections": service.rejected, "admission_counters": dict(service.reject_reasons)},
        "policy": {"telemetry_ttl_seconds": TELEMETRY_TTL_SECONDS, "maximum_clock_correction_seconds": MAX_CLOCK_CORRECTION_SECONDS},
        "storage": await hass.async_add_executor_job(storage.storage_summary),
        "parameter_inventory": list(inventory()), "devices": devices, "recent_issues": issues,
        "compatibility": compatibility,
        "profile_discovery": [{"reference":f"candidate_{index+1}",**{key:value for key,value in search.items() if key!="collector_sha256"}}
                              for index,search in enumerate(state.get("profile_searches",[]))],
        "redaction": "Names, source IPs, collector identities, device/operation IDs, credentials, paths, and raw frames are omitted.",
    }
