"""Offline checks for framing, permissions, storage recovery, and collector admission."""

import asyncio
from datetime import datetime
from pathlib import Path
import tempfile
from time import monotonic
import unittest
import uuid

from custom_components.solar_inverter_bridge.core.exchange import read_snapshot, response_frame
from custom_components.solar_inverter_bridge.core.framing import crc16, parse_read, read_request
from custom_components.solar_inverter_bridge.core.identity import peer_allowed
from custom_components.solar_inverter_bridge.core.parameters import inventory, editing_allowed, FIELDS
from custom_components.solar_inverter_bridge.core.policy import clock_write_allowed
from custom_components.solar_inverter_bridge.core.profiles import match_signature
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage
from custom_components.solar_inverter_bridge.core.telemetry import decode, required_addresses


def snapshot():
    registers = {address: 0 for address in required_addresses()}
    registers.update({201: 2, 277: 480, 280: 80, 338: 2300, 346: 2300, 302: 1200})
    return registers


class FramingTests(unittest.TestCase):
    def test_fragment_then_complete_frame(self):
        request = read_request(201, 2)
        self.assertEqual(crc16(request[:-2]), int.from_bytes(request[-2:], "little"))
        payload = bytes([1, 3, 4, 0, 2, 0, 10])
        frame = payload + crc16(payload).to_bytes(2, "little")
        self.assertIsNone(parse_read(frame[:4], 2))
        words, size = parse_read(frame + b"extra", 2)
        self.assertEqual((words, size), ((2, 10), len(frame)))

    def test_bad_crc_is_rejected(self):
        frame = bytes([1, 3, 2, 0, 1, 0, 0])
        with self.assertRaises(ValueError):
            parse_read(frame, 1)


class ProfileTests(unittest.TestCase):
    def test_only_verified_signature_auto_matches(self):
        self.assertEqual(match_signature(4, 32771)["result"], "verified")
        self.assertEqual(match_signature(4, 32768)["result"], "known_unverified")
        self.assertEqual(match_signature(9, 1)["result"], "unsupported")

    def test_complete_snapshot_has_no_invented_zero_requirement(self):
        values = decode(snapshot())
        self.assertEqual(values["operating_mode"]["value"], "mains")
        self.assertEqual(values["pv_power"]["value"], 1200)
        with self.assertRaises(ValueError):
            decode({201: 2})

    def test_parameter_list_is_complete_and_writes_follow_capability(self):
        listed = inventory()
        self.assertEqual(len(listed), len(FIELDS))
        self.assertFalse(next(item["execution_ready"] for item in listed if item["key"] == "current_output_priority"))
        self.assertTrue(next(item["execution_ready"] for item in listed if item["key"] == "primary_output_priority"))
        self.assertFalse(next(item["execution_ready"] for item in listed if item["key"] == "inverter_datetime"))
        standard = next(field for field in FIELDS if field.key == "primary_output_priority")
        advanced = next(field for field in FIELDS if field.key == "dry_contact")
        self.assertTrue(editing_allowed("monitoring", standard))
        self.assertTrue(editing_allowed("control", standard))
        self.assertTrue(editing_allowed("control", advanced))
        self.assertTrue(editing_allowed("advanced", advanced))
        self.assertFalse(clock_write_allowed(False))
        self.assertTrue(clock_write_allowed(True))


