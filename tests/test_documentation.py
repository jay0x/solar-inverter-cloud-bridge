"""Build-free regression checks for public/private documentation boundaries."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import build_release, check_docs


class DocumentationTests(unittest.TestCase):
    def test_markdown_sources_and_examples_are_distinct(self):
        text = """# Example
[Guide](INSTALL.md)
[Source][c1] and [C1].
[C1]: https://example.org/source
`[Not a reference][missing]`
```python
example = "[Not a link](private/access.md)"
```
"""
        targets, errors = check_docs.markdown_links(text)
        self.assertEqual(errors, [])
        self.assertEqual(set(targets), {"INSTALL.md", "https://example.org/source"})
        _, errors = check_docs.markdown_links("[Source][missing]\n[C99]\n````text\nunclosed")
        self.assertIn("Unclosed code fence", errors)
        self.assertIn("Undefined Markdown reference: missing", errors)
        self.assertIn("Undefined source reference: C99", errors)

    def test_package_plan_reports_private_and_broken_targets_without_building(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / "guide.md"
            guide.write_text("# Guide\n[Private](docs/private/note.md)\n[Missing](missing.md)\n")
            private = root / "docs/private/note.md"
            private.parent.mkdir(parents=True)
            private.write_text("# Local note\n")
            with patch.object(check_docs, "ROOT", root), patch.object(sys, "path", list(sys.path)), \
                 patch.object(build_release, "release_sources", return_value={"guide.md": guide, "docs/private/note.md": private}), \
                 patch.object(build_release, "build", side_effect=AssertionError("Build prohibited")), \
                 patch.object(build_release, "ZipFile", side_effect=AssertionError("Archive creation prohibited")):
                errors = []
                check_docs.check_package_plan(errors)
            self.assertTrue(any("Invalid planned package source" in error for error in errors))
            self.assertTrue(any("missing.md" in error for error in errors))
            self.assertFalse(list(root.rglob("*.zip")))

    def test_public_guide_symlink_cannot_package_private_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "docs/private/note.md"
            private.parent.mkdir(parents=True)
            private.write_text("# Local note\n")
            (root / "docs/INSTALL.md").symlink_to(private)
            with patch.object(build_release, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    build_release.release_sources()
