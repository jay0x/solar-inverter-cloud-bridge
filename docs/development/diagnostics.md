# Compatibility diagnostics and replay

Normal HA diagnostics provide redacted cached operational data. The richer
compatibility workflow also works before enrollment or when no profile matches.
It does not require a shell, cloud account or packet-sniffer privileges.

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
