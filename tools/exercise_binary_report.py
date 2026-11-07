"""Create a synthetic unsupported-map report and replay it after stopping the peer.

No Home Assistant, router, real collector, or inverter writes are involved.
"""

import argparse
import asyncio
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from custom_components.solar_inverter_bridge.core.artifact import artifact_metadata
from custom_components.solar_inverter_bridge.core.compatibility import package_report, replay, validate_package
from custom_components.solar_inverter_bridge.core.exchange import response_frame
from custom_components.solar_inverter_bridge.core.session import CollectorService


async def exercise(destination):
    bridge = CollectorService(["127.0.0.1"], None, bootstrap_preference="binary")
    host, port = (await bridge.start())[0]
    bridge.compatibility.start({"inverter_model": "Synthetic unsupported 4/33793", "symptom": "Map gate rejected; synthetic software evidence only"})

    async def peer():
        reader, writer = await asyncio.open_connection(host, port)
        try:
            while True:
                header = await reader.readexactly(8)
                tid, code, length, address, function = struct.unpack(">HHHBB", header)
                payload = await reader.readexactly(length - 2)
                if function == 1:
                    response = b""
                elif function == 2 and payload == b"\x02":
                    response = b"\x00\x02SYNTHETIC-DEMO-PN"
                elif function == 4 and payload[1] == 3:
                    register = int.from_bytes(payload[2:4], "big")
                    response = response_frame((4 if register == 184 else 33793,))
                else:
                    raise ValueError("unexpected_non_read_probe")
                frame = struct.pack(">HHHBB", tid, code, len(response) + 2, address, function) + response
                writer.write(frame[:5])
                await writer.drain()
                await asyncio.sleep(0.001)
                writer.write(frame[5:])
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    task = asyncio.create_task(peer())
    try:
        async with asyncio.timeout(10):
            while not any(event["kind"] == "native_signature_rejected" for event in bridge.compatibility.events):
                await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        bridge.compatibility.stop("synthetic_peer_stopped")
        snapshot = bridge.compatibility.snapshot(bridge.listeners, raw=True, build=await asyncio.to_thread(artifact_metadata))
        archive, _ = await asyncio.to_thread(package_report, snapshot)
        result = await asyncio.to_thread(lambda: replay(validate_package(archive)))
        admissions = [item["native_admission"] for item in result["decoder_outcomes"] if "native_admission" in item]
        if "unsupported_or_unconfirmed_identity" not in admissions:
            raise RuntimeError("original_wire_did_not_reproduce_native_map_rejection")
        destination.mkdir(parents=True, exist_ok=True)
        package_path = destination / "synthetic-compatibility.zip"
        package_path.write_bytes(archive)
        (destination / "replay.json").write_text(json.dumps(result, indent=2))
        # A separate shareable package contains no original PN bytes.
        safe, _ = package_report(bridge.compatibility.snapshot(bridge.listeners, build=snapshot["build"]))
        (destination / "redacted-compatibility.zip").write_bytes(safe)
        print(json.dumps({"synthetic_only": True, "peer_stopped_before_replay": task.done(),
                          "package": str(package_path), "coverage": result["analysis"]["coverage"],
                          "findings": [item["code"] for item in result["analysis"]["findings"]],
                          "native_admissions_from_original_wire": admissions,
                          "decoder_outcomes": [item["validation"] for item in result["decoder_outcomes"]]}))
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await bridge.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(exercise(parser.parse_args().output))
