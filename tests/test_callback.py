"""Real loopback UDP/TCP callback lifecycle; never contacts a physical collector."""
import asyncio
from hashlib import sha256
import socket
import struct
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
import uuid

from custom_components.solar_inverter_bridge.core.callback import options, payload
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.exchange import response_frame


class CallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = CollectorService(["127.0.0.1"], None)
        await self.service.start()
        self.messages = asyncio.Queue()
        messages = self.messages
        class Receiver(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr):
                messages.put_nowait(data)
        self.udp, _ = await asyncio.get_running_loop().create_datagram_endpoint(Receiver, local_addr=("127.0.0.1", 0))
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        self.config = options("callback", "127.0.0.1", "127.0.0.1", port, self.udp.get_extra_info("sockname")[1])
        self.clients = []

    async def asyncTearDown(self):
        for writer in self.clients:
            writer.close()
            await writer.wait_closed()
        self.udp.close()
        await self.service.close()

    async def identify(self, name):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.config["callback_port"])
        self.clients.append(writer)
        writer.write(b"AT+DTUPN:" + name + b"\r\n")
        await writer.drain()
        return reader, writer

    async def wait_state(self, request_id, state):
        async with asyncio.timeout(3):
            while self.service.callback.requests[request_id]["state"] != state:
                await asyncio.sleep(0.01)

    async def test_exact_udp_command_then_identified_tcp_without_automatic_inverter_queries(self):
        request = str(uuid.uuid4())
        first = await self.service.callback.connect(request, self.config)
        self.assertEqual(first["state"], "waiting")
        datagram = await asyncio.wait_for(self.messages.get(), 2)
        self.assertEqual(datagram, f"set>server=127.0.0.1:{self.config['callback_port']};".encode())
        await self.service.callback.connect(request, self.config)
        self.assertTrue(self.messages.empty(), "Same request ID must not send again")
        reader, _ = await self.identify(b"CALLBACK-ONE")
        await self.wait_state(request, "connected")
        identity = sha256(b"CALLBACK-ONE").hexdigest()
        self.assertIn(identity, self.service.connections)
        self.assertEqual(self.service.callback.requests[request]["collector_sha256"], identity)
        self.assertFalse(self.service.candidates[identity]["ready"])
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(reader.read(1), 0.1)
        self.assertEqual(self.service.callback.bind(request, "device", identity), self.config)
        self.assertEqual(self.service.callback.requests[request]["expected_identity"], identity)

    async def test_saved_callback_rejects_a_different_collector_and_stops_retries(self):
        request = str(uuid.uuid4())
        identity = sha256(b"EXPECTED").hexdigest()
        self.service.callback.configure({"device": self.config})
        await self.service.callback.connect(request, self.config, expected_identity=identity, device_id="device")
        await self.identify(b"WRONG")
        await self.wait_state(request, "failed")
        self.assertEqual(self.service.callback.requests[request]["reason"], "callback_identity_mismatch")
        self.assertEqual(self.service.connections, {})
        with patch("custom_components.solar_inverter_bridge.core.callback.send_callback", new_callable=AsyncMock) as send:
            await self.service.callback.reconnect({"device_id": "device", "collector_sha256": identity})
            send.assert_not_awaited()

    async def test_binary_callback_negotiates_identity_without_assuming_at(self):
        request = str(uuid.uuid4())
        await self.service.callback.connect(request, self.config)
        reader, writer = await asyncio.open_connection("127.0.0.1", self.config["callback_port"])
        self.clients.append(writer)
        pn = b"BINARY-CALLBACK-FULL-PN"
        for expected_function in (1, 2):
            header = await asyncio.wait_for(reader.readexactly(8), 3)
            tid, code, size, address, function = struct.unpack(">HHHBB", header)
            data = await reader.readexactly(size - 2)
            self.assertEqual(function, expected_function)
            if function == 2:
                self.assertEqual(data, b"\x02")
            body = b"" if function == 1 else b"\x00\x02" + pn
            writer.write(struct.pack(">HHHBB", tid, code, len(body) + 2, address, function) + body)
            await writer.drain()
        await self.wait_state(request, "connected")
        holder = self.service.connections[sha256(pn).hexdigest()]
        self.assertEqual(holder["dialect"], "binary")
        self.assertFalse(holder["capabilities"]["module_reset"])
        self.assertFalse(holder.get("profile_verified", False))

    async def test_idle_binary_callback_has_heartbeat_without_native_polling(self):
        self.service.binary_heartbeat_interval = 0.05
        request = str(uuid.uuid4())
        await self.service.callback.connect(request, self.config)
        reader, writer = await asyncio.open_connection("127.0.0.1", self.config["callback_port"])
        self.clients.append(writer)
        pn = b"IDLE-CALLBACK-COLLECTOR"
        for function_expected in (1, 2, 1):
            header = await asyncio.wait_for(reader.readexactly(8), 3)
            tid, code, size, address, function = struct.unpack(">HHHBB", header)
            request_body = await reader.readexactly(size - 2)
            self.assertEqual(function, function_expected)
            if function == 1:
                self.assertEqual(request_body[-2:], b"\x00\x3c")
                body = pn
            else:
                self.assertEqual(request_body, b"\x02")
                body = b"\x00\x02" + pn
            writer.write(struct.pack(">HHHBB", tid, 258, len(body) + 2, 255, function) + body)
            await writer.drain()
        await self.wait_state(request, "connected")
        self.assertFalse(self.service.observations)

    async def test_callback_listener_failure_sends_no_datagram(self):
        server = await asyncio.start_server(lambda r,w:w.close(), "127.0.0.1", self.config["callback_port"])
        try:
            with self.assertRaises(OSError):
                await self.service.callback.connect(str(uuid.uuid4()), self.config)
            self.assertTrue(self.messages.empty())
        finally:
            server.close()
            await server.wait_closed()

    async def test_fixed_callback_management_route_requires_full_identity_then_native_reads(self):
        request = str(uuid.uuid4())
        await self.service.callback.connect(request, self.config)
        reader, writer = await asyncio.open_connection("127.0.0.1", self.config["callback_port"])
        self.clients.append(writer)
        pn = b"CALLBACK-TEST-PN-18"
        for expected_function in (1, 2):
            header = await asyncio.wait_for(reader.readexactly(8), 3)
            tid, code, size, address, function = struct.unpack(">HHHBB", header)
            query = await reader.readexactly(size - 2)
            self.assertEqual(function, expected_function)
            if function == 2:self.assertEqual(query, b"\x02")
            body = pn if function == 1 else b"\x00\x02" + pn
            writer.write(struct.pack(">HHHBB", tid, 258, len(body) + 2, 255, function) + body)
            await writer.drain()
        await self.wait_state(request, "connected")
        adapter = self.service.connections[sha256(pn).hexdigest()]["reader"]
        self.assertEqual(adapter.callback_identity_route, (258, 255))
        self.assertFalse(adapter.route_qualified)
        qualification = asyncio.create_task(adapter.qualify())
        try:
            for register, value in ((184, 4), (171, 32771)):
                header = await asyncio.wait_for(reader.readexactly(8), 3)
                tid, code, size, address, function = struct.unpack(">HHHBB", header)
                query = await reader.readexactly(size - 2)
                self.assertEqual((code, address, function), (258, 255, 4))
                self.assertEqual(query[:6], bytes((1, 3)) + register.to_bytes(2, "big") + b"\x00\x01")
                body = response_frame((value,))
                writer.write(struct.pack(">HHHBB", tid, code, len(body) + 2, address, function) + body)
                await writer.drain()
            result = await qualification
            self.assertEqual(result[1:], (4, 32771))
            self.assertTrue(adapter.route_qualified)
        finally:
            qualification.cancel()
            await asyncio.gather(qualification, return_exceptions=True)

    async def test_automatic_without_ip_waits_without_udp_or_new_listener(self):
        before = len(self.service.servers)
        result = await self.service.callback.connect(str(uuid.uuid4()), options())
        self.assertEqual(result["state"], "waiting_for_connection")
        self.assertFalse(result["sent"])
        self.assertEqual(len(self.service.servers), before)

    async def test_allowlist_validation_and_request_conflict(self):
        for ip in ("8.8.8.8", "0.0.0.0", "192.168.1.255", "192.168.1.2;reset", "::1"):
            with self.assertRaises(ValueError):
                options("callback", ip, "127.0.0.1")
        with self.assertRaisesRegex(ValueError, "callback_source_not_allowed"):
            await self.service.callback.connect(str(uuid.uuid4()), options("callback", "192.168.1.2", "127.0.0.1"))
        request = str(uuid.uuid4())
        await self.service.callback.connect(request, options())
        with self.assertRaisesRegex(ValueError, "connection_request_conflict"):
            await self.service.callback.connect(request, self.config)
        self.assertTrue(self.messages.empty())

    async def test_saved_offline_connection_has_bounded_callback_attempts(self):
        self.service.callback.configure({"device": self.config})
        device = {"device_id": "device", "collector_sha256": sha256(b"EXPECTED").hexdigest()}
        with patch("custom_components.solar_inverter_bridge.core.callback.send_callback", new_callable=AsyncMock) as send:
            await self.service.callback.reconnect(device)
            await self.service.callback.reconnect(device)
            self.assertEqual(send.await_count, 1)
        record = next(iter(self.service.callback.requests.values()))
        self.assertEqual(record["expected_identity"], device["collector_sha256"])

    async def test_auto_reuses_existing_owner_instead_of_starting_second_path(self):
        first = str(uuid.uuid4())
        await self.service.callback.connect(first, self.config)
        await asyncio.wait_for(self.messages.get(), 2)
        await self.identify(b"ONE-OWNER")
        await self.wait_state(first, "connected")
        identity = sha256(b"ONE-OWNER").hexdigest()
        holder = self.service.connections[identity]
        config = {**self.config, "method": "auto"}
        result = await self.service.callback.connect(str(uuid.uuid4()), config)
        self.assertEqual(result["state"], "connected")
        self.assertIs(self.service.connections[identity], holder)
        self.assertTrue(self.messages.empty())

    async def test_closed_callback_is_retryable_without_replaying_the_old_attempt(self):
        request = str(uuid.uuid4())
        await self.service.callback.connect(request, self.config)
        await asyncio.wait_for(self.messages.get(), 2)
        _, writer = await self.identify(b"DISCONNECT")
        await self.wait_state(request, "connected")
        writer.close()
        await writer.wait_closed()
        async with asyncio.timeout(3):
            while self.service.callback.view(self.service.callback.requests[request])["state"] != "disconnected":
                await asyncio.sleep(0.01)
        same = await self.service.callback.connect(request, self.config)
        self.assertEqual(same["state"], "disconnected")
        self.assertTrue(self.messages.empty())
        await self.service.callback.connect(str(uuid.uuid4()), self.config)
        self.assertEqual(await asyncio.wait_for(self.messages.get(), 2), payload(self.config))

    def enrolled(self, name=b"SWITCH-COLLECTOR", enabled=True):
        device = {"device_id": "saved-device", "collector_sha256": sha256(name).hexdigest(), "enabled": enabled}
        self.service.storage = SimpleNamespace(list_devices=lambda: [], device=lambda key: dict(device),
                                              has_unresolved=lambda key: False)
        self.service.on_update = None
        return device

    async def wait_owner(self, identity, port):
        async with asyncio.timeout(3):
            while self.service.connections.get(identity, {}).get("listener_port") != port:
                await asyncio.sleep(0.01)
        return self.service.connections[identity]

    async def test_change_existing_connection_and_return_to_passive_redirected_channel(self):
        device = self.enrolled()
        identity = device["collector_sha256"]
        port = self.service.servers[0].sockets[0].getsockname()[1]
        self.service.auxiliary_ports = set()
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        self.clients.append(writer)
        writer.write(b"AT+DTUPN:SWITCH-COLLECTOR\r\n")
        await writer.drain()
        old = await self.wait_owner(identity, port)
        saved = []
        request = str(uuid.uuid4())
        result = await self.service.callback.change(request, device["device_id"], self.config, saved.append)
        self.assertEqual(result["state"], "waiting")
        self.assertEqual(await asyncio.wait_for(self.messages.get(), 2), payload(self.config))
        self.assertNotIn(identity, self.service.connections)
        self.assertTrue(self.service.callback.live(old), "Old channel stays passive, not closed")
        await self.service.callback.change(request, device["device_id"], self.config, saved.append)
        self.assertEqual(len(saved), 1)
        self.assertTrue(self.messages.empty(), "Duplicate save cannot send again")
        await self.identify(b"SWITCH-COLLECTOR")
        callback = await self.wait_owner(identity, self.config["callback_port"])
        self.assertIsNot(callback, old)
        self.assertFalse(self.service.callback.owner_allowed(old))
        result = await self.service.callback.change(str(uuid.uuid4()), device["device_id"], options("redirect"), saved.append)
        self.assertEqual(result["state"], "connected")
        self.assertIs(self.service.connections[identity], old)
        self.assertTrue(self.service.callback.live(callback))
        self.assertFalse(self.service.callback.owner_allowed(callback))
        self.assertTrue(self.messages.empty())
        self.assertEqual(self.service.callback.identities[identity], device["device_id"])

    async def test_change_waits_for_current_poll_and_paused_save_sends_nothing(self):
        device = self.enrolled(enabled=False)
        release = asyncio.Event()
        poll = asyncio.create_task(release.wait())
        self.service._polling[device["device_id"]] = poll
        saved = []
        change = asyncio.create_task(self.service.callback.change(str(uuid.uuid4()), device["device_id"], self.config, saved.append))
        try:
            async with asyncio.timeout(2):
                while device["device_id"] not in self.service.callback.switching:
                    await asyncio.sleep(0.01)
            self.assertFalse(saved)
            self.assertTrue(self.messages.empty())
            release.set()
            result = await change
            self.assertEqual(result["state"], "saved_paused")
            self.assertEqual(saved, [self.config])
            self.assertNotIn(device["device_id"], self.service.callback.next_attempt)
            self.assertTrue(self.messages.empty())
        finally:
            release.set()
            await asyncio.gather(poll, change, return_exceptions=True)
            self.service._polling.clear()

    async def test_change_refuses_unresolved_operation_and_bind_failure_before_saving(self):
        device = self.enrolled()
        saved = []
        self.service.storage.has_unresolved = lambda key: True
        from custom_components.solar_inverter_bridge.core.storage import StorageError
        with self.assertRaisesRegex(StorageError, "device_busy_or_unresolved"):
            await self.service.callback.change(str(uuid.uuid4()), device["device_id"], self.config, saved.append)
        self.service.storage.has_unresolved = lambda key: False
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", self.config["callback_port"])
        try:
            with self.assertRaises(OSError):
                await self.service.callback.change(str(uuid.uuid4()), device["device_id"], self.config, saved.append)
        finally:
            server.close()
            await server.wait_closed()
        self.assertFalse(saved)
        self.assertFalse(self.service.callback.switching)
        self.assertTrue(self.messages.empty())

    async def test_changed_connection_binds_full_identity_not_just_ip(self):
        device = self.enrolled()
        request = str(uuid.uuid4())
        await self.service.callback.change(request, device["device_id"], self.config, lambda config: None)
        await self.identify(b"DIFFERENT-COLLECTOR")
        await self.wait_state(request, "failed")
        self.assertEqual(self.service.callback.view(self.service.callback.requests[request])["reason"], "callback_identity_mismatch")
        self.assertIn(device["device_id"], self.service.callback.blocked)
        self.assertFalse(self.service.connections)
