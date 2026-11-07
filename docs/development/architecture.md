# Runtime architecture

The integration runs inside HA Core under one config entry. No collector or inverter
needs to be online for setup to complete when at least one listener can bind.

```text
Collector-initiated TCP (502 / 18899 / 38899)
  -> allowlist -> bounded dialect admission -> full collector PN
  -> single active inverter I/O owner
  -> payload/profile qualification -> observations and settings
  -> native HA entities / Recorder / bundled panel

Admin action / native setter / panel / optional clock service
  -> per-device policy and execution lock
  -> durable ledger -> send -> independent readback
```

## Transport and profile boundaries

- `core/transport.py` provides buffered AT and binary sessions. The binary reader
  owns frame dispatch; serialized requests use TID/function/route correlation.
- `core/binary.py` owns the EyeBond envelope. `core/framing.py` owns inner Modbus
  CRC/function/slave/length checks. Outer EyeBond FC4 is not inner Modbus FC04.
- `core/exchange.py` exposes owned reads/writes with whole-transaction deadlines,
  including write/drain backpressure and fragmented responses.
- `core/catalogue.py` and `core/drivers.py` define selected measurement/control
  subsets and payload decoding. `core/discovery.py` proposes profiles from read evidence.
- `core/smg.py` is the shared SMG variant registry: layout, protocol-specific
  measurement deltas and control subsets. Both the catalog and driver consume it;
  retail aliases do not select a map or implicitly inherit reference capabilities.
- `core/telemetry.py` supplies the canonical Protocol 4 definitions/decoder/read plan
  for both `smg_4` and retained `modbus_protocol_4` enrollments. Valid unsupported
  optional blocks fall back to documented common addresses; no zero-fill or guessed
  register sweep is performed. Shared setting blocks have illegal-address-only
  per-field fallback. `core/profile_catalog.py` owns family labels and deduplicated
  catalog presentation without renaming persistent device/entity IDs.
- `core/profile_layers.py` describes the selected common map, required extension
  and evidence state for proposals, status, catalog and diagnostics. Presentation
  metadata grants no capabilities. `catalogue.resolve_map()` applies source-defined
  MUST marker corrections in both live decoding and offline replay; the driver
  binds the effective definition before experimental control can be authorized.
- `core/session.py` owns admission, per-collector channels, verification, polling,
  capability policy and execution. A duplicate channel cannot steal an active owner.

All three ports share dialect detection. A port is a bootstrap hint, not identity.
AT on 38899 stays auxiliary; it is not promoted into another inverter poller.
Failed binds are reported separately while healthy listeners remain available.
All-listener failure refuses setup; no random fallback port is chosen.

The raw-AT adapter enforces a 50 ms receive-to-next-send gap inside the
absolute transaction deadline. Queued
unsolicited raw bytes are retained for evidence and invalidate the session rather
than being accepted as a reply to an unsent request. Binary sessions keep their
single-reader/TID dispatch and do not use this raw-session guard.

Binary framing uses `>HHHBB`, total length `6 + L`, with a 4096-byte cap. Pending
requests do not cross sessions. TIDs are not reused within a connection; exhaustion
retires it and waits for the collector to reconnect. Partial-frame timeouts do not
trigger guessed resynchronization. Full wire details and route budgets are in the
[protocol guide](../PROTOCOLS_AND_PROFILES.md) and [profile guide](../PROFILE_EXPANSION.md).

## Observations and entities

Only valid completed reads become observations. Reconnect, heartbeat, a UI refresh
or a single-setting readback does not refresh a whole measurement group. Unknown
or unavailable fields do not become zero. Telemetry expires after 60 seconds;
complete settings use `max(90 seconds, 5 * poll_interval)`.

Each saved profile defines its entity set and units. HA entity properties read
caches and do not initiate transport or database I/O. An expiry task publishes
availability even while another collector is timing out. Recorder owns history;
the Sensors tab opens native HA history for the actual registry entity ID.

HA registry names/areas/overrides are independent of the suggested enrollment
name in the ledger. Parameter controls intersect implemented profile capability,
explicit profile acceptance where required, and fresh session evidence. There are
no selectable control modes; supported writes are enabled by default.

## Lifecycle and concurrency

One runtime is kept in `entry.runtime_data`. Entry lifecycle owns servers, session
tasks, profile/capture jobs, expiry publication and subscriptions. Shutdown stops
new work and classifies possible sends before closing storage. A canceled database
waiter must not release its execution lock while a late commit is still running.

Per-device execution and per-stream locks have different roles. Apply and reconcile
serialize through the device lock; all wire users share the stream owner. One slow
or disconnected device must not block other devices or expiry publication.

For durable boundaries and schema upgrades, see [control and storage](control-and-storage.md).
For bounded reports using the same owner, see [diagnostics](diagnostics.md).
