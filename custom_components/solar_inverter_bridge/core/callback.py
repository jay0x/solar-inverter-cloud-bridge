"""Targeted EyeBond callback bootstrap; telemetry/control still use one TCP owner.

Wire fact: set>server=<IPv4>:<TCP port>; sent to UDP 58899. References:
ha-dessmonitor local/scanner.py and ha-eybond-local collector/discovery.py.
Only the canonical command is sent; no broadcast or guessed firmware variants.
"""

import asyncio
from contextlib import AsyncExitStack
from ipaddress import IPv4Address, IPv4Network
import socket
from time import monotonic
import uuid

from .identity import peer_allowed

NETWORKS = tuple(IPv4Network(s) for s in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8"))


def local_ip(value):
    try:
        address = IPv4Address(value)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid_callback_address") from error
    if not any(address in network for network in NETWORKS) or str(address).endswith((".0", ".255")):
        raise ValueError("invalid_callback_address")
    return str(address)


def options(method="auto", collector_ip="", callback_host="", callback_port=8899, udp_port=58899):
    if method not in ("auto", "callback", "redirect"):
        raise ValueError("invalid_connection_method")
    ip = local_ip(collector_ip) if collector_ip else ""
    if not ip and method != "callback":
        return {"method": method, "collector_ip": ""}
    if type(callback_port) is not int or not 1024 <= callback_port <= 65535 or callback_port in (18899, 38899):
        raise ValueError("invalid_callback_port")
    if type(udp_port) is not int or not 1 <= udp_port <= 65535:
        raise ValueError("invalid_callback_udp_port")
    saved = {"method": method, "collector_ip": ip, "callback_port": callback_port, "udp_port": udp_port}
    if callback_host:
        saved["callback_host"] = local_ip(callback_host)
    elif method != "redirect":
        raise ValueError("invalid_callback_address")
    return saved


def payload(config):
    return f"set>server={config['callback_host']}:{config['callback_port']};".encode("ascii")


async def send_callback(config):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setblocking(False)
        sock.bind((config["callback_host"], 0))
        await asyncio.get_running_loop().sock_sendto(sock, payload(config), (config["collector_ip"], config["udp_port"]))


class CallbackConnections:
    def __init__(self, service):
        self.service = service
        self.saved = {}
        self.requests = {}
        self.next_attempt = {}
        self.ports = set()
        self.blocked = set()
        self.lock = asyncio.Lock()
        self.change_lock = asyncio.Lock()
        self.switching = set()
        self.identities = {}

    def configure(self, records):
        updated = {key: options(**record) for key, record in records.items()}
        self.blocked = {key for key in self.blocked if self.saved.get(key) == updated.get(key) and key in updated}
        self.saved = updated

    def owner_allowed(self, holder):
        device_id = self.identities.get(holder["identity_sha256"])
        if device_id in self.switching:
            return False
        config = self.saved.get(device_id)
        if not config or config["method"] == "auto":
            return True
        if config["method"] == "redirect":
            return holder["listener_port"] not in self.ports
        return holder["listener_port"] == config["callback_port"] and holder["source"] == config["collector_ip"]

    def live(self, holder):
        return (not self.service._closing and not holder["closed"].is_set()
                and not holder["writer"].is_closing() and not holder["reader"].at_eof())

    async def ensure_listener(self, config):
        port = config["callback_port"]
        if port in self.ports:
            return
        if len(self.ports) >= 4:
            raise ValueError("callback_listener_capacity")
        server = await asyncio.start_server(self.service._accept, self.service._listen_host, port, limit=8192)
        if self.service._closing:
            server.close()
            await server.wait_closed()
            raise ConnectionError("bridge_stopping")
        self.service.servers.append(server)
        self.service.listeners.append({"requested_port": port, "bound": True, "port": port, "purpose": "callback"})
        self.ports.add(port)

    async def change(self, request_id, device_id, config, persist):
        """Save an existing enrollment's route without overlapping inverter I/O.

        persist is a synchronous HA config-entry update. A failed callback remains
        a saved preference with an explicit attempt result, never a confirmed link.
        """
        from .storage import StorageError
        uuid.UUID(request_id)
        config = options(**config)
        service = self.service
        async with self.change_lock:
            device = await asyncio.to_thread(service.storage.device, device_id)
            if device is None:
                raise ValueError("device_not_found")
            identity = device["collector_sha256"]
            self.identities[identity] = device_id
            previous = self.requests.get(request_id)
            if previous:
                if (previous["config"] != config or previous["device_id"] != device_id
                        or self.saved.get(device_id) != config):
                    raise ValueError("connection_request_conflict")
                return self.view(previous)
            if config["collector_ip"] and not peer_allowed(config["collector_ip"], service.sources):
                raise ValueError("callback_source_not_allowed")
            if any(self.live(h) and h["source"] == config["collector_ip"] and key != identity
                   for key, channels in service._channels.items() for h in channels):
                raise ValueError("callback_identity_mismatch")
            self.requests = {key: r for key, r in self.requests.items() if monotonic() < r["expires"]}
            if len(self.requests) >= 32:
                raise ValueError("connection_request_capacity")
            job = service._profile_jobs.get(identity)
            if job and not job.done():
                raise ValueError("collector_missing_or_busy")
            self.switching.add(device_id)
            task = asyncio.current_task()
            service._commands.add(task)
            try:
                # Let an existing cycle (including reconciliation) finish before
                # taking the command lock. Never cancel a possible write.
                poll = service._polling.get(device_id)
                if poll:
                    async with asyncio.timeout(90):
                        await asyncio.shield(poll)
                async with service._command_lock(device_id):
                    if service._closing:
                        raise ConnectionError("bridge_stopping")
                    if await asyncio.to_thread(service.storage.has_unresolved, device_id):
                        raise StorageError("device_busy_or_unresolved")
                    device = await asyncio.to_thread(service.storage.device, device_id)
                    if device is None:
                        raise ValueError("device_not_found")
                    async with AsyncExitStack() as stack:
                        old = service.connections.get(identity)
                        if old is not None:
                            await stack.enter_async_context(old["lock"])
                        await stack.enter_async_context(self.lock)
                        if config["collector_ip"]:
                            await self.ensure_listener(config)
                        # No await between saving the preference and releasing
                        # the old owner. Old sockets stay heartbeat-only.
                        persist(config)
                        self.saved[device_id] = config
                        self.identities[identity] = device_id
                        self.blocked.discard(device_id)
                        for record in self.requests.values():
                            if record["device_id"] == device_id:
                                record.update(state="superseded", expires=monotonic())
                        old = service.connections.pop(identity, None)
                        service.candidates.pop(identity, None)
                        for cache in (service.observations, service._settings_observed, service._settings_sessions):
                            cache.pop(device_id, None)
                        self.switching.discard(device_id)
                        channels = list(service._channels.get(identity, []))
                        if old in channels:
                            channels.remove(old)
                            channels.insert(0, old)
                        for holder in channels:
                            if holder["primary"] and self.live(holder) and self.owner_allowed(holder):
                                service.connections[identity] = holder
                                service.candidates[identity] = holder
                                break
                        self.next_attempt[device_id] = monotonic() + 120
                    if not device["enabled"]:
                        self.next_attempt.pop(device_id, None)
                        record = {"request_id": request_id, "config": config, "expected_identity": identity,
                                  "request_identity": identity, "device_id": device_id, "state": "saved_paused",
                                  "sent": False, "expires": monotonic() + 600}
                        self.requests[request_id] = record
                        return self.view(record)
                    try:
                        return await self.connect(request_id, config, expected_identity=identity, device_id=device_id)
                    except OSError as error:
                        await service.record_issue(error, device_id, "callback")
                        record = self.requests.get(request_id)
                        if record:
                            return self.view(record)
                        raise
            finally:
                self.switching.discard(device_id)
                service._commands.discard(task)
                service._notify()

    def view(self, record):
        state = record["state"]
        identity = record.get("collector_sha256") or record.get("expected_identity")
        owner = self.service.connections.get(identity)
        if state == "waiting_for_connection" and self.service._connected(owner):
            state = "connected"
        holders = ([owner] if owner else []) if record["device_id"] else self.service._channels.get(identity, [])
        if state != "waiting_for_connection" and monotonic() >= record["expires"]:
            state = "timed_out"
        elif state == "connected" and not any(self.service._connected(h) and
                (not record["config"].get("callback_port") or h["listener_port"] == record["config"]["callback_port"]
                 or record["config"]["method"] == "auto")
                for h in holders):
            state = "disconnected"
        return {"request_id": record["request_id"], "state": state,
                "connection_method": record["config"]["method"], "collector_ip": record["config"]["collector_ip"],
                "collector_sha256": record.get("collector_sha256"), "reason": record.get("reason"),
                 "callback_port": record["config"].get("callback_port"), "device_id": record["device_id"], "sent": record["sent"]}

    async def connect(self, request_id, config, *, expected_identity=None, device_id=None):
        uuid.UUID(request_id)
        config = options(**config)
        async with self.lock:
            if self.service._closing:
                raise ConnectionError("bridge_stopping")
            if request_id in self.requests:
                record = self.requests[request_id]
                if record["config"] != config or record["request_identity"] != expected_identity:
                    raise ValueError("connection_request_conflict")
                return self.view(record)
            self.requests = {key: value for key, value in self.requests.items() if monotonic() < value["expires"]}
            if len(self.requests) >= 32:
                raise ValueError("connection_request_capacity")
            ip = config["collector_ip"]
            if ip and not peer_allowed(ip, self.service.sources):
                raise ValueError("callback_source_not_allowed")
            record = {"request_id": request_id, "config": config, "expected_identity": expected_identity, "request_identity": expected_identity,
                      "device_id": device_id, "state": "waiting", "sent": False, "expires": monotonic() + 120}
            if config["method"] == "redirect" or not ip:
                holder = self.service.connections.get(expected_identity)
                record["state"] = "connected" if self.service._connected(holder) else "waiting_for_connection"
                if record["state"] == "connected":
                    record["collector_sha256"] = expected_identity
                self.requests[request_id] = record
                return self.view(record)
            existing = [h for h in self.service.connections.values() if h["source"] == ip and self.service._connected(h)]
            if existing:
                if len(existing) != 1 or (expected_identity and existing[0]["identity_sha256"] != expected_identity):
                    raise ValueError("callback_identity_mismatch")
                holder = existing[0]
                if config["method"] == "callback" and holder["listener_port"] != config["callback_port"]:
                    raise ValueError("collector_already_connected")
                record.update(state="connected", collector_sha256=holder["identity_sha256"], expires=monotonic() + 600)
                self.requests[request_id] = record
                return self.view(record)
            if any(r["config"]["collector_ip"] == ip and r["state"] == "waiting" for r in self.requests.values()):
                raise ValueError("callback_already_pending")
            port = config["callback_port"]
            await self.ensure_listener(config)
            self.requests[request_id] = record
            # Sent means a send was attempted, never that the collector accepted it.
            record["sent"] = True
            try:
                await send_callback(config)
            except (OSError, asyncio.CancelledError):
                record.update(state="failed", reason="callback_send_unconfirmed")
                raise
            self.service.compatibility.emit("callback_requested", request_id=request_id, listener_port=port)
            return self.view(record)

    def admit(self, source, port, identity):
        if port not in self.ports:
            return True
        matching = [r for r in self.requests.values() if r["config"]["collector_ip"] == source
                    and r["config"].get("callback_port") == port and monotonic() < r["expires"]
                    and r["state"] in ("waiting", "connected")]
        if not matching:
            return False
        valid = False
        for record in matching:
            if record["expected_identity"] and record["expected_identity"] != identity:
                record.update(state="failed", reason="callback_identity_mismatch")
                if record["device_id"]:
                    self.blocked.add(record["device_id"])
            else:
                record.update(state="connected", collector_sha256=identity, expires=monotonic() + 600)
                valid = True
        return valid

    def enrollment_options(self, request_id, identity):
        record = self.requests.get(request_id)
        if record is None or (record["config"]["collector_ip"] and monotonic() >= record["expires"]):
            raise ValueError("connection_request_expired")
        if record["config"]["collector_ip"] and (record.get("collector_sha256") != identity or record["state"] != "connected"):
            raise ValueError("callback_identity_mismatch")
        return dict(record["config"])

    def bind(self, request_id, device_id, identity):
        config = self.enrollment_options(request_id, identity)
        self.requests[request_id].update(expected_identity=identity, device_id=device_id)
        self.identities[identity] = device_id
        return config

    async def reconnect(self, device):
        config = self.saved.get(device["device_id"])
        if not config or not config.get("collector_ip") or config["method"] == "redirect":
            return
        if monotonic() < self.next_attempt.get(device["device_id"], 0):
            return
        if device["device_id"] in self.blocked:
            return
        self.next_attempt[device["device_id"]] = monotonic() + 120
        try:
            await self.connect(str(uuid.uuid4()), config, expected_identity=device["collector_sha256"], device_id=device["device_id"])
        except (ValueError, OSError) as error:
            await self.service.record_issue(error, device["device_id"], "callback")
