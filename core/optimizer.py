#!/usr/bin/env python3
"""
ZeusPrompter — optimizer.py

Called by every adapter hook when the user submits a prompt. Reads the raw
prompt + cwd from stdin, enriches it with project context from
<cwd>/.sentinel/knowledge.json, and asks an OpenRouter model to rewrite it for
precision and cost-efficiency.

Contract:
  - stdin: JSON {"prompt": "...", "cwd": "..."} (and possibly other keys)
  - stdout: the hookSpecificOutput JSON on success, or nothing on passthrough
  - errors: ALWAYS exit 0 silently so the user's workflow is never broken
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error

ZEUS_HOME = os.environ.get("ZEUS_PROMPTER_HOME") or os.path.expanduser("~/.zeus-prompter")
CONFIG_PATH = os.path.join(ZEUS_HOME, "core", "config.json")
SCANNER_PATH = os.path.join(ZEUS_HOME, "core", "scanner.py")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a prompt optimizer for AI coding agents (Claude Code, Codex, Cursor, Antigravity).
Your ONLY job is to rewrite the user's raw prompt to be precise, complete, and cost-efficient.

Rules:
- Preserve the user's intent 100%. Never change what they want to do.
- Add relevant file paths, function names, or module names from the project context when they make the prompt more precise.
- Resolve ambiguity: "fix this bug" -> "fix the null pointer in src/auth/login.py line 47"
- Add constraints the user likely forgot: "don't break existing tests", "follow the existing code style"
- Match the output's complexity to the input's: a short, simple prompt gets a tight rewrite; a long, detailed prompt gets a full, detailed rewrite. Never truncate, never pad.
- If the prompt is already precise and complete, return it unchanged.
- Output ONLY the optimized prompt. No preamble, no explanation, no markdown."""


def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_stdin_json():
    raw = sys.stdin.read()
    if not raw or not raw.strip():
        return {}
    return json.loads(raw)


