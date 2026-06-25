# ⚡ ZeusPrompter

ZeusPrompter is a zero-config, globally-installed prompt optimizer that sits between you and your AI coding agent. Every time you submit a prompt in **Claude Code**, **Codex CLI**, **Cursor**, or **Google Antigravity**, ZeusPrompter intercepts it *before the AI sees it*, enriches it with live project context from a self-building knowledge database, and runs it through `qwen/qwen3-coder:free` on OpenRouter to produce a tighter, more precise, more cost-efficient prompt — then hands that to your agent. One install wires up all four tools, and a one-command kill switch turns it off instantly with no restart.

## Install

ZeusPrompter installs with a single **cross-platform Python installer** (works on Linux, macOS, and Windows — no bash required):

```bash
git clone <repo-url> zeus-prompter
cd zeus-prompter
python install.py            # use "python3" on Linux/macOS if that's your launcher
```

> **Windows note:** run `python install.py` from PowerShell or a terminal. Do **not** double-click or `./install.sh` — `.sh` files aren't executable on Windows and will just open in an editor.

The installer copies the project to `~/.zeus-prompter`, asks once for your free [OpenRouter](https://openrouter.ai) API key (you can leave it blank and set it later), wires the hooks into all four tools using your actual Python interpreter path, and creates a `zeus` command. Running it twice is safe — it never duplicates hook entries.

If you skipped the key during install, set it any time:

```bash
zeus key sk-or-your-key-here
zeus test                    # one-shot live check that the key + model work
```

**Claude Code:** the CLI picks up the hook immediately. For the **VS Code extension**, reload the window so it re-reads `~/.claude/settings.json`.

## Kill switch

```bash
zeus off                     # pause globally (all 4 tools pass prompts through unchanged)
zeus on                      # resume globally
zeus status                  # show current state, model, and per-tool toggles
zeus off --tool cursor       # pause just one tool
zeus on  --tool cursor       # resume just one tool
zeus key   <KEY>             # set/replace the OpenRouter API key
zeus model <id>              # switch the OpenRouter model (no args = show current)
zeus test                    # live API connectivity check
```

If the `zeus` command isn't on your PATH yet, call it directly:
`python ~/.zeus-prompter/zeus.py status` (Windows: `%USERPROFILE%\.zeus-prompter\bin\zeus.cmd status`).

The switch flips a flag in `~/.zeus-prompter/core/config.json` (and toggles Claude Code's `disableAllHooks`) — it takes effect in under a second with no tool restart.

## Using it after install

**There is no command to "optimize" a prompt — it's automatic.** Once installed and active (`zeus status` shows `Global: ACTIVE`), you simply use your AI tool as normal:

1. **One-time:** in the Claude Code **VS Code extension**, reload the window (`Ctrl/Cmd+Shift+P` → *Developer: Reload Window*) so it reads the new hooks. The **CLI** picks them up on next launch.
2. Open any project and type prompts the way you always do — even short, sloppy ones.
3. ZeusPrompter quietly rewrites each prompt with your project context before the agent acts on it. You'll notice the agent responding to a sharper version of what you asked.

The `zeus` commands (`on`/`off`/`status`/`model`/`key`/`test`) are **only for control** — you never need them for everyday use.

> **`zeus` not found in your terminal?** PATH changes only apply to newly launched terminals, and editors like VS Code cache the environment at startup — fully restart the editor (not just the terminal tab). To use it immediately in the current shell, call it by full path: `python ~/.zeus-prompter/zeus.py status` (Windows: `%USERPROFILE%\.zeus-prompter\bin\zeus.cmd status`).

## How it works

```
your prompt ─▶ tool hook ─▶ optimizer.py ─▶ OpenRouter (qwen3-coder:free) ─▶ optimized prompt ─▶ agent
                                  ▲
                                  └── reads <project>/.sentinel/knowledge.json

session end ─▶ tool hook ─▶ updater.py ─▶ writes a session summary back to knowledge.json
```

- **`optimizer.py`** runs on every prompt submit. It loads project context, asks the model to rewrite your prompt for clarity and cost, and returns it. Short prompts (< 20 chars), slash commands, and large pasted code blocks pass through untouched.
- **`updater.py`** runs at session end. It reads your `git diff`/`git log`, summarizes what changed, and prepends an entry to the knowledge base so future prompts get smarter context.
- **`scanner.py`** runs automatically the first time you use ZeusPrompter in a project, building the initial knowledge base.

### A real example

You don't change how you work — you keep typing short, lazy prompts. Say you type this in Claude Code:

> add error handling to the optimizer api call so failures dont crash anything

ZeusPrompter rewrites it, using what it knows about your project, into:

> Add robust error handling to the optimizer API call (e.g., in `core/optimizer.py`). Wrap the request in a try/except block, catch network and response errors, log the exception, and return a safe fallback value so that any failure does not crash the application. Ensure the new handling respects existing code style and does not break the current test suite.

Your agent never sees the vague version as the task — it works on the precise one. Importantly, ZeusPrompter **doesn't delete your words**: the agent receives *both* (`Original:` and `Optimized:`) plus a note to act on the optimized one, so nothing is lost.

**If anything fails** — network down, API timeout, rate limit, bad config — ZeusPrompter exits silently and your original prompt goes through unchanged. It never blocks your workflow.

## Supported tools

| Tool | Submit hook | Session-end hook |
|------|-------------|------------------|
| Claude Code | `UserPromptSubmit` | `Stop` |
| Codex CLI | `UserPromptSubmit` | `Stop` |
| Cursor | `beforeSubmitPrompt` | `onSessionEnd` |
| Antigravity | `beforeAgentMessage` | `onSessionComplete` |

> **Verification status:** Claude Code is fully verified across Linux, macOS, and Windows — its config (`~/.claude/settings.json`) is identical on all three. Codex, Cursor, and Antigravity are wired at their best-known config paths but are **best-effort**; confirm the hook fired inside each app the first time you use it.

## The knowledge database

Each project gets a `.sentinel/knowledge.json` file (auto-added to `.gitignore`). It is the only thing ZeusPrompter writes during normal use, and it lives in your project — never in the install folder. It contains:

- **project**: name, detected stack, package manager, test command, entry points
- **file_tree_summary**: a 2-level-deep map of your repo (skipping `node_modules`, `.git`, `dist`, etc.)
- **recent_sessions**: rolling summaries of what changed in recent sessions (capped, configurable)
- **known_patterns / open_issues / error_patterns**: accumulated signal mined from commit history

## FAQ

**Does it slow down my prompts?**
A little — one API round-trip to a fast free model, bounded by a configurable timeout (default 25s). If the model is slow or unreachable, ZeusPrompter gives up and sends your original prompt.

**What if the API is down or rate-limited?**
Your prompt goes through unchanged. Every external call is wrapped so a failure is invisible to you. On a transient `429`/`503`, the optimizer retries once briefly (and `zeus test` retries up to three times with backoff) before falling back to passthrough.

**Which model should I use?**
The default is `qwen/qwen3-coder:free`. Free models share a tight per-minute and daily rate limit, so under load you'll occasionally get an un-optimized (passthrough) prompt. For reliable optimization on every prompt, switch to a cheap paid model — `zeus model openai/gpt-4o-mini` is fast and costs a fraction of a cent per call.

**Is my code sent to OpenRouter?**
No file contents are sent. Only your prompt plus a compact context summary (project name, stack, top-level file/dir names, and short session summaries) is transmitted — capped at ~2000 characters.

**Where's my API key?**
In `~/.zeus-prompter/core/config.json`. It is never hardcoded and never committed.

## Troubleshooting

**`zeus test` → `HTTP 429: Too Many Requests`**
Your key works (a bad key returns `401`); you've hit the free model's rate limit.
- *Per-minute limit:* wait ~60s and run `zeus test` again.
- *Daily free cap* (shared across all `:free` models, tied to your credit balance): retrying or switching free models won't help that day. Either add a small OpenRouter credit balance, or switch to a cheap paid model: `zeus model openai/gpt-4o-mini`.

Either way, Claude Code keeps working — prompts just pass through unoptimized until the limit clears.

**`zeus test` → `401 Unauthorized`** — the key is invalid. Re-set it: `zeus key <KEY>`.

**`zeus: command not found`** — the launcher isn't on your PATH. Call it directly with `python ~/.zeus-prompter/zeus.py <cmd>` (Windows: `%USERPROFILE%\.zeus-prompter\bin\zeus.cmd <cmd>`), or add the printed `bin` folder to your PATH.

**Optimization isn't happening in the VS Code extension** — reload the window (Ctrl/Cmd+Shift+P → "Developer: Reload Window") so the Claude Code extension re-reads `~/.claude/settings.json`. Also check `zeus status` shows `Global: ACTIVE`.

**`./install.sh` opened a text editor (Windows)** — `.sh` files aren't run on Windows. Use `python install.py` instead.

## Uninstall

```bash
python ~/.zeus-prompter/uninstall.py
```

This surgically removes ZeusPrompter's hook entries from each tool's config, deletes the `zeus` launcher, and removes the install folder — leaving the rest of your tool configs untouched. Per-project `.sentinel/` folders are left in place; delete them manually if you want.
