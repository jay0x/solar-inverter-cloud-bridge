"""Build a deterministic manual-install candidate without private workspace data."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from custom_components.solar_inverter_bridge.core.artifact import artifact_metadata, SUFFIXES


def component_fingerprint():
    return artifact_metadata()["sha256"]


def release_sources():
    """Return the explicit package manifest without creating files or archives."""
    component = ROOT / "custom_components/solar_inverter_bridge"
    files = {"LICENSE": ROOT / "LICENSE", "THIRD_PARTY_NOTICES.md": ROOT / "THIRD_PARTY_NOTICES.md",
             "INSTALL.md": ROOT / "docs/INSTALL.md",
             "PROTOCOLS_AND_PROFILES.md": ROOT / "docs/PROTOCOLS_AND_PROFILES.md",
             "PROFILE_EXPANSION.md": ROOT / "docs/PROFILE_EXPANSION.md",
             "DEVICE_COMPATIBILITY.md": ROOT / "docs/DEVICE_COMPATIBILITY.md"}
    for source in component.rglob("*"):
        if source.is_file() and "__pycache__" not in source.parts and source.suffix in SUFFIXES:
            if source.is_symlink():
                raise ValueError("release_source_must_not_be_a_symlink")
            if "private" in source.relative_to(ROOT).parts:
                raise ValueError("private_source_must_not_be_packaged")
            files[source.relative_to(ROOT).as_posix()] = source
    for name, source in files.items():
        if source.is_symlink():
            raise ValueError("release_source_must_not_be_a_symlink")
        resolved = source.resolve()
        if not resolved.is_relative_to(ROOT) or "private" in resolved.relative_to(ROOT).parts:
            raise ValueError("private_or_external_source_must_not_be_packaged")
    return files


def release_content(source):
    """Read the exact future archive content; no output file is written."""
    content = source.read_bytes()
    if source.parent == ROOT / "docs" and source.suffix == ".md":
        # Stable user guides live in docs/ in Git and at the ZIP root.
        content = content.replace(b"](../custom_components/", b"](custom_components/")
    return content


def build(destination):
    files = release_sources()
    version = json.loads((ROOT / "custom_components/solar_inverter_bridge/manifest.json").read_text())["version"]
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"solar-inverter-bridge-{version}.zip"
    with ZipFile(target, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, source in sorted(files.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, release_content(source))
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    target = build(parser.parse_args().output)
    print(target.name, hashlib.sha256(target.read_bytes()).hexdigest())
