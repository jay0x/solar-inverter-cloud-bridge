"""Independent polling and passive secondary collector channels over TCP."""

import asyncio
from pathlib import Path
import tempfile
import unittest

from custom_components.solar_inverter_bridge.core.exchange import response_frame
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage
from custom_components.solar_inverter_bridge.core.telemetry import required_addresses


class MultiDeviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_sixteen_devices_keep_distinct_readings_when_one_stalls(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "bridge.sqlite3")
            service = CollectorService(["127.0.0.1"], storage)
            port = (await service.start())[0][1]
            stall = set()
            release = asyncio.Event()
            native_writes = []

            async def collector(index):
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                registers = {address: 0 for address in required_addresses()}
                registers.update({171: 32771, 184: 4, 201: 2, 277: 480, 280: 50, 302: 1000 + index,
                                  696: 2026, 697: 11, 698: 2})
                try:
                    await reader.readuntil(b"\n")
                    writer.write(f"AT+DTUPN:DEVICE{index}\r\n".encode())
                    await writer.drain()
                    while True:
                        request = await reader.readexactly(8)
                        if request[1] != 3:
                            native_writes.append(index)
                            return
                        if index in stall:
                            await release.wait()
                        address, count = int.from_bytes(request[2:4], "big"), int.from_bytes(request[4:6], "big")
                        writer.write(response_frame(tuple(registers.get(address + offset, 0) for offset in range(count))))
                        await writer.drain()
                except (ConnectionError, asyncio.IncompleteReadError):
                    pass
                finally:
                    writer.close()
                    await writer.wait_closed()

            clients = [asyncio.create_task(collector(index)) for index in range(16)]
            try:
                async with asyncio.timeout(3):
                    while len(service.candidates) != 16:
                        await asyncio.sleep(0.01)
                identities = list(service.candidates)
                await asyncio.gather(*(service.verify(identity) for identity in identities))
                # The stalled transport must not keep the other 15 from polling.
                stall.add(0)
                await asyncio.gather(*(service.enroll(identity, "Inverter") for identity in identities))
                async with asyncio.timeout(4):
                    while len(service.observations) < 15:
                        await asyncio.sleep(0.02)
                powers = {observation.values["pv_power"]["value"] for observation in service.observations.values()}
                self.assertEqual(powers, set(range(1001, 1016)))
                self.assertEqual(native_writes, [])
                self.assertEqual(len(storage.list_devices()), 16)
            finally:
                release.set()
                await service.close()
                for client in clients:
                    client.cancel()
                await asyncio.gather(*clients, return_exceptions=True)
                await asyncio.to_thread(storage.close)

    async def test_secondary_port_is_passive_even_when_it_connects_first(self):
        service = CollectorService(["127.0.0.1"], None)
        addresses = await service.start(ports=(0, 0))
        service.auxiliary_ports.add(addresses[1][1])
        writers = []
        try:
            secondary, writer = await asyncio.open_connection(*addresses[1])
            writers.append(writer)
            await secondary.readuntil(b"\n")
            writer.write(b"AT+DTUPN:DUAL\r\n")
            await writer.drain()
            await asyncio.sleep(0.03)
            self.assertEqual(service.connections, {})
            primary, writer = await asyncio.open_connection(*addresses[0])
            writers.append(writer)
            await primary.readuntil(b"\n")
            writer.write(b"AT+DTUPN:DUAL\r\n")
            await writer.drain()
            async with asyncio.timeout(2):
                while not service.connections:
                    await asyncio.sleep(0)
            owner = next(iter(service.connections.values()))
            self.assertTrue(owner["primary"])
            self.assertEqual(len(next(iter(service._channels.values()))), 2)
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(secondary.read(1), 0.05)
            self.assertFalse(secondary.at_eof())
            self.assertEqual(service.rejected, 0)
        finally:
            for writer in writers:
                writer.close()
                await writer.wait_closed()
            await service.close()
