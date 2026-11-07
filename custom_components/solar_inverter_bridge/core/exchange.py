"""Single-owner native reads. This module never opens a second connection."""

import asyncio
from contextlib import contextmanager
from time import monotonic

from .framing import FrameError, parse_read, parse_write_ack, read_request, write_request
from .observations import Observation
from .profiles import auto_profile
from .telemetry import decode, required_addresses


@contextmanager
def transaction_context(address, count, function, reader=None):
    started = monotonic()
    wire = getattr(reader, "wire", reader)
    before = getattr(wire, "received_bytes", None)
    try:
        yield
    except Exception as error:
        error.register_address = address
        error.register_count = count
        error.function = function
        error.elapsed_ms = round((monotonic() - started) * 1000)
        after = getattr(wire, "received_bytes", None)
        if type(before) is int and type(after) is int:
            error.received_bytes = after - before
        if callable(getattr(reader, "emit", None)):
            reader.emit("exchange_failed", register_address=address, register_count=count, function=function,
                        code=type(error).__name__, elapsed_ms=error.elapsed_ms,
                        received_bytes=getattr(error,"received_bytes",None))
        raise


async def exchange_at(reader, writer, query: bytes, timeout=5) -> bytes:
    """Write one AT line and read its single-line reply. The caller holds the socket lock."""
    async with asyncio.timeout(timeout):
        if hasattr(reader, "send"):
            await reader.send(query)
        else:
            writer.write(query)
            await writer.drain()
        return await reader.readuntil(b"\n")


async def read_words(reader, writer, address, count, slave=1, timeout=5, function=3):
    if getattr(reader,"profile_id",None) in ("pi30","pi30_max","pi18","g_ascii"):
        from .drivers import settings
        registers = await settings(reader,writer,addresses=set(range(address,address+count)))
        if any(address+i not in registers for i in range(count)):
            raise ValueError("parameter_not_observed")
        return tuple(registers[address+i] for i in range(count)),b"",b""
    budget = getattr(reader,"probe_budget",None)
    if budget is not None:
        if budget <= 0:
            raise ValueError("profile_probe_budget_exhausted")
        reader.probe_budget -= 1
    slave = getattr(reader, "slave", slave)
    request = read_request(address, count, slave, function)
    with transaction_context(address, count, function, reader):
        async with asyncio.timeout(timeout):
            if hasattr(reader, "exchange_inverter"):
                data = await reader.exchange_inverter(request, timeout)
                try:
                    parsed = parse_read(data, count, slave, function)
                except ValueError as error:
                    if getattr(error,"exception_code",None) is not None and len(data)!=5:
                        raise FrameError("extra_inner_exception_bytes") from error
                    ascii_candidate = len(data) >= 4 and (
                        all(byte in (10, 13) or 32 <= byte <= 126 for byte in data)
                        or (data.startswith(b"(") and data.endswith(b"\r") and all(32 <= byte <= 126 for byte in data[:-3])))
                    reader.emit("inner_payload_rejected", code=str(error), payload_kind="ascii_candidate" if ascii_candidate else "binary_or_unknown",
                                slave=slave, function=function, address=address, count=count,
                                exception_code=getattr(error, "exception_code", None))
                    raise
                if parsed is None or parsed[1] != len(data):
                    raise ValueError("incomplete_or_extra_inner_frame")
                reader.emit("register_read", address=address, count=count, slave=slave, function=function,
                            words=list(parsed[0]), origin=reader.wire.origin)
                return parsed[0], b"", request
            if hasattr(reader, "send"):
                await reader.send(request)
            else:
                writer.write(request)
                await writer.drain()
            buffer = b""
            while True:
                try:
                    parsed = parse_read(buffer, count, slave, function)
                except FrameError as error:
                    if error.exception_code is not None and hasattr(reader,"unread"):
                        reader.unread(buffer[5:])
                    raise
                if parsed is not None:
                    words, size = parsed
                    if hasattr(reader, "unread"):
                        reader.unread(buffer[size:])
                    if hasattr(reader, "emit"):
                        reader.emit("register_read", address=address, count=count, slave=slave, function=function,
                                    words=list(words), origin=reader.origin)
                    return words, buffer[size:], request
                chunk = await reader.read(256)
                if not chunk:
                    raise ConnectionError("collector_closed")
                buffer += chunk


