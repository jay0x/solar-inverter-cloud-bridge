# Device recognition and profile catalog

The integration has **24 selectable profile variants**, including shared Protocol 4
and MUST maps and separate PI30/PI30 MAX command dialects. Additional profiles are
source-derived and tested with synthetic fixtures; they are not hardware-qualified
on every inverter model.

See [protocols](PROTOCOLS_AND_PROFILES.md), [installation](INSTALL.md) and the
[named-device register](DEVICE_COMPATIBILITY.md). A compatible EyeBond collector
session is required. A register map alone does not provide a vendor's proprietary
logger transport, cloud API, conventional Modbus TCP client or direct serial adapter.

## What is implemented

Counts are the maximum implemented measurement/status and control inventories.
They are not complete manufacturer maps or promises that every firmware supports
every field. Missing values remain unavailable rather than becoming zero.

| Profile | Measurements | Controls | Payload / recognition basis |
| --- | ---: | ---: | --- |
| `smg_legacy` | 13 | 11 | Classic SMG / ANENJI 4–6.2 kW common map; no asserted native protocol number |
| `smg_1` | 13 | 11 | Native protocol 1 plus two plausible snapshots |
| `smg_2` | 13 | 11 | Native protocol 2; model-specific SUB/SBU/SUF/ZEC choices |
| `smg_3` | 13 | 24 | Native protocol 3; source model 29440 candidate |
| `smg_4` (alias `modbus_protocol_4`) | Up to 35 | 48 native editors | Shared Protocol 4 map; exact reference signature 4/32771; qualified AT/binary control |
| `smg_5` | 12 | 24 | Native protocol 5; unsupported aggregate PV fields omitted |
| `smg_6` | 12 | 24 | Native protocol 6; unsupported aggregate PV fields omitted |
| `smg_11` | 13 | 11 | Native protocol 11; charging-priority enum 0 excluded |
| MUST PV/PH18, with PV3300/PV3900 variants | 27 | 27 | Slave 4; model markers select load scaling and optional BMS fields |
| SRNE Modbus | 38 | 36 | v1.96 types, phase-A scope, positive-discharge current and per-12-V setpoints |
| Growatt SPF | 36 | 7 | FC04 input telemetry, FC03/06 holding-register settings |
| Deye low-voltage map | 41 | 8 | Holding registers; optional energy, PV2, BMS and temperatures |
| Deye three-phase high map | 60 | 118 | Phase, battery, generator, energy and schedule fields; masked writes |
| Sumry GES 7530 | 9 | 0 | Registers 30000/30024/30058; no inferred extra counters |
| Aohai FSA | 34 | 0 | Input map; optional power, energy, BMS and temperatures |
| Solis ESINV | 34 | 0 | High input map; optional PV2, power, energy, BMS and faults |
| Hopewind 0237 | 59 | 3 | Holding registers; line-to-line voltages and generation power |
| SmartESS 0912 | 10 | 0 | FC04 telemetry / slave 4 |
| SmartESS 0921 | 10 | 0 | FC03 telemetry / slave 1 |
| PI30 | 17 | 20 | QPIGS/QMOD, QPIWS, QPIRI/QFLAG readback; uppercase flags |
| PI30 MAX | 25 | 20 | Lowercase flags/indexed currents; optional PV2 and dated PV/load energy |
| PI18 | 26 | 23 | CRC/length-checked reads, `^S` writes and paired-voltage readback |
| EyeBond / JsdSolar G-ASCII | 51 | 22 | Plain CR; optional groups and setting-specific queries |
| EyeBond 09C1 | 24 | 0 | Fixed-column Q1/QF/PV?/F, optional PV1/PV2 and status flags |

## Shared SMG maps and model compatibility

A retail brand does not define a protocol. ANENJI, Aninerel and Sandisolar products
can share SMG maps, while other products under those brands can use unrelated maps.
SMG protocol numbers identify inverter register layouts independently of collector framing.

| Layout | Variants | Differences |
| --- | --- | --- |
| Low-address SMG | Classic, 1, 2, 11 | Protocol-specific priority enums; Classic does not assert a native number |
| High-address SMG | 3, 4, 5, 6 | Output/load at 348/350 for 3/5, at 254/256 for 4/6; 5/6 omit aggregate PV fields |

