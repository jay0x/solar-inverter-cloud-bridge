# Solar Inverter Cloud Bridge

Local inverter monitoring and controlled settings inside Home Assistant Core.
The integration receives a Wi-Fi collector's redirected TCP connection and provides
native HA entities, a bundled **Inverters** panel and compatibility diagnostics.
No Supervisor app, MQTT broker or separate frontend plugin is required.

**Cloud is part of the product name; operation is local.** The bridge receives
supported collectors' redirected cloud-protocol connections without a vendor-cloud
account. It does not upload inverter data or forward traffic to a cloud service.

Formerly Solar Inverter Bridge. The integration domain remains
`solar_inverter_bridge`, preserving existing entities, services and history.

## Current scope

The local development candidate is **0.8.1**, with panel **0.16.1** and ledger schema **4**.
It has 24 selectable profile variants grouped by family, covering Modbus maps,
PI30, PI30 MAX, PI18, G-ASCII and EyeBond 09C1. Protocol 4 and MUST enrollment
aliases retain their IDs while sharing canonical family definitions.
It accepts mixed AT/binary EyeBond sessions on TCP **502, 18899 and 38899**.

Additional profiles are experimental. Unknown model names can receive a read-based
proposal for explicit acceptance. Source-defined controls can be enabled after a
warning and profile acceptance; fresh evidence, durable intent and readback
still apply. A profile name is not a blanket hardware-compatibility claim.

Only the reference AT installation has local hardware-read evidence. New families
are source-derived and simulator-tested. Read the [verification summary](docs/verification/README.md)
for completed checks and remaining qualification. This is not a published HACS release.
The completed 24-hour hardware-observation baseline is 0.4.0, with intermittent
read/connection problems. Source installation and the 0.6.0 full-control migration
have been exercised on the test VM; a separate stability comparison is still pending.

## Documentation

- [Install and operate](docs/INSTALL.md)
- [Named devices and possible compatibility](docs/DEVICE_COMPATIBILITY.md)
- [Ports, protocols and current reference map](docs/PROTOCOLS_AND_PROFILES.md)
- [Experimental profiles, recognition and control](docs/PROFILE_EXPANSION.md)
- [Developer setup](docs/development/contributing.md)
- [GitHub/HACS publication preparation](docs/development/publication.md)
- [All documentation](docs/README.md)

## Important behavior

- The collector initiates the connection. This is not a general Modbus TCP server
  or support for every vendor's proprietary logger.
- Implemented writable settings are available immediately after enrollment. There
  is no control-mode selector; hardware read-only and current-session checks remain.
- Commands share one durable executor. A possible-send failure remains unresolved;
  retries of the same operation ID query its result rather than send it again.
- History belongs to HA Recorder. Names and overrides belong to HA registries.
- Profile composition shows the common map separately from required model/reference
  extensions. Unlisted models can use a read-checked common map with explicit acceptance.
- The integration does not configure routers, operate an embedded DNS server,
  forward traffic to a vendor cloud or implement energy-optimization schedules.

## Repository layout

```text
custom_components/solar_inverter_bridge/  Integration, protocol core and bundled UI
docs/                                    Public en-US guides and documentation index
docs/development/                        Developer contracts and maintenance guidance
docs/verification/                       Public, dated software/evidence summaries
docs/private/                            Ignored local notes, Russian documents and archive
tests/                                   Offline/loopback and browser checks
tests_ha/                                Home Assistant integration tests
tools/                                   Validation, packaging and local test utilities
```

Start with `python3 tools/check_docs.py` for documentation validation. Runtime and
packaging checks are described in the [testing guide](docs/development/testing.md).

## License

This Source Code Form is subject to the terms of the Mozilla Public License,
v. 2.0. If a copy of the MPL was not distributed with this file, You can obtain
one at https://mozilla.org/MPL/2.0/. See [LICENSE](LICENSE) for the complete text.
Original copyright and permission notices for inherited portions are preserved
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
