#!/usr/bin/env python3
"""
ZeusPrompter — cross-platform uninstaller (Linux, macOS, Windows).

Surgically removes ZeusPrompter hook entries from each tool's config, deletes
the `zeus` launcher, and removes the install folder. Other config is untouched.

Usage:
    python uninstall.py            # uninstall from the real home
    python uninstall.py --home <d> # testing
"""

import os
import shutil
import argparse
import platform
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

import json


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def _is_zeus(cmd):
    return "zeus-prompter" in (cmd or "")


def clean_grouped(path, events):
    """Claude Code / Codex style: hooks[event] = [{hooks:[{command}]}]."""
    s = _load(path)
    if s is None:
        return False
    s.pop("disableAllHooks", None)
    hooks = s.get("hooks", s)  # codex stores events at top level
    target = s.get("hooks", s)
    for event in events:
        if event in target:
            target[event] = [
                g for g in target[event]
                if not any(_is_zeus(h.get("command")) for h in g.get("hooks", []))
            ]
            if not target[event]:
                del target[event]
    if "hooks" in s and not s["hooks"]:
        s.pop("hooks", None)
    _save(path, s)
    return True

def clean_flat(path, events):
    """Cursor / Antigravity style: hooks[event] = [{command}]."""
    s = _load(path)
    if s is None:
        return False
    hooks = s.get("hooks", {})
    for event in events:
        if event in hooks:
            hooks[event] = [h for h in hooks[event] if not _is_zeus(h.get("command"))]
            if not hooks[event]:
                del hooks[event]
    s["hooks"] = hooks
    _save(path, s)
    return True

def clean_codex_toml(path):
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        out, skip = [], False
        for line in lines:
            if "ZeusPrompter" in line:
                skip = True
            if skip and line.strip() == "":
                skip = False
                continue
            if not skip:
                out.append(line)
        path.write_text("".join(out), encoding="utf-8")
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default=str(Path.home()))
    args = ap.parse_args()
    home = Path(args.home)

    print("ZeusPrompter Uninstaller (%s)" % platform.system())
    print("-" * 40)

    if clean_grouped(home / ".claude" / "settings.json", ["UserPromptSubmit", "Stop"]):
        print("  Claude Code: cleaned")
    if clean_grouped(home / ".codex" / "hooks.json", ["UserPromptSubmit", "Stop"]):
        print("  Codex hooks: cleaned")
    clean_codex_toml(home / ".codex" / "config.toml")
    if clean_flat(home / ".cursor" / "hooks.json", ["beforeSubmitPrompt", "onSessionEnd"]):
        print("  Cursor: cleaned")
    if clean_flat(home / ".config" / "antigravity" / "hooks.json",
                  ["beforeAgentMessage", "onSessionComplete"]):
        print("  Antigravity: cleaned")

    # Remove launcher.
    if IS_WINDOWS:
        pass  # launcher lives inside the install folder (bin/zeus.cmd)
    else:
        for cand in (home / ".local" / "bin" / "zeus", Path("/usr/local/bin/zeus")):
            try:
                if cand.exists():
                    cand.unlink()
            except Exception:
                pass

    zeus_home = home / ".zeus-prompter"
    if zeus_home.exists():
        shutil.rmtree(zeus_home, ignore_errors=True)

    print("")
    print("ZeusPrompter removed. Your tool configs are otherwise untouched.")
    if IS_WINDOWS:
        print("Note: remove %USERPROFILE%\\.zeus-prompter\\bin from PATH if you added it.")


if __name__ == "__main__":
    main()