class StorageTests(unittest.TestCase):
    def test_mode_persists_and_unsent_operation_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sqlite3"
            storage = Storage(path)
            device_id = storage.enroll("a" * 64, "House")
            storage.set_mode(device_id, "advanced")
            storage.set_clock_sync(device_id, True)
            accepted = storage.accept_operation(device_id, "op-1", {"value": 1})
            self.assertEqual(accepted["state"], "accepted")
            storage.close()
            restored = Storage(path)
            self.assertEqual(restored.device(device_id)["control_mode"], "full")
            self.assertTrue(restored.device(device_id)["clock_sync"])
            self.assertEqual(restored.operation("op-1")["outcome"], "not_sent")
            restored.close()

    def test_possible_send_blocks_another_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sqlite3"
            storage = Storage(path)
            device_id = storage.enroll("b" * 64, "House")
            storage.accept_operation(device_id, "op-2", {"value": 2})
            self.assertTrue(storage.claim_send("op-2"))
            storage.close()
            restored = Storage(path)
            with self.assertRaises(RuntimeError):
                restored.accept_operation(device_id, "op-3", {"value": 3})
            restored.close()

    def test_empty_allowlist_rejects_collector(self):
        async def run():
            service = CollectorService([], None)
            host, port = (await service.start())[0]
            reader, writer = await asyncio.open_connection(host, port)
            await asyncio.sleep(0.05)
            writer.close()
            await writer.wait_closed()
            await service.close()
            self.assertEqual(service.rejected, 1)
            self.assertEqual(service.transmitted, 0)
        asyncio.run(run())

    def test_admitted_collector_does_not_start_native_reads(self):
        async def run():
            service = CollectorService(["127.0.0.1"], None)
            host, port = (await service.start())[0]
            reader, writer = await asyncio.open_connection(host, port)
            query = await asyncio.wait_for(reader.readuntil(b"\n"), 1)
            self.assertEqual(query, b"AT+DTUPN?\r\n")
            writer.write(b"AT+DTUPN:COLLECTOR1\r\n")
            await writer.drain()
            await asyncio.sleep(0.05)
            self.assertEqual(service.transmitted, len(query))
            self.assertEqual(len(service.candidates), 1)
            self.assertEqual(next(iter(service.candidates.values()))["native_reads"], 0)
            writer.close()
            await writer.wait_closed()
            await service.close()
        asyncio.run(run())

    def test_one_owner_reads_identity_and_snapshot(self):
        registers = snapshot()
        registers.update({171: 32771, 184: 4})

        async def server(reader, writer):
            while True:
                request = await reader.read(8)
                if not request:
                    break
                address = int.from_bytes(request[2:4], "big")
                count = int.from_bytes(request[4:6], "big")
                writer.write(response_frame(tuple(registers.get(address + offset, 0) for offset in range(count))))
                await writer.drain()
            writer.close()
            await writer.wait_closed()

        async def run():
            started = await asyncio.start_server(server, "127.0.0.1", 0)
            port = started.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            result = await read_snapshot(reader, writer)
            self.assertEqual((result["protocol_number"], result["model_code"]), (4, 32771))
            self.assertEqual(result["values"]["pv_power"]["value"], 1200)
            writer.close()
            await writer.wait_closed()
            started.close()
            await started.wait_closed()
        asyncio.run(run())

    def test_simulated_collector_can_be_verified_without_hardware(self):
        registers = snapshot()
        registers.update({171: 32771, 184: 4})

        async def client(port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                await reader.readuntil(b"\n")
                writer.write(b"AT+DTUPN:SIMULATOR\r\n")
                await writer.drain()
                while True:
                    request = await reader.read(8)
                    if not request:
                        break
                    address = int.from_bytes(request[2:4], "big")
                    count = int.from_bytes(request[4:6], "big")
                    writer.write(response_frame(tuple(registers.get(address + offset, 0) for offset in range(count))))
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        async def run():
            with tempfile.TemporaryDirectory() as directory:
                storage = Storage(Path(directory) / "bridge.sqlite3")
                service = CollectorService(["127.0.0.1"], storage)
                port = (await service.start())[0][1]
                task = asyncio.create_task(client(port))
                await asyncio.sleep(0.7)
                sha = next(iter(service.candidates))
                result = await service.verify(sha)
                self.assertEqual(result["snapshots"], 2)
                device_id = await service.enroll(sha, "Simulator")
                self.assertEqual(storage.device(device_id)["control_mode"], "full")
                task.cancel()
                await service.close()
                storage.close()
        asyncio.run(run())

    def test_second_collector_is_a_separate_inverter(self):
        async def client(port, name):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                await reader.readuntil(b"\n")
                writer.write(f"AT+DTUPN:{name}\r\n".encode())
                await writer.drain()
                await asyncio.Event().wait()
            finally:
                writer.close()
                await writer.wait_closed()

        async def run():
            with tempfile.TemporaryDirectory() as directory:
                storage = Storage(Path(directory) / "bridge.sqlite3")
                service = CollectorService(["127.0.0.1"], storage)
                port = (await service.start())[0][1]
                tasks = [asyncio.create_task(client(port, name)) for name in ("ONE", "TWO")]
                await asyncio.sleep(0.7)
                self.assertEqual(len(service.candidates), 2)
                for sha in list(service.candidates):
                    holder = service.candidates[sha]
                    holder["ready"] = True
                    holder["verified_at"] = monotonic()
                    holder["proof"] = {"profile_id": "protocol-4"}
                    await service.enroll(sha, holder["identity_ref"])
                status = await service.status()
                self.assertEqual(len(status["devices"]), 2)
                self.assertEqual(status["pending"], [])
                for task in tasks:
                    task.cancel()
                await service.close()
                storage.close()
        asyncio.run(run())

    def test_poll_publishes_and_a_blocked_write_sends_nothing(self):
        registers = snapshot()
        registers.update({171: 32771, 184: 4, 696: 2026, 697: 11, 698: 1, 699: 12, 700: 0, 701: 0})
        writes = []

        async def run():
            with tempfile.TemporaryDirectory() as directory:
                storage = Storage(Path(directory) / "bridge.sqlite3")
                service = CollectorService(["127.0.0.1"], storage, now=lambda: datetime(2026, 11, 1, 12, 0, 0))
                port = (await service.start())[0][1]
                task = asyncio.create_task(modbus_client(port, registers, writes, "POLL"))
                await asyncio.sleep(0.7)
                sha = next(iter(service.candidates))
                holder = service.candidates[sha]
                holder.update(ready=True, verified_at=monotonic(), proof={"profile_id": "modbus_protocol_4"})
                device_id = await service.enroll(sha, "House")
                service._polled[device_id] = monotonic()
                observation = await service.poll_once(device_id)
                self.assertEqual(observation.values["pv_power"]["value"], 1200)
                observation.observed_monotonic -= 61
                self.assertFalse(observation.available(monotonic()))
                with self.assertRaises(ValueError):
                    await service.apply(device_id, "primary_output_priority", "sbu", str(uuid.uuid4()))
                self.assertEqual(writes, [])
                task.cancel()
                await service.close()
                storage.close()
        asyncio.run(run())

    def test_control_write_and_clock_sync_are_confirmed_on_simulator(self):
        registers = snapshot()
        registers.update({171: 32771, 184: 4, 601: 2, 696: 2026, 697: 11, 698: 1, 699: 11, 700: 57, 701: 0})
        writes = []

        async def run():
            with tempfile.TemporaryDirectory() as directory:
                storage = Storage(Path(directory) / "bridge.sqlite3")
                service = CollectorService(["127.0.0.1"], storage, now=lambda: datetime(2026, 11, 1, 12, 0, 0))
                port = (await service.start())[0][1]
                task = asyncio.create_task(modbus_client(port, registers, writes, "WRITE"))
                await asyncio.sleep(0.7)
                sha = next(iter(service.candidates))
                service.candidates[sha].update(ready=True, verified_at=monotonic(), proof={"profile_id": "modbus_protocol_4"})
                device_id = await service.enroll(sha, "House")
                service._polled[device_id] = monotonic()
                storage.set_mode(device_id, "advanced")
                storage.set_clock_sync(device_id, True)
                result = await service.apply(device_id, "primary_output_priority", "sbu", str(uuid.uuid4()))
                self.assertEqual(result["outcome"], "confirmed")
                self.assertIn((601, (2,)), writes)
                await service.poll_once(device_id)
                self.assertTrue(any(address == 696 and len(words) == 6 for address, words in writes))
                task.cancel()
                await service.close()
                storage.close()
        asyncio.run(run())

    def test_large_clock_correction_is_refused_and_readback_sends_nothing(self):
        registers = snapshot()
        registers.update({171: 32771, 184: 4, 601: 2, 696: 2020, 697: 1, 698: 1, 699: 0, 700: 0, 701: 0})
        writes = []

        async def run():
            with tempfile.TemporaryDirectory() as directory:
                storage = Storage(Path(directory) / "bridge.sqlite3")
                service = CollectorService(["127.0.0.1"], storage, now=lambda: datetime(2026, 11, 2, 12, 0, 0))
                port = (await service.start())[0][1]
                task = asyncio.create_task(modbus_client(port, registers, writes, "SAFE"))
                await asyncio.sleep(0.7)
                sha = next(iter(service.candidates))
                service.candidates[sha].update(ready=True, verified_at=monotonic(), proof={"profile_id": "modbus_protocol_4"})
                device_id = await service.enroll(sha, "House")
                service._polled[device_id] = monotonic()
                storage.set_mode(device_id, "control")
                storage.set_clock_sync(device_id, True)
                await service.poll_once(device_id)
                self.assertEqual(writes, [])
                self.assertEqual(service.last_error, "clock_correction_too_large")
                storage.accept_operation(device_id, "op-readback", {"key": "primary_output_priority", "value": "sbu", "clock_sync": False})
                self.assertTrue(storage.claim_send("op-readback"))
                confirmed = await service.reconcile(device_id)
                self.assertEqual(confirmed, ["op-readback"])
                self.assertEqual(writes, [])
                self.assertFalse(storage.has_unresolved(device_id))
                service._note_failure(device_id)
                self.assertGreaterEqual(service._next_poll[device_id] - monotonic(), 2)
                task.cancel()
                await service.close()
                storage.close()
        asyncio.run(run())

    def test_restricted_network_is_rejected(self):
        with self.assertRaises(ValueError):
            peer_allowed("10.0.0.1", ["0.0.0.0/0"])


async def modbus_client(port, registers, writes, name):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await reader.readuntil(b"\n")
    writer.write(f"AT+DTUPN:{name}\r\n".encode())
    await writer.drain()
    try:
        while True:
            header = await reader.readexactly(2)
            if header[1] == 3:
                rest = await reader.readexactly(6)
                address = int.from_bytes(rest[0:2], "big")
                count = int.from_bytes(rest[2:4], "big")
                writer.write(response_frame(tuple(registers.get(address + offset, 0) for offset in range(count))))
            elif header[1] == 16:
                meta = await reader.readexactly(5)
                address = int.from_bytes(meta[0:2], "big")
                count = int.from_bytes(meta[2:4], "big")
                payload = await reader.readexactly(meta[4] + 2)
                words = tuple(int.from_bytes(payload[index:index + 2], "big") for index in range(0, count * 2, 2))
                registers.update({address + offset: word for offset, word in enumerate(words)})
                writes.append((address, words))
                ack = header + meta[:4]
                writer.write(ack + crc16(ack).to_bytes(2, "little"))
            else:
                break
            await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()
        await writer.wait_closed()


if __name__ == "__main__":
    unittest.main()
