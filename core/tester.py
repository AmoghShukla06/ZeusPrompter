#!/usr/bin/env python3
"""
ZeusPrompter — tester.py

One-shot live connectivity check: confirms the configured OpenRouter API key
and model can be reached. Run after install to verify the optimizer's API path
without submitting a real prompt.

Usage:
    python3 ~/.zeus-prompter/core/tester.py

Exit codes: 0 = reachable, 1 = failure (prints reason to stderr).
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error

ZEUS_HOME = os.environ.get("ZEUS_PROMPTER_HOME") or os.path.expanduser("~/.zeus-prompter")
CONFIG_PATH = os.path.join(ZEUS_HOME, "core", "config.json")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def ping(config):
    body = {
        "model": config["model"],
        # A tiny ceiling is fine for a connectivity ping; production calls in
        # optimizer.py scale max_tokens dynamically with prompt length instead.
        "max_tokens": 80,
        "messages": [
            {"role": "user", "content": "Reply with the single word: pong"},
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
    # Retry transient rate-limits / server errors with short backoff.
    delays = [2, 4, 8]
    for attempt in range(len(delays) + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < len(delays):
                wait = delays[attempt]
                print(f"[ZeusPrompter] {e.code} from API; retrying in {wait}s "
                      f"({attempt + 1}/{len(delays)})...", file=sys.stderr)
                time.sleep(wait)
                continue
            raise


def main():
    try:
        config = _load_config()
    except Exception as e:
        print(f"[ZeusPrompter] Could not read config: {e}", file=sys.stderr)
        sys.exit(1)

    if not config.get("openrouter_api_key"):
        print("[ZeusPrompter] No API key set in config.json.", file=sys.stderr)
        sys.exit(1)

    try:
        reply = ping(config)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("[ZeusPrompter] Rate limited (HTTP 429) after retries.\n"
                  "  Your key works — this is the free model's rate limit.\n"
                  "  - Per-minute limit: wait ~60s and run 'zeus test' again.\n"
                  "  - Daily free cap: add a small OpenRouter credit balance,\n"
                  "    or switch models, e.g.  zeus model meta-llama/llama-3.3-70b-instruct:free\n"
                  "  Meanwhile Claude Code still works — prompts pass through unoptimized.",
                  file=sys.stderr)
        elif e.code == 401:
            print("[ZeusPrompter] Unauthorized (401): the API key is invalid. "
                  "Set it with: zeus key <KEY>", file=sys.stderr)
        else:
            print(f"[ZeusPrompter] API check failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ZeusPrompter] API check failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[ZeusPrompter] OK — model '{config['model']}' reachable. Reply: {reply}")
    sys.exit(0)


if __name__ == "__main__":
    main()
