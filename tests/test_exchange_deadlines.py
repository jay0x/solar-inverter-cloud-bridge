"""A transaction deadline includes drain and cannot be extended by partial bytes."""

import asyncio
import unittest

from custom_components.solar_inverter_bridge.core.exchange import read_words, response_frame, write_words


class Writer:
    def __init__(self, blocked=False):
        self.blocked = blocked
        self.requests = []

    def write(self, data):
        self.requests.append(data)

    async def drain(self):
        if self.blocked:
            await asyncio.Event().wait()


class ExchangeDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_dripping_partial_response_does_not_restart_deadline(self):
        reader, writer = asyncio.StreamReader(), Writer()

        async def drip():
            for byte in response_frame((42,)):
                await asyncio.sleep(0.02)
                reader.feed_data(bytes([byte]))

        task = asyncio.create_task(drip())
        try:
            with self.assertRaises(TimeoutError) as raised:
                await read_words(reader, writer, 601, 1, timeout=0.05)
            self.assertEqual(raised.exception.register_address, 601)
            self.assertEqual(raised.exception.function, 3)
            self.assertEqual(len(writer.requests), 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_write_deadline_includes_backpressure(self):
        reader, writer = asyncio.StreamReader(), Writer(blocked=True)
        with self.assertRaises(TimeoutError):
            await write_words(reader, writer, 601, (2,), timeout=0.02)
        self.assertEqual(len(writer.requests), 1)
