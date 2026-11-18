# Compatibility diagnostics and replay

Normal HA diagnostics provide redacted cached operational data. The richer
compatibility workflow also works before enrollment or when no profile matches.
It does not require a shell, cloud account or packet-sniffer privileges.

Each device exports its own parameter inventory, actual telemetry/settings TTL,
current-session settings freshness, single-field readback freshness and both
maintenance preferences. The root `parameter_inventory` is a compatibility reference
explicitly labeled `modbus_protocol_4`; consumers should use device inventories.
The base telemetry grace is 60 seconds, not the full TTL: the configured pause is
added per device. Ordinary diagnostics omit rejected-payload hex along with raw wire
frames; full protocol bytes remain an explicit compatibility export choice.

## Capture contract

- A 256-event operational ring retains redacted admission/decision context.
- An explicit collection is limited to 120 seconds, 4096 events and 4 MiB of wire
  bytes. It retains startup plus a bounded tail, with dropped counts and limit flags.
- Completed traces expire after 15 minutes. They are not a permanent traffic database.
- Events distinguish session, direction, listener, timing, origin, original chunks,
  parsed frames, validation outcomes, request association, profile probes and reads.
- Exchange failures include elapsed time and stream bytes received during the
  exchange where available. These counters do not prove where a request/response
  was lost. Cumulative poll/settings errors remain visible even when issue records
  are coalesced. A valid telemetry snapshot with failed settings is not counted as
  a fully successful polling cycle.
- The source allowlist is applied before reading a rejected peer's payload. Reports
  may describe rejection metadata but do not bypass admission to capture its bytes.
- Capture uses the existing owner. Enrolled devices reuse polling evidence; extra
  verification reports busy rather than interrupting a command. Recognition has its
  own bounded read plan, described in [profile expansion](../PROFILE_EXPANSION.md).
- Diagnostic probes send no inverter writes, module resets, UART changes or clock
  adjustments. Observed user/background operations retain their distinct origins.

## Persistent passive incident recorder

`core/incidents.py` receives the same original session events independently of an
explicit two-minute compatibility capture. `IncidentRecorder.observe()` performs
bounded in-memory work only; fault hooks enqueue a coalesced snapshot to the existing
SQLite worker. Admission in `Storage.async_call()` never blocks the event loop on
the synchronous worker lock. Initial-load cancellation and writer failure cannot
leave a flush waiting for a nonexistent task.

The additive diagnostic tables `incident_state` and `incident_records` use incident
schema 1 and do not change ledger schema 4 or command recovery. Unknown diagnostic
schemas are not overwritten. There is one pending and one in-flight snapshot;
serialization and archive generation run off the event loop. Backup freeze retries
are bounded and do not recursively produce incidents.

The recorder retains 60 seconds / 512 KiB / 2048 events, up to 32 device/fingerprint
groups and 16 MiB of serialized samples, at most three samples per group. The first
sample is queued immediately; a ten-second tail is added afterward. Restart retains
saved evidence, counts, recording preference and UTC watch expiry. Raw recording
never schedules a probe or operation. Durable command readback mismatch is captured,
and a later healthy poll never marks command uncertainty recovered.

Fingerprint revision 1 includes normalized error/stage/profile/transport and native
function/register/count/exception/response shape. It excludes device identities,
IP, PN, TID, timestamps and changing measurement values. Latest firmware/model
metadata is separate. The local known-symptom catalogue and user-initiated GitHub
search do not perform network lookups or automatically open issues.

Exports reuse the compatibility archive schema and validator. Raw bytes require an
explicit choice. Session/source references are remapped; only whitelisted event
fields enter sanitized exports. Original continuous segments have separate replay
session aliases across gaps: truncated samples must never be stitched into a
fictional CRC-valid packet. `capture_gap` and `context.capture_continuity` explain
missing data. Original dialect metadata can be supplied as `context_only`.
Each sample retains its immutable `capture_build`; top-level build identifies the
exporter, explicitly labeled in context/analysis. Old samples without capture build
remain unknown, rather than acquiring the current build after an upgrade.

The administrator-only `solar_inverter_bridge/incidents` WebSocket API exposes
status, configure, watch/cancel, delete, download and separate per-feature feedback.
It changes no inverter setting. Neither diagnostics nor feedback is automatically
uploaded. Manual legacy compatibility collection continues independently.

## User workflow and export

The panel offers collection from setup and device views. Users can supply exact
model/firmware/endpoint information, symptoms and optional display readings with
time/units. Unknown fields do not block a partial report. Local findings explain
coverage and missing evidence before download.

One ZIP contains `README.txt`, `report.json`, `analysis.json`, `timeline.jsonl`,
`observations.json`, a manifest with file hashes and, if requested, original wire
evidence under `protocol/`. The issue summary identifies the report and build.

Ordinary exports omit raw bytes and household identities/addresses. Original
unknown bytes cannot be guaranteed anonymous: **Include raw protocol exchange**
is an explicit export choice and may reveal hardware identifiers or network settings.
Validation facts refer to original data, not a silently repaired CRC or reconstructed
capture. User-entered descriptions are included and should be reviewed before sharing.
No report is automatically uploaded; no support destination is configured locally.

## Analyzer and developer replay

`core/compatibility.py` implements deterministic findings for network admission,
session framing/correlation, identity, payload/map, proposal coverage, reference
differences and control capability. Findings contain evidence references, observed
facts, hypotheses, missing evidence and the next action. They do not install a new
profile, infer arbitrary register meanings or enable control automatically.

```bash
python3 tools/replay_compatibility.py path/to/compatibility-report.zip
```

Import validates archive member names, sizes, schema and hashes. It never extracts
archive paths, executes bundled code or contacts a collector. Replay reassembles
bounded binary frames and ordered raw-AT replies, validates original requests and
responses, and can reconstruct implemented Modbus/ASCII profile measurements.
Late replies, incomplete data and unassociated tails remain explicit. Decoder work
is capped; excluding raw bytes yields semantic-only replay, not wire-validity proof.

`tools/exercise_binary_report.py` creates a synthetic failure package and replays
it after stopping its peer. That tool writes ZIP files; do not run it when a task
prohibits generating archives. Tests and evidence levels are described in
[testing](testing.md) and [verification](../verification/README.md).