`core/smg.py` defines the common layouts and explicit variant differences. Battery
voltage is at 215 in the low map and 277 in the high map. Models can omit fields
or have different limits; a shared voltage field does not impose 48 V limits on a
24 V inverter. Model codes are evidence hints, not an exhaustive retail allowlist.

The IDs `modbus_protocol_4` and `smg_4` share measurement/control definitions,
decoder and read plans. The map has 35 readings and 51 parameters, of which 48 have
manual editors. Reference read evidence for 4/32771 is distinct from inferred model
compatibility. Changed definitions require recheck before commands, with a mismatch
detected before I/O.

## Protocol-map distinctions

- **Classic SMG:** its primary document marks register 171 reserved and 184 invalid.
  Document version 1.0 does not establish native protocol 1. A recognized register-184
  variant prevents the unidentified-variant fallback from bypassing a numbered map.
- **High SMG:** power at 348 is L1, while 254 is total output power. The protocol
  document named "3-10" explicitly scopes 3/4/5/6, not every number through 10.
- **SmartESS:** 0912 and 0921 have different addresses and read functions. Battery
  voltage is at 1 versus 65; grid voltage is at 53 versus 36. Binary query 14 can
  prioritize discovery once per session, but cannot replace actual read evidence.
- **MUST:** `must_pv_ph18` reads PV/model markers before telemetry. PV3300 selects
  whole-percent load scaling; PV3900 selects its anchored variant. Marker-selected
  maps expose optional BMS fields. Valid illegal-address replies permit a common
  path without markers; timeouts and corrupt replies do not prove absence.
- **Deye:** low-voltage and three-phase high maps are separate layouts. High-map
  register 653 remains a raw value without a guessed power unit.
- **ASCII:** PI30, PI18, G-ASCII and 09C1 have distinct framing and field semantics.
  Similar command letters do not make them interchangeable. An identified PI41
  response is rejected by PI30 recognition.

## What the panel shows

**Profile composition** appears in proposals, enrollment, Configuration, Connection
and the catalog. It shows the common map, any required model extension, selection
basis, native identifiers and evidence state. Saved metadata is not a fresh read check.

**Use common map** allows an unlisted model to use a checked family subset after
acceptance. Required extensions have no independent off switch. Effective maps and
observed markers participate in the acceptance binding; changed evidence requires
explicit renewal while device/entity IDs and Recorder history can remain intact.
Diagnostic replay applies the same marker-based corrections as live decoding.

## Unknown-device workflow

1. Admit the collector through the allowlist and full-PN handshake.
2. Run the read-only connection check. If it fails, the wizard starts bounded
   recognition; **Recognize protocol and profile** also starts it explicitly.
3. Read two snapshots and check CRC/function/slave/length, native protocol where
   known, and numerical consistency. A native mismatch can prioritize another SMG map.
4. Review the proposed profile, source, selection basis and readings against the
   inverter display. Family-shape matching is not exact retail-model identification.
5. Acknowledge the profile warning and choose **Use this profile**. The server reads
   again and compares the binding before allowing enrollment.
6. Use **Check other available profiles** for another proposal or **Stop recognition**
   to stop. Recognition does not write settings.
7. Use **Collect data for device support** for a compatibility report. Original wire
   bytes are included only with explicit export consent.

Budgets are 64 requests and 75 seconds per pass, a three-second transaction deadline,
ten minutes total and 32 continuation connections/passes. Search stops at the first
useful proposal and continues only explicitly. It does not sweep arbitrary registers/slaves.

Known binary routes include outer 1/1 and 1/255 with RTU slaves 1/4/5. ASCII candidates
also use source-defined 0x0994/255, 0x0994/1 and 0x0102/255 routes where applicable.
An ASCII slave placeholder 0 is not sent as a Modbus broadcast.

A raw-AT timeout or ambiguous frame closes the stream before another family is tried;
late raw bytes have no TID. Binary TIDs support bounded correlated transactions.
Incomplete searches remain explicit. Zero-only snapshots or missing voltage/frequency
evidence do not create proposals.

