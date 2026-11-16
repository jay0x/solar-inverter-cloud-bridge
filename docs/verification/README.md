# Verification and qualification

Software tests, installation checks and physical-device evidence are separate
qualifications. Commands are in the [testing guide](../development/testing.md).

## Current source candidate

- Integration: **0.9.0**; panel: **0.20.0**; ledger schema: **4**.
- Test environment: Python **3.14.4**, Home Assistant fixtures **2026.10.4**.
- Component fingerprint:
  `4399694193e7f617d003c2255161351804e605bd65f6c4b3d6af6fe9a2c21e84`.

| Check | Result / scope |
| --- | --- |
| Offline suite | 194 cases: 193 passed, one local TCP502 skip |
| Home Assistant integration suite | 30 passed |
| Browser suites | Panel and router-guide journeys passed, including callback fields and request persistence |
| Documentation | Local links, language placement, license integrity and whitespace checks passed |

These are local source checks. Hosted checks for published commits are available in
[GitHub Actions](https://github.com/jay0x/solar-inverter-cloud-bridge/actions); they
do not establish validation of uncommitted source changes.

## Covered behavior

- A real database freeze/unfreeze repeated twice does not terminate the polling
  scheduler. It resumes without an integration reload and does not replay writes.
- Loopback UDP/TCP collectors verify the canonical callback request, AT and binary
  identity negotiation, request deduplication, source restrictions, bounded retries,
  occupied listener ports, identity-mismatch rejection and single-owner reuse.
- Binary callback tests cover the fixed management-route mapping, full-PN/native
  qualification and continued rejection of wrong native routes and ordinary-session
  mismatches. Idle callback heartbeat coverage requires no native polling.
- HA tests cover administrator checks, local callback-host validation and persistent
  per-device connection preferences across reload.
- Existing-device edit tests switch between real loopback TCP channels, retain one
  active owner, wait for an in-flight poll, reject a mismatched collector, and refuse
  unresolved operations or a failed listener bind before saving. Paused edits send
  no UDP. HA tests preserve enrollment/preferences through reload and validate the
  one-second minimum. Browser journeys cover editing and paused-save feedback.
- Browser tests cover optional/required collector IP, persisted drafts and attempt
  IDs, and no automatic callback resend on browser reload.
- Save-button journeys verify normal/changed/reverted/saved styling, independently
  for each settings section, with no focus loss on refresh. The same behavior was
  checked on the test HA at 390/1440 px without submitting configuration changes.
- Settings-cadence tests check reuse only on the same connection, no artificial
  timestamp refresh, no clock sync from a cached clock, and fresh command preflight.
- Automatic clock correction starts at 60 seconds and has no upper limit.
  It no longer uses the polling pause as its minimum, so a multi-second settings
  read does not trigger a clock write.
- Existing suites cover frame validation, profiles, controls, command uncertainty,
  readback/reconciliation and entity lifecycle.

## Hardware observations — November 15, 2026

The physical cycle timings and display writes below were measured with component
fingerprint `5a842ee839c75430ca863705cd269bea20ec81a400fd8e4aa2ef1a17ee8184b4`.
They do not independently qualify the current editor's live active-channel switch.

The reference is an **ANENJI ANJ-11KW-48V-W-P**, Protocol 4/model 32771, with a
**Wi-Fi.DTU collector, firmware 8.50.12.3, AT 1.11**. Observed paths are redirected
AT TCP18899 and binary callback TCP8899, bootstrapped by targeted UDP58899.

- Callback identified the same full collector PN and delivered fresh telemetry and
  settings without a DNS override to the callback receiver. The redirected endpoint
  remained a separate Bridge; the vendor's cloud server was not part of this test.
- Reversible LCD backlight and return-home setting writes were exercised with durable
  operation IDs and independent readback. Original values were restored and checked
  using a fresh complete settings group. No electrical-setting effects were tested.
- Passive redirected TCP plus active callback supported polling and a confirmed
  backlight change/restoration. Passive means TCP/heartbeats with native collection
  disabled; it is not a second telemetry source or controller.
- Simultaneous command workflows were unsuccessful: the redirected path timed out
  in identity preflight with **zero native write frames**, while the callback write
  completed. This does not demonstrate concurrent native writes. Keep one active
  controller; the executor lock cannot coordinate separate HA instances.
- An idle callback disconnected after about 35 seconds with a 60-second heartbeat
  schedule. With the current 20-second scheduling cap, the passive channel remained
  connected throughout each approximately 100-second comparison window without
  native polling. The binary heartbeat payload and transaction deadlines are unchanged.

### Matched short-window cycle timings

Each path used the same physical collector, a 5-second delay after a completed cycle
and a 30-second settings cadence, with the other path passive. Durations below are
medians, not the interval between published updates.

| Cycle | Redirected AT | Binary callback | Samples (AT / callback) | Requests per cycle (AT / callback) |
| --- | --- | --- | --- | --- |
| Telemetry, cached settings | 2874.58 ms | 2323.45 ms | 8 / 9 | 10 / 12 |
| Telemetry and fresh settings | 4875.86 ms | 3643.68 ms | 3 / 4 | 16 / 18 |

Callback cycles were about **19% shorter for telemetry** and **25% shorter with
settings** in this sample, despite additional identity requests. Each window produced
12 completed snapshots with fresh readings and no new polling errors. This does not
establish a universal speedup, 1 Hz polling or a higher observed update count.

### Installation acceptance and limits

The hardware-measurement fingerprint above was read back on two HA 2026.10.4
installations. Its final three-minute redirected-path observation had 19/19 healthy samples, 21 new
completed snapshots and no new polling errors; one earlier runtime polling error
remained in the cumulative counter. All 85 entity registry entries and their
overrides, device identity and maintenance preferences were preserved. Test polling
was left disabled. This is a short acceptance check, not a long-term stability result.

The current source candidate was subsequently installed and hash-verified on the
test HA 2026.10.4 instance. With collection paused, the API accepted a one-second
pause, saved callback preferences without UDP, deduplicated the request and restored
the original redirected preference and pause. All 85 registry entries and overrides
were preserved. Live Chromium checked the Connection editor at 390/1440 px and draft
persistence across reload without sending a request. The integration remains loaded
for UI access with collection paused. Active hardware switching and one-second
hardware polling were not exercised in this editor acceptance check.

The current fingerprint, including save-button styling, was then verified on both
HA installations. The production instance passed configuration validation, source
readback and a roughly 90-second observation: 19/19 healthy samples, 10 new snapshots,
no new polling errors, and all 85 registry entries/overrides and current preferences
preserved. Both instances served panel JavaScript matching the local source. These
short installation checks do not remove the intermittent transport limitations above.

- Additional profiles, collector firmware and callback writes beyond the tested
  display controls require their own qualification.
- Intermittent AT polling timeouts remain under investigation. A successful short
  check is not fixed-version 24-hour stability qualification.
- Readback confirms a reported setting, not an independently observed electrical effect.
- Backup freeze/copy/recovery tests are narrower than a full Supervisor restore.
- Callback currently requires a local HA interface address and preserved collector
  source IP. Address-translating NAT callback paths remain unqualified.
- Router recipes have syntax/browser coverage, not comprehensive physical-router testing.

See the [compatibility register](../DEVICE_COMPATIBILITY.md) and
[profile matrix](../PROFILE_EXPANSION.md) for exact scope. Check tagged-release notes
before using source-candidate features through HACS.
