# Experimental device recognition and profile catalog

Development candidate 0.8.2 / panel 0.16.1. This has **24 selectable profile variants**,
including canonical Protocol 4 and MUST maps, plus separate PI30 and PI30 MAX dialects.
These are not 24 unrelated or hardware-qualified protocols. Additional profiles are independently
implemented from public protocol facts and tested with synthetic fixtures.
No additional physical inverter or collector was available during implementation.
The counts below describe the current code, not the completed 0.4.0 observation
candidate. No new installation archive has been built for this increment.

See [PROTOCOLS_AND_PROFILES.md](PROTOCOLS_AND_PROFILES.md) for transport layers and
[INSTALL.md](INSTALL.md) for installation. An EyeBond collector session is still
required: adding a Growatt/Deye/Solis register map does not implement that vendor's
proprietary Wi-Fi logger, cloud API, direct Modbus TCP client, USB or serial adapter.

The consolidated named-device list, including experimental and research candidates,
is [DEVICE_COMPATIBILITY.md](DEVICE_COMPATIBILITY.md).

## What is implemented

Counts describe published measurements/status fields and implemented controls for
the selected profile. They do not mean the complete manufacturer's register map.
Missing fields remain absent rather than being filled with zero or Protocol 4 data.

| Profile | Measurements | Controls | Payload / recognition basis |
| --- | ---: | ---: | --- |
| `smg_legacy` | 13 | 11 | Common SMG / ANENJI 4–6.2 kW map; family-shape match, no asserted native protocol number |
| `smg_1` | 13 | 11 | Native protocol 1 plus two plausible snapshots |
| `smg_2` | 13 | 11 | Native protocol 2; model-specific SUB/SBU/SUF/ZEC priority choices |
| `smg_3` | 13 | 24 | Native protocol 3; source model 29440 candidate |
| `smg_4` (also retained alias `modbus_protocol_4`) | Up to 35 | 48 native editors | Shared Protocol 4 definitions, reads and decoding; current-session qualified AT/binary writes; original reference gate remains exact 4/32771 |
| `smg_5` | 12 | 24 | Native protocol 5; excludes the unsupported aggregate PV registers |
| `smg_6` | 12 | 24 | Native protocol 6; excludes the unsupported aggregate PV registers |
| `smg_11` | 13 | 11 | Native protocol 11; excludes generic charging-priority value 0 |
| MUST PV/PH18 (retained PV3300/PV3900 aliases) | 27 | 27 | Slave 4; model markers select load scaling and optional BMS extensions |
| SRNE Modbus | 38 | 36 | Primary v1.96 types, phase-A scope and positive-discharge current; voltage settings explicitly per 12 V |
| Growatt SPF | 36 | 7 | Input-register telemetry (inner FC04), holding-register settings (inner FC03/06) |
| Deye low-voltage map | 41 | 8 | Holding registers; optional energy, PV2, BMS and temperatures |
| Deye three-phase high map | 60 | 118 | Phase, battery, generator, energy and schedule fields; masked writes preserve other bits |
| Sumry GES 7530 | 9 | 0 | Registers 30000/30024/30058, no inferred extra counters |
| Aohai FSA | 34 | 0 | Input-register map; optional power, energy, BMS and temperature groups |
| Solis ESINV | 34 | 0 | High input-register map; optional PV2, power, energy, BMS and faults |
| Hopewind 0237 | 59 | 3 | Holding registers; line-to-line voltages and generation power, not household load |
| SmartESS 0912 | 10 | 0 | Corrected FC04 input-register telemetry / slave 4; binary query-14 asset hint can prioritize discovery |
| SmartESS 0921 | 10 | 0 | Source-defined common telemetry, no guessed kW/W conversions |
| PI30 | 17 | 20 | CRC-checked QPIGS/QMOD, QPIWS, QPIRI/QFLAG readback; uppercase flag commands |
| PI30 MAX | 25 | 20 | Separate lowercase flags/indexed currents; optional PV2 and dated PV/load energy |
| PI18 | 26 | 23 | CRC/length-checked reads, `^S` writes, paired-voltage preservation and independent readback |
| EyeBond / JsdSolar G-ASCII | 51 | 22 | Plain CR; optional groups and setting-specific queries, no PI30 CRC assumption |
| EyeBond 09C1 | 24 | 0 | Fixed-column Q1/QF/PV?/F plus optional PV1/PV2 and status flags; plain CR |

