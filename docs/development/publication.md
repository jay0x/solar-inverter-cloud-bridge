# GitHub and HACS publication

## Identity and current status

- Product: **Solar Inverter Cloud Bridge**.
- Maintainer: **jay0x**; repository: [jay0x/solar-inverter-cloud-bridge](https://github.com/jay0x/solar-inverter-cloud-bridge).
- Integration domain and component directory: `solar_inverter_bridge`.
- Current candidate: **0.8.2**, panel **0.16.1**, ledger schema **4**.
- Tested minimum Home Assistant version: **2026.10.4**; tested HACS version: **2.0.5**.

The public repository is available as a HACS custom repository. There is no stable
GitHub release or default-catalog listing. Current checks and installation evidence
are in [verification](../verification/README.md).

## Repository contents and installation

HACS installs the single integration under `custom_components/solar_inverter_bridge`.
All runtime assets, translations and brand images are inside that directory.
`hacs.json` supplies the product name and minimum HA version. No `zip_release` mode
is configured: the manual-install ZIP layout is not a HACS ZIP layout.

Public source includes the component, tests, tools, public documentation, license
notices and GitHub metadata. Exclude private access/evidence files, databases,
caches and generated outputs. Review both tracked and intended untracked files.

## Required pre-release documentation review

Recheck documentation against the **exact source fingerprint to be released**.
Describe current behavior and qualification without internal development chronology.

| Area | Compare against |
| --- | --- |
| Product name, version, HA minimum and URLs | `manifest.json`, `hacs.json`, panel version and actual repository |
| Installation and updates | Config flow, component layout, saved data and preserved IDs |
| Collector routing and protocols | Listener/admission code and required network configuration |
| Profile/readings/control counts | `core/profile_catalog.py`, `catalogue.py` and `drivers.fields_for()` |
| Controls and failure behavior | Executor, readback/reconciliation, native entities and administrator checks |
| Hardware claims and gaps | Synthetic, installation and physical-device evidence |
| License/provenance | MPL license, inherited MIT notice and pinned source references |
| Links and examples | Public checkout, documentation/issue URLs and installation instructions |

Read inventories and validate documentation without packaging or hardware access:

```bash
python -c 'from custom_components.solar_inverter_bridge.core.profile_catalog import catalogue_view; print([(p["profile_id"], p["measurements"], p["controls"]) for p in catalogue_view()])'
python tools/check_docs.py
git diff --check
```

The checker validates links, language placement and license digests. Semantic
agreement with the code and the scope of hardware claims still require review.

## Release checks

1. Finish the documentation review and applicable suites in [testing](testing.md).
   Verify source hashes, retained IDs/preferences and UI behavior on an authorized
   test installation, with a fresh snapshot before changes.
2. On publication authorization, push the reviewed changes. Run **Test candidate**
   and **Validate integration metadata**. Fix failures without suppressing required
   checks. Verify documentation and issue URLs, repository description and topics.
3. Verify HACS installation of the intended candidate. Source deployment alone is
   not proof that HACS can install it.
4. When release publication is requested, use a tag matching the manifest version
   and publish a GitHub Release with supported features and limitations. A tag
   alone is not a release. A manual ZIP is optional and requires explicit build
   authorization and verification; workflows do not automatically publish one.
5. Default HACS catalog inclusion is a separate submission under its current rules.

## Official references

- [General HACS requirements](https://www.hacs.xyz/docs/publish/start/)
- [Integration requirements](https://www.hacs.xyz/docs/publish/integration/)
- [HACS action](https://www.hacs.xyz/docs/publish/action/)
- [Default repository inclusion](https://www.hacs.xyz/docs/publish/include/)
- [HA integration manifest](https://developers.home-assistant.io/docs/creating_integration_manifest)
