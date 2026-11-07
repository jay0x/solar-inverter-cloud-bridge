"""Read-only setup suggestions from HA interfaces, never from the browser URL."""

from ipaddress import IPv4Address, IPv4Interface, IPv4Network

LAN_NETWORKS = tuple(IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def lan_ip(value):
    try:
        address = IPv4Address(value)
        return str(address) if any(address in net for net in LAN_NETWORKS) else None
    except (ValueError, TypeError):
        return None


def summarize_network(adapters, host_info=None):
    addresses = []
    for adapter in adapters:
        if not adapter.get("enabled"):
            continue
        for value in adapter.get("ipv4", []):
            address = lan_ip(value.get("address"))
            if address is None:
                continue
            try:
                interface = IPv4Interface(f"{address}/{value['network_prefix']}")
            except (KeyError, ValueError):
                continue
            addresses.append({"address": address, "network": str(interface.network), "default": bool(adapter.get("default"))})
    defaults = [value for value in addresses if value["default"]]
    selected = defaults[0] if len(defaults) == 1 else addresses[0] if len(addresses) == 1 else None
    result = {"addresses": addresses, "ha_ip": selected["address"] if selected else "",
              "subnet": selected["network"] if selected else "", "router_ip": "", "dns_ip": ""}
    if selected:
        for interface in (host_info or {}).get("interfaces", []):
            ipv4 = interface.get("ipv4") or {}
            if selected["address"] not in [str(value).split("/")[0] for value in ipv4.get("address", [])]:
                continue
            result["router_ip"] = lan_ip(ipv4.get("gateway")) or ""
            result["dns_ip"] = next((ip for value in ipv4.get("nameservers", []) if (ip := lan_ip(value))), "")
            break
    return result


async def async_network_hints(hass):
    from homeassistant.components.network import async_get_adapters
    from homeassistant.exceptions import HomeAssistantError
    host_info = {}
    if "hassio" in hass.config.components:
        from homeassistant.components.hassio import get_network_info
        try:
            host_info = get_network_info(hass)
        except HomeAssistantError:
            pass
    return summarize_network(await async_get_adapters(hass), host_info)
