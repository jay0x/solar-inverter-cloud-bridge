# Solar Inverter Cloud Bridge

A Home Assistant integration for monitoring and configuring solar inverters through
their Wi-Fi collectors. Redirect the collector's cloud connection to Home Assistant,
and the integration handles communication with the inverter on your local network.

- Native sensors for solar generation, battery, grid, load and energy, where available.
- Native controls for supported inverter settings, with independent readback.
- A bundled **Inverters** panel with live readings, settings, history and diagnostics.
- Read-based protocol recognition and compatibility reports for unlisted devices.

Runs inside Home Assistant Core without a separate app, MQTT broker or vendor-cloud
account. Current development version: **0.8.2**. Available as a HACS custom repository;
no stable release or default-catalog listing exists yet.

## Inverter models

The following models have a reference installation or an implemented experimental
profile based on reviewed device reports and protocol documentation. **ANENJI
ANJ-11KW-48V-W-P** has hardware-read verification in this project; the other listed
models are experimental and require a matching collector and profile check.

| Inverter model | Protocol / profile |
| --- | --- |
| **ANENJI ANJ-11KW-48V-W-P** | SMG Protocol 4 — verified reference |
| ANENJI ANJ-11KW-48V-WIFI, ANJ-11KW-48V-WIFI-P | SMG Protocol 4 |
| ANENJI ANJ-6200W-48V, ANJ-4000W-24V-WIFI | Classic SMG / read-matched low-address variant |
| ANENJI ANJ-4000W-24V | SMG Protocol 1 |
| ANENJI ANJ-6200-48PL | SMG Protocol 2 |
| ANENJI HHS-11kW-WIFI, without parallel | SMG Protocol 3 |
| ANENJI ANJ-5KW-48V-WIFI | SMG Protocol 11 |
| Aninerel 6200 dual output, ANL-4200T-24L-W-PRO | SMG Protocol 11 |
| Sandisolar SD 11KP48V WIFI | SMG Protocol 4 |
| Sandisolar SD-HYM-4862HWP | SMG Protocol 1 |
| MUST PV18-3024, MUST-compatible PV3300, MUST PV39-8048 TLV / PV3900 | MUST PV/PH18 with marker-selected variants |
| Yingfa YF6.2K-LEL-1B, Victor NM-PRO-6.2KW, PowMr 4.2KW | PI30; MAX command variant requires separate confirmation |
| LVYUAN TY-SIC-3.6KBE-W1, Gootu GT-H2436M14P5 | EyeBond / JsdSolar G-ASCII |
| ANENJI GES48120M250-500P | Sumry GES 0x7530 |
| Bluesun BSM15K-B | Hopewind 0237 |
| Kevolt PD0080G-TPM-EU, 8 kW three-phase hybrid | Deye-compatible three-phase high map |
| ZL Power GSIII 12 kW | EyeBond 09C1 |

Additional family maps cover **SRNE, Growatt SPF, Deye low-voltage hybrids, Solis
ESINV, Sandi / Aohai FSA and SmartESS 0912/0921**. All require a compatible EyeBond
collector connection; a supported register map alone does not establish support
for a manufacturer's proprietary logger.

See the [full model list, evidence and limitations](docs/DEVICE_COMPATIBILITY.md).
Unlisted models can be checked against the available profiles from the setup wizard.

## Supported protocols

Collector connections use **EyeBond AT or binary framing** over TCP **502, 18899
and 38899**. Inside that connection, the integration supports these inverter protocols:

| Protocol family | Implemented variants |
| --- | --- |
| SMG Modbus RTU | Classic SMG and native protocols 1, 2, 3, 4, 5, 6 and 11 |
| MUST, SRNE and Growatt Modbus | MUST PV/PH18 with PV3300/PV3900 variants; SRNE v1.96-compatible map; Growatt SPF |
| Deye Modbus | Separate low-voltage and three-phase high-address maps |
| Other Modbus maps | Sumry GES 0x7530, Aohai FSA, Solis ESINV, Hopewind 0237, SmartESS 0912 and 0921 |
| PI30 / PI30 MAX | Separate command variants with CRC-checked responses |
| PI18 | Length- and CRC-checked ASCII commands |
| EyeBond / JsdSolar G-ASCII | Plain CR-terminated ASCII commands |
| EyeBond 09C1 | Fixed-column Q1/QF/PV?/F responses and optional PV1/PV2 readings |

There are **24 selectable profiles**. Available readings and writable settings vary
by profile and firmware; some profiles provide monitoring only. See the
[measurement and control matrix](docs/PROFILE_EXPANSION.md) and
[verification results](docs/verification/README.md).

## Install through HACS

Add `https://github.com/jay0x/solar-inverter-cloud-bridge` under HACS **Custom
repositories**, category **Integration**, then download **Solar Inverter Cloud
Bridge** and restart Home Assistant. Add the integration from **Settings → Devices
& services**. The integration domain is `solar_inverter_bridge`.
See [installation and collector setup](docs/INSTALL.md) before connecting a device.
The tested combination is Home Assistant **2026.10.4** and HACS **2.0.5**.

## Redirect the collector to Home Assistant

The collector initiates the connection. Configure your router or local DNS resolver
so its traffic reaches the integration:

```text
Inverter → Wi-Fi collector → router / local DNS → Home Assistant
                               redirect          TCP 502 / 18899 / 38899
```

1. **Give Home Assistant a stable LAN IP** and allow the collector's source IP or
   subnet in the integration's network settings.
2. **Start with DNS overrides.** Point the hostnames used by your collector to the
   HA IP. Common examples are `dtu_ess.eybond.com`, `iot3.eybond.com`,
   `ess.eybond.com`, `m2m.eybond.com`, `iot.eybond.com` and `vip1.eybond.com`.
   The collector must use the resolver containing those records.
3. **Use TCP destination NAT if needed.** For collectors using cached or hardcoded
   cloud IPs, redirect their outgoing TCP traffic on ports **502, 18899 and 38899**
   to the HA IP, preserving the destination port: **502 → 502**, **18899 → 18899**,
   **38899 → 38899**. Scope the rules to the collector or its IoT subnet; same-subnet
   DNAT may also need hairpin NAT for the return path.
4. **Allow those ports through the LAN firewall** and expose them to Home Assistant
   if it runs in a container. These are collector listener ports; keep access LAN-scoped.
5. **Reconnect the collector's Wi-Fi** to establish a new session. Open **Inverters →
   Add inverter**, select the connection, review the readings/profile and confirm enrollment.

The setup wizard's **Router setup** guide generates commands for your network;
you apply them on the router. See [DNS, domains and routing details](docs/PROTOCOLS_AND_PROFILES.md#3-dns-and-routing).

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
