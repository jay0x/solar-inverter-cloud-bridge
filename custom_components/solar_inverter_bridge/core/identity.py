"""Collector admission identity. Source IP is not device identity."""

import hashlib
import ipaddress


def at_query() -> bytes:
    return b"AT+DTUPN?\r\n"


HEARTBEAT_INTERVAL_SECONDS = 37
HEARTBEAT_QUERY = b"AT+HTBT?\r\n"
RESET_COMMAND = b"AT+RESET=S\r\n"
MODULE_QUERIES = (
    ("firmware_version", b"AT+FWVER?\r\n"),
    ("at_version", b"AT+ATVER?\r\n"),
    ("module_type", b"AT+DTUTYPE?\r\n"),
    ("wifi_status", b"AT+WFSS?\r\n"),
    ("cloud_assignment", b"AT+CLDSRVHOST1?\r\n"),
)


def parse_at_response(data: bytes, name: str):
    """Return the printable value from one AT reply. An empty value is valid."""
    line = data.split(b"\n", 1)[0].rstrip(b"\r\x00 ")
    prefix = f"AT+{name}:".encode()
    if not line.startswith(prefix):
        return None
    value = line[len(prefix):]
    if len(value) > 80 or any(byte < 0x20 or byte > 0x7E for byte in value):
        return None
    return value.decode("ascii")


def parse_at_identity(data: bytes):
    for line in data.split(b"\n")[:-1]:
        line = line.rstrip(b"\r")
        if not line.startswith(b"AT+DTUPN:"):
            continue
        value = line[len(b"AT+DTUPN:"):].strip().rstrip(b"\x00 ")
        if not 1 <= len(value) <= 64 or any(byte < 0x20 or byte > 0x7E for byte in value):
            return None
        if value.upper() in (b"ERROR", b"ERR", b"FAIL", b"OK"):
            return None
        return full_pn_identity(value)
    return None


def full_pn_identity(data):
    """Normalize a full-PN response without case folding or prefix truncation."""
    value = data.strip().rstrip(b"\x00 ")
    if not 1 <= len(value) <= 64 or any(byte < 0x20 or byte > 0x7E for byte in value):
        return None
    if value.upper() in (b"ERROR", b"ERR", b"FAIL", b"OK"):
        return None
    digest = hashlib.sha256(value).hexdigest()
    return {"identity_ref": "sha256:" + digest[:12], "identity_sha256": digest, "identity_length": len(value)}


def peer_allowed(address: str, sources) -> bool:
    if not sources:
        return False
    peer = ipaddress.ip_address(address)
    for source in sources:
        network = ipaddress.ip_network(source, strict=False)
        if network.prefixlen == 0:
            raise ValueError("unrestricted_source")
        if peer in network:
            return True
    return False


def normalize_sources(value):
    """Canonical explicit IPs/CIDRs, shared by config flow and panel setup."""
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    if not isinstance(value, (list, tuple)) or len(value) > 32:
        raise ValueError("invalid_allowed_sources")
    sources = []
    for source in value:
        try:
            network = ipaddress.ip_network(source, strict=False)
        except (ValueError, TypeError) as error:
            raise ValueError("invalid_allowed_sources") from error
        if network.prefixlen == 0:
            raise ValueError("unrestricted_source")
        normalized = str(network)
        if normalized not in sources:
            sources.append(normalized)
    return sources
