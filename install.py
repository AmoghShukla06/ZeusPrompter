#!/usr/bin/env python3
"""
ZeusPrompter — cross-platform installer (Linux, macOS, Windows).

Why Python instead of a shell script: Python is already required by the core
scripts and behaves identically on all three OSes, so a single installer works
everywhere. Hook commands are wired with this interpreter's absolute path
(sys.executable), which sidesteps the python/python3 difference between OSes.

Usage:
    python install.py                 # interactive (prompts for API key)
    python install.py --key sk-...    # non-interactive
    OPENROUTER_API_KEY=sk-... python install.py
Optional (mainly for testing):
    python install.py --home <dir> --no-path
"""

import os
import sys
import json
import shutil
import argparse
import platform
import subprocess
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"
SCRIPT_DIR = Path(__file__).resolve().parent
COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc")


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def hook_command(pyexe, script_path):
    """A shell-safe 'python script' command string for a hook config."""
    return f'"{pyexe}" "{script_path}"'

def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default

def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def already_wired(commands):
    """True if any command string already references our install."""
    return any("zeus-prompter" in (c or "") for c in commands)


# ----------------------------------------------------------------------------
# install steps
# ----------------------------------------------------------------------------
def copy_repo(zeus_home):
    if SCRIPT_DIR == zeus_home:
        return  # already running from the install location
    zeus_home.mkdir(parents=True, exist_ok=True)
    for item in SCRIPT_DIR.iterdir():
        if item.name in (".git", "__pycache__"):
            continue
        dest = zeus_home / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True, ignore=COPY_IGNORE)
        else:
            shutil.copy2(item, dest)

def write_config(zeus_home, api_key):
    cfg_path = zeus_home / "core" / "config.json"
    # Preserve any existing user toggles; only (re)set the key.
    cfg = load_json(cfg_path)
    if not cfg:
        cfg = load_json(SCRIPT_DIR / "core" / "config.json")
    if api_key:
        cfg["openrouter_api_key"] = api_key
    cfg.setdefault("enabled", True)
    write_json(cfg_path, cfg)
    return cfg_path

def wire_claude_code(home, opt_cmd, upd_cmd):
    path = home / ".claude" / "settings.json"
    settings = load_json(path)
    hooks = settings.get("hooks", {})

    def ensure(event, command, extra):
        groups = hooks.get(event, [])
        existing = [h.get("command", "") for g in groups for h in g.get("hooks", [])]
        if already_wired(existing):
            return False
        entry = {"type": "command", "command": command}
        entry.update(extra)
        groups.append({"hooks": [entry]})
        hooks[event] = groups
        return True

    added = ensure("UserPromptSubmit", opt_cmd, {"timeout": 28})
    added = ensure("Stop", upd_cmd, {"async": True, "timeout": 30}) or added
    settings["hooks"] = hooks
    write_json(path, settings)
    return True, "wired" if added else "already wired"

def wire_codex(home, opt_cmd, upd_cmd):
    path = home / ".codex" / "hooks.json"
    data = load_json(path)
    for event, command, extra in (
        ("UserPromptSubmit", opt_cmd, {"timeout": 28}),
        ("Stop", upd_cmd, {"async": True}),
    ):
        groups = data.get(event, [])
        existing = [h.get("command", "") for g in groups for h in g.get("hooks", [])]
        if not already_wired(existing):
            entry = {"type": "command", "command": command}
            entry.update(extra)
            groups.append({"hooks": [entry]})
            data[event] = groups
    write_json(path, data)
    # feature flag
    toml_path = home / ".codex" / "config.toml"
    block = "\n# ZeusPrompter — do not remove this block\n[features]\ncodex_hooks = true\n"
    try:
        text = toml_path.read_text(encoding="utf-8") if toml_path.exists() else ""
        if "codex_hooks = true" not in text:
            toml_path.write_text(text + block, encoding="utf-8")
    except Exception:
        pass
    return True, "wired"

def wire_flat_hooks(home, rel_dir, submit_event, end_event, opt_cmd, upd_cmd):
    """Cursor / Antigravity style: {version, hooks:{event:[{command}]}}."""
    path = home.joinpath(*rel_dir) / "hooks.json"
    data = load_json(path)
    data.setdefault("version", 1)
    hooks = data.get("hooks", {})
    for event, command in ((submit_event, opt_cmd), (end_event, upd_cmd)):
        handlers = hooks.get(event, [])
        existing = [h.get("command", "") for h in handlers]
        if not already_wired(existing):
            handlers.append({"command": command})
            hooks[event] = handlers
    data["hooks"] = hooks
    write_json(path, data)
    return True, "wired"