def _load_knowledge(cwd):
    """Load knowledge.json, running the scanner first if it does not exist."""
    kpath = os.path.join(cwd, ".sentinel", "knowledge.json")
    if not os.path.isfile(kpath):
        try:
            # Import scanner directly to avoid spawning a subprocess.
            sys.path.insert(0, os.path.join(ZEUS_HOME, "core"))
            import scanner  # type: ignore
            scanner.scan(cwd)
        except Exception:
            # Fall back to subprocess if direct import fails.
            try:
                import subprocess
                subprocess.run(
                    [sys.executable, SCANNER_PATH, cwd],
                    capture_output=True, timeout=20,
                )
            except Exception:
                return None
    if not os.path.isfile(kpath):
        return None
    try:
        with open(kpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _build_context(knowledge, max_chars):
    if not knowledge:
        return ""
    proj = knowledge.get("project", {})
    parts = []
    parts.append(f"Project: {proj.get('name', 'unknown')}")
    stack = proj.get("stack") or []
    if stack:
        parts.append(f"Stack: {', '.join(stack)}")
    if proj.get("package_manager"):
        parts.append(f"Package manager: {proj['package_manager']}")
    if proj.get("test_command"):
        parts.append(f"Test command: {proj['test_command']}")
    if proj.get("entry_points"):
        parts.append(f"Entry points: {', '.join(proj['entry_points'])}")

    tree = knowledge.get("file_tree_summary", {})
    if tree:
        top = tree.get(".", {})
        top_dirs = top.get("dirs", [])
        top_files = top.get("files", [])
        if top_dirs:
            parts.append(f"Top-level dirs: {', '.join(top_dirs[:25])}")
        if top_files:
            parts.append(f"Top-level files: {', '.join(top_files[:25])}")

    sessions = knowledge.get("recent_sessions", [])[:3]
    if sessions:
        parts.append("Recent sessions:")
        for s in sessions:
            summary = s.get("prompt_summary", "")
            files = s.get("files_changed", [])
            files_str = f" (files: {', '.join(files[:5])})" if files else ""
            parts.append(f"  - {summary}{files_str}")

    issues = knowledge.get("open_issues", [])
    if issues:
        parts.append("Open issues: " + "; ".join(str(i) for i in issues[:5]))

    errors = knowledge.get("error_patterns", [])
    if errors:
        parts.append("Known error patterns: " + "; ".join(str(e) for e in errors[:5]))

    context = "\n".join(parts)
    if len(context) > max_chars:
        context = context[:max_chars] + "..."
    return context


def _looks_like_pasted_code(prompt):
    """Detect prompts that are mostly pasted code (which we should not rewrite).

    Only treat large inputs as code when they carry real code signals — this
    avoids skipping long, legitimate natural-language feature descriptions.
    """
    if len(prompt) <= 800:
        return False
    if "```" in prompt:
        return True
    # Count total occurrences of structural code signals (not distinct types),
    # so a tight block using few constructs many times is still recognized.
    code_signals = (
        "def ", "function ", "class ", "import ", "#include",
        "public ", "private ", "return ", "const ", "let ", "var ",
        "=>", "};", "());", "</", "/>",
    )
    occurrences = sum(prompt.count(sig) for sig in code_signals)
    # Indented lines are another strong code signal.
    indented_lines = sum(
        1 for line in prompt.splitlines() if line[:1] in (" ", "\t") and line.strip()
    )
    return occurrences >= 4 or indented_lines >= 6


def _max_output_tokens(prompt):
    """Scale max_tokens with prompt length.

    Short prompts still get room to expand; longer prompts scale up
    proportionally. The result is always clamped to [300, 1500].
    """
    approx_input_tokens = len(prompt) // 4  # ~4 chars per token
    scaled = 256 + approx_input_tokens * 3
    return max(300, min(1500, scaled))


def _call_openrouter(config, context, prompt):
    user_message = (
        "PROJECT CONTEXT:\n"
        f"{context}\n\n"
        "USER'S RAW PROMPT:\n"
        f"{prompt}\n\n"
        "Rewrite this prompt for maximum clarity and cost-efficiency. "
        "Output only the rewritten prompt."
    )
    body = {
        "model": config["model"],
        "max_tokens": _max_output_tokens(prompt),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
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
    # One short retry on a transient 429/503 — kept brief so we stay within the
    # hook's overall timeout. Any remaining failure bubbles up to a passthrough.
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt == 0:
                time.sleep(1.5)
                continue
            raise


def main():
    try:
        data = _read_stdin_json()
    except Exception:
        sys.exit(0)

    prompt = (data.get("prompt") or "").strip()
    cwd = data.get("cwd") or os.getcwd()

    if not prompt:
        sys.exit(0)

    try:
        config = _load_config()
    except Exception:
        sys.exit(0)

    # Global kill switch.
    if not config.get("enabled", False):
        sys.exit(0)

    opt_cfg = config.get("optimizer", {})
    min_len = opt_cfg.get("min_prompt_length", 20)

    # Passthrough short prompts and slash commands.
    if len(prompt) < min_len:
        sys.exit(0)
    if prompt.startswith("/"):
        sys.exit(0)

    # Passthrough large pasted code blocks (only when it really looks like code).
    if _looks_like_pasted_code(prompt):
        sys.exit(0)

    if not config.get("openrouter_api_key"):
        sys.exit(0)

    knowledge = _load_knowledge(cwd)
    context = _build_context(knowledge, opt_cfg.get("max_context_tokens", 2000))

    try:
        optimized = _call_openrouter(config, context, prompt)
    except Exception:
        # Any failure -> silent passthrough.
        sys.exit(0)

    if not optimized:
        sys.exit(0)

    additional_context = (
        f'[ZeusPrompter] Original: "{prompt}"\n'
        f"[ZeusPrompter] Optimized: {optimized}\n\n"
        "Use the OPTIMIZED prompt above as your actual task."
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional_context,
        }
    }
    sys.stdout.write(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