Examples from the source research include ANENJI 33793/32768, HHS 11 kW,
ANJ-6200-48PL, Aninerel dual-output, Yingfa PI30, LVYUAN G-ASCII, MUST PV18-3024
and Sumry/ANENJI GES. These are candidate model/family associations, not new hardware
test results. Sandisolar 4/32771 may already match the original exact profile.
Optional counts are upper inventories, not promises that every field exists on a
particular model. MUST BMS fields require the corresponding marker-selected map;
MAX-only queries and commands require the explicitly selected MAX dialect.

## Shared SMG maps and model compatibility

A retail model is not a separate protocol. ANENJI, Aninerel and Sandisolar labels
can share an SMG map; different products sold under ANENJI can also use unrelated
families, including Sumry/GES. Protocol 1/2/3/4/5/6/11 here identifies an SMG
register-map variant over Modbus RTU, independently of AT or binary collector framing.

| Shared layout | Implemented variants | Explicit differences |
| --- | --- | --- |
| Low-address SMG | Legacy, 1, 2, 11 | Protocol 2 output/charging enums; Protocol 11 excludes charging enum 0; legacy does not assert a native protocol number |
| High-address SMG | 3, 4, 5, 6 | Output power/load at 348/350 for 3/5, at 254/256 for 4/6; 5/6 omit aggregate PV power |

`core/smg.py` defines the implemented variants and their common controls in one
registry. The measurement catalog and control driver consume that registry. The
high-map controls reuse an explicit subset of the reference Protocol 4 inventory;
low-map variants override only their documented enum differences. An unimplemented
protocol number receives no implicit high-map controls.

This does not make maps interchangeable. For example, battery voltage is at 215
in the low map and 277 in the high map. Even within one protocol, a model/firmware
can omit fields or have different limits. Shared voltage fields do not impose a
48 V operating range on a 24 V inverter. Model codes in the experimental catalog
are evidence hints, not an exhaustive acceptance allowlist. A new model can use
the read-based acceptance workflow below without adding a copy of its family's map.

The retained `modbus_protocol_4` ID and `smg_4` now use the same measurement/control
definitions, decoder and read plans. Saved IDs remain stable; there is one catalog
entry. Reference read evidence for 4/32771 remains distinct from other models'
inferred compatibility. Old accepted `smg_4` definitions require explicit recheck
before the expanded inventory is used for commands; a mismatch is detected before I/O.
Source-backed model-specific extensions should be small, explicit deltas with fresh
definition-bound acceptance, rather than duplicated brand-wide maps.

### Protocol-family review — November 7, 2026

The former 26 entries mixed map variants, recognition fallbacks and capability
subsets. The review led to these 0.7.0 changes:

- **Legacy belongs to classic SMG.** Its 13 implemented readings and 11 controls
  equal the `smg_1` subset. The November 2021 classic document marks register
  171 reserved and 184 invalid, so its document version 1.0 does not establish native
  protocol number 1. Keep an unidentified-variant fallback within the family rather
  than treating the ANENJI brand or 4–6.2 kW label as a protocol boundary. The UI now
  calls it **SMG Classic — variant not identified**. A recognized register-184
  variant prevents this fallback from bypassing the corresponding numbered map.
- **The reference and `smg_4` are the same SMG Protocol 4.** The current 35/48 and
  13/24 inventories were different implementation subsets. Both now use the canonical
  35-measurement/51-parameter definition (48 manual editors), including signed load
  register 256. Valid illegal-address exceptions in optional telemetry blocks fall
  back to documented common addresses; missing extras are not filled with zero.
  Settings use shared block reads with per-field fallback only for illegal addresses.
  CRC failures/timeouts remain failures. Qualified binary reference settings use
  the same FC16/readback executor; binary clock/reset remain unsupported.
