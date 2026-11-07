# GitHub and HACS publication

## Prepared identity and current status

- Product: **Solar Inverter Cloud Bridge**.
- Maintainer: **jay0x**; repository: [jay0x/solar-inverter-cloud-bridge](https://github.com/jay0x/solar-inverter-cloud-bridge).
- Technical integration domain and component directory: `solar_inverter_bridge`.
- Current candidate: **0.8.2**, panel **0.16.1**, ledger schema **4**.
- Local operation and the tested minimum Home Assistant version, **2026.10.4**,
  are unchanged by the name. Cloud does not imply a hosted service.

The public repository was created from a reviewed clean source export. The
manifest's documentation/issue URLs point to it. No GitHub release or HACS
default-catalog listing exists yet. Hosted validation and HACS installation results
are recorded in the verification guide; workflow presence alone is not a passing run.

## Repository contents and installation

HACS installs the one integration under `custom_components/solar_inverter_bridge`.
Its runtime assets, translations and brand images are inside that directory.
`hacs.json` names the product and sets the minimum HA version. No `zip_release`
mode is configured: the manual-install ZIP layout is not a HACS ZIP layout.

The public source includes the component, tests, tools, public documentation,
README, license/notices, HACS metadata and GitHub workflow/issue templates.
Exclude private evidence/access files, local databases, caches and generated outputs.
Use an explicit reviewed source list, including intended untracked source files.

The existing local Git history contains earlier private working documents. Its
default branch must not be pushed as the initial public repository. For the first
publication, prepare a separate reviewed source export and start a clean public
history there, retaining copyright and provenance notices. Keep the local history
intact. Creating that export/repository, committing and pushing require the owner's
publication instruction. `git archive HEAD` is not a substitute for reviewing the
current candidate because current work may not be committed.

## Required pre-release documentation review

Recheck documentation against the **exact source fingerprint to be released**, even
if an earlier candidate passed review. Record results in the verification guide.

| Area | Compare against |
| --- | --- |
| Product name, version, HA minimum and URLs | `manifest.json`, `hacs.json`, panel cache/version and actual repository |
| Installation, upgrade and rename | Config flow, setup/title migration, component layout and preserved IDs |
| Collector routing and protocols | Listener/admission code, supported transports and required network configuration |
| Profile/readings/control counts | `core/profile_catalog.py`, `catalogue.py` and `drivers.fields_for()` |
| Controls and failure behavior | Durable executor, readback/reconciliation, native entities and administrator checks |
| Hardware claims and gaps | Verification evidence; distinguish source-derived, synthetic and physical-device results |
| License/provenance | MPL license, inherited MIT notice and pinned source references |
| Links and examples | Public checkout, published documentation/issue URLs and installation examples |

Current inventories can be read without packaging or hardware access:

```bash
python -c 'from custom_components.solar_inverter_bridge.core.profile_catalog import catalogue_view; print([(p["profile_id"], p["measurements"], p["controls"]) for p in catalogue_view()])'
python tools/check_docs.py
git diff --check
```

The documentation checker validates links, language placement and license digests;
it does not establish semantic agreement or audit all historical secrets. Review
the content and export separately. Do not turn historical verification records into
current claims by globally replacing their versions.

## Checks and publication sequence

1. Finish the documentation review above and the build-free suites in
   [testing](testing.md). Confirm a fresh test-installation snapshot, source hashes,
   retained IDs/preferences and read-only UI acceptance for the final candidate.
2. On the owner's publication instruction, create the clean public repository with
   Issues enabled. Suggested description: **Local Home Assistant integration for
   EyeBond-connected solar inverters, with native sensors and verified settings.**
   Suggested topics: `home-assistant`, `hacs`, `solar`, `inverter`, `eybond`, `modbus`.
3. Push only the reviewed export. Run **Test candidate** and **Validate integration
   metadata**. The latter runs Hassfest and the official HACS action; fix failures
   without suppressing required checks. Verify the documentation and issue URLs.
4. Test installing the public repository as a HACS custom repository in an authorized
   isolated HA installation. Source deployment is not proof of HACS installation.
5. When release publication is requested, use a version matching the manifest
   (for example `v0.8.2`) and publish a GitHub Release with accurate changes and
   limitations. A tag alone is not a release. A manual ZIP is optional and must be
   explicitly authorized/tested; no workflow automatically builds or publishes one.
6. A public custom repository can be added to HACS before default-catalog inclusion.
   Submit it for inclusion separately after meeting the current submission rules.

Official references (reviewed November 7, 2026):

- [General HACS requirements](https://www.hacs.xyz/docs/publish/start/)
- [Integration requirements](https://www.hacs.xyz/docs/publish/integration/)
- [HACS action](https://www.hacs.xyz/docs/publish/action/)
- [Default repository inclusion](https://www.hacs.xyz/docs/publish/include/)
- [HA integration manifest](https://developers.home-assistant.io/docs/creating_integration_manifest)
