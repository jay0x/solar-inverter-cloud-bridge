"""One component fingerprint definition for releases and diagnostic reports."""

import hashlib
import json
from pathlib import Path

SUFFIXES = (".py", ".json", ".yaml", ".js", ".css", ".html", ".png")


def artifact_metadata(component=None):
    root = Path(component) if component else Path(__file__).resolve().parents[1]
    files = {f"custom_components/solar_inverter_bridge/{source.relative_to(root).as_posix()}": hashlib.sha256(source.read_bytes()).hexdigest()
             for source in root.rglob("*")
             if source.is_file() and "__pycache__" not in source.parts and source.suffix in SUFFIXES}
    return {"version": json.loads((root / "manifest.json").read_text())["version"],
            "sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}
