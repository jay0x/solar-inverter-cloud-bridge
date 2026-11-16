# Install and operate Solar Inverter Cloud Bridge

The current source candidate is 0.9.0; consult release notes for tagged-release features. The integration runs
inside Home Assistant Core. It does not require a Supervisor app, MQTT, or a separate
frontend plugin. The current target is Home Assistant Core 2026.10.4.

Read [Ports, collector protocols, and inverter profiles](PROTOCOLS_AND_PROFILES.md)
for the current support matrix. The reference binary and AT paths are included
in the manual-install ZIP and maintained with the GitHub source.

The [profile guide](PROFILE_EXPANSION.md) describes recognition and the implemented
settings. Installation is available through HACS or the
reviewed source tree. Collector communication runs locally without a vendor-cloud account.
The [named-model and family register](DEVICE_COMPATIBILITY.md) includes experimental
and unresolved devices with sources and transport qualifications. If the standard
read-only check fails, bounded recognition tries available families. Review the
proposal and preview before explicitly accepting it. Acceptance covers
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

### Local callback and connection selection

The Connect step offers **Automatic**, **Local connection (UDP callback)** and
**Redirected cloud connection**. An IP is optional in Automatic: with an IP it
requests a local callback; without one it waits for an incoming redirected connection.
Callback requires the Wi-Fi collector's private IPv4 address. Existing installations
are not automatically switched to callback.

The default bootstrap sends `set>server=<HA IPv4>:8899;` to collector UDP 58899.
The collector then connects to HA over TCP. The callback does not subscribe to UDP
telemetry. Both reads and supported writes use the negotiated AT/binary TCP session.
Entering an IP does not by itself enable or disable settings.

The HA callback address must be a local HA interface address. TCP and UDP ports can
be overridden in Callback network settings. The source allowlist still applies,
and the observed TCP source must match the collector IP. Address-translating NAT
callback paths are not qualified by this implementation. Use redirected connection
setup for those paths.

A request has a 120-second connection window. Repeating a retained attempt ID does
not resend; a visible Retry connection action creates a new attempt. Attempt IDs
are bounded runtime state, unlike the durable IDs used for inverter writes.
Saved callback devices retry only while collection is enabled and disconnected,
at most once per 120 seconds. A full-identity mismatch blocks automatic attempts for
that runtime. Review the collector identity rather than accepting a different device.
The connection preference is saved with the HA config entry after enrollment.

For an existing inverter, open **Inverters → your inverter → Connection → Connection
method**. Select Automatic, Local connection (UDP callback), or Redirected cloud
connection; supply the collector IP and, if needed, the callback network fields.
Select **Save connection**. You do not need to remove or enroll the inverter again:
its identity, entities, names and history are retained.

Saving waits for the current polling exchange and serializes with commands. An
unresolved operation must be resolved first. The selected channel becomes the sole
inverter I/O owner; other connected channels can remain heartbeat-only. Local callback
selects the configured source IP and TCP port and checks the same full collector
identity. Redirected mode selects a non-callback channel and still requires DNS/router
routing to this HA. Automatic retains a usable owner and requests callback only when
disconnected and an IP is provided. A saved preference or sent UDP request is not
proof of a working connection; check the active port and fresh readings.
The collector IP is retained when switching to a redirected connection and is not
used for callback until Local connection or Automatic with that IP is selected again.
Readings, supported setting writes, and clock sync work on AT and Binary EyeBond.
Restart Wi-Fi module is an AT command. It is unavailable on Binary EyeBond, including
the confirmed local callback. A redirected connection normally negotiates AT and keeps
that command. The connection step and Configuration page state this limitation.

With **Collect readings** unchecked, saving only stores the connection preference
and does not send a callback. Enable collection to resume polling and automatic
callback attempts. An expired or failed attempt has an explicit **Retry connection**
action; browser reload does not resend it.

Callback may affect an existing vendor-cloud session depending on firmware. The
software uses a single inverter owner and does not run a parallel callback poller.
That ownership lock is local to one runtime; it cannot coordinate another HA or a
vendor cloud. On the reference Wi-Fi.DTU 8.50.12.3 / AT 1.11 collector, binary callback
readings and reversible display-setting writes were verified without redirecting DNS
to the callback receiver. A passive redirected connection plus active callback also
worked. Here, passive means TCP/heartbeats with collection disabled, not native
inverter polling or writes. Simultaneous command workflows on both connections
produced a preflight timeout and are not supported as a two-controller setup.
These tests used another Bridge as the redirected endpoint, not the vendor server.

