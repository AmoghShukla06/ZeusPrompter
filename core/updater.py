#!/usr/bin/env python3
"""
ZeusPrompter — updater.py

Called by the session-end hook of each tool (Stop in Claude Code, session end
elsewhere). Gathers a git-based session delta, optionally summarizes it with the
LLM, and prepends a session entry to <cwd>/.sentinel/knowledge.json.

Contract:
  - stdin: JSON {"cwd": "...", "session_id": "..."}
  - errors: ALWAYS exit 0 silently.
"""

import os
import sys
import glob
import json
import subprocess
import urllib.request
from datetime import datetime, timezone

ZEUS_HOME = os.environ.get("ZEUS_PROMPTER_HOME") or os.path.expanduser("~/.zeus-prompter")
CONFIG_PATH = os.path.join(ZEUS_HOME, "core", "config.json")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_stdin_json():
    raw = sys.stdin.read()
    if not raw or not raw.strip():
        return {}
    return json.loads(raw)


def _git(cwd, args):
    try:
        out = subprocess.run(
            ["git"] + args, cwd=cwd,
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def _gather_changed_files(diff_stat):
    files = []
    for line in diff_stat.splitlines():
        line = line.strip()
        if "|" in line:
            name = line.split("|", 1)[0].strip()
            if name:
                files.append(name)
    return files


def _read_recent_log_tail(cwd, max_lines=30):
    try:
        logs = glob.glob(os.path.join(cwd, "*.log"))
        if not logs:
            return ""
        newest = max(logs, key=os.path.getmtime)
        with open(newest, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:])
    except Exception:
        return ""


def _summarize_with_llm(config, diff_stat, git_log):
    body = {
        "model": config["model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "Summarize what changed in this coding session in 2 "
                    "sentences. Be specific about files and what was fixed or added."
                ),
            },
            {
                "role": "user",
                "content": f"Changed files: {diff_stat}\nLatest commit: {git_log}",
            },
        ],
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {config['openrouter_api_key']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/zeus-prompter",
            "X-Title": "ZeusPrompter",
        },
        method="POST",
    )
    timeout = config.get("optimizer", {}).get("timeout_seconds", 25)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"].strip()


def _extract_error_patterns(cwd):
    """Pull fix:/bug: prefixed commit subjects from recent history."""
    log = _git(cwd, ["log", "--oneline", "-20"])
    patterns = []
    for line in log.splitlines():
        # Strip the short hash prefix.
        parts = line.split(" ", 1)
        msg = parts[1].strip().lower() if len(parts) > 1 else ""
        if msg.startswith("fix:") or msg.startswith("bug:"):
            patterns.append(parts[1].strip())
    return patterns


def main():
    try:
        data = _read_stdin_json()
    except Exception:
        sys.exit(0)

    cwd = data.get("cwd") or os.getcwd()
    session_id = data.get("session_id") or "unknown"

    try:
        config = _load_config()
    except Exception:
        sys.exit(0)

    if not config.get("enabled", False):
        sys.exit(0)

    kpath = os.path.join(cwd, ".sentinel", "knowledge.json")
    if not os.path.isfile(kpath):
        sys.exit(0)

    try:
        with open(kpath, "r", encoding="utf-8") as f:
            knowledge = json.load(f)
    except Exception:
        sys.exit(0)

    diff_stat = _git(cwd, ["diff", "--stat", "HEAD"])
    git_log = _git(cwd, ["log", "--oneline", "-1"])
    _read_recent_log_tail(cwd)  # captured for future use; not stored verbatim

    files_changed = _gather_changed_files(diff_stat)

    summary = git_log or "Session ended (no git changes detected)."
    upd_cfg = config.get("updater", {})
    if upd_cfg.get("summarize_with_llm", False) and config.get("openrouter_api_key") \
            and (diff_stat or git_log):
        try:
            summary = _summarize_with_llm(config, diff_stat, git_log)
        except Exception:
            summary = git_log or summary

    now = datetime.now(timezone.utc)
    session_entry = {
        "date": now.isoformat(),
        "session_id": session_id,
        "prompt_summary": summary,
        "files_changed": files_changed,
        "git_commit": git_log,
    }

    sessions = knowledge.get("recent_sessions", [])
    sessions.insert(0, session_entry)
    max_stored = upd_cfg.get("max_sessions_stored", 20)
    knowledge["recent_sessions"] = sessions[:max_stored]

    knowledge.setdefault("meta", {})["last_updated"] = now.isoformat()

    # Merge any newly discovered fix:/bug: patterns.
    try:
        new_patterns = _extract_error_patterns(cwd)
        existing = knowledge.get("error_patterns", [])
        for p in new_patterns:
            if p not in existing:
                existing.append(p)
        knowledge["error_patterns"] = existing
    except Exception:
        pass

    try:
        with open(kpath, "w", encoding="utf-8") as f:
            json.dump(knowledge, f, indent=2)
    except Exception:
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