- For the high SMG family, output power at 348 is **L1**, while 254 is **total**
  output power and is documented for 4/6. Shared definitions must preserve that
  phase/aggregate distinction, not merely substitute one register address.
- **SmartESS 0912 and 0921 share a catalog/transport layer, not one register map.**
  Battery voltage is at 1 versus 65, grid voltage at 53 versus 36, and grid frequency
  at 59 versus 38. Register 54 is phase-S grid voltage in 0912 but PV1 voltage in
  0921. Keep distinct decoders/read plans even if grouped together in the UI.
- **0912 definition corrected:** the external SmartESS protocol catalog specifies
  telemetry FC04 and inner address 4. The local entry now agrees, with an independent
  request-plan assertion and original-frame replay test. The unchanged 0921 uses
  FC03/address1. Neither profile has new hardware qualification.

The classic and 2024 protocol documents and pinned SmartESS catalog are linked in
the source section below. The filename "Communication Protocol No. 3-10" must not
be read as proof for every number 3 through 10: its reviewed scope lists 3/4/5/6.
SmartESS asset IDs and the inverter's SMG register-184 protocol number are different
identification layers. Discovery reads binary collector query 14 at most once per
session and uses recognized 0912/0921 hints to prioritize bounded plans. This hint
does not grant acceptance or bypass the two actual measurement snapshots.

### What the panel shows

**Profile composition** appears in recognition proposals, enrollment review,
Configuration, Connection and the expandable profile catalog. It separates:

- **Common map**: the implemented family/protocol subset.
- **Model extension**: an applied variant, or **None — common map only**. Protocol 4
  uses one shared map; reference read evidence for 4/32771 is a qualification note,
  not an artificial model extension or a uniquely identified retail model.
- **Selection basis** and available native protocol/model codes.
- **Evidence status**: a catalog definition, read-based proposal, current readings,
  saved profile waiting for readings, or required recheck. Saved metadata is not a
  new device verification.

For a common-only proposal, **Use common map** follows the existing explicit
acceptance flow. No exact retail name is required; acceptance covers readings and
implemented commands. Selecting `smg_4` uses the canonical Protocol 4 inventory;
unsupported optional readings/settings stay unavailable rather than becoming zeros.

Required extensions have no separate off switch. In particular, the common MUST
path reads the PV/model markers before telemetry. A positive PV3300 marker applies
its whole-percent load correction automatically, including when the selected ID is
the common `must_pv_ph18`. PV3900 markers select the corresponding anchored variant.
A validated illegal-address response permits the common path without model markers;
timeouts and corrupt replies are not treated as proof that a marker is absent.

The effective map and observed markers participate in the acceptance binding.
A changed binding requires recheck and explicit renewal; the selected profile and
HA device/entity IDs can remain the same. Existing common MUST acceptances may
therefore need renewal after this update. Diagnostic replay applies the same
PV3300 correction to captured marker/read evidence. These are source-derived
variants, not new physical-device qualification.

## Unknown-device workflow

1. Admit the collector through the normal allowlist and full-PN handshake.
2. Run the normal read-only check. If it fails, the wizard starts a bounded search
   through available profile families. **Recognize protocol and profile** also
   starts it explicitly; it does not enroll the collector.
3. The search reads two snapshots, validates CRC/function/slave/length where
   applicable, native protocol when known, and independent numerical consistency.
   A native protocol mismatch can prioritize the corresponding available SMG map.
4. A plausible match is offered with its name, basis, source and preview values.
   Family-shape matching is a hypothesis, not identification of a manufacturer's
   exact model. Compare the preview with the device display.
5. Acknowledge the inferred-profile warning and select **Use this profile**.
   The server reads it again and compares the binding before allowing enrollment.
6. **Check other available profiles** continues the bounded search if the first
   proposal is unsuitable. **Stop recognition** cancels it without sending writes.
7. Use **Collect data for device support** to download a compatibility ZIP and
   copy the issue description. Recognition begins a bounded capture if no report
   already exists. Original wire bytes are included only by explicit export choice.

