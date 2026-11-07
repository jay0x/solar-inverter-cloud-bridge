# Install and operate Solar Inverter Cloud Bridge

This is a development candidate, not a published HACS release. The integration runs
inside Home Assistant Core. It does not require a Supervisor app, MQTT, or a separate
frontend plugin. The current target is Home Assistant Core 2026.10.4.

Read [Ports, collector protocols, and inverter profiles](PROTOCOLS_AND_PROFILES.md)
for the current support matrix and experimental binary limitations. The reference is included
in the manual-install ZIP and maintained with the GitHub source.

The [profile guide](PROFILE_EXPANSION.md) describes recognition and the implemented
settings. Candidate 0.8.2 includes the 0.8.0 protocol expansion and the new product
name; the completed 24-hour observation baseline is 0.4.0. An installation archive
has not been built for this candidate. Cloud branding does not require a cloud
account or change the integration's local operation.
The [named-model and family register](DEVICE_COMPATIBILITY.md) includes experimental
and unresolved devices with sources and transport qualifications. If the standard
read-only check fails, bounded recognition tries available families. Review the
proposal and preview before explicitly accepting it. Since 0.6.0, acceptance covers
readings and implemented writable settings together. There is no separate control
enable switch or mode selection. Acceptance itself sends no setting command.

## Install the local candidate

1. Keep a backup of an existing installation before replacing files.
2. Copy `custom_components/solar_inverter_bridge` from the reviewed source tree into
   your Home Assistant configuration directory. If using an explicitly published
   manual-install ZIP later, extract that same directory. Do not copy tests or private files.
3. Restart Home Assistant, then add **Solar Inverter Cloud Bridge** from
   **Settings → Devices & services → Add integration**.
4. The detected Home Assistant LAN subnet is prefilled as the allowed source.
   Review or narrow it to the collector's source IP or the router's source IP if it translates
   addresses. Comma-separated IPs and CIDR networks are supported. An empty list
   rejects new connections. If HA has no unambiguous LAN interface, no subnet is
   guessed. Network options can be edited later; saved choices are not overwritten.
5. Open **Inverters** in the sidebar and choose **Connect your first inverter**
   (or **Add inverter** when you already have one). Name the device. The configured
   allowed network is shown; expand the network option only to add a different source.
6. Continue to connection. If the collector is already listed, choose the highlighted
   **Use this connection** button. Otherwise, open Router setup. Configure local DNS and, if necessary,
   route its outgoing TCP ports **502, 18899 and 38899** to this Home Assistant. Select
   its new connection. Choosing **Use this connection** starts the read-only check
   automatically. Unknown profiles are presented for explicit review and acceptance.
7. Review the name and profile, then choose **Add inverter**. It starts in
   full control of implemented writable settings, with clock sync off. Router help and diagnostic tools remain
   available in expandable sections without interrupting the main setup sequence.

The bridge receives the collector's connection; it does not discover or reconfigure
your router. An inbound Internet port forward is not the local redirect required here.
Only one bridge may poll a physical collector. All three listeners recognize AT
and binary independently of the port. AT port 38899 keeps heartbeats but remains
passive for inverter reads/writes. Closing the secondary connection can cause
some collectors to reconnect both channels.

The Home Assistant server must expose the collector's listener port. All three
ports have bound on the test HAOS VM; partial failures are shown separately. Other container/network layouts still need
their own verification.

### HACS installation after publication

The repository is `https://github.com/jay0x/solar-inverter-cloud-bridge`.
It has not been accepted into the default HACS catalog and has no published release.
After its validation checks pass, the development branch can be tested as follows:

1. In HACS, open **Custom repositories**, add the repository URL and choose
   **Integration** as its category.
2. Download **Solar Inverter Cloud Bridge** and restart Home Assistant.
3. Add the integration and configure the collector as described above.

HACS installs the component directory from the repository; a custom release ZIP
is not required. Inclusion in HACS's default catalog is a separate submission.
Home Assistant Core 2026.10.4 remains the tested minimum.

### Updating an existing installation after the rename

Keep the existing `solar_inverter_bridge` integration and its data directory.
The default config-entry title updates to Solar Inverter Cloud Bridge; a custom
title is preserved. The sidebar remains **Inverters**, and existing entity IDs,
service names, panel URL, device names, ledger and Recorder history are retained.
There is no need to remove and re-add the integration.

