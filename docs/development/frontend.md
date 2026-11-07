# Frontend and native HA presentation

The bundled panel is plain JavaScript/CSS served by HA, with local HTML/JS for the
router guide. It uses authenticated WebSocket commands and does not require a CDN,
separate card, frontend plugin or framework build. Product strings are en-US.

## Navigation and editing

- Device tabs are **Overview → Sensors → Configuration → Connection → Activity**.
  Existing `/settings` deep links continue to address Configuration.
- The list opens device Overview; Configuration shortcuts open the settings view.
  **All inverters** and reselecting the sidebar item return to the list.
- Parameter rows show one observed value. Editing creates a draft; Apply becomes
  usable only for a valid change. Reserved space keeps Apply/Cancel/note geometry
  stable through editing, polling and reverting.
- Polling must not replace an active input/dropdown or steal focus through nested
  HA shadow roots. Drafts, caller-owned operation IDs and uncertain results survive
  reload. A lost response is not an automatic resend.
- Show the selected profile's full implemented inventory. Explain freshness and
  capability restrictions without inventing unsupported fields or control modes.
- Profile acceptance covers its readings and implemented writable settings. A changed
  binding offers a fresh read-only recheck and reviewed proposal.
- Treat names, descriptions and reports as text, not trusted HTML.

## Profile composition

Panel 0.16.1 consumes the backend `profile_layers` description. Recognition,
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

The **Home Assistant entities** link uses the actual HA device-registry ID, not the
bridge's enrollment UUID. HA's native device page has fixed entity categories;
an integration cannot create an arbitrary extra section header there. Mode and
maintenance entities therefore use the normal Configuration category.

## First-inverter setup

The empty home view has one primary entry point, **Connect your first inverter**.
The four steps are **Name → Connect → Check → Add**. The existing allowed network is
shown as already configured; adding another source is a disclosure, not a repeated
mandatory task. Saved network rules are retained.

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
