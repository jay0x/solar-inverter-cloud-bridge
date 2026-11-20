"""Explicit collector endpoint operations on the existing, identity-bound owner.

Write and apply are separate durable operations. Neither reconnect nor retry
replays them. Readback is not proof of reconnection or nonvolatile persistence.
"""

import asyncio
from datetime import datetime, timezone
import ipaddress
import re
import socket

from .exchange import exchange_at
from .identity import full_pn_identity, parse_at_identity, parse_at_response
from .storage import StorageError


def parse_endpoint(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("invalid_collector_endpoint")
    parts = value.split(",")
    if len(parts) != 3 or parts[2] != "TCP" or not parts[1].isascii() or not parts[1].isdigit():
        raise ValueError("invalid_collector_endpoint")
    host, port, _ = parts
    if not 1 <= int(port) <= 65535 or str(int(port)) != port:
        raise ValueError("invalid_collector_endpoint")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not host or any(not re.fullmatch(r"[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?", label)
                           for label in host.split(".")):
            raise ValueError("invalid_collector_endpoint") from None
    else:
        if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified:
            raise ValueError("invalid_collector_endpoint")
    return host, int(port)


async def validate_destination(service, endpoint, local_addresses, *, restoring=False):
    host, port = parse_endpoint(endpoint)
    if not restoring and (port in service.auxiliary_ports or not any(item.get("bound") and item.get("port") == port for item in service.listeners)):
        raise ValueError("collector_destination_not_listening")
    async with asyncio.timeout(5):
        replies = await asyncio.get_running_loop().getaddrinfo(host, port, family=socket.AF_INET,
                                                              type=socket.SOCK_STREAM)
    addresses = sorted({reply[4][0] for reply in replies})
    if not addresses or (not restoring and not set(addresses).issubset(set(local_addresses))):
        raise ValueError("collector_destination_not_local")
    return addresses


async def read_endpoint(holder):
    reader, writer = holder["reader"], holder["writer"]
    if holder["dialect"] == "binary":
        identity = full_pn_identity(await reader.query(2))
    else:
        identity = parse_at_identity(await exchange_at(reader, writer, b"AT+DTUPN?\r\n"))
    if identity is None or identity["identity_sha256"] != holder["identity_sha256"]:
        raise ValueError("collector_identity_changed")
    if holder["dialect"] == "binary":
        value = (await reader.query(21)).rstrip(b"\x00").decode("ascii")
    else:
        value = parse_at_response(await exchange_at(reader, writer, b"AT+CLDSRVHOST1?\r\n"), "CLDSRVHOST1")
    parse_endpoint(value)
    return value


async def send_action(holder, action, endpoint):
    reader, writer = holder["reader"], holder["writer"]
    if holder["dialect"] == "binary":
        parameter, value = (21, endpoint) if action in ("write", "restore") else (29, "1")
        await reader.set_collector(parameter, value)
    else:
        command, value = ("CLDSRVHOST1", endpoint) if action in ("write", "restore") else ("INTPARA", "29,1")
        reply = await exchange_at(reader, writer, f"AT+{command}={value}\r\n".encode("ascii"))
        status = parse_at_response(reply, command)
        if status != "W000" and not (action in ("write", "restore") and status == endpoint):
            raise ValueError("collector_endpoint_command_unconfirmed")


async def execute(service, device_id, action, *, operation_id=None, value=None, expected_value=None,
                  expected_transport=None, expected_listener_port=None, local_addresses=(), actor_name=None, actor_id=None):
    if action not in ("state", "read", "prepare", "prepare_restore", "write", "restore", "apply", "check", "accept_current"):
        raise ValueError("invalid_collector_action")
    if service._queued.get(device_id, 0) >= 16 or len(service._commands) >= 64:
        raise ValueError("command_queue_full")
    task = asyncio.current_task()
    service._commands.add(task)
    service._queued[device_id] = service._queued.get(device_id, 0) + 1
    lock = service._command_lock(device_id)
    try:
        async with asyncio.timeout(30):
            await lock.acquire()
        try:
            return await _execute(service, device_id, action, operation_id=operation_id, value=value,
                                  expected_value=expected_value, expected_transport=expected_transport,
                                  expected_listener_port=expected_listener_port,
                                  local_addresses=local_addresses, actor_name=actor_name, actor_id=actor_id)
        finally:
            lock.release()
    finally:
        service._commands.discard(task)
        service._queued[device_id] -= 1


async def _execute(service, device_id, action, *, operation_id, value, expected_value,
                   expected_transport, expected_listener_port, local_addresses, actor_name, actor_id):
    storage = service.storage
    if action == "state":
        return await asyncio.to_thread(storage.collector_endpoint_history, device_id)
    mutation = action in ("write", "restore", "apply")
    request = {"key": "collector_server_endpoint", "collector_action": action,
               "value": value, "expected_value": expected_value,
               "expected_transport": expected_transport, "expected_listener_port": expected_listener_port}
    saved = await asyncio.to_thread(storage.operation, operation_id) if operation_id else None
    if mutation:
        if not operation_id or expected_transport not in ("at", "binary") or type(expected_listener_port) is not int:
            raise ValueError("collector_operation_context_required")
        if saved is not None:
            if saved["device_id"] != device_id or saved["request"] != request:
                raise StorageError("operation_id_conflict")
            return saved
    history = await asyncio.to_thread(storage.collector_endpoint_history, device_id)
    if mutation:
        parse_endpoint(value)
        parse_endpoint(expected_value)
        if action == "restore" and value != history["saved_endpoint"]:
            raise ValueError("collector_restore_target_mismatch")
        if action == "apply" and value != expected_value:
            raise ValueError("collector_apply_baseline_mismatch")
        if await asyncio.to_thread(storage.has_unresolved, device_id):
            raise ValueError("device_busy_or_unresolved")
    elif action in ("check", "accept_current"):
        if saved is None or saved["device_id"] != device_id or not saved["request"].get("collector_action"):
            raise ValueError("collector_operation_not_found")
    device = await asyncio.to_thread(storage.device, device_id)
    holder = service.connections.get(device["collector_sha256"]) if device else None
    if not service._connected(holder):
        raise ConnectionError("collector_not_connected")
    if device_id in service.callback.switching:
        raise ValueError("connection_change_in_progress")
    async with holder["lock"]:
        if not service._connected(holder):
            raise ConnectionError("collector_session_changed")
        if mutation and (holder["dialect"] != expected_transport or holder["listener_port"] != expected_listener_port):
            raise ValueError("collector_operation_route_changed")
        wire = getattr(holder["reader"], "wire", holder["reader"])
        wire.origin = "collector_endpoint_preflight"
        try:
            previous = await read_endpoint(holder)
        except BaseException:
            service._disconnect(holder)
            raise
        observed = {"endpoint": previous, "transport": holder["dialect"],
                    "listener_port": holder["listener_port"], "session_ref": holder["session_ref"],
                    "read_at": datetime.now(timezone.utc).isoformat(), "history": history}
        if not mutation:
            if action in ("prepare", "prepare_restore"):
                restoring = action == "prepare_restore"
                if restoring and (not history["saved_endpoint"] or value != history["saved_endpoint"]):
                    raise ValueError("collector_restore_target_mismatch")
                addresses = await validate_destination(service, value, local_addresses, restoring=restoring)
                if not service._connected(holder):
                    raise ConnectionError("collector_session_changed")
                observed.update(requested_endpoint=value, resolved_addresses=addresses,
                                prepared_action="restore" if restoring else "write",
                                destination_is_local=set(addresses).issubset(set(local_addresses)))
            if action in ("check", "accept_current"):
                if action == "accept_current" and (not actor_id or previous != expected_value):
                    raise ValueError("observed_value_changed")
                await service._durable(storage.observe_operation, operation_id, previous)
                if action == "accept_current" and saved["unresolved"]:
                    await service._durable(storage.resolve_operation, operation_id, "accepted_current_value", actor_id)
                elif saved["unresolved"] and saved["request"]["collector_action"] in ("write", "restore") and previous == saved["request"]["value"]:
                    await service._durable(storage.resolve_operation, operation_id)
                observed["operation"] = await asyncio.to_thread(storage.operation, operation_id)
                observed["history"] = await asyncio.to_thread(storage.collector_endpoint_history, device_id)
            return observed
        if previous != expected_value:
            raise ValueError("collector_endpoint_baseline_changed")
        restoring = action == "restore" or (action == "apply" and value == history["saved_endpoint"])
        addresses = await validate_destination(service, value, local_addresses, restoring=restoring)
        if not service._connected(holder):
            raise ConnectionError("collector_session_changed")
        claimed = False
        try:
            await service._durable(storage.accept_operation, device_id, operation_id, request,
                                   actor_name=actor_name, write_plan={**{k: v for k, v in observed.items() if k != "history"}, "resolved_addresses": addresses})
            # This flag is conservative if cancellation races the durable claim.
            claimed = True
            if not await service._durable(storage.claim_send, operation_id):
                return await asyncio.to_thread(storage.operation, operation_id)
            if not service._connected(holder):
                raise ConnectionError("collector_session_changed")
            wire.origin = "collector_endpoint_write" if action in ("write", "restore") else "collector_endpoint_apply"
            await send_action(holder, action, value)
            if action in ("write", "restore"):
                if not service._connected(holder):
                    raise ConnectionError("collector_session_changed")
                actual = await read_endpoint(holder)
                await service._durable(storage.observe_operation, operation_id, actual)
                if actual != value:
                    raise ValueError("collector_endpoint_readback_mismatch")
            result = await service._durable(storage.finish_operation, operation_id, state="completed",
                                            outcome="confirmed", unresolved=False,
                                            reason="endpoint_readback_matched" if action in ("write", "restore") else "apply_acknowledged_not_reconnect_proof")
        except BaseException:
            if claimed:
                service._disconnect(holder)
                await service._durable(storage.finish_operation, operation_id, state="reconciling",
                                        outcome="uncertain", unresolved=True, reason="collector_action_unconfirmed")
            else:
                await service._durable(storage.cancel_unsent, operation_id, device_id, request)
            raise
        service._notify()
        return result