## User-authorized experimental control

One profile acknowledgement covers readings and implemented source-defined commands.
Supported settings become available after enrollment and fresh read checks. Accepting
a profile does not send a setting command.

Permission binds the device, selected profile, route, observed signature and definition
digest. A changed binding refuses execution. Reconnect requires fresh readings before
controls become available. Family-only evidence does not prove physical-device identity.

**Recheck this profile** pauses control, obtains new read evidence and requires renewed
acceptance. Unresolved operations block binding replacement. PI30/MAX dialect changes
use this same explicit review flow and preserve shared entity IDs.

All commands use administrator checks, current-session identity/settings preflight,
baseline validation, policy revision, durable intent/send claim, exact ACK and independent
readback. Uncertain outcomes remain unresolved; repeated operation IDs return the saved
result without resending. Undocumented manufacturer bounds do not make a known R/W
field read-only, but exact wire limits, steps and documented dependencies still apply.

## Parameter and measurement semantics

- **SMG:** priority enums are variant-specific. High-map controls include restart flags,
  priorities, schedules, voltage/current thresholds and SOC protection/recovery.
  Shared block reads fall back per field only for valid illegal-address exceptions.
- **MUST:** 27 controls use exact FC06 echo validation. Energy high/low words use the
  documented decimal composition, not binary uint32. PV3300/PV3900 aliases use their markers.
- **SRNE:** v1.96 voltage/frequency/power fields are unsigned; signed battery current is
  positive for discharge. Explicit charge/discharge readings expose direction. Setpoints
  labeled **12 V reference** encode 14.4 V as 144, not as a 57.6 V bank value. The ambiguous
  rated-voltage field is a reading, not an editor.
- **Growatt:** FC06 holding-register controls include priorities, input range, restart
  behavior, buzzer and charging current. FC04 telemetry is a separate address space.
- **Deye:** LV uses eight source-defined controls. The high map exposes 118 settings,
  including schedules and bit fields. Fresh read-modify-write preserves unrelated bits;
  the durable complete word must match readback, including those bits.
- **Hopewind:** active/reactive regulation modes use existing setpoints; active-power
  ratio is also writable. Generation power is not household load.
- **PI30/MAX:** standard uppercase flags and MAX lowercase/indexed-current syntax are
  separate grammars. An uncertain command is never retried with another case/dialect.
- **PI18:** paired `MCHGV`/`BUCD` commands preserve the freshly read companion and check
  both values afterward. Unit-addressed current/priority commands require single-module
  mode. Queried current choices and documented voltage choices are enforced.
- **G-ASCII:** 22 whitelisted setters use independent setting-specific reads. Voltage
  bounds from a 24 V example are not generalized to 48 V systems.
- **Optional ASCII groups:** normal polling only; a valid negative reply means absence.
  Daily counters use the inverter's queried date. PI18 total ET is kWh; daily ED and
  MAX QET/QLT/QED/QLD are Wh converted to kWh. QLT means load energy.
- **Optional Modbus blocks:** at most 32 registers, with explicit high/low word order,
  decimal MUST counters and temperature offsets. Missing values are not reused.
- **09C1:** Q1 reports input frequency and QF output frequency. PV? is voltage/current,
  not verified total PV power or physical port numbering. No SOC or power is invented
  from ratings. Optional PV1/PV2 replies and status flags extend the measurement set.

CRC errors, timeouts and malformed frames are not silently treated as unsupported
fields. Writes require a freshly observed selected setting. Binary collector reset
and inverter clock writes remain unsupported. Profiles with zero controls explain
the limitation and offer report collection.

## Evidence and sources

Primary protocol references include:

