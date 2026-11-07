"""Common-map enrollment, mandatory model correction and evidence presentation."""

import asyncio
import unittest

from custom_components.solar_inverter_bridge.core.catalogue import MAPS
from custom_components.solar_inverter_bridge.core.compatibility import CompatibilityCapture, package_report, replay, validate_package
from custom_components.solar_inverter_bridge.core.drivers import snapshot
from custom_components.solar_inverter_bridge.core.exchange import read_snapshot, response_frame
from custom_components.solar_inverter_bridge.core.framing import crc16
from custom_components.solar_inverter_bridge.core.profile_layers import describe_profile
from custom_components.solar_inverter_bridge.core.transport import ATTransport
from test_profiles import SPECIMENS


class ProfileLayerTests(unittest.IsolatedAsyncioTestCase):
    def test_common_smg_does_not_invent_a_model_extension(self):
        for model in (32771, 33793, 45678):
            view = describe_profile("smg_4", binding={"signature":[4,model]}, evidence="saved")
            self.assertTrue(view["common_only"])
            self.assertIsNone(view["extension"])
            self.assertEqual(view["base_map"]["profile_id"], "smg_4")
            self.assertEqual(view["model_code"], model)
        reference = describe_profile("modbus_protocol_4", identity={"protocol_number":4,"model_code":32771}, evidence="observed")
        self.assertIsNone(reference["extension"])
        self.assertIn("4/32771",reference["qualification"])
        self.assertEqual(reference["base_map"]["profile_id"], "smg_4")
        self.assertIsNone(describe_profile("unimplemented_model"))
        for key in MAPS:
            self.assertIsNotNone(describe_profile(key))

    async def test_common_must_applies_required_correction_and_replays_the_same_scale(self):
        capture = CompatibilityCapture(); capture.start()
        capture.emit("dialect_selected", session="fixture", dialect="at")
        registers = dict(SPECIMENS["must_pv3300"])
        reader = asyncio.StreamReader()
        requests = []
        class Writer:
            def write(self, data):
                requests.append(data)
                address, count = int.from_bytes(data[2:4],"big"), int.from_bytes(data[4:6],"big")
                reader.feed_data(response_frame(tuple(registers.get(address+i,0) for i in range(count)),4))
            async def drain(self): pass
        writer = Writer()
        adapter = ATTransport(reader,writer,lambda kind,**fields:capture.emit(kind,session="fixture",**fields))
        adapter.slave = 4
        result = await snapshot(adapter,writer,"must_pv_ph18")
        self.assertEqual(result["profile_id"], "must_pv_ph18")
        self.assertEqual(result["values"]["load_percent"]["value"], 20)
        self.assertEqual(result["binding"]["effective_profile_id"], "must_pv3300")
        view = describe_profile("must_pv_ph18", binding=result["binding"])
        self.assertEqual(view["extension"]["id"], "must_pv3300")
        self.assertTrue(view["extension"]["required"])
        self.assertEqual(view["model_code"], 3300)
        report = replay(validate_package(package_report(capture.snapshot([],raw=True))[0]))
        self.assertEqual(report["profile_decodes"][-1]["values"]["load_percent"]["value"], 20)
        adapter.profile_id = "must_pv_ph18"
        adapter.accepted_fingerprint = result["fingerprint"]
        registers[20001] = 3900
        with self.assertRaisesRegex(ValueError,"accepted_profile_fingerprint_changed"):
            await read_snapshot(adapter,writer)
        self.assertTrue(all(request[1] == 3 for request in requests))

    async def test_absent_marker_allows_common_map_but_corrupt_marker_is_not_ignored(self):
        for corrupt in (False, True):
            reader = asyncio.StreamReader()
            class Writer:
                def write(self, data):
                    address, count = int.from_bytes(data[2:4],"big"), int.from_bytes(data[4:6],"big")
                    if address == 20000:
                        body = b"\x04\x83\x02"
                        reply = body + crc16(body).to_bytes(2,"little")
                        if corrupt: reply = reply[:-1] + bytes([reply[-1] ^ 1])
                    else:
                        reply = response_frame(tuple(SPECIMENS["must_pv_ph18"].get(address+i,0) for i in range(count)),4)
                    reader.feed_data(reply)
                async def drain(self): pass
            writer = Writer(); adapter = ATTransport(reader,writer,lambda *a,**k:None); adapter.slave = 4
            if corrupt:
                with self.assertRaisesRegex(ValueError,"crc_mismatch"):
                    await snapshot(adapter,writer,"must_pv_ph18")
            else:
                result = await snapshot(adapter,writer,"must_pv_ph18")
                self.assertEqual(result["values"]["load_percent"]["value"],20)
                self.assertTrue(describe_profile("must_pv_ph18",binding=result["binding"])["common_only"])
