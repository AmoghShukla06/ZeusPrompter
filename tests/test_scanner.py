#!/usr/bin/env python3
"""Unit tests for ZeusPrompter scanner.py."""

import os
import sys
import json
import tempfile
import unittest

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
sys.path.insert(0, CORE)

import scanner  # noqa: E402


class ScannerStackTests(unittest.TestCase):
    def _scan(self, files):
        tmp = tempfile.mkdtemp()
        for name, content in files.items():
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                f.write(content)
        scanner.scan(tmp)
        with open(os.path.join(tmp, ".sentinel", "knowledge.json"), encoding="utf-8") as f:
            return tmp, json.load(f)

    def test_node_react_detected(self):
        _, data = self._scan({
            "package.json": json.dumps({"dependencies": {"next": "14", "react": "18"}}),
            "pnpm-lock.yaml": "",
        })
        stack = str(data["project"]["stack"]).lower()
        self.assertIn("next.js", stack)
        self.assertEqual(data["project"]["package_manager"], "pnpm")

    def test_python_detected(self):
        _, data = self._scan({
            "requirements.txt": "flask==3.0\nrequests>=2.0\n",
        })
        self.assertIn("Python", data["project"]["stack"])
        self.assertIn("Flask", data["project"]["stack"])

    def test_go_detected(self):
        _, data = self._scan({"go.mod": "module github.com/me/app\n\ngo 1.22\n"})
        self.assertIn("Go", data["project"]["stack"])
        self.assertIn("github.com/me/app", data["project"]["entry_points"])

    def test_gitignore_appended(self):
        tmp = tempfile.mkdtemp()
        gi = os.path.join(tmp, ".gitignore")
        with open(gi, "w", encoding="utf-8") as f:
            f.write("node_modules/\n")
        scanner.scan(tmp)
        with open(gi, encoding="utf-8") as f:
            content = f.read()
        self.assertIn(".sentinel", content)
        # Idempotent: second scan must not duplicate.
        scanner.scan(tmp)
        with open(gi, encoding="utf-8") as f:
            self.assertEqual(f.read().count(".sentinel"), 1)

    def test_file_tree_summary_skips_noise(self):
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "node_modules", "pkg"))
        os.makedirs(os.path.join(tmp, "src"))
        with open(os.path.join(tmp, "src", "main.py"), "w") as f:
            f.write("print('x')\n")
        scanner.scan(tmp)
        with open(os.path.join(tmp, ".sentinel", "knowledge.json"), encoding="utf-8") as f:
            data = json.load(f)
        keys = " ".join(data["file_tree_summary"].keys())
        self.assertNotIn("node_modules", keys)
        self.assertIn("src", keys)


if __name__ == "__main__":
    unittest.main()
