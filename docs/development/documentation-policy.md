# Documentation and publication policy

## Language and scope

Public documents, UI strings and code examples use **American English (en-US)**.
Communication with the project owner is in Russian. Russian-language and non-public
working documents belong in ignored `docs/private/`.

Public materials describe **Solar Inverter Cloud Bridge as it exists now**:
capabilities, compatible devices, setup, operation, architecture and qualification.
Do not include unpublished product names, internal version milestones, development
timelines, canceled plans or migration stories for unpublished versions.
Manufacturer protocol revisions and required source/license attribution remain
part of the technical documentation.

## Document ownership

- `README.md`: product overview, models/protocols, installation and routing summary.
- `docs/README.md`: documentation index.
- Four user guides in `docs/`: installation, device compatibility, protocols and
  profile recognition/control. They are included in the manual installation package.
- `docs/development/`: current implementation contracts and contributor guidance.
- `docs/verification/`: checks and qualification of the current product, with clear
  distinctions between synthetic tests, installation evidence and hardware results.

Update the guide that owns a topic. Avoid duplicate status or planning documents.
Keep internal notes, detailed installation logs and development chronology local.

## Private material

`docs/private/` holds local working notes. The separate root `private/` directory
holds credentials, captures, databases, screenshots and deployment state.
Neither directory is a public-checkout dependency or package input. Never include
credentials, serials, household network details or raw private captures in public guides.

Public documents must not link to private material. Source and evidence URLs should
identify the exact document, revision or commit supporting a technical claim.

## Verification and publishing

Before release, compare documentation with the exact candidate as described in
[publication](publication.md). Record the current software version, method, result
and qualification limits. A running observation is not a passed stability test.

Review the full intended Git change and package contents before publication. Ignore
rules alone do not remove tracked material. Do not commit, push, rewrite history or
publish automatically during documentation cleanup.

Run `python3 tools/check_docs.py` and `git diff --check`. The checker validates local
links, language placement, license integrity and planned package links without
building an archive. Its secret/path heuristics are limited; it does not replace a
source review. Optional local private links can be checked with `--include-private`.
