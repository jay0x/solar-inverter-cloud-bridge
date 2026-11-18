"""Clock accuracy and accepted SMG4 binary execution, using synthetic wire frames."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from custom_components.solar_inverter_bridge.core.drivers import snapshot
from custom_components.solar_inverter_bridge.core.framing import crc16
from custom_components.solar_inverter_bridge.core.parameters import FIELDS, readback_matches
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage, StorageError
from custom_components.solar_inverter_bridge.core.telemetry import required_addresses
from custom_components.solar_inverter_bridge.core.transport import BinaryTransport, WireReader


PAUSES = (1, 10, 60, 300)
CLOCK = next(field for field in FIELDS if field.key == "inverter_datetime")


def clock_words(value):
    return value.timetuple()[:6]


class ClockReadbackTests(unittest.TestCase):
    def test_unchanged_clock_never_confirms_immediately_or_after_elapsed_time(self):
        sent = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
        target = datetime(2026, 11, 17, 15)
        for pause in PAUSES:
            for elapsed in (0, 180):
                for drift in (60, 120):
                    with self.subTest(pause=pause, elapsed=elapsed, drift=drift):
                        observed = target + timedelta(seconds=elapsed - drift)
                        self.assertFalse(readback_matches(
                            CLOCK, clock_words(target), clock_words(observed),
                            {"send_intent_at": sent.isoformat()}, pause,
                            now_utc=sent + timedelta(seconds=elapsed)))

    def test_three_second_boundary_is_independent_of_poll_pause(self):
        sent = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
        target = datetime(2026, 11, 17, 15)
        for pause in PAUSES:
            for offset in (-4, -3, 0, 3, 4):
                with self.subTest(pause=pause, offset=offset):
                    self.assertEqual(readback_matches(
                        CLOCK, clock_words(target), clock_words(target + timedelta(seconds=offset)),
                        {"send_intent_at": sent.isoformat()}, pause, now_utc=sent), abs(offset) <= 3)
            # An error just beyond the boundary must not be rounded into acceptance.
            self.assertFalse(readback_matches(
                CLOCK, clock_words(target), clock_words(target - timedelta(seconds=3)),
                {"send_intent_at": sent.isoformat()}, pause,
                now_utc=sent + timedelta(milliseconds=1)))

    def test_running_clock_confirms_across_date_rollover_and_fractional_elapsed_time(self):
        sent = datetime(2026, 12, 31, 20, 59, 59, tzinfo=timezone.utc)
        target = datetime(2026, 12, 31, 23, 59, 59)
        for pause in PAUSES:
            self.assertTrue(readback_matches(
                CLOCK, clock_words(target), (2027, 1, 1, 0, 2, 0),
                {"send_intent_at": sent.isoformat()}, pause,
                now_utc=sent + timedelta(seconds=121.25)))


class BinaryClockPeer:
    """In-memory peer: real outer framing, RTU CRC, FC16 ACK and separate FC03 reads."""

    route = (1, 255)
    slave = 5

    def __init__(self):
        self.reader = asyncio.StreamReader()
        self.closed = False
        self.ignore_write = False
        self.requests = []
        self.writes = []
        self.registers = {address: 0 for address in required_addresses()}
        self.registers.update({184: 4, 171: 33793, 201: 2, 277: 480, 280: 50, 338: 2300})
        self.set_clock(datetime(2026, 11, 17, 11, 58))

    def set_clock(self, value):
        self.registers.update({696 + i: word for i, word in enumerate(clock_words(value))})

    def write(self, data):
        tid, code, length, address, function = struct.unpack(">HHHBB", data[:8])
        payload = data[8:]
        assert length == len(payload) + 2
        assert (code, address) == self.route
        assert function == 4 and payload[0] == self.slave
        assert crc16(payload[:-2]) == int.from_bytes(payload[-2:], "little")
        register, count = struct.unpack(">HH", payload[2:6])
        self.requests.append((payload[1], register, count))
        if payload[1] == 3:
            assert len(payload) == 8
            words = tuple(self.registers.get(register + i, 0) for i in range(count))
            reply = bytes((self.slave, 3, 2 * count)) + struct.pack(">" + "H" * count, *words)
        elif payload[1] == 16:
            assert payload[6] == 2 * count and len(payload) == 9 + 2 * count
            words = struct.unpack(">" + "H" * count, payload[7:-2])
            self.writes.append((register, words))
            if not self.ignore_write:
                self.registers.update({register + i: word for i, word in enumerate(words)})
            reply = payload[:6]
        else:
            raise AssertionError("Unexpected inner function")
        reply += crc16(reply).to_bytes(2, "little")
        self.reader.feed_data(struct.pack(">HHHBB", tid, code, len(reply) + 2, address, function) + reply)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    def is_closing(self):
        return self.closed


class BinaryClockExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage = Storage(Path(self.directory.name) / "bridge.sqlite3")
        self.addCleanup(self.storage.close)
        self.target = datetime(2026, 11, 17, 12)
        self.service = CollectorService([], self.storage, now=lambda: self.target)
        self.addAsyncCleanup(self.service.close)
        self.peer = BinaryClockPeer()
        emit = lambda *args, **kwargs: None
        self.adapter = BinaryTransport(WireReader(self.peer.reader, self.peer, emit))
        self.addAsyncCleanup(self.adapter.close)
        self.adapter.route, self.adapter.slave = self.peer.route, self.peer.slave
        evidence = await snapshot(self.adapter, self.peer, "smg_4")
        self.device_id = self.storage.enroll("clock-fixture", "Clock fixture", "smg_4")
        self.acceptance = {"profile_id": "smg_4", "binding": evidence["binding"],
                           "fingerprint": evidence["fingerprint"]}
        self.storage.accept_profile(self.device_id, self.acceptance)
        self.holder = {"reader": self.adapter, "writer": self.peer,
                       "identity_sha256": "clock-fixture", "dialect": "binary",
                       "closed": asyncio.Event(), "lock": asyncio.Lock(),
                       "profile_verified": False, "capabilities": self.adapter.capabilities,
                       "emit": emit}
        self.service.connections["clock-fixture"] = self.holder
        await self.service.poll_once(self.device_id)
        self.peer.requests.clear()

    async def apply_clock(self, operation_id):
        return await self.service.apply(self.device_id, "inverter_datetime", self.target.isoformat(),
                                        operation_id, clock_sync=True)

    async def test_accepted_binary_clock_writes_fc16_and_reads_back_once(self):
        self.storage.set_clock_sync(self.device_id, True)
        device = self.storage.device(self.device_id)
        caps = self.service.transport_capabilities(device)
        self.assertTrue(caps["clock_write"])
        self.assertFalse(caps["module_reset"])
        # Execution must restore the accepted nondefault route/slave, not use
        # an adapter's incidental defaults or the reference profile's route.
        self.adapter.route, self.adapter.slave = (1, 1), 1
        result = await self.service._maybe_clock(device, "2026-11-17T11:58:00")
        self.assertEqual(result["outcome"], "confirmed")
        self.assertFalse(result["unresolved"])
        self.assertEqual(result["write_attempts"], 1)
        self.assertTrue(result["send_intent_at"])
        self.assertEqual(result["send_value"], self.target.isoformat())
        self.assertEqual(self.peer.writes, [(696, clock_words(self.target))])
        self.assertEqual(self.peer.requests[-2:], [(16, 696, 6), (3, 696, 6)])
        self.assertEqual(self.service.settings[self.device_id]["inverter_datetime"], self.target.isoformat())
        self.peer.requests.clear()
        self.assertEqual(await self.apply_clock(result["operation_id"]), result)
        self.assertEqual(self.peer.requests, [])

    async def test_opt_in_and_unresolved_guards_send_no_clock_commands(self):
        device = self.storage.device(self.device_id)
        self.assertIsNone(await self.service._maybe_clock(device, "2026-11-17T11:58:00"))
        with self.assertRaisesRegex(ValueError, "clock_write_not_allowed"):
            await self.apply_clock("disabled")
        self.storage.set_clock_sync(self.device_id, True)
        self.storage.accept_operation(self.device_id, "pending", {"key": "lcd_backlight", "value": "always_on"})
        self.storage.claim_send("pending")
        device = self.storage.device(self.device_id)
        self.assertIsNone(await self.service._maybe_clock(device, "2026-11-17T11:58:00"))
        with self.assertRaisesRegex(StorageError, "device_busy_or_unresolved"):
            await self.apply_clock("blocked")
        self.assertEqual(self.peer.requests, [])
        self.assertEqual(self.peer.writes, [])

    async def test_current_session_and_transport_acceptance_still_gate_clock(self):
        self.storage.set_clock_sync(self.device_id, True)
        device = self.storage.device(self.device_id)
        self.holder["profile_verified"] = False
        self.assertFalse(self.service.transport_capabilities(device)["clock_write"])
        with self.assertRaisesRegex(ValueError, "transport_write_unsupported"):
            await self.apply_clock("unverified-session")
        self.holder["profile_verified"] = True
        self.service.profile_acceptances.clear()
        self.assertFalse(self.service.transport_capabilities(device)["clock_write"])
        changed = {**self.acceptance, "binding": {**self.acceptance["binding"], "transport": "at"}}
        self.storage.accept_profile(self.device_id, changed)
        self.service.profile_acceptances[self.device_id] = changed
        self.assertFalse(self.service.transport_capabilities(device)["clock_write"])
        with self.assertRaisesRegex(ValueError, "accepted_profile_transport_changed"):
            await self.apply_clock("wrong-transport")
        self.assertEqual(self.peer.requests, [])

    async def test_changed_definition_or_identity_cannot_send_clock(self):
        self.storage.set_clock_sync(self.device_id, True)
        changed = {**self.acceptance, "binding": {**self.acceptance["binding"], "definition_sha256": "0" * 64}}
        self.storage.accept_profile(self.device_id, changed)
        with self.assertRaisesRegex(ValueError, "accepted_profile_fingerprint_changed"):
            await self.apply_clock("old-definition")
        self.assertEqual(self.peer.requests, [])
        self.storage.accept_profile(self.device_id, self.acceptance)
        self.peer.registers[171] = 32768
        with self.assertRaisesRegex(ValueError, "accepted_profile_fingerprint_changed"):
            await self.apply_clock("changed-identity")
        self.assertEqual(self.peer.writes, [])

    async def test_ack_without_effect_stays_unresolved_at_every_pause(self):
        self.storage.set_clock_sync(self.device_id, True)
        self.peer.ignore_write = True
        await self.service.incidents.arm(self.device_id, 1)
        for pause in PAUSES:
            with self.subTest(pause=pause):
                self.storage.set_collection(self.device_id, True, pause)
                self.peer.set_clock(self.target - timedelta(seconds=120))
                operation_id = f"ignored-{pause}"
                result = await self.apply_clock(operation_id)
                self.assertEqual(result["outcome"], "readback_mismatch")
                self.assertTrue(result["unresolved"])
                incidents = self.service.incidents.view(self.device_id)
                mismatch = next(item for item in incidents["incidents"] if item["code"] == "readback_mismatch")
                self.assertEqual(mismatch["status"], "unrecovered")
                self.assertEqual(incidents["watch"]["status"], "captured")
                self.service._note_success(self.device_id)
                self.assertEqual(self.service.incidents.view(self.device_id)["incidents"][0]["recovered_count"], 0)
                writes = list(self.peer.writes)
                sent = datetime.fromisoformat(result["send_intent_at"])
                # Reconciliation uses the expected running clock, not literal old words.
                self.peer.set_clock(self.target + timedelta(seconds=180 - 120))
                with patch("custom_components.solar_inverter_bridge.core.parameters.datetime", wraps=datetime) as clock:
                    clock.now.return_value = sent + timedelta(seconds=180)
                    self.assertEqual(await self.service.reconcile(self.device_id), [])
                    self.assertTrue(self.storage.operation(operation_id)["unresolved"])
                    self.peer.set_clock(self.target + timedelta(seconds=181))
                    self.assertEqual(await self.service.reconcile(self.device_id), [operation_id])
                resolved = self.storage.operation(operation_id)
                self.assertFalse(resolved["unresolved"])
                self.assertEqual(resolved["outcome"], "readback_mismatch")
                self.assertEqual(self.peer.writes, writes)