The search uses at most 64 read requests and 75 seconds per pass, a three-second
transaction deadline, a ten-minute total search lifetime and 32 continuation
connections/passes. These are implementation budgets, not vendor timing guarantees.
It stops at the first useful proposal so another route is not silently treated as
the same inverter. Continuing is explicit. There is no register/slave sweep.

Known binary routes include outer 1/1 and 1/255, with relevant RTU slaves 1/4/5.
ASCII candidates additionally use the source-defined 0x0994/255, 0x0994/1 and
0x0102/255 routes where applicable. An ASCII slave placeholder 0 means no inner
RTU slave; it is never sent as a Modbus broadcast.

After a raw-AT payload timeout or ambiguous frame, the stream is closed before
trying another family. The collector must reconnect; late raw bytes have no TID
with which to correlate them. Binary TIDs permit bounded independent transactions.
Slow or offline devices can produce incomplete searches; the UI/report says so.
Zero-only snapshots or missing frequency/voltage evidence do not create proposals.

## User-authorized experimental control

Inferred compatibility **must not permanently block control**. Since 0.6.0, the
single profile acknowledgement covers its readings and implemented source-defined
commands after the unverified-mapping warning. There is no separate control toggle
or mode selector. Supported settings are available immediately after enrollment
and fresh read checks; accepting a profile does not send a setting command.

Permission is persisted for the device, selected profile, route, observed signature
and a digest of the map/control definitions. It survives reload/restart. A changed
signature, definition digest or transport binding refuses execution rather than
silently carrying permission to another interpretation. Reconnect must establish
fresh readings before native controls become available. Family-only profiles do
not prove that the same physical inverter remains behind a collector after a swap.

**Recheck this profile** obtains a new proposal for the same saved profile after
evidence changes. It pauses control and requires a new acknowledgement before
renewing the binding. The enrollment/device/entity IDs and history are retained.
An unresolved operation blocks replacement of the binding. Rechecking is read-only;
it does not silently switch to a different profile or preserve control permission
without the user's renewed choice.

The existing executor still provides admin checks, current-session preflight,
fresh settings/baseline validation, policy revision, durable intent before send,
exact ACK and independent readback. Unknown outcomes stay unresolved and are never
replayed. A repeated operation ID returns its original result.

Baseline controls retained from 0.7.0 (expanded further below):

- Low SMG/legacy: display, source priorities, charging current limits and battery
  voltage thresholds at the low-map addresses. Protocol 2 has its own priority enums;
  protocol 11 does not inherit charging value 0. No 48 V battery window is imposed
  on a 24 V model from a shared field name.
- High SMG: display/restart flags, primary and secondary priorities, four schedule
  boundaries, voltage/current thresholds and the SOC protection/recovery pair.
  Schedule ordering and SOC dependencies retain the existing validation.
- PI30: `POP`, `PCP`, `PGR` plus `PBCV`, `PSDV`, `PCVV`, `PBFT`, `PBDV`, with exact
  decimal encoding, CRC-protected ACK and fresh QPIRI readback. A missing optional
  QPIRI field remains unavailable. MAX-only current commands are not assumed universal.
- MUST: energy saving, charging priority, grid/combined current limits, output
  voltage/frequency, float/absorption and stop-charge/discharge voltage settings.
  FC06 requires an exact echoed word. Charging enum value 1 is not defined; model-
  dependent voltage windows remain undocumented instead of borrowing a 48 V range.
- Growatt: output priority, charging priority and buzzer, FC06 holding writes;
  input-register telemetry remains a separate address space.
- Deye LV: inverter power, energy-management mode, solar export, grid/generator
  charging and selected current/export limits, FC16. Unknown model-specific limits
  remain explicitly undocumented; wire bounds are not operating recommendations.
- Deye high: four source-defined system flags, FC16.
- Hopewind: active/reactive regulation mode and active-power ratio, FC06. Changing
  a mode uses its existing setpoint; mode labels explicitly state this behavior.

Entries with zero controls in the current inventory explain that limitation and
offer a report; the interface does not fabricate register writes.
Binary collector FC3 reset/management and inverter clock writes are separate from
these accepted-profile FC4 controls and remain unavailable in this increment.

