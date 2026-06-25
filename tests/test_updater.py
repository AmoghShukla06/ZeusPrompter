#!/usr/bin/env python3
"""Unit tests for ZeusPrompter updater.py."""

import io
import os
import sys
import json
import tempfile
import unittest
from unittest import mock

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
sys.path.insert(0, CORE)

import updater  # noqa: E402
import scanner  # noqa: E402


def _write_config(tmpdir, **overrides):
    cfg = {
        "enabled": True,
        "openrouter_api_key": "sk-test-key-1234567890",
        "model": "qwen/qwen3-coder:free",
        "tools": {"claude_code": True, "codex": True, "cursor": True, "antigravity": True},
        "optimizer": {"min_prompt_length": 20, "max_context_tokens": 2000, "timeout_seconds": 25},
        "updater": {"max_sessions_stored": 3, "summarize_with_llm": False},
        "version": "1.0.0",
    }
    cfg.update(overrides)
    path = os.path.join(tmpdir, "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return path


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.cfgdir = tempfile.mkdtemp()
        self.cfg_path = _write_config(self.cfgdir)
        self._patch = mock.patch.object(updater, "CONFIG_PATH", self.cfg_path)
        self._patch.start()
        # Project dir with a knowledge base.
        self.proj = tempfile.mkdtemp()
        scanner.scan(self.proj)

    def tearDown(self):
        self._patch.stop()

    def _run(self, payload):
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
             mock.patch.object(updater, "_git", return_value=""):
            with self.assertRaises(SystemExit) as ctx:
                updater.main()
        return ctx.exception.code

    def _load(self):
        with open(os.path.join(self.proj, ".sentinel", "knowledge.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_session_appended(self):
        code = self._run({"cwd": self.proj, "session_id": "sess-001"})
        self.assertEqual(code, 0)
        data = self._load()
        self.assertEqual(len(data["recent_sessions"]), 1)
        self.assertEqual(data["recent_sessions"][0]["session_id"], "sess-001")

    def test_disabled_exits_without_writing(self):
        _write_config(self.cfgdir, enabled=False)
        before = self._load()
        self._run({"cwd": self.proj, "session_id": "sess-x"})
        after = self._load()
        self.assertEqual(before["recent_sessions"], after["recent_sessions"])

    def test_missing_knowledge_exits_cleanly(self):
        empty = tempfile.mkdtemp()
        code = self._run({"cwd": empty, "session_id": "sess-y"})
        self.assertEqual(code, 0)

    def test_max_sessions_capped(self):
        for i in range(5):
            self._run({"cwd": self.proj, "session_id": f"sess-{i}"})
        data = self._load()
        self.assertEqual(len(data["recent_sessions"]), 3)  # max_sessions_stored=3
        # Newest first.
        self.assertEqual(data["recent_sessions"][0]["session_id"], "sess-4")


if __name__ == "__main__":
    unittest.main()
