"""Install the ZIP in a separate process with no project path on sys.path."""

import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

from tools.build_release import build


def test_clean_artifact_install(tmp_path):
    archive = build(tmp_path / "artifacts")
    config = tmp_path / "config"
    config.mkdir()
    with ZipFile(archive) as candidate:
        candidate.extractall(config)
    suite = config / "test_candidate.py"
    suite.write_text('''
from pathlib import Path
import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

@pytest.fixture
def hass_config_dir():
    return str(Path(__file__).parent)

async def test_install(hass, enable_custom_integrations, socket_enabled, monkeypatch):
    from custom_components.solar_inverter_bridge.core.session import CollectorService
    import custom_components.solar_inverter_bridge as integration
    assert Path(integration.__file__).is_relative_to(Path(__file__).parent)
    original = CollectorService.start
    async def loopback(self, host=None, ports=None):
        return await original(self, host="127.0.0.1", ports=(0,0))
    monkeypatch.setattr(CollectorService, "start", loopback)
    entry = MockConfigEntry(domain="solar_inverter_bridge", data={}, options={"allowed_sources":["127.0.0.1/32"]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.services.has_service("solar_inverter_bridge", "apply_parameter")
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert await hass.config_entries.async_unload(entry.entry_id)
''')
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run([sys.executable, "-m", "pytest", "test_candidate.py", "-q",
                             "-o", "asyncio_mode=auto", "-o", "asyncio_default_fixture_loop_scope=function"],
                            cwd=config, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