## Use the interface

- **Overview:** live solar power, battery charge, output load, and operating mode.
- **Sensors:** current HA sensor values and native Recorder history.
- **Configuration:** clock sync, recovery, documented parameters, search, and
  inline editors. Each row has a name and one value. Click the value to edit;
  Apply appears only for a valid change. A lock identifies hardware read-only fields;
  an empty fixed-width slot keeps editable values aligned. Fields with undocumented
  manufacturer limits use a warning in the same slot.
- **Connection:** pause/resume polling, interval, and allowed network sources.
- **Activity:** operation results, connection health, and redacted diagnostics.

The home-card Configuration button opens configuration directly. The same local brand mark
is shown in the panel and Home Assistant's integration card.

The UI uses Home Assistant theme colors and supports narrow mobile screens.
Drafts and pending request IDs survive a browser reload. Background status updates
do not replace an active input or dropdown, including inside HA's Shadow DOM.

Implemented writable settings are available by default, without a mode selector.
Only hardware read-only fields are classified as read-only. Known R/W fields with
undocumented manufacturer limits are editable with a warning. Their
register format and step are validated; the wire range is not a manufacturer
operating range. Known documented bounds and dependencies remain enforced.
All 51 Protocol 4 fields remain
visible. Unknown native values are not replaced with invented values. Fresh readings,
supported commands, accepted profile evidence and unresolved-operation checks still apply.

Changing a parameter creates a durable operation ID and waits for native readback.
If the observed baseline changed while you edited, the draft is kept and the request
is rejected. After an uncertain response, use **Check result**. The page never
automatically replays a write after reload. An explicit retry uses the same ID.
If a different value is confirmed by a fresh read, **Keep current value** can close
the request without resending it. The original outcome remains in the journal.

Clock sync is off by default, requires its own enable switch, and uses HA's local time zone.
Corrections larger than five minutes are refused. A later readback may resolve an
uncertain clock operation by comparing its expected elapsed time; it does not erase
the original uncertainty.

The actual clock target is recomputed after preflight and durably saved before
transmission. If it becomes stale while waiting for storage, it is not sent.

## Remove an inverter

Open **Connection → Remove inverter** and confirm its name. This removes the saved
enrollment and bridge-owned HA entities, not the inverter's electrical settings.
Pending/uncertain operations must be resolved first. The operation journal remains
retained; the integration does not run a Recorder purge. HA's retention settings
continue to govern history. Adding the collector again requires a new read-only
check and creates a new bridge device ID with implemented controls available.

## Diagnostics

**Compatibility and discovery → Collect compatibility report** works from the
main page and every setup/device view, even before enrollment. Enter any known
model, firmware, original endpoint, symptom and optional display/app readings.
Start collection, reconnect the collector to capture startup, and analyze before
downloading the ZIP. No diagnostic write/reset is sent. Established devices reuse
polling; an unidentified known-family candidate gets bounded read-only verification.
The analyzer separates network, session, identity, payload and map evidence and
shows missing startup or truncated data. Copy the issue description with the package.

**Include raw protocol exchange** is an explicit export choice. Original bytes may
contain hardware identifiers or network settings; review before public sharing.
Without original chunks, unknown framing/identity failures may not be reproducible.
Collection lasts at most two minutes (4096 events / 4 MiB wire budget), with a
15-minute completed-trace retention. Nothing is automatically uploaded.
Advanced Auto/AT/Binary bootstrap preference applies only to new connections on
all ports. Use it for silent collectors; it does not prove a model or merge devices
sharing a NAT address. Per-port bind status is visible without starting collection.

Download diagnostics from Activity or the native HA integration page. Reports
include cached telemetry, decoded parameters and their named raw register values,
HA sensor states, channel roles, storage/queue limits, recent operation results,
and the last 32 timestamped issues with protocol context. They do not initiate new
device reads. Credentials, names, source addresses, identities, and raw frames are
omitted. Activity displays error times in Home Assistant's configured time zone.

## External actions

All actions require an active HA administrator context. A missing user ID does not
authorize a system caller. External clients can use a normal administrator token;
the bridge does not issue separate control keys or implement an automation engine.

- `solar_inverter_bridge.set_clock_sync`: `device_id`, `enabled`.
- `solar_inverter_bridge.apply_parameter`: `device_id`, `key`, `value`,
  `operation_id`; optional `expected_value` for baseline conflict detection.
