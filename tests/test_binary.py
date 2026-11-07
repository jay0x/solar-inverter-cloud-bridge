"""Synthetic reverse-TCP collectors, independently constructed envelope fixtures."""

import asyncio
from hashlib import sha256
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import uuid

from custom_components.solar_inverter_bridge.core.binary import BinaryFrame, decode_frame
from custom_components.solar_inverter_bridge.core.compatibility import CompatibilityCapture, analyze, package_report, validate_package, replay
from custom_components.solar_inverter_bridge.core.exchange import response_frame
from custom_components.solar_inverter_bridge.core.framing import crc16
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage
from custom_components.solar_inverter_bridge.core.telemetry import required_addresses
from custom_components.solar_inverter_bridge.core.transport import ATTransport, BinaryTransport, detect


async def wait_until(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


class BinaryCodecTests(unittest.TestCase):
    def test_independent_pinned_research_examples_and_stream_boundaries(self):
        # EYBOND_BINARY_PROTOCOL section 6: synthetic, not hardware captures.
        request = bytes.fromhex("12340001000aff04010300b80001042f")
        response = bytes.fromhex("123400010009ff040103020004b987")
        frame, size = decode_frame(request + response)
        self.assertEqual(size, 16)
        self.assertEqual((frame.tid, frame.code, frame.address, frame.function), (0x1234, 1, 255, 4))
        self.assertEqual(frame.encode(), request)
        self.assertEqual(decode_frame(response)[0].payload, response_frame((4,)))
        for end in range(16):
            self.assertIsNone(decode_frame(request[:end]))
        for length in (0, 1, 4091, 65535):
            with self.assertRaises(ValueError):
                decode_frame(struct.pack(">HHHBB", 1, 1, length, 1, 4))
        self.assertEqual(decode_frame(BinaryFrame(1, 1, 1, 1).encode())[0].payload, b"")


class Writer:
    def __init__(self, block=False):
        self.data = bytearray()
        self.closed = False
        self.block = block

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        if self.block:
            await asyncio.Event().wait()

    def close(self):
        self.closed = True

    def is_closing(self):
        return self.closed


class AdapterBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_at_on_binary_hint_and_fragmented_unsolicited_identity(self):
        reader = asyncio.StreamReader()
        writer = Writer()
        wire = ATTransport(reader, writer, lambda *a, **k: None)
        reader.feed_data(b"AT+DTUPN:Exact")
        dialect, basis = await detect(wire, "auto", "binary", passive_timeout=0.01)
        self.assertEqual((dialect, basis), ("at", "partial_identity_candidate"))
        reader.feed_data(b"PN\r\nTAIL")
        identity = await wire.identify()
        self.assertEqual(identity["identity_sha256"], sha256(b"ExactPN").hexdigest())
        self.assertEqual(await wire.read(4), b"TAIL")
        self.assertFalse(writer.data)

    async def test_at_and_binary_deadlines_include_drain_and_cancelled_waiters(self):
        from custom_components.solar_inverter_bridge.core.exchange import exchange_at
        wire = ATTransport(asyncio.StreamReader(), Writer(block=True), lambda *a, **k: None)
        with self.assertRaises(TimeoutError):
            await exchange_at(wire, wire.writer, b"AT+DTUPN?\r\n", timeout=0.01)
        adapter = BinaryTransport(wire, timeout=0.01)
        try:
            with self.assertRaises(TimeoutError):
                await adapter.heartbeat()
            self.assertIsNone(adapter._pending)
            self.assertEqual(adapter._tid, 1)
        finally:
            await adapter.close()

    async def test_late_reply_wrong_parameter_exception_and_cancel_cannot_complete_new_request(self):
        reader, writer = asyncio.StreamReader(), Writer()
        events = []
        capture = CompatibilityCapture()
        capture.start()
        capture.emit("dialect_selected", session="generation-one", dialect="binary")
        def emit(kind, **fields):
            events.append((kind, fields))
            capture.emit(kind, session="generation-one", **fields)
        wire = ATTransport(reader, writer, emit)
        adapter = BinaryTransport(wire, timeout=0.03)
        try:
            with self.assertRaises(TimeoutError):
                await adapter.query(2)
            # Only the first request tests a deadline. Correlation/cancellation
            # checks must not race a 30 ms timeout under concurrent test load.
            adapter.timeout = 1
            task = asyncio.create_task(adapter.query(2))
            await asyncio.sleep(0)
            reader.feed_data(BinaryFrame(1, 1, 1, 2, b"\x00\x02OLD").encode())
            reader.feed_data(BinaryFrame(2, 1, 1, 1).encode())
            await asyncio.sleep(0.005)
            self.assertFalse(task.done())
            reader.feed_data(BinaryFrame(2, 1, 1, 2, b"\x00\x05BAD").encode())
            with self.assertRaisesRegex(ValueError, "binary_parameter_mismatch"):
                await task
            task = asyncio.create_task(adapter.query(2))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertIsNone(adapter._pending)
            task = asyncio.create_task(adapter.query(2))
            await asyncio.sleep(0)
            reader.feed_data(BinaryFrame(3, 1, 1, 2, b"\x00\x02LATE").encode())
            reader.feed_data(BinaryFrame(4, 1, 1, 2, b"\x01\x02").encode())
            with self.assertRaisesRegex(ValueError, "binary_query_rejected"):
                await task
        finally:
            await adapter.close()
        restored = validate_package(package_report(capture.snapshot([], raw=True))[0])
        self.assertTrue(any(item.get("correlation") == "late_after_failure" for item in replay(restored)["decoder_outcomes"]))

    async def test_partial_frame_timeout_does_not_restart_at_each_chunk(self):
        reader, writer = asyncio.StreamReader(), Writer()
        events = []
        wire = ATTransport(reader, writer, lambda kind, **fields: events.append((kind, fields)))
        adapter = BinaryTransport(wire, timeout=0.03)
        try:
            reader.feed_data(b"\x00")
            await asyncio.sleep(0.02)
            reader.feed_data(b"\x01")
            await asyncio.sleep(0.02)
            self.assertTrue(writer.closed)
            self.assertTrue(any(kind == "binary_reader_failed" and fields["code"] == "TimeoutError" for kind, fields in events))
        finally:
            await adapter.close()

    async def test_transaction_deadline_retires_a_partially_consumed_frame(self):
        reader, writer = asyncio.StreamReader(), Writer()
        wire = ATTransport(reader, writer, lambda *a, **k: None)
        adapter = BinaryTransport(wire, timeout=1)
        try:
            task = asyncio.create_task(adapter.request(2, b"\x02", (1, 1), timeout=0.02))
            await asyncio.sleep(0)
            reader.feed_data(BinaryFrame(1, 1, 1, 2, b"\x00\x02PN").encode()[:4])
            with self.assertRaises(TimeoutError):
                await task
            self.assertTrue(writer.closed)
            with self.assertRaises(ConnectionError):
                await adapter.query(2)
        finally:
            await adapter.close()


class BinarySessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.directory.name) / "bridge.sqlite3")
        self.service = CollectorService(["127.0.0.1"], self.storage)
        self.port = (await self.service.start())[0][1]
        self.clients = []
        self.seen = []

    async def asyncTearDown(self):
        await self.service.close()
        for client in self.clients:
            client.cancel()
        await asyncio.gather(*self.clients, return_exceptions=True)
        self.storage.close()
        self.directory.cleanup()

    def collector(self, pn=b"SYNTHETIC-BINARY-PN", *, unsolicited=True, slave=1, route=(1, 1), model=32771, fault=None):
        async def run():
            reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
            regs = {address: 0 for address in required_addresses()}
            regs.update({184: 4, 171: model, 201: 2, 277: 480, 280: 50, 338: 2300,
                         601: 1, 696: 2026, 697: 11, 698: 5})
            try:
                if unsolicited:
                    # Printable TID 'AT' must still select binary, not AT.
                    data = struct.pack(">HHHBB", 0x4154, 0, 16, 1, 1) + b"SHORTPNPREFIX!"
                    writer.write(data[:3])
                    await writer.drain()
                    await asyncio.sleep(0.005)
                    writer.write(data[3:])
                    await writer.drain()
                while True:
                    header = await reader.readexactly(8)
                    tid, code, length, address, function = struct.unpack(">HHHBB", header)
                    payload = await reader.readexactly(length - 2)
                    self.seen.append((function, payload))
                    if function == 1:
                        reply = b""
                    elif function == 2:
                        reply = b"\x00" + payload + (pn if payload == b"\x02" else b"VERSION")
                        if fault == "pn":
                            reply = b"\x01\x02"
                    elif function == 4:
                        if (code, address) != route or payload[0] != slave:
                            continue
                        if fault == "ascii":
                            reply = b"(230.0 50.0)\r"
                        else:
                            register, count = struct.unpack(">HH", payload[2:6])
                            if payload[1]==16:
                                words=struct.unpack('>'+str(count)+'H',payload[7:-2])
                                regs.update({register+i:word for i,word in enumerate(words)})
                                reply=payload[:6]+crc16(payload[:6]).to_bytes(2,"little")
                            else:
                                reply = response_frame(tuple(regs.get(register + i, 0) for i in range(count)), slave)
                            if fault == "crc":
                                reply = reply[:-1] + bytes([reply[-1] ^ 1])
                    else:
                        raise AssertionError("unexpected function")
                    encoded = struct.pack(">HHHBB", tid, code, len(reply) + 2, address, function) + reply
                    if function == 4:
                        # Same TID, wrong FC cannot complete FC4. Wrong route and
                        # wrong TID are followed by the real response.
                        wrong = BinaryFrame(tid, code, address, 1).encode()
                        wrong += BinaryFrame(tid, code, address ^ 1, 4, reply).encode()
                        wrong += BinaryFrame((tid + 50) % 65536, code, address, 4, reply).encode()
                        writer.write(wrong)
                    writer.write(encoded[:6])
                    await writer.drain()
                    await asyncio.sleep(0)
                    writer.write(encoded[6:])
                    await writer.drain()
            except (ConnectionError, asyncio.IncompleteReadError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()
        task = asyncio.create_task(run())
        self.clients.append(task)
        return task

    async def test_mixed_admission_monitoring_and_backend_capabilities(self):
        self.collector()
        await wait_until(lambda: len(self.service.candidates) == 1)
        key = next(iter(self.service.candidates))
        result = await self.service.verify(key)
        self.assertTrue(result["ready"])
        self.assertEqual(result["transport"], "binary")
        device_id = await self.service.enroll(key, "Synthetic")
        self.storage.set_mode(device_id, "advanced")
        self.storage.set_clock_sync(device_id, True)
        self.storage.set_auto_reset(device_id, True)
        await self.service.poll_once(device_id)
        self.assertEqual(self.service.observations[device_id].values["battery_voltage"]["value"], 48)
        result=await self.service.apply(device_id, "primary_output_priority", "sbu", str(uuid.uuid4()))
        self.assertEqual(result["outcome"],"confirmed")
        with self.assertRaisesRegex(ValueError, "transport_clock_unsupported"):
            await self.service.apply(device_id,"inverter_datetime","2026-11-07T12:00:00",str(uuid.uuid4()),clock_sync=True)
        with self.assertRaisesRegex(ValueError, "transport_reset_unsupported"):
            await self.service.reset_collector(device_id)
        self.assertFalse(self.service._reset_due(self.storage.device(device_id)))
        self.assertFalse(any(function not in (1, 2, 4) or (function == 4 and payload[1] not in (3,16)) for function, payload in self.seen))
        self.assertEqual(len(self.storage.recent_operations(device_id)), 1)
        self.assertFalse(self.service.transport_capabilities(self.storage.device(device_id))["clock_write"])
        # Existing AT and binary peers coexist behind the same NAT source.
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        try:
            writer.write(b"AT+DTUPN:AT-SECOND\r\n")
            await writer.drain()
            await wait_until(lambda: len(self.service.candidates) == 2)
            self.assertEqual({holder["dialect"] for holder in self.service.candidates.values()}, {"at", "binary"})
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_silent_binary_override_and_slave_five_are_independent_of_port(self):
        self.service.bootstrap_preference = "binary"
        self.collector(unsolicited=False, slave=5, route=(1, 255))
        await wait_until(lambda: bool(self.service.candidates))
        holder = next(iter(self.service.candidates.values()))
        holder["reader"].probe_timeout = 0.05
        result = await self.service.verify(holder["identity_sha256"])
        self.assertTrue(result["ready"])
        self.assertEqual(holder["reader"].slave, 5)
        self.assertEqual(holder["reader"].route, (1, 255))

    async def test_unknown_map_report_replays_after_simulator_is_gone(self):
        self.service.compatibility.start({"inverter_model": "Synthetic variant"})
        client = self.collector(model=33793)
        await wait_until(lambda: any(e["kind"] == "native_signature_rejected" for e in self.service.compatibility.events))
        client.cancel()
        await asyncio.gather(client, return_exceptions=True)
        self.service.compatibility.stop()
        report = self.service.compatibility.snapshot(self.service.listeners, raw=True)
        data, analysis = package_report(report)
        restored = validate_package(data)
        result = replay(restored)
        self.assertEqual(result["analysis"], analysis)
        self.assertIn("native_signature_rejected", {item["code"] for item in analysis["findings"]})
        self.assertTrue(any(item["validation"] == "inner_valid" for item in result["decoder_outcomes"]))
        self.assertTrue(any(item.get("native_admission") == "unsupported_or_unconfirmed_identity"
                            and item["native_signature"]["model_code"] == 33793 for item in result["decoder_outcomes"]))
        self.assertEqual(self.storage.list_devices(), [])
        # Shareable export keeps validation facts, not the PN or original bytes.
        safe, _ = package_report(self.service.compatibility.snapshot(self.service.listeners))
        safe_report = validate_package(safe)
        self.assertNotIn("SYNTHETIC-BINARY-PN", str(safe_report))
        self.assertNotIn("wire_hex", str(safe_report))

    async def test_raw_replay_reconstructs_known_map_values_and_complete_settings(self):
        self.service.compatibility.start()
        client = self.collector()
        await wait_until(lambda: any(event["kind"] == "settings_complete" for event in self.service.compatibility.events))
        client.cancel()
        await asyncio.gather(client, return_exceptions=True)
        self.service.compatibility.stop()
        restored = validate_package(package_report(self.service.compatibility.snapshot(self.service.listeners, raw=True))[0])
        result = replay(restored)
        decoded = [item["decoded_values"] for item in result["decoder_outcomes"] if "decoded_values" in item]
        self.assertTrue(decoded)
        self.assertEqual(decoded[-1]["battery_voltage"]["value"], 48)
        self.assertEqual(result["analysis"]["coverage"]["parameters"], "complete")

    async def test_identity_failure_report_exists_before_any_candidate(self):
        self.service.compatibility.start()
        self.collector(fault="pn")
        await wait_until(lambda: any(e["kind"] == "admission_failed" for e in self.service.compatibility.events))
        self.assertFalse(self.service.candidates)
        self.assertIn("admission_failed", {item["code"] for item in analyze(self.service.compatibility.snapshot(self.service.listeners))["findings"]})

    async def test_tid_exhaustion_closes_without_reusing_a_tid(self):
        self.collector()
        await wait_until(lambda: bool(self.service.candidates))
        adapter = next(iter(self.service.candidates.values()))["reader"]
        adapter._tid = 65535
        with self.assertRaisesRegex(ConnectionError, "planned_tid_rotation"):
            await adapter.heartbeat()
        self.assertTrue(adapter.writer.is_closing())

    async def test_distinct_full_pns_share_prefix_and_source_without_merging(self):
        self.collector(pn=b"SAME-14-PREFIX-0001")
        self.collector(pn=b"SAME-14-PREFIX-0002")
        await wait_until(lambda: len(self.service.candidates) == 2)
        self.assertEqual(len({item["identity_sha256"] for item in self.service.candidates.values()}), 2)

    async def test_reconnect_on_new_listener_retains_device_id_and_saved_mode(self):
        client = self.collector()
        await wait_until(lambda: bool(self.service.candidates))
        key, old = next(iter(self.service.candidates.items()))
        await self.service.verify(key)
        device_id = await self.service.enroll(key, "Retained")
        self.storage.set_mode(device_id, "advanced")
        self.service._next_poll[device_id] = float("inf")
        client.cancel()
        await asyncio.gather(client, return_exceptions=True)
        await wait_until(lambda: key not in self.service.connections)
        server = await asyncio.start_server(self.service._accept, "127.0.0.1", 0)
        self.service.servers.append(server)
        self.port = server.sockets[0].getsockname()[1]
        self.collector()
        await wait_until(lambda: key in self.service.connections)
        self.assertIsNot(self.service.connections[key], old)
        await self.service.poll_once(device_id)
        device = self.storage.device(device_id)
        self.assertEqual(device["control_mode"], "full")
        self.assertEqual(device["name"], "Retained")
        self.assertEqual(len(self.storage.list_devices()), 1)

    async def test_bad_crc_and_ascii_are_evidence_not_zero_readings(self):
        for fault in ("crc", "ascii"):
            client = self.collector(pn=fault.encode(), fault=fault)
            await wait_until(lambda: any(item["identity_sha256"] == sha256(fault.encode()).hexdigest() for item in self.service.candidates.values()))
            key = sha256(fault.encode()).hexdigest()
            adapter = self.service.candidates[key]["reader"]
            adapter.probe_timeout = 0.01
            with self.assertRaises(ValueError):
                await self.service.verify(key)
            self.assertIsNone(self.service.observation)
            client.cancel()
            await asyncio.gather(client, return_exceptions=True)

    async def test_original_crc_failure_is_reproduced_from_report_after_peer_stops(self):
        self.service.compatibility.start()
        client = self.collector(fault="crc")
        await wait_until(lambda: any(event["kind"] == "inner_payload_rejected" and event["code"] == "crc_mismatch"
                                    for event in self.service.compatibility.events))
        client.cancel()
        await asyncio.gather(client, return_exceptions=True)
        self.service.compatibility.stop()
        report = self.service.compatibility.snapshot(self.service.listeners, raw=True)
        restored = validate_package(package_report(report)[0])
        self.assertTrue(any(item["validation"] == "crc_mismatch" for item in replay(restored)["decoder_outcomes"]))
        self.assertIsNone(self.service.observation)

    async def test_busy_collection_does_not_interrupt_or_send_extra_commands(self):
        self.collector()
        await wait_until(lambda: bool(self.service.candidates))
        holder = next(iter(self.service.candidates.values()))
        await holder["lock"].acquire()
        try:
            self.service.compatibility.start()
            count = len(self.seen)
            await self.service.compatibility_probe()
            self.assertEqual(len(self.seen), count)
            self.assertTrue(any(event["kind"] == "probe_busy" for event in self.service.compatibility.events))
        finally:
            holder["lock"].release()

    async def test_backup_freeze_is_reported_as_busy_without_probe_task_failure(self):
        self.service.compatibility.start()
        await asyncio.to_thread(self.storage.begin_backup)
        try:
            await self.service.compatibility_probe()
            self.assertTrue(any(event["kind"] == "probe_busy" and event["reason"] == "storage_backup_in_progress"
                                for event in self.service.compatibility.events))
        finally:
            await asyncio.to_thread(self.storage.end_backup)

    async def test_silent_auto_alternates_once_then_exposes_exhausted_outcome(self):
        self.service.compatibility.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.assertEqual(await reader.readuntil(b"\n"), b"AT+DTUPN?\r\n")
        writer.close()
        await writer.wait_closed()
        await wait_until(lambda: any(event["kind"] == "admission_failed" for event in self.service.compatibility.events))
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        header = await reader.readexactly(8)
        self.assertEqual(struct.unpack(">HHHBB", header)[-1], 1)
        await reader.readexactly(struct.unpack(">HHHBB", header)[2] - 2)
        writer.close()
        await writer.wait_closed()
        await wait_until(lambda: sum(event["kind"] == "admission_failed" for event in self.service.compatibility.events) >= 2)
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        try:
            self.assertEqual(await asyncio.wait_for(reader.read(1), 2), b"")
            self.assertTrue(any(event["kind"] == "bootstrap_exhausted" for event in self.service.compatibility.events))
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_source_rejection_is_reported_without_reading_payload(self):
        self.service.sources = ()
        self.service.compatibility.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        try:
            writer.write(b"MUST-NOT-BE-CAPTURED")
            await writer.drain()
            await wait_until(lambda: any(event["kind"] == "source_rejected" for event in self.service.compatibility.events))
            self.assertFalse(any(event["kind"] == "wire" for event in self.service.compatibility.events))
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_binary_and_synthetic_at_can_use_actual_port_502(self):
        probe = CollectorService(["127.0.0.1"], None)
        try:
            try:
                addresses = await probe.start(ports=(502,))
            except OSError:
                self.skipTest("TCP 502 is unavailable in this test environment; per-port errors are tested separately")
            self.service.servers[0].close()
            await self.service.servers[0].wait_closed()
            # Move the simulator to the low port without borrowing an AT port role.
            original, self.service, self.port = self.service, probe, addresses[0][1]
            try:
                self.collector(unsolicited=False)
                await wait_until(lambda: bool(probe.candidates))
                key = next(iter(probe.candidates))
                self.assertTrue((await probe.verify(key))["ready"])
                reader, writer = await asyncio.open_connection("127.0.0.1", 502)
                try:
                    writer.write(b"AT+DTUPN:AT-ON-502\r\n")
                    await writer.drain()
                    await wait_until(lambda: len(probe.candidates) == 2)
                finally:
                    writer.close()
                    await writer.wait_closed()
            finally:
                self.service = original
        finally:
            await probe.close()

    async def test_partial_bind_failure_keeps_existing_port_and_all_failure_raises(self):
        other = CollectorService(["127.0.0.1"], None)
        try:
            addresses = await other.start(ports=(self.port, 0))
            self.assertEqual(len(addresses), 1)
            self.assertFalse(other.listeners[0]["bound"])
            self.assertTrue((await other.status())["degraded"])
        finally:
            await other.close()
        failed = CollectorService([], None)
        with self.assertRaises(OSError):
            await failed.start(ports=(self.port,))
        self.assertFalse(failed.servers)

    async def test_permission_error_is_distinct_from_port_conflict(self):
        start = asyncio.start_server
        async def permissions(callback, host, port, **kwargs):
            if port == 502:
                raise PermissionError(13, "Permission denied")
            return await start(callback, host, port, **kwargs)
        service = CollectorService([], None)
        try:
            with patch("asyncio.start_server", permissions):
                await service.start(ports=(502, 0))
            self.assertEqual(service.listeners[0]["error"], "PermissionError")
            self.assertEqual(service.listeners[0]["errno"], 13)
            self.assertTrue(service.listeners[1]["bound"])
        finally:
            await service.close()

    async def test_absolute_partial_frame_deadline_and_original_failure_bytes(self):
        self.service.compatibility.start()
        self.service.bootstrap_preference = "binary"
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        try:
            writer.write(b"\x00\x01\x00")
            await writer.drain()
            # Patch the configured default for this boundary test, not framing.
            await asyncio.sleep(0.05)
            writer.close()
            await writer.wait_closed()
            await wait_until(lambda: any(e["kind"] == "binary_reader_failed" for e in self.service.compatibility.events))
            report = self.service.compatibility.snapshot(self.service.listeners, raw=True)
            outcomes = replay(validate_package(package_report(report)[0]))["decoder_outcomes"]
            self.assertTrue(any(item["validation"] == "incomplete_frame" for item in outcomes))
        finally:
            writer.close()
            await writer.wait_closed()


class CompatibilityTests(unittest.TestCase):
    def test_archive_replay_limits_empty_frame_floods(self):
        capture = CompatibilityCapture()
        capture.start()
        capture.emit("dialect_selected", session="flood", dialect="binary")
        capture.emit("wire", session="flood", direction="rx", data=BinaryFrame(1, 1, 1, 1).encode() * 5000)
        report = validate_package(package_report(capture.snapshot([], raw=True))[0])
        result = replay(report)
        self.assertTrue(result["frame_budget_hit"])
        self.assertEqual(len(result["decoder_outcomes"]), 4096)

    def test_recorded_read_values_do_not_change_with_later_cache_mutations(self):
        capture = CompatibilityCapture()
        capture.start()
        values = {"priority": "sub"}
        capture.emit("settings_complete", values=values)
        values["priority"] = "sbu"
        self.assertEqual(capture.events[-1]["values"]["priority"], "sub")

    def test_reference_comparison_is_time_unit_and_key_scoped(self):
        import json
        capture = CompatibilityCapture()
        capture.start()
        capture.emit("snapshot_complete", values={"battery_voltage": {"value": 48.2, "unit": "V"}})
        snapshot = capture.events[-1]
        capture.metadata["reference_readings"] = json.dumps({"battery_voltage": {"value": 48.1, "unit": "V", "time": snapshot["time"]}})
        analysis = analyze(capture.snapshot([]))
        self.assertEqual(analysis["coverage"]["reference_comparison"], "compared")
        self.assertEqual(analysis["reference_comparisons"][0]["difference"], 0.1)
        self.assertIn("reference_difference", {finding["code"] for finding in analysis["findings"]})
        capture.metadata["reference_readings"] = "A screenshot without a comparable timestamp"
        self.assertIn("reference_text_only", {finding["code"] for finding in analyze(capture.snapshot([]))["findings"]})

    def test_schema_one_migration_and_route_revision_preserve_unresolved_intent(self):
        import sqlite3
        from contextlib import closing
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sqlite3"
            store = Storage(path)
            identifier = store.enroll("old-at-identity", "Existing", "modbus_protocol_4")
            store.set_mode(identifier, "advanced")
            store.set_clock_sync(identifier, True)
            store.set_auto_reset(identifier, True)
            store.accept_operation(identifier, "unresolved", {"key": "primary_output_priority", "value": "sbu"})
            store.claim_send("unresolved")
            baseline = store.device(identifier)
            store.close()
            with closing(sqlite3.connect(path)) as db:
                db.execute("DROP TABLE device_routes")
                db.execute("PRAGMA user_version=1")
            store = Storage(path)
            try:
                self.assertEqual(store.storage_summary()["schema"], 4)
                self.assertEqual(store.device(identifier), baseline)
                self.assertEqual(len(store.unresolved(identifier)), 1)
                route = {"transport": "binary", "outer_code": 1, "outer_address": 255, "inner_slave": 5}
                self.assertTrue(store.bind_route(identifier, route))
                self.assertFalse(store.bind_route(identifier, route))
                self.assertEqual(store.device(identifier)["policy_revision"], baseline["policy_revision"] + 1)
                self.assertEqual(store.selected_route(identifier), route)
                self.assertEqual(len(store.unresolved(identifier)), 1)
            finally:
                store.close()

    def test_no_tcp_source_rejection_truncation_and_hash_tampering(self):
        capture = CompatibilityCapture()
        capture.start()
        self.assertIn("no_incoming_connection", {finding["code"] for finding in analyze(capture.snapshot([]))["findings"]})
        capture.emit("tcp_received", session="s1")
        capture.emit("source_rejected", session="s1")
        for i in range(4200):
            capture.emit("wire", direction="rx", data=b"UNKNOWN", session="s1")
        self.assertLessEqual(len(capture.events), 4096)
        self.assertGreater(capture.dropped, 0)
        self.assertEqual(capture.events[1]["kind"], "tcp_received")
        report = capture.snapshot([], raw=True)
        archive, _ = package_report(report)
        self.assertEqual(validate_package(archive)["schema"], 1)
        from zipfile import ZipFile
        import io
        stream = io.BytesIO(archive)
        with ZipFile(stream, "a") as output:
            output.writestr("../unsafe", b"no")
        with self.assertRaisesRegex(ValueError, "invalid_report_archive"):
            validate_package(stream.getvalue())

    def test_expiry_cancellation_byte_caps_and_invalid_packages(self):
        capture = CompatibilityCapture()
        capture.start(duration=1)
        with self.assertRaisesRegex(ValueError, "busy"):
            capture.start()
        capture.emit("wire", direction="rx", data=b"x" * (4 * 1024 * 1024 + 1), session="one")
        self.assertLessEqual(capture.byte_count, 4 * 1024 * 1024)
        capture.started -= 2
        self.assertFalse(capture.view()["active"])
        self.assertTrue(any(event.get("reason") == "deadline" for event in capture.events))
        capture._expiry = 0
        self.assertIsNone(capture.view()["report_id"])
        self.assertFalse(capture.events)
        for data in (b"not a zip", b"", b"PK\x03\x04"):
            with self.assertRaises(ValueError):
                validate_package(data)
