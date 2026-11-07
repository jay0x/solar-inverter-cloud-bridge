"""Validate public docs and planned package links without building or accessing HA."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LICENSE_SHA256 = "1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5"
INHERITED_MIT_SHA256 = "999f4f677ae386d43d947fe258be43d3d3a3eef3422909c76827814f4c9ab317"
REQUIRED = (
    "README.md", "AGENTS.md", "LICENSE", "THIRD_PARTY_NOTICES.md", ".gitignore",
    "docs/README.md", "docs/INSTALL.md", "docs/DEVICE_COMPATIBILITY.md",
    "docs/PROTOCOLS_AND_PROFILES.md", "docs/PROFILE_EXPANSION.md",
    "docs/development/contributing.md", "docs/development/architecture.md",
    "docs/development/control-and-storage.md", "docs/development/diagnostics.md",
    "docs/development/frontend.md", "docs/development/testing.md",
    "docs/development/decisions.md", "docs/development/sources.md",
    "docs/development/documentation-policy.md", "docs/development/publication.md", "docs/verification/README.md",
)
EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", "private", "connection",
            "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage"}
DOCUMENT_SUFFIXES = {".md", ".rst", ".adoc", ".txt"}
LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")
DEFINITION = re.compile(r"^\s{0,3}\[([^\]\n]+)\]:\s*<?([^\s>]+)>?.*$", re.MULTILINE)
REFERENCE = re.compile(r"(?<!!)\[([^\]\n]+)\]\[([^\]\n]*)\]")
CYRILLIC = re.compile(r"[\u0400-\u052f]")
LOCAL_PATH = re.compile(r"/media/sf_smart_home/|/tmp/opencode/|private/(?:test-vm-|observation-)|root@192\.168\.")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b")


def markdown_links(text):
    """Extract inline/reference targets without interpreting examples as links."""
    lines = []
    fence = None
    for line in text.splitlines():
        stripped = line.lstrip()
        match = re.match(r"(`{3,}|~{3,})", stripped)
        if match:
            marker = match[1]
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line)
    errors = ["Unclosed code fence"] if fence else []
    body = "\n".join(lines)
    definitions = {" ".join(label.split()).casefold(): url for label, url in DEFINITION.findall(body)}
    targets = list(definitions.values())
    body = DEFINITION.sub("", body)
    targets.extend(LINK.findall(body))
    body = LINK.sub("", body)
    body = re.sub(r"`+[^`\n]*`+", "", body)
    for label, reference in REFERENCE.findall(body):
        key = " ".join((reference or label).split()).casefold()
        if key not in definitions:
            errors.append(f"Undefined Markdown reference: {reference or label}")
    body = REFERENCE.sub("", body)
    # Undefined bare brackets are ordinary Markdown text, except the source-ID
    # convention used in the model register, where a missing definition is a bug.
    for label in re.findall(r"\[([CS]\d+)\]", body):
        if label.casefold() not in definitions:
            errors.append(f"Undefined source reference: {label}")
    return targets, errors


def is_private(path):
    return "private" in path.relative_to(ROOT).parts or "connection" in path.relative_to(ROOT).parts


def check_package_plan(errors):
    """Validate future archive paths/content in memory; never call build()."""
    sys.path.insert(0, str(ROOT))
    from tools.build_release import release_content, release_sources
    sources = release_sources()
    count = 0
    for name, source in sources.items():
        if not source.is_file() or is_private(source):
            errors.append(f"Invalid planned package source: {name}")
            continue
        if source.suffix != ".md":
            continue
        targets, issues = markdown_links(release_content(source).decode("utf-8"))
        errors.extend(f"Package {name}: {issue}" for issue in issues)
        for raw in targets:
            url = urlsplit(raw)
            if url.scheme or not url.path:
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(url.path)))
            if target not in sources:
                errors.append(f"Broken planned package link: {name} -> {raw}")
            else:
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-private", action="store_true", help="Also check local private-document/archive links")
    args = parser.parse_args()
    errors = []
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            errors.append(f"Missing required file: {relative}")
    license_path = ROOT / "LICENSE"
    license_ok = license_path.is_file() and hashlib.sha256(license_path.read_bytes()).hexdigest() == LICENSE_SHA256
    if not license_ok:
        errors.append("MPL-2.0 LICENSE differs from its recorded official-text hash")
    notice_path = ROOT / "THIRD_PARTY_NOTICES.md"
    notice = notice_path.read_text() if notice_path.is_file() else ""
    mit = re.search(r"```text\n(MIT License\n.*?\n)```", notice, re.DOTALL)
    inherited_ok = bool(mit and hashlib.sha256(mit[1].encode()).hexdigest() == INHERITED_MIT_SHA256)
    if not inherited_ok:
        errors.append("Inherited MIT notice is missing or differs from its original text")

    # Private notes are optional and must not be a tracked dependency of a public checkout.
    git = subprocess.run(["git", "-c", f"safe.directory={ROOT}", "ls-files", "-z", "--", "docs/private"],
                         cwd=ROOT, capture_output=True)
    if git.returncode == 0:
        for raw in git.stdout.split(b"\0"):
            if raw and (ROOT / raw.decode()).exists():
                errors.append(f"Private documentation is tracked by Git: {raw.decode()}")
    reports = ROOT / "reports"
    if reports.exists() and any(reports.iterdir()):
        errors.append("Retired root reports/ must not contain documents; use docs/verification or docs/private")

    pending = [ROOT]
    files_checked = markdown_checked = private_markdown_checked = links_checked = 0
    public_docs = set()
    linked_docs = set()
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(ROOT).as_posix()
            if path.is_symlink():
                errors.append(f"Unexpected symlink: {relative}")
                continue
            if path.is_dir():
                if path.name not in EXCLUDED or (args.include_private and path == ROOT / "docs/private"):
                    pending.append(path)
                continue
            files_checked += 1
            private = is_private(path)
            if path.name == ".env" or path.name.startswith(".env.") or path.suffix in {".pem", ".key", ".db", ".pcap", ".pcapng", ".ndjson"} or ".sqlite" in path.name:
                errors.append(f"Unexpected access/runtime-data file: {relative}")
                continue
            if path.suffix not in DOCUMENT_SUFFIXES | {".py", ".yml", ".yaml"} and path.name not in {"LICENSE", ".gitignore"}:
                continue
            text = path.read_text(encoding="utf-8")
            if PRIVATE_KEY.search(text) or JWT.search(text):
                errors.append(f"Secret-like content requires review: {relative}")
            if not private:
                if path.suffix in DOCUMENT_SUFFIXES or ".github/ISSUE_TEMPLATE/" in relative:
                    if CYRILLIC.search(text):
                        errors.append(f"Non-public-language document belongs in docs/private/: {relative}")
                    if LOCAL_PATH.search(text):
                        errors.append(f"Installation-specific path in public documentation: {relative}")
                for number, line in enumerate(text.splitlines(), 1):
                    if line.rstrip() != line:
                        errors.append(f"Trailing whitespace: {relative}:{number}")
                if text and not text.endswith("\n"):
                    errors.append(f"Missing final newline: {relative}")
            if path.suffix != ".md":
                continue
            if private:
                private_markdown_checked += 1
            else:
                markdown_checked += 1
                if path.is_relative_to(ROOT / "docs"):
                    public_docs.add(path.resolve())
            targets, issues = markdown_links(text)
            errors.extend(f"{relative}: {issue}" for issue in issues)
            for raw in targets:
                url = urlsplit(raw)
                if url.scheme in {"https", "http", "mailto"}:
                    continue
                if url.scheme or url.netloc:
                    errors.append(f"Unsupported link scheme: {relative}")
                    continue
                if not url.path:
                    continue
                target = (path.parent / unquote(url.path)).resolve()
                if not target.is_relative_to(ROOT):
                    errors.append(f"External workspace file link: {relative} -> {raw}")
                elif not private and is_private(target):
                    errors.append(f"Public document depends on private material: {relative} -> {raw}")
                elif not target.exists():
                    errors.append(f"Broken local link: {relative} -> {raw}")
                else:
                    links_checked += 1
                    if not private:
                        linked_docs.add(target)
    for path in sorted(public_docs - linked_docs):
        errors.append(f"Public guide is not linked from another public document: {path.relative_to(ROOT)}")
    package_links = check_package_plan(errors)
    print(json.dumps({"ok": not errors, "files_checked": files_checked,
                      "public_markdown_checked": markdown_checked, "private_markdown_checked": private_markdown_checked,
                      "local_links_checked": links_checked, "planned_package_links_checked": package_links,
                      "project_license": "MPL-2.0", "license_source_hash_matches": license_ok,
                      "inherited_mit_notice_preserved": inherited_ok, "archive_built": False,
                      "privacy_check": "Limited filename/path/private-key/JWT heuristic; not a full secret or Git-history audit",
                      "external_urls_fetched": False, "runtime_or_hardware_tested": False, "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
