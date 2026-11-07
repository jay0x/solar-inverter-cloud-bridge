"""Independent EyeBond envelope codec; protocol facts are attributed in docs.

Outer functions and routes are independent of the tunneled inverter protocol.
No source implementation is imported or copied.
"""

from dataclasses import dataclass
import struct

MAX_FRAME_BYTES = 4096
HEADER = struct.Struct(">HHHBB")


@dataclass(frozen=True)
class BinaryFrame:
    tid: int
    code: int
    address: int
    function: int
    payload: bytes = b""

    def encode(self):
        if len(self.payload) + HEADER.size > MAX_FRAME_BYTES:
            raise ValueError("binary_frame_too_large")
        return HEADER.pack(self.tid, self.code, len(self.payload) + 2,
                           self.address, self.function) + self.payload


def frame_size(header):
    if len(header) < 8:
        return None
    length = HEADER.unpack_from(header)[2]
    if length < 2:
        raise ValueError("binary_invalid_length")
    if length + 6 > MAX_FRAME_BYTES:
        raise ValueError("binary_frame_too_large")
    return length + 6


def decode_frame(data):
    size = frame_size(data)
    if size is None or len(data) < size:
        return None
    tid, code, _, address, function = HEADER.unpack_from(data)
    return BinaryFrame(tid, code, address, function, bytes(data[8:size])), size


def heartbeat_payload(now, interval=60):
    return bytes((now.year - 2000, now.month, now.day, now.hour, now.minute, now.second)) + interval.to_bytes(2, "big")
