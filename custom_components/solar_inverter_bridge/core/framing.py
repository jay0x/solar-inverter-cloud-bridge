"""Bounded Modbus RTU framing adapted from the MIT predecessor. No arbitrary writes."""

import hashlib
import struct


class FrameError(ValueError):
    def __init__(self, reason, exception_code=None):
        super().__init__(reason)
        self.reason = reason
        self.exception_code = exception_code


def crc16(data: bytes) -> int:
    value = 0xFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ 0xA001 if value & 1 else value >> 1
    return value


def write_request(address: int, words, slave: int = 1, function=16) -> bytes:
    words = tuple(words)
    if any(type(value) is not int for value in (address, slave, *words)):
        raise FrameError("non_integer_route")
    count = len(words)
    if not 1 <= slave <= 247 or not 0 <= address <= 65535 or not 1 <= count <= 123 or address + count > 65536:
        raise FrameError("invalid_write_range")
    if any(not 0 <= word <= 65535 for word in words):
        raise FrameError("invalid_register_word")
    if function==6 and count==1:
        body = struct.pack(">BBHH",slave,6,address,words[0])
    elif function==16:
        body = struct.pack(">BBHHB", slave, 16, address, count, count * 2) + b"".join(word.to_bytes(2, "big") for word in words)
    else:
        raise FrameError("unsupported_write_function")
    return body + crc16(body).to_bytes(2, "little")


def parse_write_ack(data: bytes, address: int, count: int, slave: int = 1, function=16, value=None):
    if len(data) < 2:
        return None
    if data[0] != slave:
        raise FrameError("unexpected_slave_or_transport")
    if data[1] == (function | 0x80):
        if len(data) < 5:
            return None
        frame = data[:5]
        if crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
            raise FrameError("crc_mismatch")
        raise FrameError("modbus_exception", frame[2])
    if data[1] != function:
        raise FrameError("unexpected_function_or_transport")
    if len(data) < 8:
        return None
    frame = data[:8]
    if crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
        raise FrameError("crc_mismatch")
    if frame[:6] != struct.pack(">BBHH", slave, function, address, value if function==6 else count):
        raise FrameError("wrong_ack_route")
    return 8


def read_request(address: int, count: int, slave: int = 1, function=3) -> bytes:
    if any(type(value) is not int for value in (address, count, slave)):
        raise FrameError("non_integer_route")
    if not 1 <= slave <= 247 or not 0 <= address <= 65535 or not 1 <= count <= 125 or address + count > 65536:
        raise FrameError("invalid_read_range")
    if function not in (3,4):
        raise FrameError("unsupported_read_function")
    body = struct.pack(">BBHH", slave, function, address, count)
    return body + crc16(body).to_bytes(2, "little")


def parse_read(data: bytes, count: int, slave: int = 1, function=3):
    """Return words and consumed size, or None while the frame is incomplete."""
    if not data:
        return None
    if data[0] != slave:
        raise FrameError("unexpected_slave_or_transport")
    if len(data) < 2:
        return None
    if data[1] not in (function, function | 0x80):
        raise FrameError("unexpected_function_or_transport")
    if len(data) < 3:
        return None
    if data[1] == function and data[2] != count * 2:
        raise FrameError("unexpected_byte_count")
    size = 5 if data[1] == (function | 0x80) else 5 + count * 2
    if len(data) < size:
        return None
    frame = data[:size]
    if crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
        raise FrameError("crc_mismatch")
    if frame[1] == (function | 0x80):
        raise FrameError("modbus_exception", frame[2])
    words = tuple(int.from_bytes(frame[index:index + 2], "big") for index in range(3, size - 2, 2))
    return words, size


def serial_reference(words):
    if len(words) != 12:
        raise FrameError("incomplete_serial")
    raw = b"".join(value.to_bytes(2, "big") for value in words).rstrip(b"\x00 ")
    if not raw or any(byte < 33 or byte > 126 for byte in raw):
        raise FrameError("invalid_serial")
    digest = hashlib.sha256(raw).hexdigest()
    return {"inverter_serial_ref": "sha256:" + digest[:12], "inverter_serial_sha256": digest, "inverter_serial_length": len(raw)}
