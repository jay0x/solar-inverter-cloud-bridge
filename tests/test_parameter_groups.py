"""Presentation groups must not borrow another protocol's register layout."""
from dataclasses import asdict
import unittest

from custom_components.solar_inverter_bridge.core.drivers import fields_for
from custom_components.solar_inverter_bridge.core.parameters import Parameter, inventory, parameter_group
from custom_components.solar_inverter_bridge.core.profile_catalog import catalogue_view


class ParameterGroupTests(unittest.TestCase):
    def test_current_profiles_have_named_groups_without_mutating_protocol_fields(self):
        profiles = [item['profile_id'] for item in catalogue_view()] + ['modbus_protocol_4', 'must_pv3300', 'must_pv3900']
        for profile in profiles:
            with self.subTest(profile=profile):
                fields = fields_for(profile)
                before = [asdict(field) for field in fields]
                entries = inventory(fields)
                self.assertEqual(len(entries), len(fields))
                self.assertTrue(all(entry['group'] and entry['group'] != 'Other settings' for entry in entries))
                self.assertEqual([asdict(field) for field in fields], before)

    def test_same_parameter_purpose_is_grouped_across_smg_and_ascii_maps(self):
        for profile in ('modbus_protocol_4', 'smg_legacy', 'smg_1', 'smg_2', 'smg_11', 'pi30', 'pi30_max', 'pi18'):
            with self.subTest(profile=profile):
                groups = {entry['key']: entry['group'] for entry in inventory(fields_for(profile))}
                self.assertEqual(groups['primary_output_priority'], 'Output')
                self.assertEqual(groups['maximum_charging_current'], 'Charging')
                self.assertEqual(groups['battery_protection_voltage_offgrid'], 'Battery')
                self.assertEqual(groups['lcd_backlight'], 'AC input and display')

    def test_other_families_keep_explicit_and_semantic_sections(self):
        deye = {entry['key']: entry['group'] for entry in inventory(fields_for('deye_lv'))}
        self.assertEqual(deye['maximum_discharge_current'], 'Battery')
        self.assertEqual(deye['maximum_charging_current'], 'Charging')
        self.assertEqual(deye['solar_sell'], 'Energy')
        self.assertEqual(deye['remote_switch'], 'System')
        self.assertEqual({entry['group'] for entry in inventory(fields_for('hopewind_0237'))}, {'Power regulation'})
        for profile in ('srne_modbus', 'must_pv_ph18', 'deye_3ph_high_80kw', 'g_ascii'):
            for field, entry in zip(fields_for(profile), inventory(fields_for(profile))):
                if field.group:
                    self.assertEqual(entry['group'], field.group)

    def test_unknown_fields_do_not_inherit_groups_from_addresses(self):
        for address in (1, 600, 640, 9000, 40011):
            self.assertEqual(parameter_group(Parameter('future_setting', address, 'Future')), 'Other settings')
        self.assertEqual(parameter_group(Parameter('primary_output_priority', 1, 'Custom', group='Custom group')), 'Custom group')
