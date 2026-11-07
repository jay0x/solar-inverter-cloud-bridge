"""Collector TCP admission. Native polling starts only for an explicit saved device."""

import asyncio
from collections import Counter, deque
from datetime import datetime, timezone
import re
from time import monotonic
import uuid
import hashlib

from .identity import at_query, parse_at_identity, peer_allowed
from .drivers import fields_for

UNSPECIFIED = object()


class CollectorService:
    def __init__(self, sources, storage, now=None, heartbeat_interval=None, bootstrap_preference="auto"):
        self.sources = tuple(sources)
        self.storage = storage
        self.runtime_id = str(uuid.uuid4())
        self.now = now or (lambda: datetime.now().replace(microsecond=0))
        self.servers = []
        self.candidates = {}
        self.connections = {}
        self.observation = None
        self.observations = {}
        self.settings = {}
        self.settings_registers = {}
        self.parameter_readbacks = {}
        self.last_error = None
        self.last_error_at = None
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.issues = deque(maxlen=32)
        self.reject_reasons = Counter()
        self.poll_cycles = Counter()
        self.poll_errors = Counter()
        self._planned_reconnect = {}
        self.poll_duration_ms = {}
        self.on_update = None
        self.transmitted = 0
        self.rejected = 0
        self.tasks = set()
        self._polled = {}
        self._failures = {}
        self._healthy = {}
        self._next_poll = {}
        self._command_locks = {}
        self._commands = set()
        self._closing = False
        self._availability = {}
        self._queued = {}
        self.collection_enabled = {}
        self._polling = {}
        self._settings_observed = {}
        self.settings_observed_at = {}
        self.native_identity = {}
        self._channels = {}
        self.auxiliary_ports = {38899}
        self.listeners = []
        self.bootstrap_preference = bootstrap_preference
        self._bootstrap_attempts = {}
        from .compatibility import CompatibilityCapture
        self.compatibility = CompatibilityCapture()
        self._source_salt = uuid.uuid4().bytes
        self._compatibility_tasks = set()
        self.profile_searches = {}
        self.profile_acceptances = {}
        self._profile_jobs = {}
        self.heartbeat_interval = 37 if heartbeat_interval is None else heartbeat_interval
        self.binary_heartbeat_interval = 60 if heartbeat_interval is None else heartbeat_interval
        self.module_info = {}
        self._started_monotonic = monotonic()
        self._reset_not_before = {}
        self._enrolled_monotonic = {}

    def _command_lock(self, device_id):
        return self._command_locks.setdefault(device_id, asyncio.Lock())

    async def _bind_holder_route(self, device_id, holder):
        binary = holder.get("dialect") == "binary"
        adapter = holder["reader"]
        slave = getattr(adapter,"slave",1)
        route = {"transport": "binary" if binary else "at", "inner_slave": slave if type(slave) is int else 1,
                 "outer_code": adapter.route[0] if binary else None,
                 "outer_address": adapter.route[1] if binary else None}
        await self._durable(self.storage.bind_route, device_id, route)

    def set_bootstrap_preference(self, value):
        if value not in ("auto", "at", "binary"):
            raise ValueError("invalid_bootstrap_preference")
        if value != self.bootstrap_preference:
            self._bootstrap_attempts.clear()
        self.bootstrap_preference = value

    def restore_issues(self, records):
        self.issues.extend(records[-32:])
        if self.issues:
            self.last_error = self.issues[-1]["code"]
            self.last_error_at = self.issues[-1]["occurred_at"]

    async def record_issue(self, error, device_id=None, stage="runtime", parameter=None):
        if device_id is not None and stage in ("poll", "settings_read"):
            self.poll_errors[device_id] += 1
        from .storage import StorageError
        detail = str(error)
        code = detail if re.fullmatch(r"[a-z][a-z0-9_]{0,80}", detail) else type(error).__name__
        record = {"occurred_at": datetime.now(timezone.utc).isoformat(), "runtime_id": self.runtime_id,
                  "device_id": device_id, "stage": stage, "code": code}
        if parameter is not None:
            record["parameter"] = parameter
        for key in ("register_address", "register_count", "function", "exception_code", "protocol_number", "model_code", "elapsed_ms", "received_bytes"):
            value = getattr(error, key, None)
            if isinstance(value, int):
                record[key] = value
        persisted = record
        if self.storage is not None:
            try:
                persisted = await asyncio.to_thread(self.storage.record_diagnostic, record)
            except StorageError:
                # The in-memory event survives even when the original fault is disk I/O.
                persisted = record
        if persisted is None:
            return
        if (self.issues and persisted.get("repeat_count")
                and self.issues[-1].get("occurred_at") == persisted.get("occurred_at")
                and self.issues[-1].get("code") == persisted.get("code")):
            self.issues[-1] = persisted
        else:
            self.issues.append(persisted)
        self.last_error, self.last_error_at = persisted["code"], persisted.get("last_seen_at") or persisted["occurred_at"]

    def _connected(self, holder):
        return (holder is not None and not self._closing
                and not holder["closed"].is_set() and not holder["writer"].is_closing()
                and not holder["reader"].at_eof()
                and self.connections.get(holder["identity_sha256"]) is holder)

    def _disconnect(self, holder):
        holder["closed"].set()
        adapter = holder["reader"]
        if hasattr(adapter, "_closing_reason"):
            adapter._closing_reason = adapter._closing_reason or "owner_disconnected"
        holder["writer"].close()

    async def _send_heartbeat(self, holder):
        wire = getattr(holder["reader"], "wire", holder["reader"])
        wire.origin = "heartbeat"
        if holder.get("dialect") == "binary":
            try:
                await holder["reader"].heartbeat()
            except (ValueError, ConnectionError, TimeoutError):
                holder["reader"].counters["heartbeat_failures"] += 1
                holder["emit"]("heartbeat_failed")
                raise
            holder["heartbeat_at"] = datetime.now(timezone.utc).isoformat()
            return
        from .exchange import exchange_at
        from .identity import HEARTBEAT_QUERY, parse_at_response
        reply = await exchange_at(holder["reader"], holder["writer"], HEARTBEAT_QUERY)
        if parse_at_response(reply, "HTBT") is None:
            raise ConnectionError("heartbeat_rejected")
        holder["heartbeat_at"] = datetime.now(timezone.utc).isoformat()

    async def _at_values(self, holder, queries):
        from .exchange import exchange_at
        from .identity import parse_at_response
        values = {}
        for key, query in queries:
            name = query.split(b"?", 1)[0].decode().removeprefix("AT+")
            reply = await exchange_at(holder["reader"], holder["writer"], query)
            value = parse_at_response(reply, name)
            if value is None:
                raise ConnectionError("collector_at_rejected")
            values[key] = value
        return values

    async def read_module_info(self, device_id):
        """Read collector identity fields. This never writes module configuration."""
        from .identity import MODULE_QUERIES
        device = await asyncio.to_thread(self.storage.device, device_id)
        if device is None:
            raise ValueError("device_missing")
        holder = self.connections.get(device["collector_sha256"])
        if not self._connected(holder):
            raise ConnectionError("collector_not_connected")
        async with self._command_lock(device_id):
            async with holder["lock"]:
                if not self._connected(holder):
                    raise ConnectionError("collector_not_connected")
                wire = getattr(holder["reader"], "wire", holder["reader"])
                wire.origin = "manual_metadata_read"
                try:
                    if holder.get("dialect") == "binary":
                        values = {}
                        for parameter, name in ((5, "firmware_version"), (6, "hardware_version")):
                            data = await holder["reader"].query(parameter)
                            values[name] = data.rstrip(b"\x00").decode("ascii", errors="replace")[:80]
                    else:
                        values = await self._at_values(holder, MODULE_QUERIES)
                except BaseException:
                    self._disconnect(holder)
                    raise
        values["read_at"] = datetime.now(timezone.utc).isoformat()
        self.module_info[device["collector_sha256"]] = values
        self._notify()
        return values

    def _reset_due(self, device):
        holder = self.connections.get(device["collector_sha256"])
        if holder is not None and not holder.get("capabilities", {}).get("module_reset", True):
            return False
        if not device.get("auto_reset") or not device["enabled"]:
            return False
        if monotonic() < self._reset_not_before.get(device["collector_sha256"], 0):
            return False
        observed = self.observations.get(device["device_id"])
        last_data = observed.observed_monotonic if observed is not None else self._started_monotonic
        baseline = max(last_data, self._started_monotonic, self._enrolled_monotonic.get(device["device_id"], 0))
        return monotonic() - baseline >= max(300, 3 * device["poll_interval"])

    async def reset_collector(self, device_id, *, automatic=False):
        """Reboot the Wi-Fi module. This does not write inverter registers."""
        from .exchange import exchange_at
        from .identity import RESET_COMMAND, parse_at_response
        device = await asyncio.to_thread(self.storage.device, device_id)
        if device is None:
            raise ValueError("device_missing")
        if await asyncio.to_thread(self.storage.has_unresolved, device_id):
            raise ValueError("device_busy_or_unresolved")
        holder = self.connections.get(device["collector_sha256"])
        if not self._connected(holder):
            raise ConnectionError("collector_not_connected")
        if not holder.get("capabilities", {}).get("module_reset", True):
            raise ValueError("transport_reset_unsupported")
        async with self._command_lock(device_id):
            async with holder["lock"]:
                if not self._connected(holder):
                    raise ConnectionError("collector_not_connected")
                current = await asyncio.to_thread(self.storage.device, device_id)
                if automatic and (current is None or not self._reset_due(current)):
                    return {"reset": "skipped"}
                if not await self._durable(self.storage.reserve_collector_reset, device_id, automatic=automatic):
                    return {"reset": "skipped"}
                self._reset_not_before[device["collector_sha256"]] = monotonic() + 3600
                wire = getattr(holder["reader"], "wire", holder["reader"])
                wire.origin = "automatic_maintenance" if automatic else "manual_command"
                try:
                    reply = await exchange_at(holder["reader"], holder["writer"], RESET_COMMAND, timeout=3)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
                    reply = b""
                finally:
                    # A late AT response must not enter a later Modbus exchange.
                    self._disconnect(holder)
                accepted = reply == b"" or parse_at_response(reply, "RESET") is not None
                if automatic:
                    await self.record_issue("automatic_collector_reset_attempted", device_id, "recovery")
        self._disconnect(holder)
        self._notify()
        if not accepted:
            raise ConnectionError("collector_reset_rejected")
        return {"reset": "accepted" if reply else "uncertain"}

    async def _durable(self, function, *args, **kwargs):
        """Wait for a cancelled DB call to settle before releasing its owner lock."""
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            finally:
                raise

    async def start(self, host="127.0.0.1", ports=(0,)):
        try:
            for port in ports:
                state = {"requested_port": port, "bound": False}
                self.listeners.append(state)
                try:
                    server = await asyncio.start_server(self._accept, host, port, limit=8192)
                except OSError as error:
                    state.update(error=type(error).__name__, errno=error.errno)
                    self.compatibility.emit("listener_failed", **state)
                    continue
                self.servers.append(server)
                state.update(bound=True, port=server.sockets[0].getsockname()[1])
                self.compatibility.emit("listener_bound", **state)
            if not self.servers:
                raise OSError("all_collector_ports_unavailable")
        except BaseException:
            await self.close()
            raise
        task = asyncio.create_task(self._poll_loop())
        self.tasks.add(task)
        self.tasks.add(asyncio.create_task(self._expiry_loop()))
        return tuple(server.sockets[0].getsockname() for server in self.servers)

    async def close(self):
        self._closing = True
        for server in self.servers:
            server.close()
        # Finish possible-send bookkeeping while the storage worker still exists.
        commands = list(self._commands)
        for task in commands:
            task.cancel()
        if commands:
            await asyncio.gather(*commands, return_exceptions=True)
        for holder in list(self.connections.values()):
            holder["closed"].set()
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        for server in self.servers:
            server.close()
        for server in self.servers:
            await server.wait_closed()
        self.servers.clear()

    async def _accept(self, reader, writer):
        if self._closing or len(self.tasks) >= 80:
            self.rejected += 1
            self.reject_reasons["capacity"] += 1
            writer.close()
            await writer.wait_closed()
            return
        peer = writer.get_extra_info("peername")
        address = peer[0] if peer else ""
        session_ref = str(uuid.uuid4())
        port = writer.get_extra_info("sockname")[1]
        source_ref = "source_" + hashlib.sha256(self._source_salt + address.encode()).hexdigest()[:12]

        def emit(kind, **fields):
            if kind == "wire" and fields.get("direction") == "tx":
                self.transmitted += len(fields.get("data", b""))
            self.compatibility.emit(kind, session=session_ref, listener_port=port, source_ref=source_ref, **fields)

        emit("tcp_received")
        try:
            if not peer_allowed(address, self.sources):
                self.rejected += 1
                self.reject_reasons["source_not_allowed"] += 1
                emit("source_rejected")
                writer.close()
                await writer.wait_closed()
                return
        except ValueError:
            self.rejected += 1
            self.reject_reasons["invalid_network_options"] += 1
            writer.close()
            await writer.wait_closed()
            return
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            from .transport import ATTransport, BinaryTransport, detect
            wire = ATTransport(reader, writer, emit)
            attempt_key = (address, port)
            attempts, since = self._bootstrap_attempts.get(attempt_key, (set(), monotonic()))
            if monotonic() - since > 600:
                attempts, since = set(), monotonic()
            hint = "binary" if port == 502 else "at"
            if hint in attempts:
                hint = "at" if hint == "binary" else "binary"
            async with asyncio.timeout(15):
                dialect, basis = await detect(wire, self.bootstrap_preference, hint)
                if basis == "silent_bootstrap_hint":
                    if len(attempts) >= 2:
                        emit("bootstrap_exhausted", shared_source_ambiguity=True)
                        raise ValueError("bootstrap_exhausted")
                    attempts.add(dialect)
                    if len(self._bootstrap_attempts) >= 256:
                        self._bootstrap_attempts.pop(next(iter(self._bootstrap_attempts)))
                    self._bootstrap_attempts[attempt_key] = (attempts, since)
                emit("dialect_selected", dialect=dialect, basis=basis)
                transport = BinaryTransport(wire) if dialect == "binary" else wire
                identity = await transport.identify()
                emit("identity_confirmed", identity_method=identity["identity_method"], identity_length=identity["identity_length"],
                     collector_ref="collector_" + hashlib.sha256(self._source_salt + identity["identity_sha256"].encode()).hexdigest()[:12])
            self._bootstrap_attempts.pop(attempt_key, None)
            reader = transport
            holder = {
                "reader": reader, "writer": writer, "source": address, "native_reads": 0,
                "snapshots": 0, "ready": False, "lock": asyncio.Lock(), "closed": asyncio.Event(),
                "primary": dialect == "binary" or port not in self.auxiliary_ports,
                "listener_port": port, "dialect": dialect, "capabilities": dict(transport.capabilities),
                "session_ref": session_ref, "emit": emit,
                **identity,
            }
            key = identity["identity_sha256"]
            channels = self._channels.setdefault(key, [])
            if len(channels) >= 4:
                self.rejected += 1
                self.reject_reasons["channel_capacity"] += 1
                return
            channels.append(holder)
            # The collector maintains a second channel on 38899. Closing that
            # channel can cause it to reset both sockets. Keep it passive; native
            # reads/writes use the primary listener only (18899 in production).
            interval = self.binary_heartbeat_interval if dialect == "binary" else self.heartbeat_interval
            next_heartbeat = monotonic() + interval
            while not self._closing and not holder["closed"].is_set() and not writer.is_closing() and not reader.at_eof():
                if holder["primary"] and not self._connected(self.connections.get(key)):
                    self.connections[key] = holder
                    self.candidates[key] = holder
                    state = self.profile_searches.get(key)
                    if state and state["state"] == "waiting_for_reconnect" and monotonic() < state["expires"]:
                        self.schedule_profile_search(key)
                capture_state = self.compatibility.view()
                if (holder["primary"] and capture_state["active"]
                        and holder.get("capture_probe") != capture_state["report_id"]):
                    holder["capture_probe"] = capture_state["report_id"]
                    self.schedule_compatibility_probe()
                if monotonic() >= next_heartbeat and not holder["lock"].locked():
                    try:
                        async with holder["lock"]:
                            if holder["closed"].is_set() or writer.is_closing() or reader.at_eof():
                                break
                            await self._send_heartbeat(holder)
                        next_heartbeat = monotonic() + interval
                    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError):
                        self._disconnect(holder)
                        break
                await asyncio.sleep(0.05 if self.heartbeat_interval < 1 else 0.2)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError, ValueError) as error:
            self.rejected += 1
            self.reject_reasons["admission_connection_error"] += 1
            emit("admission_failed", code=str(error) if isinstance(error, ValueError) else type(error).__name__)
            return
        finally:
            self.tasks.discard(task)
            if "transport" in locals():
                await transport.close()
            if "holder" in locals():
                key = holder["identity_sha256"]
                if self.connections.get(key) is holder:
                    self.connections.pop(key, None)
                if self.candidates.get(key) is holder:
                    self.candidates.pop(key, None)
                channels = self._channels.get(key, [])
                if holder in channels:
                    channels.remove(holder)
                if not channels:
                    self._channels.pop(key, None)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    async def verify(self, collector_sha256, *, discover=False):
        holder = self.connections.get(collector_sha256)
        if holder is None or holder["writer"].is_closing():
            raise ConnectionError("collector_not_connected")
        from time import monotonic
        from .exchange import read_snapshot
        from .observations import Observation
        async with holder["lock"]:
            wire = getattr(holder["reader"], "wire", holder["reader"])
            wire.origin = "diagnostic_probe"
            holder.update(ready=False, snapshots=0)
            if not holder.get("acceptance"):
                holder["reader"].profile_id=None
                holder["reader"].slave=1
                if holder.get("dialect")=="binary":
                    holder["reader"].route_qualified=False
            try:
                async with asyncio.timeout(90):
                    if holder.get("dialect") == "binary" and not holder.get("acceptance"):
                        await holder["reader"].qualify()
                    first = await read_snapshot(holder["reader"], holder["writer"])
                    holder["snapshots"] = 1
                    second = await read_snapshot(holder["reader"], holder["writer"])
                    if (first["profile_id"], first["model_code"]) != (second["profile_id"], second["model_code"]):
                        raise ValueError("identity_changed_during_verification")
            except BaseException as error:
                if not hasattr(error,"protocol_number"):
                    self._disconnect(holder)
                if isinstance(error, Exception):
                    if hasattr(error, "protocol_number"):
                        holder["emit"]("native_signature_rejected", protocol_number=error.protocol_number, model_code=error.model_code)
                    else:
                        holder["emit"]("verification_failed", code=str(error) if isinstance(error, ValueError) else type(error).__name__,
                                       **{key: getattr(error, key) for key in ("register_address", "register_count", "function", "exception_code") if isinstance(getattr(error, key, None), int)})
                    await self.record_issue(error, stage="verification")
                if discover:
                    from .discovery import new_search
                    state=new_search(holder["dialect"])
                    self.profile_searches[collector_sha256]=state
                    if holder["writer"].is_closing():
                        state["state"]="waiting_for_reconnect"
                    else:
                        self.schedule_profile_search(collector_sha256)
                raise
            holder["native_reads"] += 2
            holder["snapshots"] = 2
            holder["ready"] = True
            holder["proof"] = second
            holder["verified_at"] = monotonic()
            self.observation = Observation(second["values"], holder["verified_at"])
            holder["emit"]("snapshot_complete", profile_id=second["profile_id"], model_code=second["model_code"],
                           snapshots=2, values=second["values"])
        return self.candidate_view(holder)

    async def discover_profiles(self, collector_sha256, *, resume=False):
        from .discovery import new_search,search
        holder = self.connections.get(collector_sha256)
        if not self._connected(holder):
            raise ConnectionError("collector_not_connected")
        state = self.profile_searches.get(collector_sha256)
        if self.storage:
            enrolled=next((d for d in await asyncio.to_thread(self.storage.list_devices) if d["collector_sha256"]==collector_sha256),None)
            if enrolled and (not state or state.get("device_id")!=enrolled["device_id"]):
                raise ValueError("profile_search_requires_unenrolled_collector")
            if enrolled and (not resume or monotonic()>=state["expires"]):
                raise ValueError("profile_search_expired")
            if enrolled and await asyncio.to_thread(self.storage.has_unresolved,enrolled["device_id"]):
                raise ValueError("device_busy_or_unresolved")
        if holder["lock"].locked():
            raise ValueError("device_busy_or_unresolved")
        if not resume or state is None or monotonic() >= state["expires"]:
            if len(self.profile_searches) >= 16:
                self.profile_searches.pop(next(iter(self.profile_searches)))
            state = new_search(holder["dialect"])
            self.profile_searches[collector_sha256] = state
        async with holder["lock"]:
            state["state"]="searching"
            holder.pop("acceptance",None)
            holder.pop("proof",None)
            holder.update(ready=False,profile_verified=False)
            holder["reader"].write_authorized=False
            try:
                await search(holder,state)
            except asyncio.CancelledError:
                self._disconnect(holder)
                state["state"]="cancelled"
                raise
            finally:
                self._notify()
        return self.search_view(collector_sha256)

    def schedule_profile_search(self,key,resume=True):
        if key in self._profile_jobs and not self._profile_jobs[key].done():
            raise ValueError("profile_search_busy")
        if not self.compatibility.view()["report_id"]:
            self.compatibility.start({"symptom":"Profile recognition requested; compare inferred measurements with the device display."})
        async def run():
            from .storage import StorageError
            try:
                await self.discover_profiles(key,resume=resume)
            except (ValueError,ConnectionError,TimeoutError,StorageError) as error:
                if key in self.profile_searches:
                    self.profile_searches[key]["state"]="failed"
                await self.record_issue(error,stage="profile_discovery")
        task=asyncio.create_task(run())
        self._profile_jobs[key]=task
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task.add_done_callback(lambda done:self._profile_jobs.pop(key,None) if self._profile_jobs.get(key) is done else None)

    async def cancel_profile_search(self,key):
        state=self.profile_searches.get(key)
        if state:
            state["state"]="cancelled"
        task=self._profile_jobs.get(key)
        if task:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        self._notify()

    async def recheck_profile(self,device_id,variant_id=None):
        """Offer a fresh binding for the same profile without replacing HA IDs."""
        from .discovery import new_search
        async with self._command_lock(device_id):
            device=await asyncio.to_thread(self.storage.device,device_id)
            if not device or not await asyncio.to_thread(self.storage.profile_acceptance,device_id):
                raise ValueError("profile_acceptance_required")
            if await asyncio.to_thread(self.storage.has_unresolved,device_id):
                raise ValueError("device_busy_or_unresolved")
            target=variant_id or device["profile_id"]
            if target!=device["profile_id"] and {target,device["profile_id"]}!={"pi30","pi30_max"}:
                raise ValueError("unsupported_profile_variant")
            key=device["collector_sha256"]
            holder=self.connections.get(key)
            if not self._connected(holder) or holder["lock"].locked() or key in self._profile_jobs:
                raise ValueError("collector_missing_or_busy")
            state=new_search(holder["dialect"],profile_id=target)
            state["plans"]=[plan for plan in state["plans"] if plan[0]==target]
            state["device_id"]=device_id
            self.profile_searches[key]=state
            holder.update(profile_verified=False,ready=False)
            self.schedule_profile_search(key)
        return {"started":True}

    def search_view(self, key):
        state = self.profile_searches.get(key)
        if not state:
            return None
        return {"collector_sha256":key,"state":"expired" if monotonic()>state["expires"] else state["state"],
                "device_id":state.get("device_id"),
                "tested":state["index"],"total":len(state["plans"]),"candidates":state["candidates"],
                "attempts":state["attempts"][-64:]}

    async def select_profile(self, collector_sha256, fingerprint, acknowledged, allow_control=True):
        state=self.profile_searches.get(collector_sha256) or {}
        async with self._command_lock(state.get("device_id") or collector_sha256):
            return await self._select_profile(collector_sha256,fingerprint,acknowledged,allow_control)

    async def _select_profile(self, collector_sha256, fingerprint, acknowledged, allow_control):
        from .discovery import confirm
        if acknowledged is not True:
            raise ValueError("profile_warning_acknowledgement_required")
        state = self.profile_searches.get(collector_sha256)
        if not state or monotonic() > state["expires"]:
            raise ValueError("profile_search_expired")
        candidate = next((item for item in state["candidates"] if item["fingerprint"]==fingerprint),None)
        if candidate is None:
            raise ValueError("profile_not_suggested")
        device_id=state.get("device_id")
        if device_id:
            device=await asyncio.to_thread(self.storage.device,device_id)
            if not device or (device["profile_id"]!=candidate["profile_id"] and {device["profile_id"],candidate["profile_id"]}!={"pi30","pi30_max"}) or device["collector_sha256"]!=collector_sha256:
                raise ValueError("profile_acceptance_mismatch")
            if await asyncio.to_thread(self.storage.has_unresolved,device_id):
                raise ValueError("device_busy_or_unresolved")
        holder = self.connections.get(collector_sha256)
        if not self._connected(holder):
            raise ConnectionError("collector_not_connected")
        if holder["lock"].locked():
            raise ValueError("profile_search_busy")
        async with holder["lock"]:
            try:
                result = await confirm(holder,candidate)
                holder.update(ready=True,snapshots=2,proof=result,verified_at=monotonic(),
                              acceptance={"profile_id":candidate["profile_id"],"fingerprint":fingerprint,"binding":candidate["binding"],
                                           "allow_control":True,"warning_version":2,"basis":candidate["basis"]})
                holder["profile_verified"]=True
                holder.pop("profile_change_required",None)
                if device_id:
                    await self._durable(self.storage.accept_profile,device_id,holder["acceptance"],device["profile_id"])
                    self.profile_acceptances[device_id]=holder["acceptance"]
                    await self._bind_holder_route(device_id,holder)
                    self._next_poll[device_id]=0
                holder["emit"]("experimental_profile_selected",profile_id=candidate["profile_id"],fingerprint=fingerprint,
                                allow_control=True,binding=candidate["binding"],warning_version=2)
                state["state"]="selected"
            except BaseException:
                self._disconnect(holder)
                raise
        self._notify()
        if device_id:
            self.profile_searches.pop(collector_sha256,None)
        return {**self.candidate_view(holder),"device_id":device_id}

    async def _configure_profile(self, device, holder):
        record = await asyncio.to_thread(self.storage.profile_acceptance,device["device_id"])
        if record:
            self.profile_acceptances[device["device_id"]]=record
            adapter=holder["reader"]
            if record["binding"].get("transport") != holder.get("dialect"):
                raise ValueError("accepted_profile_transport_changed")
            from .drivers import definition_hash
            saved_definition=record["binding"].get("definition_sha256")
            if saved_definition is not None and saved_definition!=definition_hash(record["profile_id"],record["binding"].get("effective_profile_id")):
                raise ValueError("accepted_profile_fingerprint_changed")
            adapter.profile_id=record["profile_id"]
            adapter.accepted_fingerprint=record["fingerprint"]
            adapter.slave=record["binding"]["slave"]
            if holder.get("dialect")=="binary":
                adapter.route=tuple(record["binding"]["route"])
            # Consent is necessary, but each write still rechecks the fingerprint
            # and current settings through the durable executor.
            adapter.write_authorized=True
        elif device["profile_id"] != "modbus_protocol_4":
            raise ValueError("profile_acceptance_required")
        elif holder.get("dialect") == "binary":
            # The retained reference ID uses the same Protocol 4 write executor.
            # Qualification is session-local; every write still re-reads identity.
            holder["reader"].write_authorized = bool(holder.get("profile_verified") and holder["reader"].route_qualified)

    async def set_experimental_control(self,device_id,enabled,fingerprint,acknowledged=False):
        if enabled and acknowledged is not True:
            raise ValueError("profile_warning_acknowledgement_required")
        async with self._command_lock(device_id):
            record=await self._durable(self.storage.set_experimental_control,device_id,enabled,fingerprint)
            self.profile_acceptances[device_id]=record
            self.compatibility.emit("experimental_control_preference",profile_id=record["profile_id"],enabled=bool(enabled),fingerprint=fingerprint)
        self._notify()
        return record

    def _notify(self):
        if self.on_update is not None:
            self.on_update()

    def _expire_observations(self):
        availability = {key: observation.available(monotonic()) for key, observation in self.observations.items()}
        if availability != self._availability:
            self._availability = availability
            self._notify()

    async def _expiry_loop(self):
        # Expiry must be published even while a different device is timing out.
        while True:
            await asyncio.sleep(1)
            self._expire_observations()
            if not self.compatibility.view()["active"]:
                for task in list(self._compatibility_tasks):
                    task.cancel()

    async def _poll_loop(self):
        while True:
            await asyncio.sleep(1)
            if self.storage is None:
                continue
            devices = await asyncio.to_thread(self.storage.list_devices)
            for device in devices:
                self.collection_enabled[device["device_id"]] = device["enabled"]
                if not device["enabled"]:
                    continue
                if device["device_id"] in self._polling:
                    continue
                holder = self.connections.get(device["collector_sha256"])
                if holder is None or holder["closed"].is_set():
                    continue
                search=self.profile_searches.get(device["collector_sha256"])
                if holder.get("profile_change_required") or (search and search.get("device_id") and monotonic()<search["expires"]
                    and search["state"] not in ("cancelled","complete","expired","failed")):
                    continue
                if monotonic() < self._next_poll.get(device["device_id"], 0):
                    continue
                elapsed = monotonic() - self._polled.get(device["device_id"], 0)
                if device["device_id"] in self._polled and elapsed < device["poll_interval"]:
                    continue
                device_id = device["device_id"]
                task = asyncio.create_task(self._poll_device(device_id))
                self._polling[device_id] = task
                self.tasks.add(task)
                task.add_done_callback(lambda finished, key=device_id: self._poll_finished(key, finished))

    def _poll_finished(self, device_id, task):
        self.tasks.discard(task)
        if self._polling.get(device_id) is task:
            self._polling.pop(device_id, None)

    async def _poll_device(self, device_id):
        try:
            device = await asyncio.to_thread(self.storage.device, device_id)
            if device and self._reset_due(device) and not await asyncio.to_thread(self.storage.has_unresolved, device_id):
                result = await self.reset_collector(device_id, automatic=True)
                if result["reset"] != "skipped":
                    return
            await self.poll_once(device_id)
            if self._planned_reconnect.pop(device_id, False):
                self._next_poll[device_id] = monotonic()
            elif device_id in self._settings_observed:
                self._note_success(device_id)
            else:
                # A valid telemetry snapshot does not make a failed settings
                # exchange a healthy cycle or reset its failure backoff.
                self._note_failure(device_id)
        except Exception as err:
            if str(err) == "planned_tid_rotation":
                self._next_poll[device_id] = monotonic()
                return
            await self.record_issue(err, device_id, "poll")
            self._note_failure(device_id)

    async def poll_once(self, device_id):
        self._planned_reconnect.pop(device_id, None)
        device = await asyncio.to_thread(self.storage.device, device_id)
        holder = None if device is None else self.connections.get(device["collector_sha256"])
        if device is None or holder is None or holder["writer"].is_closing():
            raise ConnectionError("collector_not_connected")
        from .exchange import read_settings, read_snapshot
        from .observations import Observation
        from .parameters import decode_observed
        started = monotonic()
        try:
            async with holder["lock"]:
                if not self._connected(holder):
                    raise ConnectionError("collector_not_connected")
                await self._configure_profile(device,holder)
                wire = getattr(holder["reader"], "wire", holder["reader"])
                wire.origin = "normal_poll"
                if holder.get("dialect") == "binary" and device["profile_id"] == "modbus_protocol_4":
                    await holder["reader"].qualify()
                snapshot = await read_snapshot(holder["reader"], holder["writer"])
                holder["profile_verified"]=True
                observed_at = monotonic()
                observed_utc = datetime.now(timezone.utc).isoformat()
                try:
                    registers = await read_settings(holder["reader"], holder["writer"])
                    settings = decode_observed(registers,fields_for(device["profile_id"]))
                    self.settings_registers[device_id] = registers
                    self.parameter_readbacks.pop(device_id, None)
                    self._settings_observed[device_id] = monotonic()
                    self.settings_observed_at[device_id] = datetime.now(timezone.utc).isoformat()
                    holder["emit"]("settings_complete", values=settings)
                except (ValueError, ConnectionError, TimeoutError) as error:
                    self._settings_observed.pop(device_id, None)
                    if str(error) == "planned_tid_rotation":
                        self._planned_reconnect[device_id] = True
                    else:
                        await self.record_issue(error, device_id, "settings_read")
                    self._disconnect(holder)
                    settings = dict(self.settings.get(device_id, {}))
                await self._bind_holder_route(device_id, holder)
        except BaseException as error:
            if str(error) in ("accepted_profile_fingerprint_changed","profile_native_protocol_mismatch","profile_identity_anchor_mismatch","accepted_profile_transport_changed"):
                holder.update(profile_verified=False,profile_change_required=True)
                self._settings_observed.pop(device_id,None)
                self.observations.pop(device_id,None)
                self._notify()
            else:
                self._disconnect(holder)
            raise
        self.observations[device_id] = Observation(snapshot["values"], observed_at, observed_utc)
        self.native_identity[device_id] = {key: snapshot[key] for key in ("profile_id", "protocol_number", "model_code")}
        self.poll_cycles[device_id] += 1
        holder["emit"]("snapshot_complete", profile_id=snapshot["profile_id"], model_code=snapshot["model_code"], values=snapshot["values"])
        self.poll_duration_ms[device_id] = round((monotonic() - started) * 1000, 1)
        self.settings[device_id] = settings
        self._polled[device_id] = monotonic()
        self._notify()
        try:
            await self.reconcile(device_id)
            if device_id in self._settings_observed:
                await self._maybe_clock(device, settings.get("inverter_datetime"))
        except Exception as err:
            await self.record_issue(err, device_id, "reconcile_or_clock")
            if isinstance(err, (ConnectionError, TimeoutError)):
                self._disconnect(holder)
        return self.observations[device_id]

    def _note_failure(self, device_id):
        count = self._failures.get(device_id, 0) + 1
        self._failures[device_id] = count
        self._healthy[device_id] = 0
        self._next_poll[device_id] = monotonic() + (3, 10, 30)[min(count, 3) - 1]

    def _remember_parameter(self, device_id, field, words):
        from .parameters import decode_observed
        registers = {field.address + offset: word for offset, word in enumerate(words)}
        actual = decode_observed(registers,(field,)).get(field.key)
        self.settings.setdefault(device_id, {})[field.key] = actual
        self.settings_registers.setdefault(device_id, {}).update(registers)
        self.parameter_readbacks.setdefault(device_id, {})[field.key] = {
            "value": actual, "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        # A single-field readback never refreshes the complete settings group TTL.
        return actual

    def _note_success(self, device_id):
        healthy = self._healthy.get(device_id, 0) + 1
        self._healthy[device_id] = healthy
        if healthy >= 3:
            self._failures[device_id] = 0

    async def reconcile(self, device_id):
        async with self._command_lock(device_id):
            return await self._reconcile(device_id)

    async def _reconcile(self, device_id):
        records = await asyncio.to_thread(self.storage.unresolved, device_id)
        if not records:
            return []
        device = await asyncio.to_thread(self.storage.device, device_id)
        holder = None if device is None else self.connections.get(device["collector_sha256"])
        if not self._connected(holder):
            return []
        from .exchange import read_words, read_identity
        from .parameters import FIELDS, decode_observed, encode_value, readback_matches
        confirmed = []
        for record in records:
            field = next(item for item in fields_for(device["profile_id"]) if item.key == record["request"]["key"])
            words = tuple(record["planned_words"]) if "planned_words" in record else encode_value(field, record.get("send_value", record["request"]["value"]))
            async with holder["lock"]:
                if not self._connected(holder):
                    return confirmed
                try:
                    await self._configure_profile(device,holder)
                    if holder.get("dialect") == "binary" and device["profile_id"] == "modbus_protocol_4":
                        await holder["reader"].qualify()
                    profile, _, _ = await read_identity(holder["reader"], holder["writer"])
                    if profile.profile_id != device["profile_id"]:
                        raise ValueError("profile_changed")
                    observed, _, _ = await read_words(holder["reader"], holder["writer"], field.address, len(words))
                except BaseException:
                    self._disconnect(holder)
                    raise
            actual = self._remember_parameter(device_id, field, observed)
            plan_matches=True
            if record.get("write_plan"):
                from .ascii_settings import readback_matches as plan_readback_matches
                plan_matches=plan_readback_matches(record["write_plan"],getattr(holder["reader"],"latest_ascii_settings",{}))
            if not plan_matches or not readback_matches(field, words, observed, record, device["poll_interval"]):
                await self._durable(self.storage.observe_operation, record["operation_id"], actual)
                continue
            await self._durable(self.storage.resolve_operation, record["operation_id"])
            confirmed.append(record["operation_id"])
        return confirmed

    async def accept_current_value(self, device_id, operation_id, expected_value, actor_id, expected_observed_at=None):
        """Explicit admin resolution: re-read and keep the current value, never write."""
        from .exchange import read_identity, read_words
        from .parameters import FIELDS, decode_observed, encode_value, readback_matches
        async with self._command_lock(device_id):
            record = await asyncio.to_thread(self.storage.operation, operation_id)
            if record is None or record["device_id"] != device_id:
                raise ValueError("operation_not_found")
            if not record["unresolved"]:
                return record
            device = await asyncio.to_thread(self.storage.device,device_id)
            field = next(item for item in fields_for(device["profile_id"]) if item.key == record["request"]["key"])
            if field.kind == "datetime" and (expected_value != record.get("last_observed_value") or expected_observed_at != record.get("last_observed_at")):
                raise ValueError("observed_value_changed")
            device = await asyncio.to_thread(self.storage.device, device_id)
            holder = self.connections.get(device["collector_sha256"])
            if not self._connected(holder):
                raise ConnectionError("collector_not_connected")
            async with holder["lock"]:
                try:
                    await self._configure_profile(device,holder)
                    if holder.get("dialect") == "binary" and device["profile_id"] == "modbus_protocol_4":
                        await holder["reader"].qualify()
                    profile, _, _ = await read_identity(holder["reader"], holder["writer"])
                    if profile.profile_id != device["profile_id"]:
                        raise ValueError("profile_changed")
                    words, _, _ = await read_words(holder["reader"], holder["writer"], field.address, 6 if field.kind == "datetime" else 1)
                except BaseException:
                    self._disconnect(holder)
                    raise
                actual = decode_observed({field.address + i: word for i, word in enumerate(words)},(field,)).get(field.key)
                matches = actual == expected_value
                if field.kind == "datetime":
                    matches = readback_matches(field, encode_value(field, expected_value), words,
                                               {"send_intent_at": expected_observed_at}, poll_interval=1)
                if actual is None or not matches:
                    raise ValueError("observed_value_changed")
                await self._durable(self.storage.observe_operation, operation_id, actual)
                result = await self._durable(self.storage.resolve_operation, operation_id, "accepted_current_value", actor_id)
                self._remember_parameter(device_id, field, words)
            self._notify()
            return result

    async def _maybe_clock(self, device, observed):
        if not self.transport_capabilities(device).get("clock_write", False):
            return None
        from .policy import clock_write_allowed
        if not observed or not clock_write_allowed(device["clock_sync"]):
            return None
        if await asyncio.to_thread(self.storage.has_unresolved, device["device_id"]):
            return None
        from .policy import MAX_CLOCK_CORRECTION_SECONDS, clock_drift_seconds
        target = self.now().replace(microsecond=0)
        drift = clock_drift_seconds(observed, target.isoformat())
        if drift < device["poll_interval"] or drift > MAX_CLOCK_CORRECTION_SECONDS:
            if drift > MAX_CLOCK_CORRECTION_SECONDS:
                await self.record_issue("clock_correction_too_large", device["device_id"], "clock")
            return None
        return await self.apply(device["device_id"], "inverter_datetime", target.isoformat(), str(uuid.uuid4()), clock_sync=True, actor_name="Automatic clock sync")

    async def apply(self, device_id, key, value, operation_id, *, clock_sync=False, expected_value=UNSPECIFIED, actor_name=None):
        if self._queued.get(device_id, 0) >= 16 or len(self._commands) >= 64:
            raise ValueError("command_queue_full")
        task = asyncio.current_task()
        self._queued[device_id] = self._queued.get(device_id, 0) + 1
        self._commands.add(task)
        try:
            admission = await asyncio.to_thread(self.storage.device, device_id)
            revision = admission["policy_revision"] if admission is not None else None
            lock = self._command_lock(device_id)
            async with asyncio.timeout(30):
                await lock.acquire()
            try:
                return await self._apply(device_id, key, value, operation_id, clock_sync=clock_sync,
                                         revision=revision, expected_value=expected_value, actor_name=actor_name)
            finally:
                lock.release()
        finally:
            self._commands.discard(task)
            self._queued[device_id] -= 1

    @staticmethod
    def _check_permission(device, field, clock_sync):
        from .parameters import execution_ready
        from .policy import clock_write_allowed
        if device is None or field is None:
            raise ValueError("device_or_parameter_missing")
        if not device["enabled"]:
            raise ValueError("device_disabled")
        if clock_sync:
            if field.key != "inverter_datetime" or not clock_write_allowed(device["clock_sync"]):
                raise ValueError("clock_write_not_allowed")
        elif not execution_ready(field):
            raise ValueError("editing_not_allowed")

    async def _apply(self, device_id, key, value, operation_id, *, clock_sync, revision, expected_value, actor_name=None):
        from .exchange import read_identity, read_settings, read_words, write_words
        from .parameters import FIELDS, decode_observed, encode_value, validate_change, readback_matches
        from .storage import StorageError

        request = {"key": key, "value": value, "clock_sync": clock_sync}
        if expected_value is not UNSPECIFIED:
            request["expected_value"] = expected_value
        saved = await asyncio.to_thread(self.storage.operation, operation_id)
        if saved is not None:
            if saved["device_id"] != device_id or saved["request"] != request:
                raise StorageError("operation_id_conflict")
            # A duplicate is a status query, including after restart/disconnection.
            return saved
        device = await asyncio.to_thread(self.storage.device, device_id)
        field = next((item for item in fields_for(device["profile_id"] if device else "") if item.key == key), None)
        self._check_permission(device, field, clock_sync)
        words = encode_value(field, value)
        holder = self.connections.get(device["collector_sha256"])
        if not self._connected(holder):
            raise ConnectionError("collector_not_connected")
        async with holder["lock"]:
            if not self._connected(holder):
                raise ConnectionError("collector_session_changed")
            await self._configure_profile(device,holder)
            if not self.transport_capabilities(device).get("inverter_write",False):
                raise ValueError("transport_write_unsupported")
            if clock_sync and not self.transport_capabilities(device).get("clock_write",False):
                raise ValueError("transport_clock_unsupported")
            wire = getattr(holder["reader"], "wire", holder["reader"])
            wire.origin = "automatic_maintenance" if clock_sync else "manual_command"
            current = await asyncio.to_thread(self.storage.device, device_id)
            self._check_permission(current, field, clock_sync)
            if current["policy_revision"] != revision:
                raise ValueError("permissions_changed")
            if await asyncio.to_thread(self.storage.has_unresolved, device_id):
                raise StorageError("device_busy_or_unresolved")
            # Never authorize a write from a cached snapshot or a collector ID alone.
            try:
                profile, _, _ = await read_identity(holder["reader"], holder["writer"])
                if profile.profile_id != current["profile_id"]:
                    raise ValueError("profile_changed")
                await self._bind_holder_route(device_id, holder)
                if (await asyncio.to_thread(self.storage.device, device_id))["policy_revision"] != revision:
                    raise ValueError("permissions_changed")
                baseline_registers = await read_settings(holder["reader"], holder["writer"])
                baseline = decode_observed(baseline_registers,fields_for(device["profile_id"]))
            except BaseException:
                self._disconnect(holder)
                raise
            validate_change(field, value, baseline)
            if expected_value is not UNSPECIFIED and baseline.get(key) != expected_value:
                raise ValueError("baseline_conflict")
            if field.mask is not None:
                from .parameters import merge_masked_value
                words=merge_masked_value(field,words,baseline_registers.get(field.address))
            write_plan=None
            if device["profile_id"] in ("pi30","pi30_max","pi18","g_ascii"):
                from .ascii_settings import prepare
                write_plan=prepare(device["profile_id"],field.address,words,baseline_registers,getattr(holder["reader"],"setting_choices",None))
            send_value = None
            target_created = None
            if clock_sync:
                from .policy import MAX_CLOCK_CORRECTION_SECONDS, clock_drift_seconds
                observed_clock = baseline.get("inverter_datetime")
                # Preflight may take time: persist a freshly computed clock target,
                # separately from the caller's immutable request, before claiming send.
                send_value = self.now().replace(microsecond=0).isoformat()
                target_created = monotonic()
                if not observed_clock or clock_drift_seconds(observed_clock, send_value) > MAX_CLOCK_CORRECTION_SECONDS:
                    raise ValueError("clock_correction_too_large")
                words = encode_value(field, send_value)
            sent = False
            admission_started = False
            claim_started = False
            try:
                admission_started = True
                send_options = {"send_value": send_value} if clock_sync else {}
                if field.mask is not None:
                    send_options["planned_words"]=words
                if write_plan is not None:
                    send_options["planned_words"]=words
                    send_options["write_plan"]=write_plan
                await self._durable(self.storage.accept_operation, device_id, operation_id, request, actor_name=actor_name, **send_options)
                claim_started = True
                if not await self._durable(self.storage.claim_send, operation_id):
                    return await asyncio.to_thread(self.storage.operation, operation_id)
                claimed = await asyncio.to_thread(self.storage.operation, operation_id)
                current = await asyncio.to_thread(self.storage.device, device_id)
                self._check_permission(current, field, clock_sync)
                if current["policy_revision"] != revision:
                    raise ValueError("permissions_changed")
                if not self._connected(holder):
                    raise ConnectionError("collector_session_changed")
                if target_created is not None and monotonic() - target_created > 2:
                    raise ValueError("clock_target_expired")
                sent = True
                if write_plan is not None:
                    holder["reader"].pending_ascii_write=write_plan
                await write_words(holder["reader"], holder["writer"], field.address, words)
                observed, _, _ = await read_words(holder["reader"], holder["writer"], field.address, len(words))
                actual = self._remember_parameter(device_id, field, observed)
                plan_matches=True
                if write_plan is not None:
                    from .ascii_settings import readback_matches as plan_readback_matches
                    plan_matches=plan_readback_matches(write_plan,getattr(holder["reader"],"latest_ascii_settings",{}))
                if not plan_matches or not readback_matches(field, words, observed, claimed, current["poll_interval"]):
                    await self._durable(self.storage.observe_operation, operation_id, actual)
                    return await self._durable(self.storage.finish_operation, operation_id, state="reconciling", outcome="readback_mismatch", unresolved=True, reason="readback_mismatch")
                result = await self._durable(self.storage.finish_operation, operation_id, state="completed", outcome="confirmed", unresolved=False, reason=None)
                self._notify()
                return result
            except BaseException as error:
                if sent:
                    # A late ACK must not become another transaction's response.
                    self._disconnect(holder)
                    await self._durable(self.storage.finish_operation, operation_id, state="reconciling", outcome="uncertain", unresolved=True, reason="send_uncertain")
                elif claim_started:
                    await self._durable(self.storage.finish_operation, operation_id, state="completed", outcome="not_sent", unresolved=False, reason="send_not_started")
                elif admission_started:
                    await self._durable(self.storage.cancel_unsent, operation_id, device_id, request)
                if isinstance(error, Exception):
                    await self.record_issue(error, device_id, "command", key)
                raise

    async def enroll(self, collector_sha256, name):
        holder=self.candidates.get(collector_sha256)
        if not self._connected(holder):
            raise ValueError("verification_required")
        if holder["lock"].locked():
            raise ValueError("profile_search_busy")
        async with holder["lock"]:
            return await self._enroll(collector_sha256,name)

    async def _enroll(self, collector_sha256, name):
        holder = self.candidates.get(collector_sha256)
        if not self._connected(holder) or not holder.get("ready") or monotonic() - holder.get("verified_at", float("-inf")) > 90:
            raise ValueError("verification_required")
        profile_id = holder["proof"]["profile_id"]
        device_id = await asyncio.to_thread(self.storage.enroll, collector_sha256, name, profile_id)
        if holder.get("acceptance"):
            await self._durable(self.storage.accept_profile,device_id,holder["acceptance"])
            self.profile_acceptances[device_id]=holder["acceptance"]
        self.profile_searches.pop(collector_sha256,None)
        await self._bind_holder_route(device_id, holder)
        self._enrolled_monotonic[device_id] = monotonic()
        holder["device_id"] = device_id
        self._notify()
        return device_id

    async def remove_device(self, device_id):
        if self._queued.get(device_id, 0):
            raise ValueError("device_busy_or_unresolved")
        async with self._command_lock(device_id):
            device = await asyncio.to_thread(self.storage.device, device_id)
            if device is None:
                return
            polling = self._polling.get(device_id)
            if polling is not None:
                polling.cancel()
                await asyncio.gather(polling, return_exceptions=True)
            try:
                await self._durable(self.storage.remove_device, device_id)
            finally:
                # A cancelled waiter may still have committed deletion. Publish the
                # actual result; HA cleanup also runs at the next setup if interrupted.
                if await asyncio.to_thread(self.storage.device, device_id) is None:
                    for cache in (self._enrolled_monotonic, self.observations, self.settings, self.settings_registers, self.parameter_readbacks, self._settings_observed, self._polled,
                                  self._failures, self._healthy, self._next_poll, self._availability, self.collection_enabled,
                                  self.native_identity, self.settings_observed_at, self.poll_cycles, self.poll_errors, self._planned_reconnect, self.poll_duration_ms):
                        cache.pop(device_id, None)
                    holder = self.connections.get(device["collector_sha256"])
                    if holder is not None:
                        holder.update(ready=False, snapshots=0)
                        holder.pop("proof", None)
                        holder.pop("verified_at", None)
                    self._notify()

    def candidate_view(self, holder):
        from .catalogue import MAPS
        from .profile_layers import describe_profile
        from .profile_catalog import profile_name
        profile_id=(holder.get("proof") or {}).get("profile_id")
        acceptance = holder.get("acceptance") or {}
        ready = holder.get("ready", False) and 0 <= monotonic() - holder.get("verified_at", float("-inf")) <= 90
        return {
            "identity_ref": holder["identity_ref"],
            "identity_sha256": holder["identity_sha256"],
            "source": holder["source"],
            "snapshots": holder.get("snapshots", 0),
            "ready": ready,
            "profile_id": (holder.get("proof") or {}).get("profile_id"),
            "model_code": (holder.get("proof") or {}).get("model_code"),
            "transport": holder.get("dialect", "at"), "listener_port": holder["listener_port"],
            "capabilities": holder.get("capabilities"),
            "profile_name": profile_name(profile_id),
            "experimental": bool(holder.get("acceptance")),
            "profile_layers": describe_profile(profile_id, identity=holder.get("proof"), binding=acceptance.get("binding"),
                                               basis=acceptance.get("basis"), evidence="checked" if ready else "saved"),
        }

    def transport_capabilities(self, device):
        from .transport import AT_CAPABILITIES
        holder = self.connections.get(device["collector_sha256"])
        caps = dict(holder.get("capabilities", AT_CAPABILITIES)) if holder else {key: False for key in AT_CAPABILITIES}
        if device.get("profile_id") == "modbus_protocol_4" and holder and holder.get("dialect") == "binary":
            caps["inverter_write"] = bool(holder.get("profile_verified") and getattr(holder["reader"],"route_qualified",False))
        if device.get("profile_id") != "modbus_protocol_4":
            accepted=self.profile_acceptances.get(device["device_id"],{})
            caps["inverter_write"]=bool(holder and holder.get("profile_verified") and accepted and fields_for(device.get("profile_id",""))
                                       and accepted.get("binding",{}).get("transport")==holder.get("dialect"))
            caps["clock_write"]=bool(device.get("profile_id")=="smg_4" and holder and holder.get("dialect")=="at" and caps["inverter_write"])
            caps["settings_read"]=bool(fields_for(device.get("profile_id","")))
        return caps

    def schedule_compatibility_probe(self):
        task = asyncio.create_task(self.compatibility_probe())
        self.tasks.add(task)
        self._compatibility_tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task.add_done_callback(self._compatibility_tasks.discard)

    async def compatibility_probe(self):
        """Reuse current owners and polls; unidentified sockets are never reopened."""
        from .storage import StorageError
        try:
            devices = await asyncio.to_thread(self.storage.list_devices) if self.storage else []
        except StorageError as error:
            self.compatibility.emit("probe_busy", reason=str(error))
            return
        enrolled = {device["collector_sha256"] for device in devices}
        for key, holder in list(self.candidates.items()):
            capture_state = self.compatibility.view()
            if not capture_state["active"]:
                return
            if holder.get("probe_run") == capture_state["report_id"]:
                continue
            holder["probe_run"] = capture_state["report_id"]
            if key in self.profile_searches:
                holder["emit"]("profile_evidence_reused")
                continue
            if key in enrolled:
                holder["emit"]("poll_evidence_reused")
                continue
            if holder["lock"].locked():
                holder["emit"]("probe_busy")
                continue
            try:
                async with asyncio.timeout(90):
                    await self.verify(key)
                    async with holder["lock"]:
                        if not self._connected(holder):
                            continue
                        from .exchange import read_settings
                        from .parameters import decode_observed
                        wire = getattr(holder["reader"], "wire", holder["reader"])
                        wire.origin = "diagnostic_probe"
                        values = decode_observed(await read_settings(holder["reader"], holder["writer"]),fields_for(getattr(holder["reader"],"profile_id",None) or "modbus_protocol_4"))
                        holder["emit"]("settings_complete", values=values)
            except asyncio.CancelledError:
                self._disconnect(holder)
                raise
            except (ValueError, ConnectionError, TimeoutError) as error:
                holder["emit"]("probe_failed", code=str(error) if isinstance(error, ValueError) else type(error).__name__,
                               **{key: getattr(error, key) for key in ("register_address", "register_count", "function", "exception_code") if isinstance(getattr(error, key, None), int)})
                self._disconnect(holder)
                pass

    async def status(self):
        from .catalogue import MAPS
        from .profile_layers import describe_profile
        from .profile_catalog import catalogue_view
        devices = await asyncio.to_thread(self.storage.list_devices) if self.storage else []
        observation = None
        if self.observation is not None:
            observation = {
                "available": self.observation.available(monotonic()),
                "age_seconds": round(self.observation.age(monotonic()), 1),
                "values": self.observation.values,
            }
        enrolled = {device["collector_sha256"] for device in devices}
        pending = [
            self.candidate_view(item)
            for item in self.candidates.values()
            if item["identity_sha256"] not in enrolled
        ]
        stages = {}
        for event in self.compatibility.recent:
            if event["kind"] not in ("tcp_received", "source_rejected", "dialect_selected", "identity_confirmed",
                                      "route_qualified", "native_signature_rejected", "verification_failed", "admission_failed", "bootstrap_exhausted"):
                continue
            session = event.get("session")
            if session is None or monotonic() - event["monotonic"] > 120:
                continue
            stages[session] = {"session_ref": session, "stage": event["kind"], "time": event["time"],
                               **{key: event[key] for key in ("listener_port", "dialect", "code", "protocol_number", "model_code") if key in event}}
        for device in devices:
            accepted=await asyncio.to_thread(self.storage.profile_acceptance,device["device_id"])
            if accepted:
                self.profile_acceptances[device["device_id"]]=accepted
            device["profile_acceptance"]=accepted
            device["profile_change_required"]=bool(self.connections.get(device["collector_sha256"],{}).get("profile_change_required"))
            device["connected"] = self._connected(self.connections.get(device["collector_sha256"]))
            holder = self.connections.get(device["collector_sha256"])
            device["transport"] = holder.get("dialect", "at") if holder else None
            device["capabilities"] = self.transport_capabilities(device)
            device["capability_reason"] = "Binary EyeBond: setting writes require current-session qualification; clock writes and module reset are unavailable." if holder and holder.get("dialect") == "binary" else None
            if accepted:
                device["capability_reason"]="Experimental profile: device compatibility is inferred. Implemented writable settings are available after fresh read checks."
                if not fields_for(device["profile_id"]):
                    device["capability_reason"]="Monitoring is available; no source-defined setting controls are implemented for this profile yet."
                if device["profile_change_required"]:
                    device["capability_reason"]="The accepted profile evidence changed. Recheck this profile and review the new proposal before control resumes."
            device["route"] = {"outer": list(holder["reader"].route), "inner_slave": holder["reader"].slave} if holder and holder.get("dialect") == "binary" else None
            device["transport_counters"] = dict(holder["reader"].counters) if holder and holder.get("dialect") == "binary" else {}
            device["selected_route"] = await asyncio.to_thread(self.storage.selected_route, device["device_id"])
            device["collector_channels"] = len(self._channels.get(device["collector_sha256"], []))
            observed = self.observations.get(device["device_id"])
            device["stale"] = observed is None or not observed.available(monotonic())
            device["profile_layers"] = describe_profile(device["profile_id"], identity=self.native_identity.get(device["device_id"]),
                binding=(accepted or {}).get("binding"), basis=(accepted or {}).get("basis"),
                evidence="recheck_required" if device["profile_change_required"] else "saved" if device["stale"] or not device["connected"] or not device["enabled"] else "observed")
            device["age_seconds"] = None if observed is None else round(observed.age(monotonic()), 1)
            device["observed_at"] = None if observed is None else observed.observed_utc
            device["last_issue"] = next((event for event in reversed(self.issues) if event.get("device_id") == device["device_id"]), None)
            device["telemetry"] = None if device["stale"] or not device["enabled"] else observed.values
            device["settings"] = self.settings.get(device["device_id"], {})
            settings_at = self._settings_observed.get(device["device_id"])
            device["settings_available"] = settings_at is not None and monotonic() - settings_at <= max(90, 5 * device["poll_interval"])
            device["unresolved"] = len(await asyncio.to_thread(self.storage.unresolved, device["device_id"]))
            device["operations"] = await asyncio.to_thread(self.storage.recent_operations, device["device_id"])
            device["poll_backoff_seconds"] = max(0, round(self._next_poll.get(device["device_id"], 0) - monotonic(), 1))
            device["module"] = self.module_info.get(device["collector_sha256"])
            device["poll_error_count"] = self.poll_errors[device["device_id"]]
            device["setting_choices"] = getattr(holder["reader"],"setting_choices",{}) if holder and "reader" in holder else {}
        return {
            "runtime_id": self.runtime_id,
            "started_at": self.started_at,
            "last_error_at": self.last_error_at,
            "listening": bool(self.servers),
            "listeners": self.listeners, "degraded": any(not item["bound"] for item in self.listeners),
            "bootstrap_preference": self.bootstrap_preference,
            "compatibility": self.compatibility.view(),
            "discovery": list(stages.values())[-8:],
            "profile_searches":[self.search_view(key) for key in self.profile_searches],
            "profile_catalogue":catalogue_view(),
            "rejected": self.rejected,
            "candidates": pending,
            "pending": pending,
            "devices": devices,
            "observation": observation,
        }
