# Verification record and remaining qualification

This records 0.8.1 branding/publication preparation, earlier profile/full-control/setup checks and the
**completed 0.4.0 observation baseline**.
Current commands are in [the testing guide](../development/testing.md). A local test
result is not a new hardware qualification or an installation-archive build.

## Public repository and HACS installation — November 7, 2026

Public source: [jay0x/solar-inverter-cloud-bridge](https://github.com/jay0x/solar-inverter-cloud-bridge).
The initial import contains only the reviewed source tree, with a clean Git history;
private files, installation-specific access tools and old local commits were excluded.
Gitleaks found no secrets after a narrow exception for the public SRNE parameter
identifier `bulk_charging_voltage_per_12v`; no credential/file-wide exceptions were used.

Candidate **0.8.2 / panel 0.16.1 / schema 4**, component fingerprint:
`877458045c64ccfe2c74b3e5794a1847976665f31f048585799b4849fab16a75`.

- Hosted [tests](https://github.com/jay0x/solar-inverter-cloud-bridge/actions/runs/42393286327)
  and [Hassfest/HACS validation](https://github.com/jay0x/solar-inverter-cloud-bridge/actions/runs/42393286408)
  passed for commit `0677cfa`: 175 offline cases (174 passed/one skip), 27 HA tests,
  documentation checks and both browser suites. No installation build was run.
- The initial checks found undeclared optional `hassio`/`network` dependencies and
  a configuration-schema assignment hidden from static validation. These were
  corrected. Recovery-test timestamps now use a controlled clock instead of assuming
  the hosted runner has been up longer than the grace periods; runtime reset logic
  was not relaxed to pass tests.
- HACS **2.0.5** on HA **2026.10.4** registered the public custom repository and
  downloaded `main` at `0677cfa` over its normal authenticated WebSocket workflow.
  All **53 installed component files** matched the public source hashes. Core check
  and restart passed. This was an in-place transition from the manual source
  installation to HACS management, not a fresh empty-HA installation.
- API readback confirmed the exact component fingerprint, existing config entry,
  the same reference inverter and all **85 entity IDs/registry overrides**, saved
  maintenance preferences, fresh telemetry/settings and unresolved 0. Live Chromium
  passed afterward, including native sensors/history and diagnostics.
- No physical inverter Apply/reset command was sent. No GitHub Release, tag,
  default-catalog submission or new 24-hour observation was created. Development
  availability through a HACS custom repository is distinct from a stable release.

## Deployed 0.8.1 rename and publication preparation — November 7, 2026

Product: **Solar Inverter Cloud Bridge**. Integration 0.8.1 / panel 0.16.1 /
schema 4, source fingerprint:
`b95f95a7dde539d89a5a612e46caf3763fe886ddb1b8cc3b1671566fe96dad2f`.

- Updated display names, HACS/manifest metadata, config flow, panel, diagnostics
  and documentation. Domain, service names and storage paths remain stable.
  The old default config-entry title updates through the HA API; custom titles remain.
- **175 offline cases: 174 passed, one local TCP502 skip; 27 HA tests passed**,
  including default-title migration and custom-title preservation. Both synthetic
  browser suites passed with the longer name and updated panel cache version.
- Source deployment verified 53 files and passed Core check/start. API readback
  confirmed the new title and exact fingerprint, all 85 entity IDs and registry
  overrides, unchanged maintenance preferences, fresh readings/settings and no
  unresolved operations. Live Chromium passed without inverter Apply/reset commands.
- Reviewed the installation, compatibility and protocol guides against code.
  Corrected stale 25-profile counts, old MUST/PI30/G-ASCII control inventories,
  optional BMS/09C1 coverage, PI41 rejection and obsolete separate-control wording.
  Documented local operation despite Cloud branding, HACS installation after
  publication, and the stable-domain rename path. Historical evidence versions remain.
- Documentation/link checks, MPL/inherited-MIT integrity checks and `git diff --check`
  passed. The pre-release semantic documentation review is now an explicit requirement
  in the agent instructions and [publication guide](../development/publication.md).

Prepared owner/repository metadata: `jay0x/solar-inverter-cloud-bridge`.
GitHub/HACS/Hassfest workflows and issue templates are prepared, but no repository
or release has been published and no hosted validation/HACS installation has run.
The manifest URLs are reserved for that future repository. A reviewed clean source
export is required because older local history contains private working documents.
No installation archive, commit, push or new 24-hour run was made in this step.

## Deployed 0.8.0 source-backed expansion — November 7, 2026

Integration 0.8.0 / panel 0.16.0 / schema 4, source fingerprint:
`97422c08ded740ea56ae42122b2f077cfbe861601ec71893ed77d8e9ef6cd0bd`.

- **175 offline cases: 174 passed, one local TCP502 skip**, using the build-prohibited
  runner. Twelve new cases exercise independent primary-document specimens and
  simulated peers: MUST decimal counters, Deye word order/offsets, SRNE unsigned
  power and per-12-V settings, PI18 compound commands/readback, PI30/MAX case and
  indexed currents, G-ASCII decimal writes, dates/energy units and optional-read CRC
  failures. Masked and paired operations persist complete intent; reconciliation and
  duplicate IDs do not send again. Companion/unrelated-bit mismatches stay unresolved.
- **26 HA integration tests passed**, including engineering-unit supported-values
  attributes and PI30-to-MAX renewal with existing entity IDs preserved, expanded
  battery options and additional energy sensors.
- **Both synthetic Chromium suites passed**, including explicit dialect recheck,
  selection persistence, unsupported-value rejection and existing responsive journeys.
- Source deployment verified **53 component files**, passed the Core configuration
  check and restarted successfully. API readback confirmed the exact fingerprint,
  24-entry catalog, the same reference device and all **85 existing entity IDs**,
  unchanged maintenance/polling preferences, fresh telemetry/settings and unresolved 0.
- **Live Chromium passed**: catalog disclosure persistence, native editors, 35 reference
  sensors and Recorder history, diagnostic build identity, native device navigation,
  mobile layout and the router guide. Compatibility capture/export was read-only;
  no Apply or reset was sent to the physical inverter.
- Documentation validation and whitespace checks passed. No installation archive,
  commit, publication or new 24-hour observation was made for this increment.

New-family controls and expanded readings remain source-derived and simulated.
The live installation checks regression behavior on the reference AT inverter;
they do not qualify writes on additional devices. The unchanged reference map does
not require expanded-profile acceptance. Changed inferred definitions require recheck.
Sumry's larger map, 09C1 writes, ambiguous scale claims and GivEnergy transport remain
explicit gaps, as described in the [profile guide](../PROFILE_EXPANSION.md).

## Deployed 0.7.0 profile unification — November 7, 2026

Integration 0.7.0 / panel 0.15.0 / schema 4, final source fingerprint:
`d47e12e16e5d0ec6ea9854ee13f5e6831e2429da6670303fed79c484ab8c9280`.

- **163 offline cases: 162 passed, one local TCP502 skip**, with installation builds
  prohibited. New tests assert SmartESS 0912 FC04/slave4 wire requests, descriptor-hint
  ordering and original-wire replay; shared reference/common Protocol 4 decoding,
  partial optional registers, CRC rejection, known-variant fallback refusal and
  renewal of an old definition binding without changing the device ID.
- **24 HA integration tests passed**; both browser suites passed with the unified
  catalog, qualification notes, full-control policy and stable disclosure behavior.
- Qualified binary reference Protocol 4 settings now exercise FC16 ACK plus separate
  readback on the synthetic collector. Clock writes and collector reset remain
  unavailable on binary; a direct backend clock attempt is explicitly rejected.
- The first source deployment verified 49 component files and passed the Core check.
  Live Chromium passed on that deployment, including the 25-entry grouped catalog,
  full-control editors, native history, diagnostics and unchanged entity navigation.
  The final backend-only clock-capability guard then passed the offline/HA suites
  and was deployed/read back with the fingerprint above; UI assets were unchanged.
- Final API verification confirmed the same one reference inverter and all 85 HA
  entity IDs, saved name/allowlist/maintenance preferences, fresh telemetry/settings
  and unresolved 0. The retained reference profile ID is not rewritten in storage;
  it resolves to the canonical Protocol 4 catalog/decoder.
- No electrical/reset command was sent to hardware for verification, no installation
  archive was built, and no new 24-hour observation was started. New-family coverage
  and binary write qualification are source-derived/simulator evidence, not new
  physical-device tests.

One preexisting correlation test exposed a scheduling race when its post-timeout
assertions shared a 30 ms deadline under parallel test load. The initial timeout
case is retained; later correlation/cancellation checks now use a one-second budget.

The remaining-family audit is recorded in
[the profile guide](../PROFILE_EXPANSION.md#remaining-family-audit--november-7-2026).
Its proposed expansions and SRNE source-conflict resolution are not implemented
by this deployment.

## Deployed 0.6.0 full control — November 7, 2026

Integration 0.6.0 / panel 0.14.0 / ledger schema 4, source fingerprint:
`371f01fa602b63cabae8755a7d6af9d4ac1d2ad622e0b97eb11990c6e1f4a1a6`.

- Offline build-prohibited suite: **157 cases, 156 passed, one local TCP502 skip**.
  Migration fixtures cover all three legacy modes, preserved IDs/preferences and
  profile bindings, one-time policy revision and no replay of unsent/uncertain work.
- **24 HA integration tests passed**. Native parameter controls are available by
  capability/freshness rather than mode; the retired selector is removed through
  the registry API without changing parameter IDs. The old mode action is absent.
- Both browser suites passed. All parameter rows remain visible, unknown-limit
  decimal settings are editable with warnings by default, and profile acceptance
  has one acknowledgement covering readings and implemented commands. Existing
  setup, responsiveness, draft/focus and uncertain-result checks still pass.
- Test-VM source deployment verified 48 files and passed the Core configuration
  check. Live readback confirmed schema 4, full control, preserved device identity,
  allowlist and maintenance preferences, fresh settings/telemetry and unresolved 0.
  The registry changed from 86 entries to 85: only the obsolete mode selector was
  removed. Consumer checks found no references to it or the old mode action.
- Live Chromium confirmed immediately available numeric editors, no mode/control
  switches, actual native history, diagnostics, profile catalog and native controls.
  No Apply/reset command was sent for verification. Automatic clock/recovery switches
  retained their prior values. No installation archive or new 24-hour run was made.

## Deployed 0.5.0 setup UX — November 6, 2026

Integration 0.5.0 / panel 0.13.0 / ledger schema 3, source fingerprint:
`7f9d34970fddd6ffe749affbf5c3dd9440c0207f90c4688f7ef4ae4d7c1d0114`.

- **24 HA integration tests passed**, including the initial detected-LAN default,
  actual network prefix, input preservation and ambiguous-interface handling.
- Both browser suites passed. First-inverter journeys cover the single entry point,
  saved network, asynchronous collector arrival, multiple collectors, one read-only
  check after selection, explicit enrollment, expired/disconnected recovery and
  proposals scoped to the selected collector. Existing editing/consent/router checks
  remain covered.
- Layout checks measure equal widths and **24 px gaps** between direct wizard blocks.
  Connection actions were checked at 360/390/768/1440 px in light/dark synthetic themes.
- Source deployment verified all 48 component files and passed the Core configuration
  check. Live readback preserved the saved allowlist and the empty inverter inventory.
- Live Chromium checks on the test HA confirmed the first-inverter path, highlighted
  connection action and measured geometry at the same four widths. Only status and
  network-hint requests were sent; verification/enrollment were left for the owner.
- No installation ZIP was built, no inverter settings were written, and no new
  stability observation or family hardware qualification is claimed by this UI check.

## Earlier local 0.5.0 software checkpoint — November 6, 2026

Component fingerprint:
`e35cc1d79739188184dd3fb79a283e738bd62ffbb8d911d75dafc832905d1d53`.
Panel was 0.12.0 and ledger schema 3. These checks preceded the later source
installations and setup revisions above; no installation archive was built.

- The build-prohibited offline runner completed 156 cases: **155 passed, one local
  TCP502 case skipped**. The installation-builder test was excluded, not counted
  as passing. Diagnostic report formats were exercised in memory.
- **23 HA integration tests passed**, excluding the separate ZIP-install test.
- Both synthetic browser suites passed (64 panel and 24 guide responsive checks
  plus editing/consent/report journeys). Additional profile-composition checks cover
  common-only, reference and mandatory model extensions at four widths, saved evidence
  and escaped descriptions. These results are synthetic; later live setup checks are above.
- SMG family regression checks preserve the pre-refactor definitions for all eight
  experimental SMG profiles and the reference control inventory. Independent register
  specimens exercise low/high layouts, Protocol 3/5 versus 4/6 power/load addresses
  and the omitted PV aggregate in 5/6. Unimplemented SMG protocol IDs expose no controls.
  Definition stability is relative to the earlier local 0.5.0 increment, not 0.4.0's
  smaller experimental control sets, which still require renewed acceptance.
- Common-only enrollment/control was exercised with an unknown SMG model code.
  MUST common-map tests apply positive PV3300 identity markers to the load scale in
  live reads and original-wire replay. Changed markers invalidate the old binding;
  explicit renewal retains the device ID and survives a fresh runtime's status read.
  Valid absent-marker exceptions permit the common map; bad CRCs do not.
- 09C1 was tested with independent fixed-column examples, malformed/other-dialect
  rejection, AT and binary sessions, explicit enrollment and original-wire replay.
  Fifteen readings/status fields are implemented; no actual power, SOC or energy
  is inferred from the voltage/current fields, and no write command map is invented.
- Expanded SMG/MUST/PI30 controls were checked for source-specific enums, decimal
  encoding, schedule guards, exact ACK and independent readback. A validated
  unsupported setting address does not hide other supported settings. Bad CRCs
  and unassociated tail bytes remain failures rather than being silently skipped.
- Raw-session tests reproduce a busy endpoint dropping unspaced requests and verify
  the 50 ms turnaround/deadline behavior. Queued raw replies cannot complete an
  unsent query. Settings failures increment backoff/error accounting; planned TID
  rotation remains a reconnect lifecycle, not a failure.

Read-only observation of the deployed reference found sub-millisecond receive-to-
next-send gaps; the predecessor's raw reader used 50 ms. That is a concrete transport
difference and a plausible contributor to missing replies, **not proof of the live
timeout root cause**. Its impact needs a controlled deployment/comparison after the
existing 24-hour run is reviewed. Cumulative error counts and exchange timing/byte
evidence were added to support that comparison.

## Deployed 0.4.0 candidate identity — November 5, 2026

- Integration 0.4.0, panel 0.11.0, bridge ledger schema 3.
- Runtime component fingerprint:
  `fd4d9a9f424fce5db015c2d0c3f5bcde44c0fcdfc7392bbed2958722579b24b5`.
- Local implementation checkpoint: `c6dce9e`.
- HA fixture and test installation: Core 2026.10.4. Test Python: 3.14.
- Later MPL-2.0 and documentation changes have not been rebuilt or redeployed.
  Existing archives must not be described as newly MPL-packaged releases.

## Recorded checks

| Level | Recorded result | What it establishes |
| --- | --- | --- |
| Offline/loopback | 134 cases: 133 passed, one skipped | Codec/identity/correlation, independent map specimens, discovery/consent, command failure boundaries, migration, reports/replay and packaging |
| Local TCP 502 | One case skipped because the port was unavailable in the development environment | A skipped local bind is not a pass; all three actual listener binds were checked separately on the test HA |
| HA integration | 24 passed | Real entity/state/config/service behavior, profile inventories, admin-only permission, clean ZIP install and 100 reload cycles |
| Browser | Both suites passed | 64 panel and 24 guide responsive checks plus consent, draft/focus, uncertain-result, Recorder-event and guide-generation journeys |
| Live test installation | Readback/browser checks passed | Three listeners, catalog, preserved reference-device IDs/mode/preferences, fresh data, no unresolved operation and native Recorder behavior |
| New-family hardware | Not available | New maps/transports are source-derived and simulator-tested, not locally hardware-qualified |

Source-defined control tests include binary FC4, Modbus FC06/16 exact ACK/readback,
PI30 CRC/ACK plus QPIRI readback, definition/signature changes, explicit binding renewal
without new entity IDs, and uncertain outcomes without replay. No electrical or reset
command was used merely for the live UI verification.

## Supporting load evidence

A preceding 0.4.0 component candidate
`b2d6358e4e02a332f9d73544b59ecf74393ce7c025b4adc4e13247fa1795a77e`
ran a 45.06-second loopback benchmark with eight AT and eight binary peers at a
10-second poll interval. Forced TID exhaustion produced eight reconnects; all
16 devices remained observed, with no recorded poll failures/issues. There were
944 reads after warmup; p99 loop lag was 20.943 ms and maximum 56.569 ms while
other checks ran concurrently. This is bounded software evidence for that hash,
not a long-duration guarantee or 16 hardware installations.

## Completed 0.4.0 fixed-candidate observation

Reviewed November 6, 2026. The run lasted from November 5 17:07:41 UTC to
November 6 17:07:41 UTC: 86,400.15 seconds. Its final state is `complete`, and
the candidate fingerprint remained the deployed 0.4.0 hash recorded above.

- 1,436 samples; 1,422 healthy (99.025% of samples).
- Zero API errors, runtime restarts, sampled stale-telemetry states or unresolved
  operations. The final sample had a connected collector and fresh telemetry/settings.
- Fourteen isolated unhealthy samples: two disconnected, twelve with settings
  unavailable. Each was followed by a healthy sample at the next observation,
  approximately 60 to 67 seconds later.
- The recorded last-error field was `TimeoutError` in thirteen unhealthy samples
  and `unexpected_byte_count` in one. A retained last-error field is not a distinct
  transaction count or proof of the cause of every health transition.
- Sampling intervals ranged from 60.01 to 71.36 seconds. Sample health is not an
  exact uptime percentage, and these intervals do not establish fault duration or
  exclude shorter unobserved faults.

This establishes a completed 24-hour unchanged-candidate baseline with intermittent
read/connection problems, not a fault-free stability pass. The waiting gate for
0.5.0 deployment is cleared; its timing/error-accounting changes still need a
separate fixed-candidate comparison. No 0.5.0 hardware result follows from this run.

## Open qualification boundaries

- The completed 0.4.0 baseline above does not qualify the later 0.5.0 changes.
  Their effect on timeouts and settings availability still needs comparison.
- Full Supervisor archive restore remains unproven; worker freeze/copy/recovery
  tests are narrower evidence.
- Community reports must establish exact model/firmware/collector behavior for new
  families. External projects' successes do not become local hardware verification.
- Router generators have syntax/browser coverage, not comprehensive physical router
  qualification. The canceled manual WAN-loss exercise is not an active task.
- Repository publication, support destination and maintainer metadata remain separate
  from local builds and implementation checks.

Detailed deployment transcripts, old acceptance reports, benchmark JSON and agent
history are retained privately. Add a new public report only when it contributes
new dated evidence under the [documentation policy](../development/documentation-policy.md).
