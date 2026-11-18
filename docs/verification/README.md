# Verification and qualification

Software checks, installation acceptance and physical-device evidence are separate.
The commands below do not establish support for every inverter or firmware.
See the [testing guide](../development/testing.md) for reproducible checks.

## Release 1.0.0

- Integration **1.0.0**, panel **0.24.0**, ledger schema **4**, incident schema **1**.
- Test environment: Python **3.14.4**, Home Assistant fixtures **2026.10.4**.
- Component fingerprint:
  `c15bedcb59e4a6dfa71ee6bf1dfcddbf0cc10507d3680db5f37d546a938be867`.

| Check | Result / scope |
| --- | --- |
| Offline suite | 260 cases: 259 passed, one local TCP502 skip |
| HA integration suite | 36 passed |
| Browser suites | Panel and router-guide journeys, including incident recording/export and responsive layouts |
| Documentation | Local and planned-package links, language placement, license integrity and whitespace |

The release uses the same runtime and frontend implementation as the installed
component fingerprint `62b3e9e7ee073cf7e566d26cbb3f5f806357061a3820eb6933d5526fe921ae26`;
only the manifest version changes. Documentation is updated for normal release
installation. Hosted checks for the tagged commit are available in
[GitHub Actions](https://github.com/jay0x/solar-inverter-cloud-bridge/actions).

## Software coverage

- **Connection ownership:** callback admission checks source and full identity.
  Switching an existing enrollment preserves IDs and serializes with its I/O.
  A queued verification cannot send through a holder that lost ownership while
  waiting for its lock. Redirect with retained IP needs no callback listener.
- **Reconnect:** 100-cycle simulations keep automatic requests bounded. Old
  successful requests cannot extend each other's lifetime. Manual request IDs
  retain their bounded deduplication contract; waiting requests are not evicted.
- **Binary framing:** fixed callback management-route mapping, full-PN/native
  qualification, CRC/slave/TID/route checks, empty-read retries, idle heartbeat,
  unsolicited traffic and partial-frame boundaries. Writes are never replayed.
- **Durable controls:** current baseline and profile acceptance, one send claim,
  independent readback, possible-send uncertainty and reconciliation. All native
  controls and panel actions use the same executor and administrator checks.
- **Clock:** correction begins at 60 seconds with no upper drift limit. The
  readback tolerance is three seconds after elapsed-time adjustment, independent
  of polling pause. Synthetic FC16/ACK/FC03 cases exercise both Protocol 4 IDs,
  accepted nondefault routes, clock opt-in, stale bindings and unresolved barriers.
- **Freshness:** telemetry TTL is 60 seconds plus polling pause. Full settings and
  individual readbacks retain separate ages and current-session evidence. Settings
  expiry can update native entities even after telemetry has already expired.
- **Backup/lifecycle:** repeated real database freeze/unfreeze leaves polling alive;
  lifecycle tests cover unload/reload, cancellation and storage ownership.
- **Passive incidents:** prelude/tail capture, stable fingerprints, repeated-event
  counters, count/byte bounds, restart-safe watches, storage retry and cancelled
  initialization. Successful polling does not resolve uncertain commands.
- **Report integrity:** default exports omit wire bytes; explicit raw exports pass
  archive validation. Capture gaps isolate replay buffers and correlation, so
  disjoint fragments cannot fabricate a valid packet. Capture build is retained
  per sample independently of the exporting build.
- **UI:** focus/drafts survive refresh; save buttons highlight only changes; a
  saved recording preference is distinct from a checkbox draft. Tests cover disable,
  delete all incidents and re-enable, including empty lists. Raw opt-in resets,
  feedback remains user-reported, and GitHub links require a user action.

## Installation acceptance

The runtime and frontend were installed on HA 2026.10.4 test and production
instances before the manifest version was changed to 1.0.0. Source hashes, Core
configuration validation, retained IDs/preferences and compressed HTTP responses
were checked. Both retained **85 existing registry entries and overrides**.

With test collection disabled, a recording preference and one-hour watch survived
an integration reload. The watch was cancelled and the original preference restored.
A feedback archive passed validation. Live Chromium checked the incident tools,
raw-off default, saved/draft explanation and layouts at 360/390/1440 px without
inverter actions. An additional exact-candidate Marketplace installation check is
recorded in the GitHub release notes; source copying alone is not evidence of it.

A two-minute production AT observation produced 20 new snapshots and 25/25 healthy
sampled states, while two polling timeouts occurred between samples. The recorder
grouped them into one fingerprint with two occurrences, two retained samples and
two recovered occurrences. Sanitized and raw archives were downloaded, validated
and replayed. This demonstrates incident capture, not elimination of the timeout.

## Physical reference and scope

Reference: **ANENJI ANJ-11KW-48V-W-P**, native Protocol 4/model 32771, with
**Wi-Fi.DTU firmware 8.50.12.3 / AT 1.11**. Observed paths are redirected AT TCP18899
and binary callback TCP8899, bootstrapped by targeted UDP58899.

- Full collector identity, telemetry and settings were read on both paths.
- Reversible LCD backlight and return-home writes used operation IDs and independent
  readback. Original values were restored and checked using a fresh settings group.
- Passive redirected TCP plus active callback supported polling and a confirmed
  display-setting change/restoration. Passive means heartbeats with native collection
  disabled. The redirected endpoint was another Bridge, not a vendor cloud server.
- Simultaneous workflows on two independent controllers were unsuccessful: one
  timed out during preflight with zero native write frames while the other completed.
  Keep one active controller; locks are local to one runtime.
- A 20-second callback heartbeat schedule kept a passive connection alive through
  short comparison windows. This is not a 24-hour stability qualification.

### Original empty-FC4 capture — November 17, 2026

Build `87bd97d60df071459063c990d771bb065c08df30599c2adcf10b9f6018f57881`
retained 14,337 wire bytes and 2,880 events without drops during a two-minute
callback observation. One original request/reply/retry sequence was:

```text
TX  0060 0102 000a ff04 010300b80001042f
RX  0060 0102 0002 ff04
TX  0061 0102 000a ff04 010300b80001042f
RX  0061 0102 0009 ff04 0103020004b987
```

The eight-byte reply has matching TID 96, route 258/255 and function 4. Length 2
contains only address/function: there are no inverter bytes. After 202.4 ms, the
read of register 184 was retried with TID 97 on the same session. The reply arrived
after 183.5 ms, passed CRC/route/slave/function checks and returned protocol value 4.
The observation contained 27 complete binary snapshots and no binary session closure.

This confirms handling of that recorded empty response, not why the collector
returned it or the contents of earlier incidents known only from byte counters.

## Known limitations and open qualification

- Intermittent AT timeouts and occasional empty callback replies remain observed
  behavior. The physical causes and fixed-build long-term reliability need further
  investigation. Healthy sampled states can coexist with failures between samples.
- Additional profiles are source-derived and simulator-tested. Implemented controls
  are available after explicit profile acceptance; hardware qualification is narrower.
- Binary clock execution has synthetic coverage, not a dedicated physical clock-write
  acceptance result. Electrical/schedule effects were not tested by the display tests.
- Binary collector reset and clock setters outside Protocol 4 are not implemented.
  A permission switch cannot provide a missing wire command.
- Readback confirms a reported setting, not an independently measured physical effect.
- Backup freeze/copy/recovery tests do not establish a full Supervisor restore.
- Callback requires a local HA interface and preserved collector source IP.
  Address-translating NAT and arbitrary vendor-cloud concurrency remain unqualified.
- Router recipes have syntax/browser coverage, not comprehensive physical-router tests.

See the [compatibility register](../DEVICE_COMPATIBILITY.md) and
[profile matrix](../PROFILE_EXPANSION.md) for model-specific scope.