A CRC-valid illegal-address exception for an additional-profile setting marks that
field unsupported while other settings remain readable. Timeouts, malformed replies
and CRC failures are not silently treated as unsupported fields. Writes still need
a freshly observed value of the selected setting. Expanded definitions change the
binding digest; existing inferred devices require explicit profile recheck/renewal
before using expanded controls, without changing their HA IDs.

### Source-backed expansion in 0.8.0

The current inventory above supersedes the earlier audit's subset counts:

- MUST has one catalog entry and 27 controls. Saved PV3300/PV3900 IDs remain valid;
  exact recheck still uses their model markers. Energy combines the documented
  decimal high/low words, not an assumed binary 32-bit counter.
- SRNE v1.96 voltage/frequency/power fields are unsigned. The existing signed
  battery-current value and history are preserved; explicit charge/discharge
  readings interpret positive as discharge. Battery setpoints labeled **12 V
  reference** use per-12-V values: 14.4 V is encoded as 144, not a 57.6 V bank value.
  The ambiguous rated-voltage field remains a reading, not an editor.
- Growatt adds input-range and restart controls. Deye high-map exposes 118
  source-defined settings, including schedules and bit fields. Fresh read-modify-write
  preserves unrelated bits; the complete intended word is durable and must match
  independent readback, including those unrelated bits.
- PI30 has battery type, charge-current choices and nine flags. PI30 MAX has its
  own lowercase flag and indexed-current grammar. **Protocol write dialect** selects
  an explicit recheck/acceptance path; shared entity IDs and history are retained.
  The executor never retries an uncertain command with another case or dialect.
- PI18 has 23 editors. Paired `MCHGV`/`BUCD` commands preserve the freshly read
  companion value and verify both values afterward. Unit-addressed current/priority
  commands require observed single-module mode. Queried current choices and documented
  voltage choices are enforced, including after a stale UI draft.
- G-ASCII has 22 exact, whitelisted setters and independent setting-specific reads.
  Voltage bounds from a 24 V example are not generalized to 48 V systems.
- Optional ASCII groups run only during normal polling. Valid negative replies mean
  absence; timeouts, CRC errors and malformed required layouts remain failures.
  Daily counters use the inverter's queried calendar date. PI18 total ET is kWh;
  its daily ED and MAX QET/QLT/QED/QLD are Wh, converted to kWh. QLT is load energy.
- Optional Modbus blocks contain at most 32 registers. Low-word-first Deye/Hopewind,
  high-word-first counters, decimal MUST counters and temperature offsets have
  separate explicit definitions. Missing values are not reused from the prior cycle.

The earlier bullets describing eight PI30 controls, four high-map Deye flags and
three Growatt controls describe the 0.7.0 baseline. They are expanded by this section.
Sumry GES remains limited to nine sourced readings; 09C1 still has no sourced writes.
GivEnergy's proprietary framing/heartbeat and 60-aligned reads need a distinct
transport implementation and are not supported by adding an EyeBond register map.

09C1 is source-derived, not a new local hardware claim. Q1 reports input frequency;
QF reports output frequency. PV? is a legacy voltage/current reading, not verified
total PV power or physical port numbering. No SOC, actual power or energy is
invented from these values. Ratings are readings, not a unique inverter identity.

## Evidence and sources

### Remaining-family audit — November 7, 2026

This historical audit describes the deployed **0.7.0** baseline. The implemented
0.8.0 inventory and reconciled semantics are listed above. At that baseline, the
remaining 15 entries were mostly **incomplete subsets, not duplicate maps**.
MUST PV/PH18/PV3300/PV3900 are the next candidates for one canonical map with
marker-selected variants. Deye LV/high-map share a family but use different address
layouts. PI30/PI18/G-ASCII/09C1 retain distinct framing and response semantics even
when individual command names overlap.

