#!/usr/bin/env python3
"""
ZeusPrompter — cross-platform kill switch & control (Linux, macOS, Windows).

Commands:
    zeus on                       enable globally
    zeus off                      pause globally (all tools pass through)
    zeus on  --tool cursor        enable one tool
    zeus off --tool cursor        pause one tool
    zeus status                   show current state
    zeus key  <KEY>               set the OpenRouter API key
    zeus test                     live API connectivity check
"""

import os
import sys
import json
from pathlib import Path

ZEUS_HOME = Path(os.environ.get("ZEUS_PROMPTER_HOME", Path.home() / ".zeus-prompter"))
CONFIG = ZEUS_HOME / "core" / "config.json"


def _load():
    with open(CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)

def _save(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

def _toggle_claude_hooks(disable):
    """Mirror the global switch into Claude Code for instant effect."""
    p = Path.home() / ".claude" / "settings.json"
    if not p.exists():
        return
    try:
        with open(p, "r", encoding="utf-8") as f:
            s = json.load(f)
        if disable:
            s["disableAllHooks"] = True
        else:
            s.pop("disableAllHooks", None)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass


def cmd_on(tool):
    cfg = _load()
    if tool:
        cfg.setdefault("tools", {})[tool] = True
        _save(cfg)
        print(f"ZeusPrompter: {tool} resumed.")
    else:
        cfg["enabled"] = True
        _save(cfg)
        _toggle_claude_hooks(disable=False)
        print("ZeusPrompter: ACTIVE globally on all tools.")

def cmd_off(tool):
    cfg = _load()
    if tool:
        cfg.setdefault("tools", {})[tool] = False
        _save(cfg)
        print(f"ZeusPrompter: {tool} paused. Run 'zeus on --tool {tool}' to resume.")
    else:
        cfg["enabled"] = False
        _save(cfg)
        _toggle_claude_hooks(disable=True)
        print("ZeusPrompter: PAUSED globally. All tools pass prompts through unchanged.")

def cmd_status():
    cfg = _load()
    enabled = cfg.get("enabled", False)
    print("")
    print("ZeusPrompter Status")
    print("-" * 30)
    print(f"  Global:    {'ACTIVE' if enabled else 'PAUSED'}")
    print(f"  Model:     {cfg.get('model', 'unknown')}")
    print("  Tools:")
    for tool, active in cfg.get("tools", {}).items():
        print(f"    {tool:<14} {'on' if active else 'off'}")
    key = cfg.get("openrouter_api_key", "")
    masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "(not set)"
    print(f"  API Key:   {masked}")
    print("")

def cmd_key(value):
    if not value:
        print("Usage: zeus key <YOUR_OPENROUTER_KEY>", file=sys.stderr)
        sys.exit(1)
    cfg = _load()
    cfg["openrouter_api_key"] = value
    _save(cfg)
    print("ZeusPrompter: API key saved. Run 'zeus test' to verify.")

def cmd_model(value):
    cfg = _load()
    if not value:
        print(f"Current model: {cfg.get('model', 'unknown')}")
        print("Set with: zeus model <openrouter-model-id>")
        return
    cfg["model"] = value
    _save(cfg)
    print(f"ZeusPrompter: model set to '{value}'. Run 'zeus test' to verify.")

def cmd_test():
    tester = ZEUS_HOME / "core" / "tester.py"
    os.execv(sys.executable, [sys.executable, str(tester)])


def usage():
    print("Usage: zeus <on|off|status|key|model|test> [--tool <name>] [VALUE]", file=sys.stderr)
    sys.exit(1)


def main():
    args = sys.argv[1:]
    if not args:
        usage()
    cmd = args[0]
    tool = None
    rest = []
    i = 1
    while i < len(args):
        if args[i] == "--tool" and i + 1 < len(args):
            tool = args[i + 1]; i += 2
        else:
            rest.append(args[i]); i += 1

    if not CONFIG.exists() and cmd != "test":
        print(f"ZeusPrompter not installed (no config at {CONFIG}).", file=sys.stderr)
        sys.exit(1)

    if cmd == "on":
        cmd_on(tool)
    elif cmd == "off":
        cmd_off(tool)
    elif cmd == "status":
        cmd_status()
    elif cmd == "key":
        cmd_key(rest[0] if rest else "")
    elif cmd == "model":
        cmd_model(rest[0] if rest else "")
    elif cmd == "test":
        cmd_test()
    else:
        usage()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # robust on Windows consoles
    except Exception:
        pass
    main()
