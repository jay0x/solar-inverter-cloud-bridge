# Documentation and publication policy

## Placement and language

All public project documents use **American English (en-US)**, including root
README/agent instructions, guides, source notices and issue templates. Product
strings are also en-US; HA's technical locale key may remain `en`.

Every document containing Russian text belongs in **`docs/private/`**. This includes
existing Russian documents and any document the owner explicitly requests in Russian.
Non-public documents belong there even when written entirely in English: installation
notes, local handoffs, agent task briefs, private source discussions and detailed logs.
Conversation with the owner may remain in Russian.

The separate root `private/` directory stores credentials, captures, databases,
screenshots and generated deployment/observation state. Do not move those into a
documentation archive or print them while reorganizing documents.

## Public document ownership

- `README.md`: entry point, product scope and navigation.
- `docs/README.md`: public documentation map.
- Four stable user guides in `docs/`: installation, device compatibility, protocol
  reference and profile expansion. They are also packaged for manual installation.
- `docs/development/`: current implementation contracts and contributor guidance.
- `docs/verification/`: dated public evidence summaries with methods and limitations.

Do not maintain parallel current STATUS, WORK_PLAN, PRODUCT and NEXT_AGENT narratives.
Update the guide that owns the topic. Put local next steps in the private handoff.
Label a proposal as a proposal and a historical report as historical, never as
present-tense implementation status.

## What happened to reports and old plans

The former top-level `reports/` directory is retired. Useful verification conclusions
are summarized in `docs/verification/README.md`; detailed original reports and
benchmark JSON live under `docs/private/archive/reports/`.

Original mixed-language plans, local research logs and obsolete implementation
briefs were retained under `docs/private/archive/docs/`, with historical banners.
The private archive retains the old docs/reports relationship for source navigation.
Small pointers lead from archived user-guide names to their current public versions.
Root documents with Russian text were also preserved there before being rewritten.

Public technical content was consolidated, not merely moved out of sight: runtime
and HA boundaries are in architecture, policy/ledger behavior in control/storage,
UI requirements in frontend, evidence/provenance in testing/sources/verification.
Unselected old wireframes, canceled procedures and installation transcripts remain
history and are not instructions to resume those tasks.

## When a public verification report is useful

Keep a report when it adds reproducible evidence: candidate fingerprint/revision,
environment, method, results and explicit limits. It must be en-US and must not
contain household addresses, credentials, serials, private filesystem paths or raw
captures. Keep full local artifacts privately and publish only reviewed summaries.
Do not publish every agent session transcript or duplicate a passing-test count
across multiple guides. A running observation is not a completed result.

## Git and package boundaries

`docs/private/` is ignored. Public documents must not have required links into it;
a public checkout must remain usable without local history. Optional private paths
may be mentioned in code formatting for local maintainers, but not as dependencies.
The release builder uses an explicit public-document allowlist, never a recursive
`docs/` or `reports/` glob.

Ignoring or moving current files does **not** erase their older versions from Git
history. Earlier local commits already contain Russian/installation-specific
documents. Before publishing, review the actual history/export and use an explicitly
agreed clean public export/history. Do not rewrite history, add a remote, push or
publish automatically during documentation cleanup.

Validate with `python3 tools/check_docs.py`. It checks Cyrillic placement, local
targets/reference definitions, license integrity, forbidden public/private links,
and the package's planned document links without building an archive. Use
`--include-private` to additionally validate local archive navigation when present.
