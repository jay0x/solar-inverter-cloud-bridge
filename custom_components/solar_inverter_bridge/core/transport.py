"""Bounded session adapters. One socket reader and no cross-session transactions."""

import asyncio
from collections import Counter
from datetime import datetime, timezone
from time import monotonic

from .binary import BinaryFrame, decode_frame, frame_size, heartbeat_payload
from .identity import at_query, parse_at_identity, full_pn_identity

AT_CAPABILITIES = {"monitoring": True, "settings_read": True, "inverter_write": True,
                   "clock_write": True, "module_reset": True, "module_metadata": True}
BINARY_CAPABILITIES = {**AT_CAPABILITIES, "inverter_write": False, "clock_write": False, "module_reset": False}


class WireReader:
    """Retain unread tails and original receive chunks, including failed frames."""

    def __init__(self, reader, writer, emit):
        self.raw = reader
        self.writer = writer
        self.emit = emit
        self.buffer = bytearray()
        self.origin = "identity_probe"
        self.received_bytes = 0
        self.last_receive_monotonic = None

    def unread(self, data):
        self.buffer[:0] = data

    def at_eof(self):
        return not self.buffer and self.raw.at_eof()

    async def read(self, count=256):
        if self.buffer:
            data = bytes(self.buffer[:count])
            del self.buffer[:count]
            return data
        data = await self.raw.read(count)
        if data:
            self.received_bytes += len(data)
            self.last_receive_monotonic = monotonic()
            self.emit("wire", direction="rx", data=data, origin=self.origin)
        return data

    async def readexactly(self, count):
        data = bytearray()
        while len(data) < count:
            chunk = await self.read(count - len(data))
            if not chunk:
                raise asyncio.IncompleteReadError(bytes(data), count)
            data.extend(chunk)
        return bytes(data)

    async def readuntil(self, separator=b"\n"):
        data = bytearray()
        while True:
            end = data.find(separator)
            if end >= 0:
                size = end + len(separator)
                if size > 1024:
                    raise ValueError("at_line_too_large")
                self.unread(data[size:])
                return bytes(data[:size])
            if len(data) >= 1024:
                raise ValueError("at_line_too_large")
            chunk = await self.read(256)
            if not chunk:
                raise asyncio.IncompleteReadError(bytes(data), None)
            data.extend(chunk)

    async def send(self, data):
        self.emit("wire", direction="tx", data=data, origin=self.origin)
        self.writer.write(data)
        await self.writer.drain()


async def detect(wire, preference, hint, passive_timeout=0.5):
    """Receive before probing. A printable binary TID is not an AT classifier."""
    if preference != "auto":
        return preference, "explicit_override"
    incoming = bytearray()
    try:
        async with asyncio.timeout(passive_timeout):
            while True:
                chunk = await wire.read(256)
                if not chunk:
                    raise ConnectionError("collector_closed")
                incoming.extend(chunk)
                # A *complete identity*, not an AT prefix, establishes AT.
                if parse_at_identity(bytes(incoming)) is not None:
                    return "at", "unsolicited_identity"
                if len(incoming) >= 8:
                    try:
                        size = frame_size(incoming)
                    except ValueError:
                        size = None
                    if size is not None and len(incoming) >= size:
                        return "binary", "unsolicited_binary_candidate"
                if len(incoming) >= 4096:
                    raise ValueError("unrecognized_startup")
    except TimeoutError:
        if incoming:
            if incoming.startswith(b"AT+DTUPN:"):
                return "at", "partial_identity_candidate"
            # Fragmented binary headers cannot be discarded or mixed with AT probes.
            if len(incoming) >= 8:
                frame_size(incoming)
            return "binary", "partial_binary_candidate"
        return hint, "silent_bootstrap_hint"
    finally:
        wire.unread(incoming)


