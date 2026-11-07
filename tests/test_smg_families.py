"""SMG family isolation and pre-refactor permission-definition compatibility."""

from dataclasses import asdict
import hashlib
import json
import unittest

from custom_components.solar_inverter_bridge.core.catalogue import MAPS, decode_map
from custom_components.solar_inverter_bridge.core.drivers import fields_for, write_function, definition_hash


class SMGFamilyTests(unittest.TestCase):
    def test_refactor_preserves_existing_map_and_permission_definitions(self):
        # Captured before the family refactor. Order, names and source URLs also
        # participate in saved permission digests, not just register addresses.
        expected = {
            "smg_legacy": "de791467273f587c5bad2e0f17a0a69a1fe5eeb6dbd63a44447ee2880373019d",
            "smg_1": "ecfaad6a61c690d1b69cdc34a0f8057e8b9207d071299603091b3567fc0b47b3",
            "smg_2": "35b242cfa3127081957eed7d7e127caadaba1f054ce96bc5ebd9e997175cd992",
            "smg_3": "a42f53b9d256c042a797db4b3bc71cb37e535bdeb4f3edbfe44bc49b9253ed4b",
            "smg_5": "d2bccd083fdca2fa232da5bc0c199a3e7d518a5e687e66b3bb8e0652883a0dc7",
            "smg_6": "9134ef04243655f5f5e3b420ec1f6c2041f051b9837d07d5df61cde72a6a9615",
            "smg_11": "da8f660eb97ded77b2b56281574816da882a81f645eb1c040e438f7979008a75",
        }
        for profile_id, digest in expected.items():
            with self.subTest(profile_id=profile_id):
                actual = definition_hash(profile_id)
                self.assertEqual(actual, digest)
        self.assertEqual(fields_for("smg_4"),fields_for("modbus_protocol_4"))

    def test_shared_register_specimens_keep_protocol_deltas(self):
        low = {201:3, 202:2300, 203:5000, 210:2300, 212:5000, 213:1500,
               215:512, 219:3000, 223:1700, 225:25, 227:35, 229:80, 232:100}
        high = {201:3, 203:5000, 231:35, 253:5000, 277:512, 280:80,
                302:1700, 338:2300, 346:2300, 351:3000, 353:1700,
                348:1111, 350:11, 254:2222, 256:22}
        for profile_id in ("smg_legacy", "smg_1", "smg_2", "smg_11"):
            with self.subTest(profile_id=profile_id):
                values = decode_map(MAPS[profile_id], low)
                self.assertEqual(values["battery_voltage"]["value"], 51.2)
                self.assertEqual(values["output_power"]["value"], 1500)
                self.assertEqual(values["inverter_temperature"]["value"], 35)
        for protocol, power, load in ((3,1111,11), (4,2222,22), (5,1111,11), (6,2222,22)):
            with self.subTest(protocol=protocol):
                values = decode_map(MAPS[f"smg_{protocol}"], high)
                self.assertEqual(values["output_power"]["value"], power)
                self.assertEqual(values["load_percent"]["value"], load)
                self.assertEqual(values["battery_voltage"]["value"], 51.2)
                self.assertEqual("pv_power" in values, protocol in (3,4))

    def test_unimplemented_protocol_does_not_inherit_high_map_writes(self):
        for profile_id in ("smg_0", "smg_7", "smg_10", "smg_12", "smg_unknown"):
            with self.subTest(profile_id=profile_id):
                self.assertNotIn(profile_id, MAPS)
                self.assertEqual(fields_for(profile_id), ())
