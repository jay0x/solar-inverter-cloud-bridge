# Documentation

Public documentation is written in **American English (en-US)** and describes the
current candidate, not an accumulation of agent plans. Start with the guide for
your task; each topic has one primary document.

## Users

| Guide | Purpose |
| --- | --- |
| [Install and operate](INSTALL.md) | Setup, network routing, panel, actions, backup and maintenance |
| [Device compatibility](DEVICE_COMPATIBILITY.md) | Named inverters, aliases, experimental candidates and unresolved devices |
| [Protocols and profiles](PROTOCOLS_AND_PROFILES.md) | Network/dialect/payload/map layers, ports, identity and the reference map |
| [Profile expansion](PROFILE_EXPANSION.md) | Additional profile/control subsets, recognition, explicit permission and support reports |

These four guides retain their stable filenames and are included in the manual
installation package. Developer guides remain in the source repository.

## Developers and maintainers

| Guide | Purpose |
| --- | --- |
| [Contributing](development/contributing.md) | Actual code layout, environments and scope of changes |
| [Architecture](development/architecture.md) | Runtime, transport, profile and HA adapter boundaries |
| [Control and storage](development/control-and-storage.md) | Permissions, durable commands, schema and recovery guarantees |
| [Diagnostics](development/diagnostics.md) | Capture, analysis, privacy, export and offline replay |
| [Frontend](development/frontend.md) | UI behavior, accessibility, entity history and branding |
| [Testing](development/testing.md) | Check selection and reproducible commands |
| [Decisions](development/decisions.md) | Active product/technical decisions and retained decision IDs |
| [Sources](development/sources.md) | Provenance, pinned external evidence and license boundaries |
| [Documentation policy](development/documentation-policy.md) | Public/private placement, language, archives and publishing |
| [GitHub and HACS publication](development/publication.md) | Prepared identity, clean export, mandatory documentation review and release sequence |

## Verification evidence

[Verification summary](verification/README.md) records the last documented candidate
and separates software checks from hardware qualification. A useful public report
needs a build, method, results and limitations; transcripts and installation logs
belong in local notes, not a separate top-level `reports/` directory.

## Local-only material

`docs/private/` is ignored by Git and excluded from packages. It holds Russian
documents, installation-specific notes, current local handoff and archived plans/
reports. It is optional and will be absent from a normal public checkout. Access
files, raw captures, databases and deployment snapshots remain in the separate
ignored root `private/` directory; they are not documentation.

Historical decisions and implementation briefs were consolidated into the guides
above. They are not competing current instructions. See the documentation policy
for the archival mapping and treatment of existing Git history.