class ATTransport(WireReader):
    dialect = "at"
    capabilities = AT_CAPABILITIES
    slave = 1
    minimum_gap = 0.05
    raw_session_identified = False

    async def send(self, data):
        # Preserve the predecessor's conservative raw-session UART turnaround.
        # The caller's transaction deadline includes this wait and drain.
        if self.last_receive_monotonic is not None and self.minimum_gap:
            remaining = self.minimum_gap - (monotonic() - self.last_receive_monotonic)
            if remaining > 0:
                await asyncio.sleep(remaining)
        if self.raw_session_identified:
            # A queued raw reply has no TID and cannot belong to an unsent query.
            # timeout(0) permits an immediately buffered read but does not wait
            # for new input. Retain evidence instead of flushing or guessing.
            try:
                async with asyncio.timeout(0):
                    queued = await self.read(4096)
            except TimeoutError:
                queued = None
            if queued == b"":
                raise ConnectionError("collector_closed")
            if queued:
                self.unread(queued)
                self.emit("unsolicited_data_before_request", queued_bytes=len(queued))
                raise ValueError("unsolicited_data_before_request")
        await super().send(data)

    async def identify(self):
        from .exchange import exchange_at
        identity = parse_at_identity(bytes(self.buffer))
        if identity is not None:
            await self.readuntil()
        elif self.buffer:
            async with asyncio.timeout(5):
                identity = parse_at_identity(await self.readuntil())
        else:
            identity = parse_at_identity(await exchange_at(self, self.writer, at_query()))
        if identity is None:
            raise ValueError("invalid_identity")
        self.raw_session_identified = True
        return {**identity, "identity_method": "at_dtupn"}

    async def close(self):
        self.writer.close()


