# Development workflow

Read the [project overview](../../README.md), [documentation index](../README.md)
and [active decisions](decisions.md). This is an implemented development candidate,
not an empty skeleton. Current release/qualification status is in
[verification](../verification/README.md).

## Actual source layout

```text
custom_components/solar_inverter_bridge/
  __init__.py, config_flow.py, const.py       HA setup/options and listeners
  services.py, websocket_api.py              Authorized command interfaces
  sensor.py, number.py, select.py, time.py,
  switch.py, control_entity.py               Native entity publication and editing
  device_management.py, network_hints.py      HA registry/network integration
  diagnostics.py, backup.py                  Diagnostics and HA backup hooks
  core/session.py                            Collector ownership, polling and execution
  core/transport.py, binary.py, framing.py    Transport adapters and codecs
  core/catalogue.py, drivers.py, discovery.py Profile maps and recognition
  core/parameters.py, telemetry.py           Original reference map/codecs
  core/storage.py                           Worker-owned SQLite ledger
  core/compatibility.py, artifact.py          Reports/replay and build identity
  frontend/                                 Bundled JS, CSS, HTML and domain catalog
  brand/, translations/                     Local artwork and en-US strings
```

There is no separate frontend compilation framework or old application process.
The bundled assets run directly through HA. Developer browser dependencies belong
to `tests/`; they are not shipped as runtime libraries.

## Environments

The current integration target and HA fixture version are Home Assistant Core
2026.10.4. Use Python compatible with the pinned test requirements (the current
CI environment uses Python 3.14). Install dependencies into an isolated development
environment, never into the running HA installation for a local test.

```bash
python -m pip install -r tests/requirements.txt -r tests_ha/requirements.txt
npm ci --prefix tests
npx --prefix tests playwright install chromium
```

See [testing](testing.md) before choosing a suite: some tests build an archive and
some tools contact an explicitly configured test HA. Public checks must not depend
on a developer's private installation files.

## Change boundaries

- Keep HA imports and lifecycle handling in the adapter layer. Pure protocol code
  must run offline without HA or the predecessor's source tree.
- Do not add blocking SQLite/filesystem work to the event loop. Use the existing
  worker/executor boundaries and preserve cancellation bookkeeping.
- Add profiles with pinned source facts and independent fixtures. The catalog
  owns sensor/setting inventories; do not reuse the full reference map for a new family.
- Preserve device/entity IDs and HA registry overrides. Do not edit `.storage`.
- Preserve source/license notices. See [sources](sources.md) and
  [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
- Update the corresponding existing guide instead of creating another generic
  STATUS, WORK_PLAN or NEXT_AGENT document.

## Packaging and publication

`tools/build_release.py` creates a deterministic manual-install ZIP containing the
component, MPL license, full inherited notices and four public user guides. Source
and installed component fingerprints share `core/artifact.py`. Root documentation
is not part of the runtime fingerprint.

Only run packaging when requested or when the applicable task permits it. A local
build is not publication. A public repository, codeowners/maintainer metadata,
remote and release authorization must be established separately. The existing
local Git history contains earlier private/Russian documents; moving current files
does not remove them from history. Follow [publication policy](documentation-policy.md).

The prepared GitHub/HACS metadata, clean-source export boundary and mandatory
pre-release documentation review are described in [publication](publication.md).
Default CI runs build-free tests; packaging and publication remain explicit steps.