- `solar_inverter_bridge.get_operation`: `device_id`, `operation_id`; read-only response.

Here `device_id` is the bridge enrollment UUID returned by its status/enrollment
API, not the Home Assistant device-registry ID. Supply one stable operation ID per
intent. Reusing it for a different device or payload is a conflict. Retrying the
same ID returns its record even if the collector is offline or permissions changed.

Equivalent admin WebSocket commands are under `solar_inverter_bridge/`:
`status`, `verify`, `enroll`, `set_clock_sync`, `apply`, `get_operation`,
`configure_network`, `set_collection`, `remove_device`, `diagnostics`,
`check_operation`, `accept_current_value`, and `compatibility`. The latter accepts
`action: start|stop|status|download`, optional description `metadata` and explicit
`include_raw` (default false); download returns a ZIP as base64 with its filename.
`configure_network` also accepts `bootstrap_preference: auto|at|binary`.
`apply` requires a caller-owned ID.
`get_operation` reads the journal; `check_operation` can perform read-only native
reconciliation for an uncertain result.

## Data, backup, and update

Saved enrollment, maintenance preferences, and operations live in
`solar_inverter_bridge/bridge.sqlite3` under the HA config directory. That file is
the only authority for command policy and the operation journal. Sensor history
belongs to Recorder. Display names and areas belong to Home Assistant's device
registry; renaming a device there does not require editing the bridge database.
The config entry stores allowed collector sources and an optional bootstrap preference. Do not edit HA's `.storage`
files. A database that fails `quick_check` is not opened.

Version 0.3.0 upgrades the bridge ledger from schema 1 to 2, adding only qualified
logical routes. Device/entity IDs, names, modes, clock/recovery preferences and
unresolved operations are retained. A changed route increments policy revision;
it does not replay commands. Keep a consistent pre-upgrade backup: old 0.2 code
refuses schema 2, so reverting files alone is not a database downgrade.

Version 0.4.0 upgrades to schema 3, adding explicit profile acceptance and control
permission. The stored binding includes a digest of the map/control definitions,
observed signature, transport and route. Changed evidence refuses execution and
requires a fresh reviewed binding; permission changes increment policy revision.
Existing baseline devices and unresolved operations are preserved. Keep the
consistent pre-upgrade backup for any downgrade; older code refuses schema 3.

Version 0.6.0 upgrades to schema 4 and retires Monitoring/Control/Advanced modes.
Existing accepted profiles gain the same full-control policy as new devices;
their identity/definition binding is retained and still checked before writing.
Maintenance preferences, device IDs and parameter entity IDs are preserved. The
obsolete HA control-mode selector and `set_mode` action are removed. Existing
automations calling that action should remove the obsolete mode-setting step.
No command is replayed by migration. Downgrade requires the consistent pre-upgrade
ledger backup; older code refuses schema 4.

Home Assistant's backup platform calls this integration before and after copying
config. The bridge checkpoints its SQLite WAL and freezes its own writer for that
copy, so `bridge.sqlite3` and any sidecars in the archive are one checkpoint.
New bridge writes are refused with `storage_backup_in_progress` while the freeze
is held. An accepted operation that has not claimed send is finished as `not_sent`
and is not sent later. A possible send stays unresolved and is never replayed.
A stopped Core can still be copied manually, including WAL sidecars. Restore only
a mutually consistent checkpoint. An older database cannot preserve deduplication
for operations it never contained, and no backup restores physical inverter settings.

The current software limits are 16 saved devices, 100,000 retained operation IDs,
16 waiting/active command callers per device, 64 overall, and a 64-job DB queue.
UUIDs are not automatically deleted: reaching capacity refuses new writes but keeps
existing results. An administrator can download the journal in pages. That export
does not purge IDs. Identical faults are persisted at most once a minute.

## Evidence and remaining validation

Protocol 4/model 32771 has live read evidence on the test VM. Other model signatures
are not automatically admitted. The 16-device test is synthetic, not a claim of
hardware validation for 16 installations. Parameter writes, loss of reply, cancellation,
and restart boundaries are tested with simulators. Electrical/schedule writes have
not been exercised on the operating inverter by this acceptance session.
Binary EyeBond and additional Modbus/PI30/PI18/G-ASCII profiles are source-derived
and simulator-tested, without new local hardware qualification. The original exact
gate remains 4/32771. Other profiles are offered after read-based recognition and
require explicit acceptance. The profile warning/acceptance covers implemented
source-defined controls, including on binary FC4. Binary clock/reset remain
unsupported; AT reference control remains available under its existing guards.

