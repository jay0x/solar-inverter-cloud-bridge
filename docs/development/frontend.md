# Frontend and native HA presentation

The bundled panel is plain JavaScript/CSS served by HA, with local HTML/JS for the
router guide. It uses authenticated WebSocket commands and does not require a CDN,
separate card, frontend plugin or framework build. Product strings are en-US.

## Navigation and editing

- Device tabs are **Overview → Sensors → Configuration → Connection → Activity**.
  The `/settings` route opens Configuration.
- The list opens device Overview; Configuration shortcuts open the settings view.
  **All inverters** and reselecting the sidebar item return to the list.
- Parameter rows show one observed value. Editing creates a draft; Apply becomes
  usable only for a valid change. Reserved space keeps Apply/Cancel/note geometry
  stable through editing, polling and reverting.
- Polling must not replace an active input/dropdown or steal focus through nested
  HA shadow roots. Drafts, caller-owned operation IDs and uncertain results survive
  reload. A lost response is not an automatic resend.
- Save buttons use the normal outline style when values match saved settings and
  the primary style while that section has changes. Reverting or successfully saving
  clears the highlight. Connection, collection, clock, recovery and network settings
  are compared independently, including during background refresh with an active input.
  Numeric formatting and reordered/duplicate source entries do not create false changes.
- Show the selected profile's full implemented inventory. Explain freshness and
  capability restrictions without inventing unsupported fields or control modes.
- Distinguish hardware-unverified implementations from missing wire commands. The
  Configuration view offers report collection without an extra control-mode gate.
  Current per-field readback freshness can keep one editor usable without labeling
  the entire settings group current. Binary reset is described as unimplemented,
  not as a proven hardware limitation.
- Profile acceptance covers its readings and implemented writable settings. A changed
  binding offers a fresh read-only recheck and reviewed proposal.
- Treat names, descriptions and reports as text, not trusted HTML.

## Profile composition

Panel 0.26.0 consumes the backend `profile_layers` description. Recognition,
enrollment review, Configuration, Connection and catalog details show the common
map separately from a required model extension and qualification evidence. A common-only candidate
uses **Use common map** without requiring an exact model name. Required corrections
and identity anchors have no independent toggle. Protocol 4 has one catalog entry;
the retained reference enrollment ID resolves to that same map. Read qualification
for 4/32771 is not a separate protocol or a retail-model identification. The catalog
groups SMG Classic/2024, SmartESS assets, MUST and Deye variants by family.

Display the selection basis and evidence state separately: a saved binding after
restart/offline/paused collection is not current verification. This presentation
does not enable control or change the existing acceptance/fingerprint contract.
Profile labels, change descriptions and native identifiers are escaped as text.
The available-profile catalog and each nested map-composition disclosure retain
their open/closed state across status refreshes, including manual collapse.

## HA entities and history

Use real entity-registry IDs and overrides. The Sensors tab opens native
`hass-more-info` history; it does not create a second history store. Recorder
configuration governs retention and exclusions. Offline sensors can still show
history; an entity without a current HA state cannot open more-info.

Overview metrics and At a glance rows use the same history action directly on the
reading. `ha_sensors` includes its stable measurement `key`, actual entity ID and HA
`entity_category`. Never derive a history target from a suggested entity name.
Diagnostic-category readings are rendered in At a glance for each profile. Home
device cards keep static metrics to avoid nesting metric buttons inside the card button.
History-link keyboard focus is retained across live refreshes.

Settings groups use explicit `Parameter.group` values where supplied; otherwise the
inventory resolves semantic keys with a neutral Other settings fallback. Presentation
grouping never mutates fields or definition fingerprints. Register ranges from
Protocol 4 must not classify low-address SMG, Deye or virtual ASCII slots.

Overview places **Recent changes** beside At a glance, replacing its former Inverter
settings shortcut. It has no standalone Cloud assignment operation card. Recent
rows retain outcomes, actors and timestamps; **Full journal** opens Activity's
command-journal section. Direct heading/paragraph/action sections use explicit
spacing and remain contained across 360/390/768/1440 px in both themes.

The **Home Assistant entities** link uses the actual HA device-registry ID, not the
bridge's enrollment UUID. HA's native device page has fixed entity categories;
an integration cannot create an arbitrary extra section header there. Parameter and
maintenance entities use the normal Configuration category.

## First-inverter setup

The empty home view has one primary entry point, **Connect your first inverter**.
The four steps are **Name → Connect → Check → Add**. The existing allowed network is
shown as already configured; adding another source is a disclosure, not a repeated
mandatory task. Saved network rules are retained.

Connect offers Automatic, local UDP callback and redirected connection. Collector
IP is optional in Automatic and required for callback. Advanced fields specify the
HA LAN address and ports. A connection-attempt ID is saved before sending; reload
does not resend automatically. Inverter verification and explicit enrollment remain
separate from callback bootstrap, and the connection choice persists after enrollment.

