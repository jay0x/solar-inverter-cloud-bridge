# Active product and technical decisions

This is a concise maintenance contract, not an implementation diary. Retained IDs
refer to the original owner decisions; detailed chronological notes are local history.

| Decision | Current rule |
| --- | --- |
| D01–D03, D16 | One clean integration in HA Core, named Solar Inverter Cloud Bridge, domain `solar_inverter_bridge`; no legacy application/backend migration framework |
| D07 | Public documents, UI, messages, comments and examples use American English (en-US). Russian or non-public documents belong only in ignored `docs/private/` |
| D10–D15, D21 | Manual commands require HA admin. The panel, native entities and optional clock service share the executor; mode selection is superseded by D27 |
| D12 | External applications own automations/energy optimization. The integration exposes checked entities/actions, not its own scheduling engine |
| D13 | Persisting policy never replays an old command; former mode preservation is superseded by D27 |
| D17 | Known R/W without manufacturer limits is editable with a warning and exact wire checks; only actual hardware R/O is read-only |
| D18, D23 | SQLite owns the durable ledger/related policy; Recorder owns history; HA registries own display overrides. No second authority or blanket Store migration |
| D19 | Optional automatic Wi-Fi recovery is off initially, capability/collection guarded and durably rate-limited; disconnected collectors cannot receive a reset |
| D20, D22 | DNS belongs to the local resolver/router. Embedded DNS was declined. The manual WAN-loss task was canceled after the owner identified local DNS behavior |
| D24 | New binary work uses public source evidence and fixtures without locally available hardware. Useful pre-enrollment capture, analysis and replay are required |
| D25 | Recognize unlisted devices against implemented families and offer plausible profiles; maintain a sourced list of named models and unresolved candidates |
| D26 | Inferred compatibility is not a permanent control ban. Permit implemented source-defined controls after explicit warning/permission, with the normal durable and readback checks |
| D27 | One full-control policy: implemented writable settings are enabled by default. Remove Monitoring/Control/Advanced selection and the separate experimental-control switch. Profile acceptance includes its implemented commands; retain fresh evidence, hardware R/O, admin checks, exact validation, readback and unresolved barriers |
| D28 | Rename the product Solar Inverter Cloud Bridge; keep domain, service names, entity IDs and local operation. Prepare GitHub/HACS metadata and recheck documentation against the exact candidate before release |

## Additional implementation boundaries

All three TCP listeners share dialect admission. A failed listener is reported
without disabling healthy listeners; no silent port fallback is made. One physical
path has one active inverter owner. AT's auxiliary channel is not another poller.
Binding identity is not a source IP, port or brand string.

Current additional-profile bindings include the map/control definition digest and
observed route/signature. A changed binding is reviewed explicitly; same-profile
renewal retains HA device/entity IDs and cannot bypass an unresolved operation.

MPL-2.0 is the project license. Preserve the original MIT notice for inherited
portions and the provenance/licensing of external sources.

## Publication and qualification still require their own work

Do not treat fixtures as hardware proof, packet contents as physical effects, or
an archive build as release authorization. A public repository/support destination,
maintainer metadata, publication and any high-impact installation operation need
their own explicit scope. Follow [documentation policy](documentation-policy.md)
and the [verification summary](../verification/README.md).
