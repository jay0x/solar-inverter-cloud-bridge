"""Shared network option validation does not silently widen admission."""

import unittest

from custom_components.solar_inverter_bridge.core.identity import normalize_sources, peer_allowed


class NetworkTests(unittest.TestCase):
    def test_exact_addresses_cidrs_and_deduplication(self):
        sources = normalize_sources("192.168.10.1, 192.168.20.42/24\n192.168.10.1")
        self.assertEqual(sources, ["192.168.10.1/32", "192.168.20.0/24"])
        self.assertTrue(peer_allowed("192.168.10.1", sources))
        self.assertFalse(peer_allowed("192.168.10.2", sources))

    def test_invalid_unrestricted_and_oversized_lists_are_rejected(self):
        for value in ("0.0.0.0/0", "::/0", "not-an-ip", ["127.0.0.1"] * 33, {"ip": "127.0.0.1"}):
            with self.assertRaises(ValueError):
                normalize_sources(value)
        self.assertEqual(normalize_sources(""), [])
