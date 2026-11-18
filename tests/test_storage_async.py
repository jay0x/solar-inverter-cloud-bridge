"""Cancelled storage waiters and a full queue must not stall the event loop."""

import asyncio
from pathlib import Path
import tempfile
import threading
from time import monotonic
import unittest
from unittest.mock import patch

from custom_components.solar_inverter_bridge.core.storage import Storage, StorageError


class AsyncStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_caller_waiting_for_queue_space_does_not_block_async_admission_or_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "bridge.sqlite3")
            worker_entered, release, sync_entered = threading.Event(), threading.Event(), threading.Event()
            rejected_job_ran = threading.Event()
            pending = []
            sync = heartbeat = None
            # Keep a broken implementation from deadlocking the test runner.
            watchdog = threading.Timer(2, release.set)

            def slow_job():
                worker_entered.set()
                if not release.wait(5):
                    raise RuntimeError("job_not_released")

            original_put = storage.queue.put

            def blocked_sync_put(*args, **kwargs):
                # Storage.call holds _admit before entering Queue.put.
                sync_entered.set()
                return original_put(*args, **kwargs)

            async def pulse():
                for _ in range(3):
                    await asyncio.sleep(0.01)
                    self.assertFalse(release.is_set(), "Heartbeat stalled until the watchdog released the worker")

            try:
                pending.append(asyncio.create_task(storage.async_call(slow_job)))
                self.assertTrue(await asyncio.to_thread(worker_entered.wait, 2))
                for _ in range(storage.queue.maxsize):
                    pending.append(asyncio.create_task(storage.async_call(lambda: None)))
                await asyncio.sleep(0)
                self.assertTrue(storage.queue.full())
                with patch.object(storage.queue, "put", side_effect=blocked_sync_put):
                    sync = asyncio.create_task(asyncio.to_thread(storage.call, lambda: 73, timeout=4))
                    self.assertTrue(await asyncio.to_thread(sync_entered.wait, 2))
                    self.assertTrue(storage._admit.locked())
                    watchdog.start()
                    heartbeat = asyncio.create_task(pulse())
                    started = monotonic()
                    with self.assertRaisesRegex(StorageError, "storage_busy"):
                        await storage.async_call(rejected_job_ran.set)
                    self.assertLess(monotonic() - started, 0.5)
                    await asyncio.wait_for(heartbeat, 0.5)
                    self.assertFalse(sync.done(), "The synchronous caller should still be waiting for queue space")
                    release.set()
                    self.assertEqual(await sync, 73, "Synchronous admission must still wait and execute normally")
                await asyncio.gather(*pending)
                self.assertFalse(rejected_job_ran.is_set(), "Rejected async work must never reach the worker")
                self.assertEqual(await storage.async_call(lambda: 74), 74)
            finally:
                watchdog.cancel()
                release.set()
                await asyncio.gather(*pending, *(task for task in (sync, heartbeat) if task is not None),
                                     return_exceptions=True)
                await asyncio.to_thread(storage.close)

    async def test_async_admission_preserves_backup_refusal_and_resumes_after_release(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "bridge.sqlite3")
            attempted = threading.Event()
            try:
                await asyncio.to_thread(storage.begin_backup)
                with self.assertRaisesRegex(StorageError, "storage_backup_in_progress"):
                    await storage.async_call(attempted.set)
                self.assertFalse(storage._admit.locked(), "Refusal must release admission")
                self.assertFalse(attempted.is_set())
                await asyncio.to_thread(storage.end_backup)
                self.assertEqual(await storage.async_call(lambda: 42), 42)
            finally:
                await asyncio.to_thread(storage.end_backup)
                await asyncio.to_thread(storage.close)

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
