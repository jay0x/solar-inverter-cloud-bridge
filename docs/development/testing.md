# Testing and evidence boundaries

Run commands from the repository root using an appropriate isolated environment.
Use only the checks relevant to the change. Passing software tests does not imply
hardware qualification. Last recorded results are in [verification](../verification/README.md).

## Documentation only — no build or server access

```bash
python3 tools/check_docs.py
git diff --check
```

The checker validates the public document inventory, links, Markdown reference
definitions, en-US/Cyrillic placement, license digests and a limited secret/path
heuristic. It also validates the planned package's document links without creating
a ZIP. It skips ignored local evidence and can optionally check private archive links.
English-only characters are a useful guard, not proof of American-English style.

## Offline and HA suites

```bash
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python -m pytest tests_ha -q --tb=short
```

The offline suite covers codecs, profile specimens, ownership, discovery, explicit
permission, durable failure boundaries, database migration and loopback collectors.
The HA suite covers actual lifecycle/state/config/service behavior, native entity
inventories and permissions, registry handling, diagnostics, 100 reloads and ZIP installation.

**Both full suites include packaging checks.** If the task prohibits a build, run
documentation validation or select an explicitly suitable non-packaging test target;
do not run `test_release.py`, the full HA install suite, or a report-archive generator.

For runtime work with installation builds prohibited:

```bash
python3 -W error::ResourceWarning tools/test_without_build.py
python -m pytest tests_ha/test_integration.py -q --tb=short
```

The first command uses unittest (without HA's pytest socket-blocking plugin), omits
the release test and guards the installation builder against accidental calls.
Compatibility-format tests still exercise diagnostic ZIP data in memory; those
are evidence-format tests, not installation builds or distribution archives.

## Browser checks

```bash
npm test --prefix tests
```

Chromium tests use synthetic HA data. They exercise drafts/focus, uncertain results,
parameter/profile controls, consent, removal, Recorder events, guide generation and
responsive layouts. Router recipe syntax checks also use shell, Python and PHP;
they do not configure a router or establish router hardware compatibility.

## Explicit archive and load exercises

Run these only when archive generation is permitted:

```bash
python3 tools/exercise_binary_report.py --output /tmp/bridge-compatibility-example
python3 tools/replay_compatibility.py /tmp/bridge-compatibility-example/synthetic-compatibility.zip
python3 tools/build_release.py
```

The report exercise stops its simulated peer before replay, preserving the
distinction between original bytes, structured evidence and constructed fixtures.
The release test checks reproducibility, contents and local document targets.

```bash
python3 tools/benchmark_runtime.py --devices 16 --seconds 45 --transport mixed --rotate
```

This loopback benchmark handles AT heartbeats and binary TID exhaustion/reconnect.
It does not contact HA or write inverter registers. Record build hash, environment,
duration, device count, CPU/memory, loop lag and failure counts with any result.

## Live installation work

Local deployment/browser/observation tools require the explicitly authorized test
installation and ignored access material. They are not generic public acceptance
commands to run against an arbitrary HA host. Read local instructions, snapshot
the affected configuration, preserve current maintenance preferences/IDs, and read back
actual results. Do not send resets or electrical/schedule writes just to prove a UI.

A completed fixed-candidate observation needs an unchanged fingerprint and a final
recorded result. A running or interrupted process is not a passed 24-hour test.
