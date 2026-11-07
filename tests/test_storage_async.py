"""Cancelled storage waiters and a full queue must not stall the event loop."""

import asyncio
from pathlib import Path
import tempfile
import threading
import unittest

from custom_components.solar_inverter_bridge.core.storage import Storage, StorageError


class AsyncStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_waiter_does_not_break_worker_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "bridge.sqlite3")
            entered, release = threading.Event(), threading.Event()
            errors = []
            loop = asyncio.get_running_loop()
            previous = loop.get_exception_handler()
            loop.set_exception_handler(lambda _, context: errors.append(context))

            def slow_job():
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("job_not_released")
                return 42

            try:
                job = asyncio.create_task(storage.async_call(slow_job))
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                job.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await job
                release.set()
                self.assertEqual(await storage.async_call(lambda: 43), 43)
                await asyncio.sleep(0)
                self.assertEqual(errors, [])
            finally:
                release.set()
                await asyncio.to_thread(storage.close)
                loop.set_exception_handler(previous)

    async def test_full_queue_fails_immediately_and_closed_worker_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "bridge.sqlite3")
            entered, release = threading.Event(), threading.Event()

            def slow_job():
                entered.set()
                release.wait(3)

            pending = []
            try:
                pending.append(asyncio.create_task(storage.async_call(slow_job)))
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                for _ in range(storage.queue.maxsize):
                    pending.append(asyncio.create_task(storage.async_call(lambda: None)))
                await asyncio.sleep(0)
                self.assertTrue(storage.queue.full())
                with self.assertRaisesRegex(StorageError, "storage_busy"):
                    await asyncio.wait_for(storage.async_call(lambda: None), 0.1)
            finally:
                release.set()
                await asyncio.gather(*pending)
                await asyncio.to_thread(storage.close)
            with self.assertRaisesRegex(StorageError, "storage_closed"):
                await storage.async_call(lambda: None)
