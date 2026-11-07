# Solar Inverter Cloud Bridge — contributor and agent instructions

## Start here

- Communicate with the project owner in Russian. Product strings and public project
  documents must use American English (en-US).
- Read `README.md`, `docs/README.md`, and the relevant development guide. For local
  installation work, also read `docs/private/HANDOFF.md` if it exists. Private files
  are optional local context, not prerequisites for a public checkout.
- Put every Russian-language document and every non-public working note in
  `docs/private/`, including documents the owner explicitly requests in Russian.
  Do not publish, stage or package that directory. Follow
  `docs/development/documentation-policy.md` for documentation changes.
- Historical plans and agent conversations are not current implementation status
  or inherited permission to change hardware. The active technical decisions are
  summarized in `docs/development/decisions.md`.

## Product and implementation boundaries

- One integration in Home Assistant Core; domain `solar_inverter_bridge`, product
  name Solar Inverter Cloud Bridge. Retain the technical domain and existing IDs
  when changing branding. Do not add an app, MQTT bridge or second runtime.
- Current collector transports are mixed AT/binary EyeBond on TCP 502/18899/38899.
  Do not introduce UDP callback, direct serial, vendor HTTP or cloud forwarding as
  an incidental refactor. A port or brand does not establish an inverter profile.
- Keep one active inverter I/O owner per physical path. Reconnect/restart never
  replays writes. New writes require durable intent and independent readback.
- Manual control requires an active HA administrator context. All callers share
  the same executor, profile, baseline and current-session checks.
- D27 supersedes the old three-mode policy: implemented writable parameters are
  available by default. Do not reintroduce Monitoring/Control/Advanced selectors
  or a separate experimental-control switch. Preserve maintenance preferences.
- Keep the full implemented parameter inventory visible, explaining hardware
  read-only, unsupported writes, missing readings and unresolved-operation barriers.
- D17: only actual hardware R/O is read-only. Known R/W parameters without
  manufacturer limits can be edited with a warning. Preserve exact
  scaling, encoding, known bounds and dependencies; wire limits are not operating limits.
- D25–D26: offer source-derived profiles for unlisted models based on actual read
  evidence. Inferred compatibility may use implemented source-defined controls
  after explicit profile warning/acceptance. Bind acceptance to the profile definition and
  fresh evidence; do not guess write addresses or enable unimplemented controls.
- User automations and energy optimization are outside the integration. External
  projects use its native entities/actions. The optional built-in clock service
  still obeys its own enable switch, capability and durable execution rules.
- Keep SQLite/fsync/file I/O off the event loop. Do not edit HA `.storage` directly;
  use HA registry/config APIs. Recorder owns measurement history, HA registries own
  display overrides, SQLite owns the ledger and related policy state.

## Local work and deployment

- Preserve existing uncommitted work. Commit, push, add a remote or publish only
  when the user explicitly requests it. Do not launch subagents independently.
- Credentials, captures, databases and local deployment state stay in the ignored
  root `private/` directory. Never print access files or include them in documents.
- Use only the test installation identified by the local private handoff. Production
  HA, router changes, collector migration and physical writes require explicit scope.
  Do not send resets or electrical/schedule changes merely to verify software.
- Read the local HA-access instructions before live access. Snapshot affected state,
  preserve user changes, use the existing deployment mechanism and read back results.
  Deploy requested UI changes to the authorized test instance after verification.
- Embedded DNS was declined; storage ownership was retained; the manual WAN-loss
  task was canceled. Do not reinstate them from an archived document.
- Preserve provenance, copyright and third-party notices. The project is MPL-2.0;
  original MIT terms for inherited portions remain in `THIRD_PARTY_NOTICES.md`.

## Verification and reporting

- Documentation-only work: `python3 tools/check_docs.py`, plus
  `git diff --check`. Neither command builds an archive or contacts HA.
- Runtime work: the applicable offline, HA and browser suites in
  `docs/development/testing.md`. The offline discovery suite includes packaging;
  do not run it or release tests when the user has prohibited a build.
- Record public evidence under `docs/verification/`; put detailed local logs,
  deployments and agent handoffs under `docs/private/`. There is no root `reports/`.
- Distinguish implemented, source-derived, simulated and hardware-observed results.
  Update the active guide rather than appending another competing status document.
- Before a release, recheck documentation against the exact candidate: installation,
  profile/control inventories, limitations, versions, links and licenses. Follow
  `docs/development/publication.md`; passing link checks alone is insufficient.
