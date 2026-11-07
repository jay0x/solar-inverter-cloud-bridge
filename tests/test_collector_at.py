"""Collector AT session: heartbeat, read-only module data, and explicit reset."""

import asyncio
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from custom_components.solar_inverter_bridge.core.identity import parse_at_response
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage


class AtResponseTests(unittest.TestCase):
    def test_empty_heartbeat_and_module_values_parse_without_accepting_other_commands(self):
        self.assertEqual(parse_at_response(b"AT+HTBT:\r\n", "HTBT"), "")
        self.assertEqual(parse_at_response(b"AT+FWVER:8.50.12.3\r\n", "FWVER"), "8.50.12.3")
        self.assertIsNone(parse_at_response(b"AT+UART:9600\r\n", "FWVER"))
        self.assertIsNone(parse_at_response(b"AT+FWVER:bad\x00value\r\n", "FWVER"))


class CollectorAtTests(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_uses_the_observed_query_and_waits_for_its_interval(self):
        service = CollectorService(["127.0.0.1"], None, heartbeat_interval=0.05)
        host, port = (await service.start())[0]
        reader, writer = await asyncio.open_connection(host, port)
        try:
            self.assertEqual(await asyncio.wait_for(reader.readuntil(b"\n"), 1), b"AT+DTUPN?\r\n")
            writer.write(b"AT+DTUPN:COLLECTOR1\r\n")
            await writer.drain()
            query = await asyncio.wait_for(reader.readuntil(b"\n"), 1)
            self.assertEqual(query, b"AT+HTBT?\r\n")
            writer.write(b"AT+HTBT:\r\n")
            await writer.drain()
            await asyncio.sleep(0.02)
            self.assertFalse(reader.at_eof())
        finally:
            writer.close()
            await writer.wait_closed()
            await service.close()

    async def test_module_queries_are_read_only_and_reset_matches_the_capture(self):
        identity = b"COLLECTOR1"
        digest = sha256(identity).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "bridge.sqlite3")
            service = CollectorService(["127.0.0.1"], storage, heartbeat_interval=30)
            device_id = storage.enroll(digest, "Unit", "modbus_protocol_4")
            host, port = (await service.start())[0]
            reader, writer = await asyncio.open_connection(host, port)
            try:
                await reader.readuntil(b"\n")
                writer.write(b"AT+DTUPN:" + identity + b"\r\n")
                await writer.drain()
                await asyncio.sleep(0.05)

                async def answer_info():
                    seen = []
                    for _ in range(5):
                        query = await asyncio.wait_for(reader.readuntil(b"\n"), 1)
                        seen.append(query)
                        name = query.split(b"?", 1)[0]
                        writer.write(name + b":VALUE\r\n")
                        await writer.drain()
                    return seen

                info_task = asyncio.create_task(answer_info())
                values = await service.read_module_info(device_id)
                self.assertEqual(await info_task, [
                    b"AT+FWVER?\r\n", b"AT+ATVER?\r\n", b"AT+DTUTYPE?\r\n",
                    b"AT+WFSS?\r\n", b"AT+CLDSRVHOST1?\r\n",
                ])
                self.assertEqual(values["cloud_assignment"], "VALUE")

                async def answer_reset():
                    query = await asyncio.wait_for(reader.readuntil(b"\n"), 1)
                    writer.write(b"AT+RESET:W000\r\n")
                    await writer.drain()
                    return query

                reset_task = asyncio.create_task(answer_reset())
                result = await service.reset_collector(device_id)
                self.assertEqual(await reset_task, b"AT+RESET=S\r\n")
                self.assertEqual(result, {"reset": "accepted"})
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()
                storage.close()