class BinaryTransport:
    dialect = "binary"
    capabilities = BINARY_CAPABILITIES

    def __init__(self, wire, *, timeout=5):
        self.wire = wire
        self.wire.minimum_gap = 0
        self.wire.raw_session_identified = False
        self.writer = wire.writer
        self.emit = wire.emit
        self.timeout = timeout
        self.probe_timeout = 2
        self.slave = 1
        self.route = (1, 1)
        self.route_qualified = False
        self.counters = Counter()
        self._tid = 0
        self._peer_tids = set()
        self._pending = None
        self._serial = asyncio.Lock()
        self._writer_lock = asyncio.Lock()
        self._failed = None
        self._closing_reason = None
        self._assembling = False
        self._reader_task = asyncio.create_task(self._reader())

    def at_eof(self):
        return self._failed is not None or self.wire.at_eof()

    async def close(self):
        self._closing_reason = self._closing_reason or "owner_closed"
        self.writer.close()
        self._reader_task.cancel()
        await asyncio.gather(self._reader_task, return_exceptions=True)

    async def _send(self, frame):
        async with self._writer_lock:
            await self.wire.send(frame.encode())

    async def _reader(self):
        try:
            while True:
                # Idle connections have no frame deadline until the first byte.
                first = await self.wire.readexactly(1)
                self._assembling = True
                async with asyncio.timeout(self.timeout):
                    header = first + await self.wire.readexactly(7)
                    size = frame_size(header)
                    data = header + await self.wire.readexactly(size - 8)
                self._assembling = False
                frame, _ = decode_frame(data)
                self.emit("binary_frame", direction="rx", tid=frame.tid, function=frame.function,
                          code=frame.code, address=frame.address, payload_length=len(frame.payload))
                if frame.function == 1 and frame.payload:
                    self.emit("heartbeat_identity_provisional", identity_length=len(frame.payload.rstrip(b"\x00")),
                              classification="prefix_not_authoritative")
                pending = self._pending
                if pending is not None:
                    request, future = pending
                    if frame.tid == request.tid and frame.function == request.function:
                        if (frame.code, frame.address) != (request.code, request.address):
                            self.counters["wrong_route"] += 1
                            self.emit("wrong_route", tid=frame.tid, function=frame.function,
                                      expected_route=[request.code, request.address], observed_route=[frame.code, frame.address])
                            continue
                        if not future.done():
                            future.set_result(frame.payload)
                        continue
                    reason = "unexpected_function" if frame.tid == request.tid else "unexpected_tid"
                    self.counters[reason] += 1
                    self.emit(reason, tid=frame.tid, function=frame.function,
                              expected_tid=request.tid, expected_function=request.function)
                self.counters["unsolicited"] += 1
                self.emit("unsolicited_frame", tid=frame.tid, function=frame.function)
                if (frame.function == 1 and 0 < len(frame.payload) <= 64
                        and all(byte == 0 or 32 <= byte <= 126 for byte in frame.payload)
                        and frame.tid > self._tid and frame.tid not in self._peer_tids
                        and (pending is None or frame.tid != pending[0].tid)):
                    # Reply to a volunteered heartbeat, never to an empty ACK or
                    # a mismatched function colliding with an outgoing request.
                    self._peer_tids.add(frame.tid)
                    async with asyncio.timeout(self.timeout):
                        await self._send(BinaryFrame(frame.tid, frame.code, frame.address, 1,
                                                    heartbeat_payload(datetime.now(timezone.utc))))
        except (Exception, asyncio.CancelledError) as error:
            self._failed = error
            if isinstance(error, ValueError):
                self.counters[str(error)] += 1
            if self._closing_reason or isinstance(error, asyncio.CancelledError):
                self.emit("session_closed", reason=self._closing_reason or "cancelled")
            else:
                self.emit("binary_reader_failed", code=str(error) if isinstance(error, ValueError) else type(error).__name__)
            if self._pending is not None and not self._pending[1].done():
                self._pending[1].set_exception(ConnectionError("binary_session_closed"))
            self.writer.close()

    async def request(self, function, payload, route=None, timeout=None):
        async with self._serial:
            if self.at_eof() or self.writer.is_closing():
                raise ConnectionError("binary_session_closed")
            while self._tid < 65535 and self._tid + 1 in self._peer_tids:
                self._tid += 1
            if self._tid >= 65535:
                self.emit("planned_tid_rotation")
                self._closing_reason = "planned_tid_rotation"
                self.writer.close()
                raise ConnectionError("planned_tid_rotation")
            self._tid += 1
            code, address = route or self.route
            frame = BinaryFrame(self._tid, code, address, function, payload)
            self.emit("binary_request", tid=frame.tid, function=function, code=code, address=address,
                      parameter=payload[0] if function == 2 and payload else None,
                      origin=self.wire.origin)
            future = asyncio.get_running_loop().create_future()
            self._pending = (frame, future)
            try:
                async with asyncio.timeout(self.timeout if timeout is None else timeout):
                    await self._send(frame)
                    return await future
            except BaseException as error:
                self.emit("transaction_failed", tid=frame.tid, function=function, code=type(error).__name__)
                if self._assembling:
                    # A timed-out partial frame must never absorb a subsequent
                    # response. Retain its original chunks and retire this socket.
                    self.emit("partial_frame_abandoned", tid=frame.tid)
                    self.writer.close()
                raise
            finally:
                self._pending = None
                if not future.done():
                    future.cancel()

    async def query(self, parameter):
        data = await self.request(2, bytes([parameter]), (1, 1))
        if len(data) < 2 or data[1] != parameter:
            self.emit("query_rejected", parameter=parameter, code="binary_parameter_mismatch")
            raise ValueError("binary_parameter_mismatch")
        if data[0] != 0:
            self.emit("query_rejected", parameter=parameter, status=data[0], code="binary_query_rejected")
            raise ValueError("binary_query_rejected")
        return data[2:]

    async def identify(self):
        # FC2 supplies the full PN even when FC1 yields only a 14-byte prefix.
        try:
            await self.heartbeat()
        except TimeoutError:
            self.emit("heartbeat_timeout", origin="identity_probe")
        identity = full_pn_identity(await self.query(2))
        if identity is None:
            raise ValueError("binary_full_identity_missing")
        return {**identity, "identity_method": "binary_fc2_parameter_2"}

    async def heartbeat(self):
        await self.request(1, heartbeat_payload(datetime.now(timezone.utc)), (0, 1))

    async def exchange_inverter(self, request, timeout=5):
        # Initial binary milestone intentionally has no write implementation.
        if len(request) < 2 or request[1] not in (3,4):
            raise ValueError("transport_write_unsupported")
        return await self.request(4, request, timeout=timeout)

    async def qualify(self):
        """Reviewed bounded routes, not a route/slave sweep or a map guess."""
        from .exchange import read_identity
        if self.route_qualified:
            return await read_identity(self, self.writer)
        async with asyncio.timeout(15):
            for route, slave in (((1, 1), 1), ((1, 255), 1), ((1, 255), 5), ((1, 1), 5)):
                self.route, self.slave = route, slave
                self.emit("route_probe", route=list(route), slave=slave, origin="diagnostic_probe")
                try:
                    result = await read_identity(self, self.writer, timeout=self.probe_timeout)
                except TimeoutError:
                    continue
                except ValueError as error:
                    # Valid but unsupported native identity must not trigger a
                    # search for some other inverter behind the collector.
                    if hasattr(error, "protocol_number"):
                        raise
                    self.emit("payload_rejected", code=str(error), route=list(route), slave=slave)
                    continue
                self.route_qualified = True
                self.emit("route_qualified", route=list(route), slave=slave,
                          protocol_number=result[1], model_code=result[2])
                return result
        raise ValueError("binary_route_not_qualified")