| Family | 0.7.0 readings / controls | Gaps identified before the 0.8.0 expansion |
| --- | ---: | --- |
| MUST (three variants) | 11 / 10 each | Shared base; BMS 109–113, energy/status and further controls. The external base profile has 27 capability definitions; model applicability still matters |
| SRNE | 11 / 0 | Additional PV2, temperature, phase/status fields and documented R/W settings. Resolve the v1.96 type/polarity conflict below before expansion |
| Growatt SPF | 10 / 3 | The selected source has seven control definitions; energy, PV2, temperature and BMS SOC are also omitted. Holding and input registers are different spaces |
| Deye LV | 9 / 8 | The eight selected source control definitions are covered, but energy, BMS, PV2 and temperatures are not; this is not full manufacturer coverage |
| Deye high-map | 16 / 4 | The source has 70 measurement descriptions and 118 capability definitions: substantial phase, energy, generator, battery and scheduling gaps |
| Sumry GES | 9 / 0 | Matches the small nine-field source subset, not a full vendor map. Output/grid points are phase A; more reliable documentation is needed |
| Aohai FSA | 7 / 0 | Source telemetry includes power, energy, generator, temperature and BMS groups beyond this subset |
| Solis ESINV | 6 / 0 | Power, PV2, energy, BMS and fault fields remain omitted. Do not merge different Solis generations by brand alone |
| Hopewind 0237 | 7 / 3 | The three selected controls are represented; generation power, energy, extra PV and status readings remain incomplete. Generation is not household load |
| PI30 / MAX | 15 / 8 | Flags, energy, additional PV and model-specific controls; MAX commands must not become universal PI30 commands |
| PI18 | 17 / 0 | Additional FLAG/FWS/ET reads; independent mpp-solar defines setter commands even though the selected donor driver does not implement writes |
| G-ASCII | 16 / 0 | Only GMOD/GPDAT0 are polled. The source contains many other reads and 22 control definitions with setting-specific readback commands |
| 09C1 | 15 / 0 | Optional PV1/PV2 and status flags remain. No verified write implementation was found in the reviewed source; do not infer power/energy from ratings |

Source description/capability counts mix live values, settings and diagnostics;
they are **not coverage percentages** or proof that every model supports every field.
Zero implemented controls does not establish hardware read-only behavior.