Callback heartbeat scheduling is capped at 20 seconds to keep an otherwise idle
connection alive. This does not change TCP transaction deadlines. There is no
automatic callback-over-cloud priority switch in Automatic mode; choose Local
connection explicitly to select the callback path.
See the source repository's
[verification guide](https://github.com/jay0x/solar-inverter-cloud-bridge/blob/main/docs/verification/README.md)
for the hardware scope and timings of its documented candidate.

### Polling cadence

**Pause between polls, seconds** accepts whole seconds from **1 to 300**. The pause
starts after a completed telemetry cycle. A 10-second cycle with a 1-second pause
starts the next cycle about 11 seconds later, with possible scheduler delay. Polls
for one inverter never overlap and missed starts do not accumulate in a queue.
Existing saved values are retained; the API/storage key remains `poll_interval`.

Settings refresh
on the first poll of each connection, then at least 30 seconds apart (or the telemetry
interval if longer), and after writes or profile renewal. A skipped settings read
does not refresh its timestamp. Commands always read fresh identity/settings before
writing and independently read back afterward. Clock synchronization uses only a
new clock reading, not a cached clock value. TCP transaction timeouts are unchanged.

**Collect readings** is a per-inverter pause switch. Unchecking it stops regular
polling, automatic callback attempts and new inverter-setting writes. An exchange
already in progress may finish. Existing sockets may retain heartbeats. This does
not stop the physical inverter, remove its entities or delete Recorder history;
current telemetry is presented as unavailable while collection is paused. Use it
for maintenance or when another controller is responsible for polling.

### HACS custom-repository installation

The repository is `https://github.com/jay0x/solar-inverter-cloud-bridge`.
It has not yet been accepted into the default HACS catalog.
GitHub tests, Hassfest and HACS validation pass for the reviewed candidate.
Installation from the development branch was verified using HACS 2.0.5 on HA 2026.10.4:

1. In HACS, open **Custom repositories**, add the repository URL and choose
   **Integration** as its category.
2. Enable beta versions for the repository to select pre-release `v0.8.2`, download
   **Solar Inverter Cloud Bridge**, and restart Home Assistant.
3. Add the integration and configure the collector as described above.

HACS installs the component directory from the repository; a custom release ZIP
is not required. Inclusion in HACS's default catalog is a separate submission.
Home Assistant Core 2026.10.4 remains the tested minimum.

### Updating an installation

Use HACS to update the `solar_inverter_bridge` integration, then restart Home
Assistant. Keep its data directory and config entry. Device/entity IDs, names,
maintenance preferences, the ledger and Recorder history should remain intact.
Check that the collector reconnects and produces fresh readings after the update.

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
It corrects any difference of **one minute or more**, including differences of several hours.
A shorter difference is ignored because reading the clock itself takes several seconds.
There is no upper limit. A later readback may resolve an
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
The config entry stores allowed collector sources, an optional bootstrap preference,
and per-device connection preferences. Do not edit HA's `.storage`
files. A database that fails `quick_check` is not opened.

The ledger uses schema 4. Profile acceptance binds the device to the map/control
definitions, observed signature, transport and route. Changed evidence requires
a new read check and explicit acceptance. Policy changes increment a revision;
they never replay commands. Keep a consistent backup before an update. Software
that does not support the saved schema cannot use that database; replacing code
alone is not a database downgrade.

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

## Updating an existing installation

Copy or download the reviewed source over the existing component, then restart
Home Assistant Core so Python changes load. A config-entry reload alone does not
reload Python modules. Enrollment IDs, entity overrides, polling preferences and
the operation ledger are retained. Existing devices remain on redirected connection
until an administrator explicitly saves another method.

After a HACS or manual update, also remove or replace stale precompressed siblings
such as `frontend/panel.js.gz` when their decompressed content differs from the new
source. Home Assistant can serve that sibling to browsers requesting gzip even though
the uncompressed file and its hash are current. Compare both uncompressed and
gzip-negotiated responses, as described in the testing guide. A browser reload or
version query string does not correct a stale compressed asset.

The panel highlights a save button only while its own section differs from the saved
values. **Save connection** and **Save collection settings** are independent: changing
the polling pause does not save the connection method.

## Evidence and remaining validation

Protocol 4/model 32771 has redirected-path and local-callback read evidence on the
reference ANENJI installation. Reversible display-setting writes were also verified
on both paths; electrical and schedule writes were not part of that acceptance.
Other model signatures are not automatically admitted. The 16-device test is synthetic,
not a claim of hardware validation for 16 installations. Loss of reply, cancellation,
and restart boundaries are tested with simulators.
Additional Modbus/PI30/PI18/G-ASCII profiles are source-derived
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

The inverter tabs are **Overview**, **Sensors**, **Configuration**,
**Connection**, and **Activity**.

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
