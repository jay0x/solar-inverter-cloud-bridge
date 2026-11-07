"""Raw UART turnaround, deadline evidence and partial polling failure accounting."""

import asyncio
from pathlib import Path
import tempfile
from time import monotonic
import unittest
from unittest.mock import AsyncMock, patch

from custom_components.solar_inverter_bridge.core.exchange import read_words, response_frame, write_words
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage
from custom_components.solar_inverter_bridge.core.transport import ATTransport


class TurnaroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_same_length_reply_is_not_used_for_an_unsent_query(self):
        reader=asyncio.StreamReader()
        class Writer:
            sent=[]
            def write(self,data):self.sent.append(data)
            async def drain(self):pass
        writer=Writer();adapter=ATTransport(reader,writer,lambda *a,**k:None)
        adapter.raw_session_identified=True
        stale=response_frame((123,))
        reader.feed_data(stale)
        with self.assertRaisesRegex(ValueError,"unsolicited_data_before_request"):
            await read_words(adapter,writer,184,1)
        self.assertFalse(writer.sent)
        self.assertEqual(await adapter.readexactly(len(stale)),stale)

    async def test_busy_uart_drops_unspaced_requests_but_accepts_guarded_reads(self):
        for gap in (0, 0.05):
            reader = asyncio.StreamReader()
            emitted = []
            class Writer:
                last_reply = None
                def write(self, data):
                    now = monotonic()
                    if self.last_reply is not None and now - self.last_reply < .045:
                        return
                    self.last_reply = now
                    reader.feed_data(response_frame((4,)))
                async def drain(self): pass
            writer = Writer()
            adapter = ATTransport(reader, writer, lambda kind, **fields: emitted.append((kind, fields)))
            adapter.minimum_gap = gap
            await read_words(adapter, writer, 184, 1, timeout=.2)
            if gap:
                values, _, _ = await read_words(adapter, writer, 184, 1, timeout=.2)
                self.assertEqual(values, (4,))
            else:
                with self.assertRaises(TimeoutError) as caught:
                    await read_words(adapter, writer, 184, 1, timeout=.02)
                self.assertEqual(caught.exception.received_bytes, 0)
                self.assertGreaterEqual(caught.exception.elapsed_ms, 15)
                self.assertEqual(emitted[-1][0], "exchange_failed")

    async def test_turnaround_is_inside_write_deadline_and_sends_nothing_after_cancel(self):
        reader = asyncio.StreamReader()
        class Writer:
            sent = []
            def write(self, data): self.sent.append(data)
            async def drain(self): pass
        writer = Writer()
        adapter = ATTransport(reader, writer, lambda *a, **k: None)
        adapter.last_receive_monotonic = monotonic()
        with self.assertRaises(TimeoutError):
            await write_words(adapter, writer, 679, (1,), timeout=.01)
        self.assertFalse(writer.sent)

    async def test_settings_timeout_is_not_counted_as_a_successful_poll(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory)/"bridge.sqlite3")
            service = CollectorService([], storage)
            device_id = storage.enroll("test-pn", "Test", "modbus_protocol_4")
            class Writer:
                closed = False
                def is_closing(self): return self.closed
                def close(self): self.closed = True
            def connect():
                writer = Writer()
                adapter = ATTransport(asyncio.StreamReader(), writer, lambda *a, **k: None)
                service.connections["test-pn"] = {"reader":adapter,"writer":writer,"identity_sha256":"test-pn",
                    "closed":asyncio.Event(),"lock":asyncio.Lock(),"dialect":"at","emit":lambda *a,**k:None}
            snapshot = {"profile_id":"modbus_protocol_4","protocol_number":4,"model_code":32771,
                        "values":{"battery_voltage":{"value":48,"unit":"V"}}}
            try:
                with patch("custom_components.solar_inverter_bridge.core.exchange.read_snapshot", AsyncMock(return_value=snapshot)), \
                     patch("custom_components.solar_inverter_bridge.core.exchange.read_settings", AsyncMock(side_effect=TimeoutError())):
                    for _ in range(3):
                        connect()
                        await service._poll_device(device_id)
                self.assertEqual(service._failures[device_id], 3)
                self.assertEqual(service.poll_errors[device_id], 3)
                self.assertEqual(service._healthy[device_id], 0)
                self.assertGreater(service._next_poll[device_id]-monotonic(), 25)
                self.assertIn(device_id, service.observations)
                self.assertNotIn(device_id, service._settings_observed)
                # Planned binary TID rotation during settings is neither a
                # settings success nor a fault/backoff increment.
                before=service._failures[device_id]
                with patch("custom_components.solar_inverter_bridge.core.exchange.read_snapshot", AsyncMock(return_value=snapshot)), \
                     patch("custom_components.solar_inverter_bridge.core.exchange.read_settings", AsyncMock(side_effect=ConnectionError("planned_tid_rotation"))):
                    connect()
                    await service._poll_device(device_id)
                self.assertEqual(service._failures[device_id],before)
                self.assertEqual(service.poll_errors[device_id],3)
            finally:
                await service.close()
                storage.close()
