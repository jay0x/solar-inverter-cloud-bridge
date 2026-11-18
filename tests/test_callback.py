"""Real loopback UDP/TCP callback lifecycle; never contacts a physical collector."""
import ast
import asyncio
from hashlib import sha256
from pathlib import Path
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
        with self.assertRaisesRegex(ValueError, "callback_identity_mismatch"):
            self.service.callback.enrollment_options(request, sha256(b"CALLBACK-ONE").hexdigest())
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
        with self.assertRaisesRegex(ValueError, "callback_identity_mismatch"):
            self.service.callback.enrollment_options(request, sha256(b"OTHER-PN").hexdigest())
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(reader.read(1), 0.1)
        self.assertEqual(self.service.callback.bind(request, "device", identity), self.config)
        self.assertEqual(self.service.callback.requests[request]["expected_identity"], identity)
        with patch("custom_components.solar_inverter_bridge.core.callback.monotonic",
                   return_value=self.service.callback.requests[request]["expires"] + 1):
            with self.assertRaisesRegex(ValueError, "connection_request_expired"):
                self.service.callback.enrollment_options(request, identity)

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

    async def test_one_hundred_reconnects_keep_manual_dedup_and_bounded_attempts(self):
        callback = self.service.callback
        callback.configure({"device": self.config})
        callback.ports.add(self.config["callback_port"])
        device = {"device_id": "device", "collector_sha256": sha256(b"EXPECTED").hexdigest()}
        manual = str(uuid.uuid4())
        with patch("custom_components.solar_inverter_bridge.core.callback.monotonic", return_value=1000) as clock, \
                patch("custom_components.solar_inverter_bridge.core.callback.send_callback", new_callable=AsyncMock) as send, \
                patch.object(callback, "ensure_listener", new_callable=AsyncMock):
            await callback.connect(manual, self.config, expected_identity=device["collector_sha256"], device_id="device")
            self.assertTrue(callback.admit("127.0.0.1", self.config["callback_port"], device["collector_sha256"]))
            manual_expiry = callback.requests[manual]["expires"]
            for cycle in range(100):
                clock.return_value = 1000 + 121 * (cycle + 1)
                await callback.reconnect(device)
                self.assertEqual(send.await_count, cycle + 2)
                self.assertTrue(callback.admit("127.0.0.1", self.config["callback_port"], device["collector_sha256"]))
                automatic = [r for r in callback.requests.values() if r.get("automatic")]
                self.assertEqual(len(automatic), 1)
                self.assertLessEqual(len(callback.requests), 2)
                record = automatic[0]
                await callback.connect(record["request_id"], self.config,
                                       expected_identity=device["collector_sha256"], device_id="device")
                await callback.reconnect(device)
                if clock.return_value < manual_expiry:
                    self.assertEqual(callback.requests[manual]["expires"], manual_expiry)
                    await callback.connect(manual, self.config, expected_identity=device["collector_sha256"], device_id="device")
                else:
                    self.assertNotIn(manual, callback.requests)
                self.assertEqual(send.await_count, cycle + 2, "Status queries and rate-limited reconnects cannot resend")
            self.assertFalse(self.service.issues)
            self.service.sources = ("127.0.0.0/8",)
            await callback.connect(str(uuid.uuid4()), {**self.config, "collector_ip": "127.0.0.2"},
                                   expected_identity="another-full-identity", device_id="another-device")
            self.assertEqual(send.await_count, 102)

    async def test_expired_pending_request_retains_manual_id_without_blocking_new_attempt(self):
        callback = self.service.callback
        request = str(uuid.uuid4())
        with patch("custom_components.solar_inverter_bridge.core.callback.monotonic", return_value=1000) as clock, \
                patch("custom_components.solar_inverter_bridge.core.callback.send_callback", new_callable=AsyncMock) as send, \
                patch.object(callback, "ensure_listener", new_callable=AsyncMock):
            await callback.connect(request, self.config)
            clock.return_value = 1121
            self.assertEqual((await callback.connect(request, self.config))["state"], "timed_out")
            self.assertEqual(send.await_count, 1)
            with self.assertRaisesRegex(ValueError, "connection_request_conflict"):
                await callback.connect(request, {**self.config, "method": "auto"})
            await callback.connect(str(uuid.uuid4()), self.config)
            self.assertEqual(send.await_count, 2)
            clock.return_value = 1601
            await callback.connect(str(uuid.uuid4()), options())
            self.assertNotIn(request, callback.requests, "Manual result retention must expire")
            self.assertEqual(send.await_count, 2)

    async def test_request_capacity_never_evicts_inflight_requests(self):
        callback = self.service.callback
        self.service.sources = ("127.0.0.0/8",)
        with patch("custom_components.solar_inverter_bridge.core.callback.monotonic", return_value=1000), \
                patch("custom_components.solar_inverter_bridge.core.callback.send_callback", new_callable=AsyncMock) as send, \
                patch.object(callback, "ensure_listener", new_callable=AsyncMock):
            for index in range(32):
                await callback.connect(str(uuid.uuid4()), {**self.config, "collector_ip": f"127.0.0.{index + 1}"},
                                       expected_identity=f"identity-{index}", device_id=f"device-{index}", _automatic=True)
            pending = dict(callback.requests)
            with self.assertRaisesRegex(ValueError, "connection_request_capacity"):
                await callback.connect(str(uuid.uuid4()), self.config,
                                       expected_identity="identity-0", device_id="device-0", _automatic=True)
            self.assertEqual(callback.requests, pending)
            self.assertEqual(send.await_count, 32)

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

    async def test_connected_view_and_admission_preserve_callback_route_constraints(self):
        request = str(uuid.uuid4())
        callback = self.service.callback
        await callback.connect(request, self.config)
        await self.identify(b"ROUTE-CHECK")
        await self.wait_state(request, "connected")
        record = callback.requests[request]
        self.assertEqual(callback.view(record)["state"], "connected")
        for config in ({**self.config, "collector_ip": "127.0.0.2"},
                       {**self.config, "callback_port": 8899 if self.config["callback_port"] != 8899 else 8900},
                       {**self.config, "method": "redirect"}):
            self.assertEqual(callback.view({**record, "config": config})["state"], "disconnected")
        callback.requests[request] = {**record, "config": {**self.config, "method": "redirect"}}
        self.assertFalse(callback.admit("127.0.0.1", self.config["callback_port"], record["collector_sha256"]),
                         "Stored redirect hints cannot authorize a callback socket")

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
        redirect = {**self.config, "method": "redirect"}
        result = await self.service.callback.change(str(uuid.uuid4()), device["device_id"], redirect, saved.append)
        self.assertEqual(result["state"], "connected")
        self.assertEqual(saved[-1]["collector_ip"], "127.0.0.1")
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

    async def test_redirect_keeps_hints_without_listener_or_udp(self):
        device = self.enrolled()
        persisted = []
        before = len(self.service.servers)
        with patch.object(self.service.callback, "ensure_listener", new_callable=AsyncMock,
                          side_effect=OSError("port_in_use")) as listener, \
                patch("custom_components.solar_inverter_bridge.core.callback.send_callback", new_callable=AsyncMock) as send:
            for host in ("", "192.168.200.17"):
                saved = options("redirect", "127.0.0.1", host)
                result = await self.service.callback.change(str(uuid.uuid4()), device["device_id"], saved, persisted.append)
                self.assertEqual(persisted[-1], saved)
                self.assertEqual(result["collector_ip"], "127.0.0.1")
                self.assertEqual(result["connection_method"], "redirect")
                self.assertFalse(result["sent"])
                await self.service.callback.reconnect(device)
            listener.assert_not_awaited()
            send.assert_not_awaited()
        self.assertEqual(len(self.service.servers), before)
        self.assertTrue(self.messages.empty())

    async def test_redirect_wizard_binds_selected_full_pn_with_unused_retained_ip(self):
        callback = self.service.callback
        config = options("redirect", "192.168.200.17")
        request = str(uuid.uuid4())
        with patch.object(callback, "ensure_listener", new_callable=AsyncMock) as listener, \
                patch("custom_components.solar_inverter_bridge.core.callback.send_callback", new_callable=AsyncMock) as send:
            result = await callback.connect(request, config)
            self.assertEqual(result["state"], "waiting_for_connection")
            port = self.service.servers[0].sockets[0].getsockname()[1]
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            self.clients.append(writer)
            pn = b"REDIRECT-WIZARD-FULL-PN"
            writer.write(b"AT+DTUPN:" + pn + b"\r\n")
            await writer.drain()
            identity = sha256(pn).hexdigest()
            holder = await self.wait_owner(identity, port)
            self.assertEqual(holder["source"], "127.0.0.1")
            self.assertEqual(callback.enrollment_options(request, identity), config)
            with patch("custom_components.solar_inverter_bridge.core.callback.monotonic",
                       return_value=callback.requests[request]["expires"] + 1):
                self.assertEqual(callback.enrollment_options(request, identity), config,
                                 "Redirect enrollment must not depend on the callback admission deadline")
            with self.assertRaisesRegex(ValueError, "verification_required"):
                await self.service.enroll(identity, "Still requires native verification")
            self.assertEqual(callback.bind(request, "selected-device", identity), config)
            self.assertEqual(callback.requests[request]["expected_identity"], identity)
            self.assertEqual(callback.identities[identity], "selected-device")
            listener.assert_not_awaited()
            send.assert_not_awaited()

    async def test_redirect_change_ignores_hint_allowlist_and_other_collector_at_hint(self):
        device = self.enrolled()
        callback = self.service.callback
        port = self.service.servers[0].sockets[0].getsockname()[1]
        for pn in (b"SWITCH-COLLECTOR", b"OTHER-COLLECTOR"):
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            self.clients.append(writer)
            writer.write(b"AT+DTUPN:" + pn + b"\r\n")
            await writer.drain()
            await self.wait_owner(sha256(pn).hexdigest(), port)
        owner = self.service.connections[device["collector_sha256"]]
        saved = []
        with patch.object(callback, "ensure_listener", new_callable=AsyncMock) as listener, \
                patch("custom_components.solar_inverter_bridge.core.callback.send_callback", new_callable=AsyncMock) as send:
            for ip, error in (("192.168.200.17", "callback_source_not_allowed"),
                              ("127.0.0.1", "callback_identity_mismatch")):
                config = options("redirect", ip)
                result = await callback.change(str(uuid.uuid4()), device["device_id"], config, saved.append)
                self.assertEqual(result["state"], "connected")
                self.assertEqual(saved[-1], config)
                self.assertIs(self.service.connections[device["collector_sha256"]], owner)
                for method in ("callback", "auto"):
                    active = {**self.config, "method": method, "collector_ip": ip}
                    with self.assertRaisesRegex(ValueError, error):
                        await callback.change(str(uuid.uuid4()), device["device_id"], active, saved.append)
                    with self.assertRaisesRegex(ValueError, error):
                        await callback.connect(str(uuid.uuid4()), active, expected_identity=device["collector_sha256"])
            listener.assert_not_awaited()
            send.assert_not_awaited()
        self.assertEqual(len(saved), 2)

    async def test_redirect_retained_ip_never_authorizes_actual_tcp_source(self):
        config = options("redirect", "127.0.0.2")
        await self.service.callback.connect(str(uuid.uuid4()), config)
        self.assertEqual(self.service.sources, ("127.0.0.1",))
        port = self.service.servers[0].sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port, local_addr=("127.0.0.2", 0))
        self.clients.append(writer)
        self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
        self.assertEqual(self.service.reject_reasons["source_not_allowed"], 1)
        self.assertFalse(self.service.connections)
        self.assertFalse(self.service.candidates)

    async def test_superseded_manual_change_cannot_revert_saved_connection(self):
        device = self.enrolled(enabled=False)
        callback = self.service.callback
        saved = []
        request = str(uuid.uuid4())
        with patch("custom_components.solar_inverter_bridge.core.callback.monotonic", return_value=1000) as clock:
            await callback.change(request, device["device_id"], self.config, saved.append)
            await callback.change(str(uuid.uuid4()), device["device_id"], options("redirect"), saved.append)
            with self.assertRaisesRegex(ValueError, "connection_request_conflict"):
                await callback.change(request, device["device_id"], self.config, saved.append)
            self.assertEqual(len(saved), 2)
            clock.return_value = 1601
            await callback.connect(str(uuid.uuid4()), options())
            self.assertNotIn(request, callback.requests)
        self.assertTrue(self.messages.empty())

    async def test_queued_verify_sends_nothing_after_connection_change(self):
        device = self.enrolled()
        identity = device["collector_sha256"]
        port = self.service.servers[0].sockets[0].getsockname()[1]
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        self.clients.append(writer)
        writer.write(b"AT+DTUPN:SWITCH-COLLECTOR\r\n")
        await writer.drain()
        old = await self.wait_owner(identity, port)
        await self.service.callback.change(str(uuid.uuid4()), device["device_id"], self.config, lambda config: None)
        await self.identify(b"SWITCH-COLLECTOR")
        current = await self.wait_owner(identity, self.config["callback_port"])

        class QueuedLock:
            def __init__(self):
                self.lock = asyncio.Lock()
                self.waiters = asyncio.Queue()
            def locked(self):
                return self.lock.locked()
            async def __aenter__(self):
                self.waiters.put_nowait(asyncio.current_task())
                await self.lock.acquire()
            async def __aexit__(self, *args):
                self.lock.release()

        lock = current["lock"] = QueuedLock()
        await lock.lock.acquire()
        change = asyncio.create_task(self.service.callback.change(
            str(uuid.uuid4()), device["device_id"], {**self.config, "method": "redirect"}, lambda config: None))
        verify = None
        try:
            self.assertIs(await asyncio.wait_for(lock.waiters.get(), 2), change)
            with patch("custom_components.solar_inverter_bridge.core.exchange.read_snapshot", new_callable=AsyncMock) as read, \
                    patch.object(current["reader"], "send", new_callable=AsyncMock) as send:
                verify = asyncio.create_task(self.service.verify(identity, discover=True))
                self.assertIs(await asyncio.wait_for(lock.waiters.get(), 2), verify)
                lock.lock.release()
                self.assertEqual((await change)["state"], "connected")
                with self.assertRaisesRegex(ConnectionError, "collector_session_changed"):
                    await verify
                self.assertIs(self.service.connections[identity], old)
                read.assert_not_awaited()
                send.assert_not_awaited()
                self.assertTrue(self.service.callback.live(current))
                self.assertNotIn(identity, self.service.profile_searches)
        finally:
            for task in (change, verify):
                if task is not None:
                    task.cancel()
            await asyncio.gather(*(t for t in (change, verify) if t is not None), return_exceptions=True)

    async def test_verify_rejects_owner_while_connection_switch_is_pending(self):
        device = self.enrolled()
        identity = device["collector_sha256"]
        await self.service.callback.change(str(uuid.uuid4()), device["device_id"], self.config, lambda config: None)
        await self.identify(b"SWITCH-COLLECTOR")
        holder = await self.wait_owner(identity, self.config["callback_port"])
        self.service.callback.switching.add(device["device_id"])
        try:
            with patch.object(holder["reader"], "send", new_callable=AsyncMock) as send:
                with self.assertRaisesRegex(ConnectionError, "collector_session_changed"):
                    await self.service.verify(identity)
                send.assert_not_awaited()
                self.assertTrue(self.service.callback.live(holder))
        finally:
            self.service.callback.switching.clear()


class ConnectionOptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirect_hints_skip_interface_validation_but_callback_still_requires_it(self):
        # Execute the real, isolated adapter function without HA's registration
        # decorators. This is an offline option contract, not an HA lifecycle test.
        path = Path(__file__).parents[1] / "custom_components/solar_inverter_bridge/websocket_api.py"
        tree = ast.parse(path.read_text())
        function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_connection_options")
        namespace = {"__package__": "custom_components.solar_inverter_bridge"}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
        configure = namespace["_connection_options"]
        message = {"method": "redirect", "collector_ip": "192.168.1.20", "callback_host": "",
                   "callback_port": 8899, "udp_port": 58899}
        with patch("custom_components.solar_inverter_bridge.network_hints.async_network_hints", new_callable=AsyncMock,
                   return_value={"addresses": [{"address": "192.168.1.10"}]}) as hints:
            for host in ("", "192.168.99.99"):
                result = await configure(None, {**message, "callback_host": host})
                self.assertEqual(result["collector_ip"], message["collector_ip"])
                self.assertEqual(result.get("callback_host", ""), host)
            hints.assert_not_awaited()
            for method in ("auto", "callback"):
                with self.assertRaisesRegex(ValueError, "callback_host_not_local"):
                    await configure(None, {**message, "method": method, "callback_host": "192.168.99.99"})
                result = await configure(None, {**message, "method": method, "callback_host": "192.168.1.10"})
                self.assertEqual(result["method"], method)
            with self.assertRaisesRegex(ValueError, "invalid_callback_address"):
                await configure(None, {**message, "method": "callback", "collector_ip": "", "callback_host": "192.168.1.10"})
