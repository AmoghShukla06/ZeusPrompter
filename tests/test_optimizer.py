#!/usr/bin/env python3
"""Unit tests for ZeusPrompter optimizer + scanner + install merge logic."""

import io
import os
import sys
import json
import tempfile
import unittest
from unittest import mock

# Make core/ importable.
CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
sys.path.insert(0, CORE)

import optimizer  # noqa: E402
import scanner    # noqa: E402


def _write_config(tmpdir, **overrides):
    cfg = {
        "enabled": True,
        "openrouter_api_key": "sk-test-key-1234567890",
        "model": "qwen/qwen3-coder:free",
        "tools": {"claude_code": True, "codex": True, "cursor": True, "antigravity": True},
        "optimizer": {"min_prompt_length": 20, "max_context_tokens": 2000, "timeout_seconds": 25},
        "updater": {"max_sessions_stored": 20, "summarize_with_llm": True},
        "version": "1.0.0",
    }
    cfg.update(overrides)
    path = os.path.join(tmpdir, "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return path


class OptimizerPassthroughTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg_path = _write_config(self.tmp)
        self._patch = mock.patch.object(optimizer, "CONFIG_PATH", self.cfg_path)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def _run(self, payload):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
             mock.patch.object(sys, "stdout", out):
            with self.assertRaises(SystemExit) as ctx:
                optimizer.main()
        return ctx.exception.code, out.getvalue()

    def test_passthrough_when_disabled(self):
        _write_config(self.tmp, enabled=False)
        code, out = self._run({"prompt": "this is a long enough prompt to optimize", "cwd": self.tmp})
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_passthrough_short_prompt(self):
        code, out = self._run({"prompt": "hi yo", "cwd": self.tmp})
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_passthrough_slash_command(self):
        code, out = self._run({"prompt": "/clear something something long enough", "cwd": self.tmp})
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_optimizer_returns_valid_json(self):
        with mock.patch.object(optimizer, "_call_openrouter", return_value="OPTIMIZED PROMPT TEXT"):
            code, out = self._run({"prompt": "fix the login bug in the auth module", "cwd": self.tmp})
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertIn("hookSpecificOutput", parsed)
        self.assertEqual(parsed["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("OPTIMIZED PROMPT TEXT", parsed["hookSpecificOutput"]["additionalContext"])

    def test_api_failure_is_silent_passthrough(self):
        with mock.patch.object(optimizer, "_call_openrouter", side_effect=RuntimeError("network down")):
            code, out = self._run({"prompt": "fix the login bug in the auth module", "cwd": self.tmp})
        self.assertEqual(code, 0)
        self.assertEqual(out, "")


class ScannerTests(unittest.TestCase):
    def test_scanner_builds_knowledge_json(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"dependencies": {"react": "18.0.0"}}, f)
        with open(os.path.join(tmp, "package-lock.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        scanner.scan(tmp)
        kpath = os.path.join(tmp, ".sentinel", "knowledge.json")
        self.assertTrue(os.path.isfile(kpath))
        with open(kpath, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("react", str(data["project"]["stack"]).lower())
        self.assertEqual(data["project"]["package_manager"], "npm")
        self.assertIn("meta", data)
        self.assertIn("recent_sessions", data)


class InstallMergeIdempotencyTests(unittest.TestCase):
    """Replicates the install.sh Claude Code merge logic to assert idempotency."""

    @staticmethod
    def _merge(settings, fragment):
        existing_hooks = settings.get("hooks", {})
        new_hooks = fragment.get("hooks", {})
        for event, matchers in new_hooks.items():
            if event not in existing_hooks:
                existing_hooks[event] = matchers
            else:
                existing_commands = []
                for group in existing_hooks[event]:
                    for h in group.get("hooks", []):
                        existing_commands.append(h.get("command", ""))
                zeus_cmds = []
                for group in matchers:
                    for h in group.get("hooks", []):
                        zeus_cmds.append(h.get("command", ""))
                already = any(any(z in e for z in zeus_cmds) for e in existing_commands)
                if not already:
                    existing_hooks[event].extend(matchers)
        settings["hooks"] = existing_hooks
        return settings

    def test_idempotent_install(self):
        fragment = {
            "hooks": {
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command",
                                "command": "python3 /home/u/.zeus-prompter/core/optimizer.py"}]}
                ]
            }
        }
        settings = {}
        settings = self._merge(settings, json.loads(json.dumps(fragment)))
        settings = self._merge(settings, json.loads(json.dumps(fragment)))
        groups = settings["hooks"]["UserPromptSubmit"]
        cmds = [h["command"] for g in groups for h in g["hooks"]]
        zeus_cmds = [c for c in cmds if ".zeus-prompter" in c]
        self.assertEqual(len(zeus_cmds), 1, "zeus hook must not be duplicated")


if __name__ == "__main__":
    unittest.main()
