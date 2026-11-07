"""The installable candidate is deterministic and excludes private workspace data."""

import hashlib
import posixpath
import re
from pathlib import Path
import tempfile
import unittest
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from tools.build_release import build


class ReleaseTests(unittest.TestCase):
    def test_archive_is_reproducible_and_installable(self):
        with tempfile.TemporaryDirectory() as directory:
            target = build(Path(directory))
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            target = build(Path(directory))
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)
            with ZipFile(target) as archive:
                names = archive.namelist()
                self.assertIn("custom_components/solar_inverter_bridge/manifest.json", names)
                self.assertIn("custom_components/solar_inverter_bridge/frontend/panel.css", names)
                self.assertIn("custom_components/solar_inverter_bridge/frontend/routers.html", names)
                self.assertIn("custom_components/solar_inverter_bridge/frontend/router-guide.js", names)
                self.assertIn("custom_components/solar_inverter_bridge/frontend/collector-domains.json", names)
                self.assertIn("custom_components/solar_inverter_bridge/brand/icon.png", names)
                self.assertIn("custom_components/solar_inverter_bridge/diagnostics.py", names)
                self.assertIn("LICENSE", names)
                self.assertIn("THIRD_PARTY_NOTICES.md", names)
                self.assertIn("Copyright (c) 2026 Inverter Local Bridge contributors", archive.read("THIRD_PARTY_NOTICES.md").decode())
                self.assertTrue(archive.read("LICENSE").startswith(b"Mozilla Public License Version 2.0"))
                self.assertIn("INSTALL.md", names)
                self.assertIn("PROTOCOLS_AND_PROFILES.md", names)
                self.assertIn("PROFILE_EXPANSION.md", names)
                self.assertIn("DEVICE_COMPATIBILITY.md", names)
                self.assertTrue(all(name.startswith("custom_components/solar_inverter_bridge/") or name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "INSTALL.md", "PROTOCOLS_AND_PROFILES.md", "PROFILE_EXPANSION.md", "DEVICE_COMPATIBILITY.md") for name in names))
                self.assertFalse(any("__pycache__" in name or "private" in name or name.endswith(".sqlite3") for name in names))
                for name in ("INSTALL.md", "PROTOCOLS_AND_PROFILES.md", "PROFILE_EXPANSION.md", "DEVICE_COMPATIBILITY.md", "THIRD_PARTY_NOTICES.md"):
                    text = archive.read(name).decode()
                    for raw in re.findall(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)", text):
                        link = urlsplit(raw)
                        if link.scheme or not link.path:
                            continue
                        target = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(link.path)))
                        self.assertIn(target, names, f"Broken packaged link: {name} -> {raw}")