- [Classic SMG RS232 protocol](https://github.com/syssi/esphome-smg-ii/blob/b0ff1caec3ce395d774fcf496fcc03a75f925ca2/docs/SMG-RS232%2BCommunication%2BProtocol%2BV1.0.1.pdf).
- [Native protocol 3/4/5/6 document](https://github.com/PreK/esphome-anenji-11kw-native-modbus/blob/55a330585846d57b4f24e6467201d8dde8985ee7/Communication.Protocol.No.3-10.docx).
- [SRNE Modbus v1.96](https://github.com/syssi/esphome-smg-ii/blob/b0ff1caec3ce395d774fcf496fcc03a75f925ca2/docs/SRNE.Solar.Charge.Inverter.MODBUS.Protocol1.96.pdf).
- [PI18/PI30/MAX documents](https://github.com/jblance/mpp-solar/tree/eafdd4328c77f516cf82430c5bcb6fa042c45d3a/docs/protocols).
- [MUST protocol spreadsheets](https://github.com/vladyspavlov/esphome-must-inverter/tree/e3c43a4915901dcc399dc2ac68eb7a5eb36a426d/docs).

Pinned catalog reference:
[ha-eybond-local, 6ca2b23cda042f5919e3831a907f784000d5de27](https://github.com/groove-max/ha-eybond-local/tree/6ca2b23cda042f5919e3831a907f784000d5de27),
MPL-2.0. Paths below are under `custom_components/eybond_local/`:

- `protocol_catalogs/register_schemas/modbus_smg/base.json` and
  `protocols/communication_protocol_{1,2,3,3_10,4,5,6,11}.json`.
- `protocol_catalogs/register_schemas/{must_pv_ph18,srne_modbus,growatt_spf,deye_lv,deye_3ph_high_80kw,sumry_ges_7530,aohai_fsa,solis_esinv,hopewind_0237}/base.json`.
- `protocol_catalogs/register_schemas/smartess_local/models/{0912,0921}.json`
  and `protocol_catalogs/smartess_local.json` for asset/function/address facts.
- `protocol_catalogs/profiles/modbus_catalog/{growatt_spf,deye_lv,deye_3ph_high_80kw,hopewind_0237}.json`
  and `protocol_catalogs/profiles/must_pv_ph18/base.json` for controls.
- `payload/pi30.py`, `payload/pi18.py`, `payload/ascii_line.py`,
  `drivers/pi30_settings.py`, `eybond_g_ascii_settings.py` and
  `protocol_catalogs/command_schemas/eybond_g_ascii/base.json`.
- `payload/urtu09c1.py` and `drivers/eybond_09c1.py` for 09C1 framing/columns.
- `protocol_catalogs/inverter_catalog.json` for scoped route candidates.

Independent cross-references:
[Local-Cloud-Bridge, 34f5abe](https://github.com/samuelolteanu/Local-Cloud-Bridge-for-Anenji-Easun-MPP-Solar-Inverters/blob/34f5abe/inverter_bridge.py)
(GPL-3.0 protocol reference, implementation not copied) and
[PowMr proxy, b7a3ada](https://github.com/andronick83/powmr-eybond-proxy/blob/b7a3ada/proxy.py) (MIT).
Selected protocol facts are independently implemented. External driver/schema files,
manufacturer documents and private captures are not bundled as runtime code.

## Reports, replay and support destination

Reports identify attempted families/routes, rejection reasons, proposals, acceptance
and original validation facts. Replay uses correlated binary frames or ordered raw-AT
requests/replies to reconstruct supported readings. Incomplete frames and unassociated
tails remain explicit; replay never executes commands or guesses a frame boundary.

Use [GitHub Issues](https://github.com/jay0x/solar-inverter-cloud-bridge/issues) to share
the downloaded report and copyable issue description. Raw bytes are optional. No report
is automatically uploaded to GitHub or external reference projects.

## Storage and scope

Schema 4 stores enrollment, definition-bound profile acceptance, maintenance policy
and durable operations. Policy changes increment a revision. Updates must preserve
device/entity IDs, registry overrides and unresolved operations. Keep a consistent
backup; code that cannot read the saved schema refuses that database.

The catalog is extensible. Sumry GES is limited to nine sourced readings; 09C1 has
no sourced writes. GivEnergy requires a different transport with proprietary framing
and aligned reads. Unknown/encrypted payloads, missing responses and vendor-specific
loggers remain reportable gaps. Hardware claims require exact device/firmware evidence.
