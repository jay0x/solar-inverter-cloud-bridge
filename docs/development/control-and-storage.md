# Control policy, durable operations, and storage

## Full control and effective availability

Implemented writable settings are available by default under one full-control
policy. Effective availability is determined by the field, transport, current
readings and profile acceptance.

All manual command interfaces require an active HA administrator context. A missing
user context does not authorize an external system caller. Native entities, services
and WebSocket commands share the same executor rather than separate write paths.

Effective editability requires a supported field/transport, fresh
current-session evidence, no unresolved operation, and a valid baseline. Inferred
profiles additionally require explicit permission bound to their definition digest,
observed signature and route. Read-only diagnostic probes never grant that permission.

Unknown manufacturer limits do not make an otherwise known R/W field hardware R/O.
It remains editable with a warning, exact scale/step checks and known dependencies.
For example, a documented 0.1 A step encodes 12.5 A as 125 without rounding. Unsigned
register bounds describe the wire format, not a recommended operating range. The
reference map's registers 605 and 636 are hardware read-only; register 643's zero
sentinel means full recovery rather than a zero-volt target.

## Command lifecycle

```text
in-memory request -> durable accepted intent -> durable send claim
  -> write/ACK -> independent readback -> completed
                      |
                      +-> uncertain / unresolved -> read-only reconciliation
```

- A caller-owned operation ID binds the device and immutable request. Repeating it
  returns the stored outcome, even offline or after a permission change; it never
  means "send again." Reusing it for another request is a conflict.
- Fresh identity/profile/settings and the caller's observed baseline are checked
  before sending. Policy revisions catch permission changes, including round trips.
- A possible send followed by timeout/disconnect/cancellation remains unresolved.
  A late ACK cannot answer another transaction. New writes on that device are blocked.
- Reconciliation reads current values, retains the original outcome and records
  its resolution separately. An administrator may explicitly keep a fresh different
  value without sending a replacement write.
- Reconnect/restart never replays accepted work. Unsent work becomes `not_sent`;
  possible-send work remains unresolved. No backup restores physical inverter state.
- Readback confirms the reported parameter, not a physical transfer, charging effect,
  sound, relay movement or other hardware outcome.

Source-defined FC06/FC16 and PI30, PI30 MAX, PI18 and G-ASCII writes use these same boundaries.
There is no arbitrary register/ASCII command API. See the
[profile matrix](../PROFILE_EXPANSION.md) for implemented controls and opt-in behavior.

Masked writes durably retain the full read-modify-write word, including unrelated
bits. PI18 paired-voltage commands retain the exact command and both expected
readbacks; the nominal battery voltage is also checked when observed. Reconciliation
uses that saved plan rather than rebuilding a command from new settings. A target
match with a companion mismatch remains unresolved. ACK alone is never success.
Device-queried current choices and documented voltage choices are checked after
fresh preflight; UI and native attributes show engineering units, not raw words.

PI30/PI30 MAX dialect replacement requires an explicit proposal and renewed
acceptance. Shared control IDs are retained, options refresh in place, and extra
measurement entities are added. No case-based write retry or automatic dialect
fallback is performed. Accepted-profile digests include the setting/telemetry grammars.

## Storage ownership and limits

| Owner | Data |
| --- | --- |
| Config-entry options | Allowed network sources and bootstrap preference |
| HA registries | Display names, areas, labels and entity overrides |
| Recorder | Measurement history and statistics |
| Bridge SQLite | Enrollment, policy revision, polling/maintenance preferences, operations, qualified routes, profile acceptance, removal markers and bounded issues |
| Memory | Current observations, generations, TIDs, futures, locks and bounded capture jobs |

The database is `solar_inverter_bridge/bridge.sqlite3` under the HA configuration
directory. A single worker owns its connection, with WAL and `synchronous=FULL`.

Config-entry options also store per-device connection preferences in
`collector_connections`. They contain private collector/callback addresses, not
write permissions. Callback reconnects are pinned to the ledger's collector identity.
Network bootstrap never replays an inverter setting command.
The administrator-only `set_connection` WebSocket command edits an existing device
under its command/stream ownership guards. Preferences persist through HA's
config-entry API; no direct `.storage` write or enrollment replacement is involved.
Connection attempt UUIDs are bounded runtime deduplication, not durable inverter
operation IDs. Collection pause uses the existing `enabled` field; the retained
`poll_interval` field now accepts whole seconds 1–300 and denotes a post-cycle pause.

Periodic settings reads are separated from telemetry: at least 30 seconds between
complete settings reads on the same session. Reconnect, profile renewal and writes
invalidate reuse. The settings observation timestamp is not advanced by telemetry
alone. Every command retains its own fresh identity/settings preflight and readback.
Panel status and native controls share `settings_freshness()`: only the current
verified session's full group or a fresh individual readback authorizes its observed
baseline. Individual readbacks do not renew the full group's clock/settings timestamp.
Settings expiry signals are independent of telemetry expiry. Native entities keep
unresolved checks in the executor and cache the barrier for presentation through
async synchronization, never blocking entity properties with SQLite I/O.

Protocol 4 clock setters are implemented for `modbus_protocol_4` and accepted
`smg_4` on AT and binary. Clock readback permits three seconds of error after accounting
for elapsed time since send intent, independently of the 1–300-second polling pause.
The minimum correction threshold is a separate 60-second policy; no upper drift
limit prevents correcting a valid old clock. Binary collector reset is not implemented.
Failed integrity checks refuse startup. Do not edit HA-owned `.storage` files.

Current software bounds: 16 saved devices, 100,000 retained operation IDs, 16 queued/
active command callers per device, 64 overall and a 64-job database queue. UUIDs are
not automatically purged to bypass deduplication. Journal export is paginated.

The ledger uses schema 4. It stores qualified routes, definition-bound profile
acceptance and the full-control policy (`control_mode: full`). There is no public
mode-setting action or WebSocket command. Updates must preserve enrollment IDs,
maintenance preferences and unresolved operations. Database downgrades require a
compatible, consistent backup; unsupported schemas are rejected.
The optional incident recorder has additive schema-1 diagnostic tables on the same
worker. Its samples, recording preference and watches do not authorize writes or
alter operation outcomes. Counts are bounded independently of the command journal.
Changing a qualified route or permission increments policy revision. Same-profile
binding renewal is explicit and retains HA IDs; unresolved work blocks replacement.

## Backup and maintenance

The HA backup hook checkpoints WAL and freezes the bridge writer during copying.
The polling scheduler waits through the database freeze and resumes from fresh
enrollment data afterward; a temporary backup refusal must not terminate it.
New writes are refused during the freeze. Restore only a consistent ledger/sidecar
checkpoint; old code refuses a newer schema. The software freeze/copy/recovery
tests do not establish a completed Supervisor archive restore on hardware.

Optional clock sync and Wi-Fi recovery obey saved policy and transport capability.
Clock targets are recomputed after preflight and persisted before send. Automatic
recovery reserves an attempt durably before reset and retains its cooldown through
restart/re-enrollment. They are not part of diagnostic recognition and do not form
a user automation or energy-optimization engine. User-facing behavior is in
[installation and operation](../INSTALL.md).
