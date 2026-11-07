"""Protocol R/W classification and exact unsigned decimal register encoding."""

from dataclasses import replace
import math
import unittest

from custom_components.solar_inverter_bridge.core.parameters import (
    FIELDS, access_class, decode_observed, editing_allowed, encode_value, inventory,
)


class AdvancedNumericTests(unittest.TestCase):
    def setUp(self):
        self.fields = {field.key: field for field in FIELDS}

    def test_only_protocol_read_only_fields_are_classified_read_only(self):
        self.assertEqual({field.address for field in FIELDS if access_class(field) == "read_only"}, {605, 636})
        for key in ("current_output_priority", "current_charging_priority"):
            with self.assertRaisesRegex(ValueError, "read_only_parameter"):
                encode_value(self.fields[key], "sbu" if "output" in key else "snu")

    def test_undocumented_limits_warn_without_a_mode_gate(self):
        descriptors = {item["key"]: item for item in inventory()}
        for key in ("maximum_charging_current", "maximum_ac_charging_current", "equalization_voltage",
                    "battery_protection_voltage_ac", "op1_protection_voltage_offgrid", "battery_protection_voltage_offgrid"):
            with self.subTest(key=key):
                field = self.fields[key]
                for legacy in ("full", "monitoring", "control", "advanced"):
                    self.assertTrue(editing_allowed(legacy, field))
                self.assertTrue(descriptors[key]["execution_ready"])
                self.assertEqual(descriptors[key]["protocol_access"], "R/W")
                self.assertEqual(descriptors[key]["warning"], "manufacturer_limits_unknown")
                self.assertEqual(descriptors[key]["step"], 0.1)
                self.assertIsNone(descriptors[key]["bounds"])

    def test_decimal_values_encode_without_truncation_or_rounding(self):
        self.assertEqual(encode_value(self.fields["maximum_charging_current"], 12.5), (125,))
        self.assertEqual(encode_value(self.fields["equalization_voltage"], 57.6), (576,))
        self.assertEqual(encode_value(self.fields["battery_protection_voltage_ac"], 46.8), (468,))
        field = self.fields["maximum_ac_charging_current"]
        for value in (12.55, -0.1, 6553.6, True, False, "12.5", math.inf, -math.inf, math.nan):
            with self.subTest(value=value), self.assertRaises(ValueError):
                encode_value(field, value)
        self.assertEqual(encode_value(field, 6553.5), (65535,))  # Wire boundary, not a recommended setting.

    def test_known_bounds_remain_enforced_and_zero_sentinel_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "value_outside_documented_bounds"):
            encode_value(self.fields["battery_protection_soc_ac"], 101)
        bounded = replace(self.fields["equalization_voltage"], bounds=(40, 60))
        self.assertEqual(encode_value(bounded, 56.4), (564,))
        with self.assertRaisesRegex(ValueError, "value_outside_documented_bounds"):
            encode_value(bounded, 60.1)
        recovery = self.fields["battery_recovery_voltage_ac"]
        self.assertEqual(encode_value(recovery, "full_recovery"), (0,))
        self.assertEqual(encode_value(recovery, 0), (0,))
        self.assertEqual(decode_observed({643: 0})[recovery.key], "full_recovery")
        self.assertEqual(encode_value(recovery, 52.3), (523,))
