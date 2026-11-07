"""Protocol 4 aliases, optional registers, fallback identity and catalog semantics."""

import asyncio
import unittest

from custom_components.solar_inverter_bridge.core.catalogue import MAPS, decode_map, descriptors
from custom_components.solar_inverter_bridge.core.drivers import fields_for, snapshot
from custom_components.solar_inverter_bridge.core.exchange import read_snapshot, response_frame
from custom_components.solar_inverter_bridge.core.framing import crc16
from custom_components.solar_inverter_bridge.core.profile_catalog import catalogue_view
from custom_components.solar_inverter_bridge.core.transport import ATTransport
from test_profiles import SPECIMENS


class CanonicalProtocolTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, registers, *, missing=(), corrupt=False):
        reader=asyncio.StreamReader();requests=[]
        class Writer:
            def write(self,data):
                address,count=int.from_bytes(data[2:4],"big"),int.from_bytes(data[4:6],"big")
                requests.append((address,count))
                if set(range(address,address+count)) & set(missing):
                    body=b"\x01\x83\x02"
                    reply=body+crc16(body).to_bytes(2,"little")
                    if corrupt:reply=reply[:-1]+bytes([reply[-1]^1])
                else:
                    reply=response_frame(tuple(registers.get(address+i,0) for i in range(count)))
                reader.feed_data(reply)
            async def drain(self):pass
        writer=Writer()
        return ATTransport(reader,writer,lambda *a,**k:None),writer,requests

    async def test_reference_and_common_share_decoder_and_inventory(self):
        registers=SPECIMENS["smg_4"]|{184:4,171:32771,278:65526,702:123,703:1,704:234}
        adapter,writer,_=self.adapter(registers)
        legacy=await read_snapshot(adapter,writer)
        common=await snapshot(adapter,writer,"smg_4")
        self.assertEqual(legacy["profile_id"],"modbus_protocol_4")
        self.assertEqual(legacy["values"],common["values"])
        self.assertEqual(len(common["values"]),35)
        self.assertEqual(common["values"]["battery_discharge_current"]["value"],1)
        self.assertEqual(common["values"]["pv_energy_total"]["value"],657.7)
        self.assertEqual(descriptors("smg_4"),descriptors("modbus_protocol_4"))
        self.assertIs(fields_for("smg_4"),fields_for("modbus_protocol_4"))
        for key in ("load_percent",):
            field=next(f for f in MAPS["smg_4"].fields if f.key==key)
            self.assertTrue(field.signed)

    async def test_optional_absence_keeps_common_values_without_invented_zero(self):
        registers=SPECIMENS["smg_4"]|{184:4,171:32771}
        missing=(206,227,278,384,702)
        adapter,writer,requests=self.adapter(registers,missing=missing)
        result=await read_snapshot(adapter,writer)
        self.assertEqual(result["values"]["battery_voltage"]["value"],48)
        self.assertNotIn("pv_energy_total",result["values"])
        self.assertNotIn("battery_current",result["values"])
        self.assertLess(len(requests),32)
        adapter,writer,_=self.adapter(registers,missing=missing,corrupt=True)
        with self.assertRaisesRegex(ValueError,"crc_mismatch"):
            await read_snapshot(adapter,writer)

    async def test_classic_fallback_cannot_override_known_protocol(self):
        adapter,writer,requests=self.adapter(SPECIMENS["smg_2"]|{184:2})
        with self.assertRaisesRegex(ValueError,"profile_native_protocol_mismatch"):
            await snapshot(adapter,writer,"smg_legacy")
        self.assertEqual(requests,[(184,1)])

    def test_catalog_has_one_protocol4_and_explicit_family_variants(self):
        rows=catalogue_view()
        self.assertEqual(len(rows),24)
        self.assertNotIn("must_pv3300",{r["profile_id"] for r in rows})
        self.assertNotIn("must_pv3900",{r["profile_id"] for r in rows})
        self.assertNotIn("modbus_protocol_4",{r["profile_id"] for r in rows})
        four=next(r for r in rows if r["profile_id"]=="smg_4")
        self.assertEqual((four["measurements"],four["controls"]),(35,48))
        self.assertEqual(four["family_id"],"smg_2024")
        legacy=next(r for r in rows if r["profile_id"]=="smg_legacy")
        self.assertEqual(legacy["name"],"SMG Classic — variant not identified")
        self.assertNotEqual(MAPS["smartess_0912"].function,MAPS["smartess_0921"].function)
        self.assertEqual([d["name"] for d in descriptors("smg_3") if d["key"]=="output_power"],["Output power L1"])