The [SRNE v1.96 document](https://github.com/syssi/esphome-smg-ii/blob/b0ff1caec3ce395d774fcf496fcc03a75f925ca2/docs/SRNE.Solar.Charge.Inverter.MODBUS.Protocol1.96.pdf)
marks several voltage/frequency/power fields unsigned where the selected donor schema
and the 0.7.0 implementation used signed decoding. It also defines positive battery
current at hex 0102 as **discharging**, opposite to classic SMG. The 0.8.0
reconciliation preserves signed current history and adds explicit direction readings.
Phase-A points are not presented as multi-phase totals.

Two concrete expansion sources are the
[G-ASCII control/readback definitions](https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/custom_components/eybond_local/eybond_g_ascii_settings.py)
and [mpp-solar PI18 commands](https://github.com/jblance/mpp-solar/blob/eafdd4328c77f516cf82430c5bcb6fa042c45d3a/mppsolar/protocols/pi18.py).
The latter contains 11 active setter-command definitions, not necessarily 11 separate
editors. These are research findings; those expansions are not part of 0.7.0.

Energy expansion also needs explicit word order: several Deye/Hopewind counters
are low-word-first, while the earlier generic multiword Measurement decoder was
high-word-first. The expanded decoder makes word order explicit. Similarly, the G-ASCII F
response includes rated current while 09C1 F includes rated power; shared command
letters do not make those payloads interchangeable.

The November 7 family review additionally checked:

- [Classic SMG RS232 protocol, November 2021](https://github.com/syssi/esphome-smg-ii/blob/b0ff1caec3ce395d774fcf496fcc03a75f925ca2/docs/SMG-RS232%2BCommunication%2BProtocol%2BV1.0.1.pdf).
- [Protocol No. 3-10 document, November 2024](https://github.com/PreK/esphome-anenji-11kw-native-modbus/blob/55a330585846d57b4f24e6467201d8dde8985ee7/Communication.Protocol.No.3-10.docx).
- [SmartESS asset/function/address catalog](https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/custom_components/eybond_local/protocol_catalogs/smartess_local.json),
  reconfirmed at commit `88436d8629ef72835b4aae95297aa9332c51d11e`.

Primary pinned reference:
[ha-eybond-local at 6ca2b23cda042f5919e3831a907f784000d5de27](https://github.com/groove-max/ha-eybond-local/tree/6ca2b23cda042f5919e3831a907f784000d5de27),
MPL-2.0. Relevant paths below are under `custom_components/eybond_local/`:

- `protocol_catalogs/register_schemas/modbus_smg/base.json` and
  `protocols/communication_protocol_{1,2,3,3_10,4,5,6,11}.json`.
- `protocol_catalogs/register_schemas/{must_pv_ph18,srne_modbus,growatt_spf,deye_lv,deye_3ph_high_80kw,sumry_ges_7530,aohai_fsa,solis_esinv,hopewind_0237}/base.json`.
- `protocol_catalogs/register_schemas/smartess_local/models/{0912,0921}.json`.
- `protocol_catalogs/profiles/modbus_catalog/{growatt_spf,deye_lv,deye_3ph_high_80kw,hopewind_0237}.json`
  and `protocol_catalogs/profiles/must_pv_ph18/base.json` for control addresses/functions.
- `payload/pi30.py`, `payload/pi18.py`, `payload/ascii_line.py`,
  `drivers/pi30_settings.py`, and `protocol_catalogs/command_schemas/eybond_g_ascii/base.json`.
- `payload/urtu09c1.py` and `drivers/eybond_09c1.py` for 09C1 framing/columns;
  protocol-specific SMG profiles and `profiles/must_pv_ph18/base.json` for expanded
  setting addresses, scales and function codes.
- `protocol_catalogs/inverter_catalog.json` for independently scoped route candidates.

Independent cross-reference for the low SMG map:
[Local-Cloud-Bridge, 34f5abe](https://github.com/samuelolteanu/Local-Cloud-Bridge-for-Anenji-Easun-MPP-Solar-Inverters/blob/34f5abe/inverter_bridge.py),
GPL-3.0, and for PI30/FC4:
[PowMr proxy, b7a3ada](https://github.com/andronick83/powmr-eybond-proxy/blob/b7a3ada/proxy.py), MIT.

Only protocol facts and selected field meanings were independently implemented.
No third-party driver, schema file, private support archive or hardware capture
was copied into the runtime. Tests use labeled synthetic register/ASCII specimens,
not relabeled manufacturer or hardware evidence. Every profile's metadata contains
its pinned public source URL.

## Reports, replay and support destination

Reports include attempted families/routes, reasons for rejection, proposed profiles,
acceptance/control preference and original validation facts. Binary replay can
reconstruct supported Modbus/ASCII profile values from correlated original frames.
Raw-AT replay uses the original ordered request/receive chunks, validates the
expected Modbus or ASCII response and reconstructs selected-profile measurements.
Incomplete replies, absent requests and unassociated tails stay explicit; it does
not guess a new frame boundary after an ambiguous failure or execute any command.

Support is available through [GitHub Issues](https://github.com/jay0x/solar-inverter-cloud-bridge/issues).
The UI offers a ZIP and copyable issue text for manual sharing with the maintainer;
the repository includes a device-support issue template. Reports are never
automatically uploaded to GitHub or reference projects.

## Storage and scope

Schema 3 introduced `profile_acceptances`. Schema 4 retires the control-mode and
separate control-permission gates; existing accepted profiles use full control,
with their definition/signature bindings retained. Device IDs, registry names,
parameter/sensor IDs, maintenance preferences and unresolved operations are preserved;
only the obsolete mode selector is removed. Policy changes increment the revision.
Keep a consistent backup before upgrading; older code refuses a newer schema.

The catalog is extensible, not a claim to cover all inverter brands/protocols.
Unknown/encrypted payloads, missing replies, vendor-specific loggers and variants
with insufficient public semantics remain reportable gaps. Hardware qualification
will come from community reports, not from pretending synthetic tests were hardware.