def response_frame(words, slave=1) -> bytes:
    from .framing import crc16
    payload = bytes([slave, 3, len(words) * 2]) + b"".join(value.to_bytes(2, "big") for value in words)
    return payload + crc16(payload).to_bytes(2, "little")


async def write_words(reader, writer, address, words, slave=1, timeout=5):
    from .drivers import write_function
    function = write_function(getattr(reader,"profile_id",None))
    words = tuple(words)
    if getattr(reader,"profile_id",None) in ("pi30","pi30_max","pi18","g_ascii"):
        from .drivers import write_ascii_setting
        await write_ascii_setting(reader,address,tuple(words))
        return b"",b""
    if hasattr(reader, "exchange_inverter"):
        if not getattr(reader,"write_authorized",False):
            raise ValueError("transport_write_unsupported")
        request = write_request(address,words,reader.slave,function)
        async with asyncio.timeout(timeout):
            data = await reader.request(4,request,timeout=timeout)
            size = parse_write_ack(data,address,len(words),reader.slave,function,words[0])
            if size is None or size != len(data):
                raise ValueError("invalid_binary_write_ack")
        return b"",request
    slave = getattr(reader,"slave",slave)
    words = tuple(words)
    request = write_request(address, words, slave, function)
    with transaction_context(address, len(words), function, reader):
        async with asyncio.timeout(timeout):
            if hasattr(reader, "send"):
                await reader.send(request)
            else:
                writer.write(request)
                await writer.drain()
            buffer = b""
            while True:
                consumed = parse_write_ack(buffer, address, len(words), slave, function, words[0])
                if consumed is not None:
                    if hasattr(reader, "unread"):
                        reader.unread(buffer[consumed:])
                    return buffer[consumed:], request
                chunk = await reader.read(256)
                if not chunk:
                    raise ConnectionError("collector_closed")
                buffer += chunk


async def read_settings(reader, writer, slave=1):
    from .drivers import settings
    return await settings(reader,writer,slave)


async def read_identity(reader, writer, timeout=5):
    """Validate the native signature on the current connection."""
    if getattr(reader,"profile_id",None) not in (None,"modbus_protocol_4"):
        from .drivers import snapshot
        from .catalogue import MAPS
        result = await snapshot(reader,writer,reader.profile_id,timeout)
        if getattr(reader,"accepted_fingerprint",None) != result["fingerprint"]:
            raise ValueError("accepted_profile_fingerprint_changed")
        return MAPS[reader.profile_id],result["protocol_number"],result["model_code"]
    protocol, _, _ = await read_words(reader, writer, 184, 1, timeout=timeout)
    model, _, _ = await read_words(reader, writer, 171, 1, timeout=timeout)
    profile = auto_profile(protocol[0], model[0])
    if profile is None:
        error = ValueError("unsupported_or_unconfirmed_identity")
        error.protocol_number = protocol[0]
        error.model_code = model[0]
        raise error
    return profile, protocol[0], model[0]


async def read_snapshot(reader, writer):
    """Read identity and one complete Protocol 4 snapshot on the current owner."""
    if getattr(reader,"profile_id",None) not in (None,"modbus_protocol_4"):
        from .drivers import snapshot
        result = await snapshot(reader,writer,reader.profile_id)
        if getattr(reader,"accepted_fingerprint",None) != result["fingerprint"]:
            raise ValueError("accepted_profile_fingerprint_changed")
        return result
    if hasattr(reader,"emit"):
        reader.emit("profile_read_started",profile_id="smg_4",function=3,payload="modbus")
    profile, protocol_number, model_code = await read_identity(reader, writer)
    from .telemetry import read_registers
    registers = await read_registers(reader,writer)
    return {"profile_id": profile.profile_id, "protocol_number": protocol_number, "model_code": model_code, "values": decode(registers,require_full=False)}


def remember(service, values, now):
    service.observation = Observation(values, now)
    return service.observation
