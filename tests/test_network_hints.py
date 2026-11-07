"""Setup hints keep unknown gateways unknown and use actual HA network masks."""

import unittest
from custom_components.solar_inverter_bridge.network_hints import summarize_network


class NetworkHintTests(unittest.TestCase):
    def test_single_default_interface_with_host_gateway_and_resolver(self):
        result = summarize_network([
            {"enabled": False, "default": False, "ipv4": [{"address": "172.30.32.1", "network_prefix": 23}]},
            {"enabled": True, "default": True, "ipv4": [{"address": "192.168.10.77", "network_prefix": 23}]},
        ], {"interfaces": [{"ipv4": {"address": ["192.168.10.77/23"], "gateway": "192.168.10.254", "nameservers": ["8.8.8.8", "192.168.10.20"]}}]})
        self.assertEqual(result["ha_ip"], "192.168.10.77")
        self.assertEqual(result["subnet"], "192.168.10.0/23")
        self.assertEqual(result["router_ip"], "192.168.10.254")
        self.assertEqual(result["dns_ip"], "192.168.10.20")

    def test_unknown_gateway_and_multiple_interfaces_are_not_guessed(self):
        adapters = [{"enabled": True, "ipv4": [{"address": "10.12.4.5", "network_prefix": 16}]}]
        result = summarize_network(adapters)
        self.assertEqual(result["subnet"], "10.12.0.0/16")
        self.assertEqual(result["router_ip"], "")
        self.assertEqual(result["dns_ip"], "")
        adapters.append({"enabled": True, "ipv4": [{"address": "192.168.4.3", "network_prefix": 24}]})
        result = summarize_network(adapters)
        self.assertEqual(result["ha_ip"], "")
        self.assertEqual(len(result["addresses"]), 2)

    def test_loopback_public_or_unrelated_gateway_is_not_suggested(self):
        adapters = [{"enabled": True, "ipv4": [{"address": "127.0.0.1", "network_prefix": 8}, {"address": "8.8.8.8", "network_prefix": 32}, {"address": "10.1.2.3", "network_prefix": 24}]}]
        result = summarize_network(adapters, {"interfaces": [{"ipv4": {"address": ["192.168.1.2/24"], "gateway": "192.168.1.1"}}]})
        self.assertEqual(len(result["addresses"]), 1)
        self.assertEqual(result["router_ip"], "")
