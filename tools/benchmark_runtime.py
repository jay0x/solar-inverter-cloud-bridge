"""Bounded loopback monitoring benchmark. It never connects to HA or equipment."""

import argparse
import asyncio
import json
from pathlib import Path
import platform
import os
import resource
import sys
import tempfile
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.solar_inverter_bridge.core.exchange import response_frame
from custom_components.solar_inverter_bridge.core.session import CollectorService
from custom_components.solar_inverter_bridge.core.storage import Storage
from custom_components.solar_inverter_bridge.core.telemetry import required_addresses
from tools.build_release import component_fingerprint
from custom_components.solar_inverter_bridge.core.binary import BinaryFrame
import struct


def resident_kib():
    if sys.platform != "linux":
        return None
    return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE") // 1024


async def benchmark(count, duration, transport="at", rotate=False):
    with tempfile.TemporaryDirectory() as directory:
        storage = Storage(Path(directory) / "bridge.sqlite3")
        service = CollectorService(["127.0.0.1"], storage)
        port = (await service.start())[0][1]
        reads = 0
        reconnects = {}
        stopping = asyncio.Event()

        async def collector(index):
            nonlocal reads
            binary = transport == "binary" or (transport == "mixed" and index % 2 == 1)
            registers = {address: 0 for address in required_addresses()}
            registers.update({171: 32771, 184: 4, 201: 2, 277: 480, 280: 50, 302: 1000 + index,
                              696: 2026, 697: 11, 698: 2})
            pn = f"BENCH{index}".encode()
            reconnects[index] = -1
            while not stopping.is_set():
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                reconnects[index] += 1
                try:
                    if binary:
                        writer.write(BinaryFrame(0x7000, 0, 1, 1, pn).encode())
                    else:
                        await reader.readuntil(b"\n")
                        writer.write(b"AT+DTUPN:" + pn + b"\r\n")
                    await writer.drain()
                    while True:
                        if binary:
                            header = await reader.readexactly(8)
                            tid, code, length, outer_address, function = struct.unpack(">HHHBB", header)
                            frame = await reader.readexactly(length - 2)
                            if function == 1:
                                reply = b""
                            elif function == 2:
                                reply = b"\x00" + frame + pn
                            elif function != 4:
                                raise RuntimeError("unexpected_binary_function")
                            else:
                                reply = None
                        else:
                            prefix = await reader.readexactly(2)
                            if prefix == b"AT":
                                line = prefix + await reader.readuntil(b"\n")
                                if line != b"AT+HTBT?\r\n":
                                    raise RuntimeError("unexpected_at_command")
                                writer.write(b"AT+HTBT:\r\n")
                                await writer.drain()
                                continue
                            frame = prefix + await reader.readexactly(6)
                            reply = None
                        if reply is None:
                            if frame[1] != 3:
                                raise RuntimeError("unexpected_write_in_monitoring_benchmark")
                            reads += 1
                            address, words = int.from_bytes(frame[2:4], "big"), int.from_bytes(frame[4:6], "big")
                            reply = response_frame(tuple(registers.get(address + i, 0) for i in range(words)))
                        writer.write(BinaryFrame(tid, code, outer_address, function, reply).encode() if binary else reply)
                        await writer.drain()
                except (ConnectionError, asyncio.IncompleteReadError):
                    pass
                finally:
                    writer.close()
                    await writer.wait_closed()
                if not stopping.is_set():
                    await asyncio.sleep(0.05)

        tasks = [asyncio.create_task(collector(i)) for i in range(count)]
        try:
            async with asyncio.timeout(5):
                while len(service.candidates) != count:
                    await asyncio.sleep(0.01)
            await asyncio.gather(*(service.verify(key) for key in service.candidates))
            await asyncio.gather(*(service.enroll(key, "Benchmark") for key in service.candidates))
            async with asyncio.timeout(5):
                while len(service.observations) != count:
                    await asyncio.sleep(0.01)
            lags = []
            started = previous = monotonic()
            before = resource.getrusage(resource.RUSAGE_SELF)
            start_rss = resident_kib()
            start_reads = reads
            queue_peak = task_peak = 0
            rotated = False
            while monotonic() - started < duration:
                await asyncio.sleep(0.01)
                current = monotonic()
                lags.append(max(0, current - previous - 0.01) * 1000)
                previous = current
                if rotate and not rotated and current - started >= 5:
                    for holder in service.connections.values():
                        if holder.get("dialect") == "binary":
                            holder["reader"]._tid = 65535
                    rotated = True
                queue_peak = max(queue_peak, storage.queue.qsize())
                task_peak = max(task_peak, len(service.tasks))
            after = resource.getrusage(resource.RUSAGE_SELF)
            lags.sort()
            percentile = lambda fraction: round(lags[min(len(lags) - 1, int(len(lags) * fraction))], 3)
            return {
                "kind": "synthetic_loopback_not_hardware", "python": platform.python_version(), "platform": sys.platform,
                "candidate_sha256": component_fingerprint(),
                "devices": count, "poll_interval_seconds": 10, "duration_seconds": round(monotonic() - started, 2),
                "transport": transport, "forced_tid_exhaustion": rotated, "reconnections": sum(reconnects.values()),
                "poll_failures": dict(service._failures), "poll_cycles": dict(service.poll_cycles),
                "issues": [issue["code"] for issue in service.issues],
                "lag_samples": len(lags), "loop_lag_ms": {"p50": percentile(.5), "p95": percentile(.95), "p99": percentile(.99), "max": round(max(lags), 3)},
                "peak_rss_kib": after.ru_maxrss, "cpu_seconds": round(after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime, 3),
                "warmup_rss_kib": start_rss, "final_rss_kib": resident_kib(),
                "native_reads": reads - start_reads, "observed_devices": len(service.observations),
                "db_queue_sampled_peak": queue_peak, "service_tasks_sampled_peak": task_peak,
            }
        finally:
            stopping.set()
            await service.close()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.to_thread(storage.close)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--devices", type=int, choices=range(1, 17), default=16)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--transport", choices=("at", "binary", "mixed"), default="at")
    parser.add_argument("--rotate", action="store_true", help="Force binary TID exhaustion after five seconds")
    args = parser.parse_args()
    result = asyncio.run(benchmark(args.devices, args.seconds, args.transport, args.rotate))
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text, end="")
