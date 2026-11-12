# Verification and qualification

This page describes the checks and limitations of the current product. Software
tests, installation checks and physical-device evidence are separate qualifications.
Commands are in the [testing guide](../development/testing.md).

## Verified software

- Integration: **0.8.2**; panel: **0.16.1**; ledger schema: **4**.
- Tested environment: Home Assistant Core **2026.10.4**, Python **3.14**, HACS **2.0.5**.
- Component fingerprint:
  `effb89ce8d53db88ee3ec1cf77245bc0678b166a5677b5ac5d419f1c220ac930`.

| Check | Result / scope |
| --- | --- |
| Offline suite | 175 cases: 174 passed, one local TCP502 skip |
| Home Assistant integration suite | 27 passed |
| Browser suites | Panel and router-guide journeys passed, including mobile/desktop layouts |
| Metadata | Hassfest and HACS validation passed |
| Documentation | Local links, language placement, license integrity and whitespace checks passed |
| Source scan | Gitleaks passed; its narrow exception identifies a public SRNE parameter name, not a credential |

Hosted results are available in [GitHub Actions](https://github.com/jay0x/solar-inverter-cloud-bridge/actions).
The suites exercise codecs, discovery, profile acceptance, entity lifecycle,
readback, reconciliation, durable failure boundaries and command deduplication.
Protocol specimens and simulated collectors are labeled as synthetic evidence.

## HACS installation

The integration was installed from the public repository through HACS 2.0.5 on
Home Assistant 2026.10.4. All **53 installed component files** matched the source
hashes. Core configuration validation and restart passed.

The installation check used an existing configured integration. It confirmed:

- The same reference inverter and all **85 entity IDs**, registry overrides and
  maintenance preferences remained intact.
- Telemetry and settings were fresh, with no unresolved operations.
- The live panel, native sensor history, diagnostics, device navigation and mobile
  layout passed browser acceptance.

This is evidence for installation over a configured system, not a fresh empty-HA
installation. No inverter Apply or reset command was sent during these checks.

## Hardware evidence and limits

- **ANENJI ANJ-11KW-48V-W-P**, native Protocol 4 / model 32771, has hardware-read
  verification over the AT collector path.
- Additional profiles and binary collector paths are source-derived and simulator-tested.
  They do not have project hardware-write qualification for every model or firmware.
- The current candidate has no completed fixed-version 24-hour stability qualification.
- Intermittent polling timeouts occur on the reference AT installation. Their cause
  and long-term impact remain under investigation; fresh readings after recovery
  do not establish fault-free continuous operation.
- Readback confirms a reported setting, not an independently observed electrical effect.
- Backup freeze/copy/recovery tests do not establish a completed Supervisor archive restore.
- Router recipes have syntax and browser coverage, not comprehensive physical-router testing.

See the [compatibility register](../DEVICE_COMPATIBILITY.md) and
[profile matrix](../PROFILE_EXPANSION.md) for exact scope. Development source is
available as a HACS custom repository. Version 0.8.2 is a pre-release, and
default-catalog inclusion requires approval by the HACS maintainers.