The device's **Connection** tab presents one column: read-only status, connection
settings, compact collection options, collapsed Advanced & maintenance and removal.
The **Change connection** flow has Method, Address, Review and Result steps. Callback
and Direct are primary choices; Automatic is under Advanced. Drafts and request IDs
are device-scoped and independent of the Add wizard. Navigation/closing the flow
does not save or send a connection request. Saving preserves
enrollment and registry IDs. Paused collection saves the preference without UDP.
Show the attempt result separately from the active connection and fresh readings.
**Pause between polls, seconds** accepts integers 1–300; retain `poll_interval` as
the API/storage field for compatibility. **Collect readings** explains that pausing
also blocks new setting writes and automatic callback attempts, while retaining the
inverter's operation, entities, history and possible TCP heartbeats.

When collectors are found, their cards and primary **Use this connection** buttons
come before router instructions. Choosing a connection immediately runs the existing
read-only check; a fresh verified connection can proceed directly to review. Enrollment
still requires **Add inverter**. A disconnected collector or expired verification has
an explicit recovery action. Unknown-profile proposals are scoped to the selected
collector and keep the warning, map composition and explicit acceptance.

All wizard blocks share one column. Direct children of `.setup-flow` have equal
width and a 24 px gap at desktop and mobile sizes. Router/DNS instructions and report
tools use disclosures; their open state survives status refresh. Focused inputs retain
their existing refresh protection, while a focused help summary does not stop new
connections from appearing. The home page's technical tools are collapsed initially.

## Cloud assignment editor

The Direct connection address step offers an explicit collector-server rewrite.
Keeping the existing server only changes the bridge preference after confirmation.
Address inputs/checks, risk review and results are presented in separate steps;
the Result step retains explicit recovery/Apply continuation after a lost response.
Advanced & maintenance also opens the saved-address restoration flow.
Host defaults to `homeassistant.local`
and port to 18899; discovered HA LAN IP and the server-saved return address are explicit
alternatives. Opening the page reads only journal state. Read/Check explicitly query
the collector. A successful destination/identity check is valid for one minute and
is invalidated by field edits; risk acknowledgement is scoped to that check.
Destination-check errors appear directly below the Check button, with `role="alert"`
and field descriptions pointing to that result. They survive status refresh, clear
when the address is edited or checked again, and are brought into view after the
explicit check. They are not routed to the page-level error banner.

Save and apply persists the write request ID in browser storage before sending and
starts a separately journaled Apply only after confirmed write/readback. Lost replies
never trigger an automatic retry, Apply or restart. Browser reload retrieves server
history without hardware commands; verified incomplete writes offer explicit Apply.
The original return address belongs to the server journal, not browser drafts.
Uncertainty checks and explicit keep-current resolution do not resend writes.

The editor distinguishes address readback, Apply acceptance and a new primary session
with the requested address. Callback users can explicitly select the direct connection
after Apply. It does not infer restart/power-loss persistence from these checks.
Recovery help explains callback/BLE/AP limits and why a restart is not rollback.
The final Add step offers review on Connection after enrollment, with no automatic
endpoint mutation. Tests cover lost replies, reload, saved-address restoration,
check/consent invalidation, escaping and 360/390/768/1440 layouts.

## Incident reports and compatibility feedback

The device's **Diagnostics** section lives in Activity; Connection links there with
the one-word **Diagnostics** button. Report tools open with **Reports**. Overview and
Configuration do not append the large report block. Pre-enrollment/global tools remain
available behind a collapsed Diagnostics disclosure on the inverter list and in setup.

Activity's **Command journal → Download full journal** exports all retained operation
records across devices, not raw TCP exchanges. Pagination is awaited sequentially;
the export count is fixed from the first page so concurrent new operations do not
extend the download indefinitely. It reports a failed/incomplete export instead of
silently stopping at 200 records. Browser verification downloads 405 records over
three pages. The maintenance journal may contain private values; sanitized diagnostics
are a separate export.

Activity and the compatibility tools expose the local incident recorder for enrolled
and bridge-level failures. Known recovered events remain counters/cards, not automatic
notifications. Unknown/unrecovered cards show available evidence and manual support
actions. Watch does not resume polling or change a collector connection.

Incident metadata drafts are scoped separately from user compatibility feedback.
Raw export is an explicit one-shot choice, reset on export or reload. GitHub links
are restricted to this repository's HTTPS issue paths; data/metadata are rendered as
text. Search and clipboard/download actions are user initiated. A feedback result
is user-reported evidence for its selected feature, not blanket model qualification.

## Network guidance

The add flow and router page share `frontend/collector-domains.json`. Use HA network
hints where available, not the browser hostname, an invented gateway or a guessed
subnet. DNS-only is the initial method. DNS interception starts unchecked; selecting
the optional EyeBond wildcard disables its covered children without losing their
saved choices. Recipes match explicit source IP/CIDR and preserve destination ports.
The UI generates text; it never executes router configuration.

## Visual checks and artwork

Use HA theme colors, readable value/unit distinctions, visible focus and controls
at least 44 px high. Check 360/390/768/1440 px, light/dark themes, long names, stale/
offline states, conflicting edits, unknown outcomes and empty installations.

`tools/generate_brand.py` independently draws the sun/lightning mark at 256 and
512 pixels. Native HA and the panel serve the same local assets. Reference material:
[HA Brands specification](https://github.com/home-assistant/brands#image-specification)
and Lucide [sun](https://lucide.dev/icons/sun)/[zap](https://lucide.dev/icons/zap).
Reference SVGs/logos are not copied. Browser and native asset checks are documented
in [testing](testing.md).