def install_launcher(zeus_home, home, add_to_path):
    """Create a `zeus` command for the current OS."""
    pyexe = sys.executable
    zeus_py = zeus_home / "zeus.py"
    if IS_WINDOWS:
        # zeus.cmd wrapper inside a bin dir we control.
        bindir = zeus_home / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        cmd_path = bindir / "zeus.cmd"
        cmd_path.write_text(f'@echo off\r\n"{pyexe}" "{zeus_py}" %*\r\n', encoding="utf-8")
        note = f"zeus command: {cmd_path}"
        if str(bindir) not in os.environ.get("PATH", ""):
            # We deliberately do NOT auto-edit PATH (setx can truncate a long
            # PATH at 1024 chars). Offer a safe, opt-in one-liner instead.
            note += (
                "\n  To use `zeus` from any terminal, run this once in PowerShell:\n"
                f'    [Environment]::SetEnvironmentVariable("Path",'
                f' [Environment]::GetEnvironmentVariable("Path","User") + ";{bindir}", "User")\n'
                f'  Or just call it directly:  "{cmd_path}" status'
            )
        return note
    else:
        # Prefer ~/.local/bin (no sudo); fall back to /usr/local/bin.
        candidates = [home / ".local" / "bin", Path("/usr/local/bin")]
        for bindir in candidates:
            try:
                bindir.mkdir(parents=True, exist_ok=True)
                link = bindir / "zeus"
                wrapper = f'#!/usr/bin/env bash\nexec "{pyexe}" "{zeus_py}" "$@"\n'
                link.write_text(wrapper, encoding="utf-8")
                link.chmod(0o755)
                note = f"zeus command: {link}"
                if str(bindir) not in os.environ.get("PATH", ""):
                    note += f"\n  (add {bindir} to your PATH if `zeus` isn't found)"
                return note
            except Exception:
                continue
        return f"Could not create launcher; run: {pyexe} {zeus_py} <on|off|status>"


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Install ZeusPrompter (cross-platform).")
    ap.add_argument("--home", default=str(Path.home()), help="target home dir (testing)")
    ap.add_argument("--key", default=os.environ.get("OPENROUTER_API_KEY", ""),
                    help="OpenRouter API key (else prompts)")
    ap.add_argument("--no-path", action="store_true", help="don't modify PATH")
    args = ap.parse_args()

    home = Path(args.home)
    zeus_home = home / ".zeus-prompter"

    print("")
    print("ZeusPrompter Installer  (%s)" % platform.system())
    print("-" * 45)

    print("[1/6] Installing to %s ..." % zeus_home)
    copy_repo(zeus_home)

    api_key = args.key
    if not api_key:
        try:
            api_key = input("[2/6] Enter your OpenRouter API key (free at openrouter.ai)\n      (leave blank to set later with `zeus key <KEY>`): ").strip()
        except EOFError:
            api_key = ""
    else:
        print("[2/6] Using API key from --key/env.")

    print("[3/6] Writing config ...")
    write_config(zeus_home, api_key)

    pyexe = sys.executable
    core = zeus_home / "core"
    opt_cmd = hook_command(pyexe, core / "optimizer.py")
    upd_cmd = hook_command(pyexe, core / "updater.py")

    print("[4/6] Wiring tools ...")
    results = {}
    try:
        _, msg = wire_claude_code(home, opt_cmd, upd_cmd); results["Claude Code"] = msg
    except Exception as e:
        results["Claude Code"] = f"FAILED: {e}"
    try:
        _, msg = wire_codex(home, opt_cmd, upd_cmd); results["Codex"] = msg + " (best-effort)"
    except Exception as e:
        results["Codex"] = f"FAILED: {e}"
    try:
        _, msg = wire_flat_hooks(home, (".cursor",), "beforeSubmitPrompt",
                                 "onSessionEnd", opt_cmd, upd_cmd)
        results["Cursor"] = msg + " (best-effort)"
    except Exception as e:
        results["Cursor"] = f"FAILED: {e}"
    try:
        _, msg = wire_flat_hooks(home, (".config", "antigravity"), "beforeAgentMessage",
                                 "onSessionComplete", opt_cmd, upd_cmd)
        results["Antigravity"] = msg + " (best-effort path)"
    except Exception as e:
        results["Antigravity"] = f"FAILED: {e}"
    for tool, msg in results.items():
        print(f"      {tool:<13} {msg}")

    print("[5/6] Creating `zeus` command ...")
    launcher_note = install_launcher(zeus_home, home, add_to_path=not args.no_path)

    print("[6/6] Done.")
    print("-" * 45)
    print(launcher_note)
    print("")
    if not api_key:
        print("!! No API key set yet. Run:  zeus key <YOUR_OPENROUTER_KEY>")
    print("Verify the API path with:   zeus test")
    print("Controls:  zeus on | zeus off | zeus status")
    print("")
    print("Claude Code is fully wired (settings.json). For the VS Code")
    print("extension, reload the window so it re-reads settings.json.")
    print("")


if __name__ == "__main__":
    main()