See `docs/verification/README.md` in the source repository for the dated evidence summary.
A 24-hour run on an unchanged candidate and broader hardware qualification remain
separate qualification work. Public development source is not a published stable release.
Configure DNS and any necessary TCP routing using the
[bundled router guide](../custom_components/solar_inverter_bridge/frontend/routers.html),
also linked from Add inverter. See [DNS and routing](PROTOCOLS_AND_PROFILES.md#3-dns-and-routing).

The router guide now starts with an address form and generates copyable commands.
In **Connect the collector**, a prominent **Router setup** button opens that form.
The highlighted **Collector domains** section shows the shared domain catalog
before the DNS-server reminder. The guide displays **`*.eybond.com`** as an explicit
unchecked wildcard with six indented exact names. Enabling it disables those exact
choices; disabling it restores their selections. See [the domain reference](PROTOCOLS_AND_PROFILES.md#collector-domains)
for sources and protocol differences. Both pages use the same bundled JSON list.
Known HA interface addresses, gateway, resolver, and actual network mask are suggested;
unknown values require input. Choose DNS-only first, or add source-scoped TCP/DNS
interception when needed. You can leave the individual collector IP unknown and
use shared subnet rules. Select collector domains individually or use Select all.
The integration does not execute the generated router commands.
All router recipes match the selected source IP or subnet directly, without
source address-list aliases or split CIDR ranges. If DNS interception targets an
external resolver, its own queries bypass that redirect.

Interface/zone inputs are optional under Advanced: MikroTik/Linux use IP-scoped
rules when empty; OpenWrt/pfSense/OPNsense use standard `lan` with a visible note.
Override them for VLANs or nonstandard zones. Ensure the collector actually queries
the DNS server where these records are added. Set that resolver through DHCP or the
collector's network settings and reconnect, or use DNS interception when necessary.

Switching requires a new TCP session. Restart the collector's Wi-Fi module through
its app if available, or reconnect Wi-Fi; router restart affects other devices.
Reserve the collector's DHCP lease for IP-specific rules. With DNS-only or shared
subnet rules, changed IPs are less significant: Bridge recognizes native identity,
but the new address must still pass its allowlist.

## Native Home Assistant controls and recovery

The Bridge inverter tabs are **Overview**, **Sensors**, **Configuration**,
**Connection**, and **Activity**. Configuration replaces the former Settings label;
existing `/settings` links continue to work.

**Sensors** lists the device's real HA sensor names, entity IDs, current values,
and units. Select **History** to open HA's native entity dialog and Recorder graph.
Recorded data follows your Recorder inclusion and retention configuration. Offline
sensors can still show previously recorded data. Disabled entities without a live
HA state are marked as disabled. If Recorder is not loaded, **Details** opens
the entity dialog and the panel explains that history requires Recorder.

Open an inverter in the Bridge panel and select **Home Assistant entities** in its
header. The link opens that inverter's native HA device page, where its sensors and
controls are available for dashboards and automations. It is present on every
inverter tab.

The device page exposes select, number, and time entities for executable settings,
plus switches for automatic clock sync and Wi-Fi recovery. They share the panel's
executor, administrator checks, baseline validation and command journal. Values are
read back, not optimistically set. Supported controls need no unlock step. Missing
readings, unsupported transport writes or changed profile evidence can still make
controls unavailable. Inferred profiles require explicit profile acceptance; only
their own fields/entities are created. Maintenance preferences stay configurable;
the panel explains that binary clock writes and recovery are paused. Use the Bridge
panel to inspect all parameter readings even when editing is blocked.
Undocumented numeric bounds represent wire format only. The number entity for full
recovery uses 0 for that special value.
Hardware read-only fields are not writable controls. Date/time correction stays
with the existing automatic clock-sync feature.

Automatic Wi-Fi recovery is off by default. It may reset the connected module after
no complete readings for at least 5 minutes and three polling intervals, at most
once per hour. The attempt is saved before sending, including timeouts; the cooldown
survives HA restarts and re-enrollment of the same collector. It is paused while
polling is disabled and while commands remain unresolved.
It cannot send a reset to a disconnected module or fix a missing DNS route.
