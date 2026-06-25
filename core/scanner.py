#!/usr/bin/env python3
"""
ZeusPrompter — scanner.py

First-run project scanner. Builds <cwd>/.sentinel/knowledge.json by inspecting
the project: tech stack, package manager, file tree, README, and git log.

Runs automatically (invoked by optimizer.py) when knowledge.json does not yet
exist for a project. Silent on success; only prints a notice to stderr.
"""

import os
import sys
import json
import subprocess
from datetime import datetime, timezone

ZEUS_VERSION = "1.0.0"

# Directories we never descend into when building the file tree summary.
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".next", "dist", "build",
    "venv", ".venv", ".sentinel", ".idea", ".vscode", "target",
    "coverage", ".pytest_cache", ".mypy_cache",
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _safe_read(path, limit=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit) if limit else f.read()
    except Exception:
        return None


def _detect_stack(cwd):
    """Return (stack_list, package_manager_hint, entry_points)."""
    stack = []
    entry_points = []

    # --- Node.js / JavaScript ---
    pkg_path = os.path.join(cwd, "package.json")
    if os.path.isfile(pkg_path):
        stack.append("Node.js")
        raw = _safe_read(pkg_path)
        if raw:
            try:
                pkg = json.loads(raw)
            except Exception:
                pkg = {}
            deps = {}
            deps.update(pkg.get("dependencies", {}) or {})
            deps.update(pkg.get("devDependencies", {}) or {})
            framework_map = {
                "next": "Next.js",
                "react": "React",
                "react-dom": "React",
                "vue": "Vue",
                "@angular/core": "Angular",
                "svelte": "Svelte",
                "express": "Express",
                "fastify": "Fastify",
                "nestjs": "NestJS",
                "@nestjs/core": "NestJS",
                "vite": "Vite",
                "typescript": "TypeScript",
                "jest": "Jest",
                "vitest": "Vitest",
            }
            for dep, label in framework_map.items():
                if dep in deps and label not in stack:
                    stack.append(label)
            main = pkg.get("main")
            if main:
                entry_points.append(main)

    # --- Python ---
    pyproject = os.path.join(cwd, "pyproject.toml")
    requirements = os.path.join(cwd, "requirements.txt")
    if os.path.isfile(pyproject) or os.path.isfile(requirements):
        if "Python" not in stack:
            stack.append("Python")
        pkgs = []
        if os.path.isfile(requirements):
            raw = _safe_read(requirements) or ""
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name = line.split("==")[0].split(">=")[0].split("<=")[0]
                name = name.split("[")[0].split("~")[0].strip()
                if name:
                    pkgs.append(name)
        if os.path.isfile(pyproject):
            raw = _safe_read(pyproject) or ""
            # Lightweight extraction of dependency names without a TOML parser.
            for line in raw.splitlines():
                line = line.strip().strip('"').strip("'")
                for fw in ("django", "flask", "fastapi", "pytest", "numpy",
                           "pandas", "torch", "tensorflow"):
                    if line.lower().startswith(fw) and fw not in pkgs:
                        pkgs.append(fw)
        for fw_label in ("django", "flask", "fastapi"):
            if any(p.lower() == fw_label for p in pkgs):
                label = fw_label.capitalize() if fw_label != "fastapi" else "FastAPI"
                if label not in stack:
                    stack.append(label)
        for ep in ("main.py", "app.py", "manage.py", "__main__.py"):
            if os.path.isfile(os.path.join(cwd, ep)):
                entry_points.append(ep)

    # --- Go ---
    gomod = os.path.join(cwd, "go.mod")
    if os.path.isfile(gomod):
        if "Go" not in stack:
            stack.append("Go")
        raw = _safe_read(gomod) or ""
        for line in raw.splitlines():
            if line.startswith("module "):
                entry_points.append(line.split("module ", 1)[1].strip())
                break

    # --- Rust ---
    if os.path.isfile(os.path.join(cwd, "Cargo.toml")):
        if "Rust" not in stack:
            stack.append("Rust")

    # --- Java / JVM ---
    if os.path.isfile(os.path.join(cwd, "pom.xml")):
        if "Java" not in stack:
            stack.append("Java")
        stack.append("Maven")
    if os.path.isfile(os.path.join(cwd, "build.gradle")) or \
       os.path.isfile(os.path.join(cwd, "build.gradle.kts")):
        if "Java" not in stack and "Kotlin" not in stack:
            stack.append("Java")
        if "Gradle" not in stack:
            stack.append("Gradle")

    return stack, entry_points


def _detect_package_manager(cwd):
    lockfiles = [
        ("package-lock.json", "npm"),
        ("yarn.lock", "yarn"),
        ("pnpm-lock.yaml", "pnpm"),
        ("bun.lockb", "bun"),
        ("poetry.lock", "poetry"),
        ("Pipfile.lock", "pipenv"),
    ]
    for fname, mgr in lockfiles:
        if os.path.isfile(os.path.join(cwd, fname)):
            return mgr
    return None


def _detect_test_command(cwd, package_manager):
    pkg_path = os.path.join(cwd, "package.json")
    if os.path.isfile(pkg_path):
        raw = _safe_read(pkg_path)
        if raw:
            try:
                pkg = json.loads(raw)
                if "test" in (pkg.get("scripts") or {}):
                    runner = package_manager or "npm"
                    return f"{runner} test" if runner != "npm" else "npm test"
            except Exception:
                pass
    if os.path.isfile(os.path.join(cwd, "pytest.ini")) or \
       os.path.isfile(os.path.join(cwd, "pyproject.toml")) or \
       os.path.isdir(os.path.join(cwd, "tests")):
        return "pytest"
    if os.path.isfile(os.path.join(cwd, "go.mod")):
        return "go test ./..."
    if os.path.isfile(os.path.join(cwd, "Cargo.toml")):
        return "cargo test"
    return None


def _build_file_tree(cwd, max_depth=2):
    """Walk up to max_depth levels, skipping noisy directories."""
    summary = {}
    cwd_abs = os.path.abspath(cwd)
    for root, dirs, files in os.walk(cwd_abs):
        # Prune skipped dirs and dotfiles dirs in place.
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".env")]
        rel = os.path.relpath(root, cwd_abs)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > max_depth:
            dirs[:] = []
            continue
        key = "." if rel == "." else rel.replace(os.sep, "/")
        entry = {
            "dirs": sorted(dirs),
            "files": sorted(f for f in files if not f.startswith(".env")),
        }
        summary[key] = entry
    return summary


def _git_log(cwd):
    try:
        out = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip().splitlines()
    except Exception:
        pass
    return []


def _append_gitignore(cwd):
    gi = os.path.join(cwd, ".gitignore")
    if not os.path.isfile(gi):
        return
    raw = _safe_read(gi) or ""
    if any(line.strip().rstrip("/") == ".sentinel" for line in raw.splitlines()):
        return
    try:
        with open(gi, "a", encoding="utf-8") as f:
            if raw and not raw.endswith("\n"):
                f.write("\n")
            f.write(".sentinel/\n")
    except Exception:
        pass


def scan(cwd):
    cwd = os.path.abspath(cwd)
    sentinel_dir = os.path.join(cwd, ".sentinel")
    os.makedirs(sentinel_dir, exist_ok=True)

    stack, entry_points = _detect_stack(cwd)
    package_manager = _detect_package_manager(cwd)
    test_command = _detect_test_command(cwd, package_manager)

    now = _now_iso()
    knowledge = {
        "meta": {
            "created_at": now,
            "last_updated": now,
            "zeus_version": ZEUS_VERSION,
        },
        "project": {
            "name": os.path.basename(cwd) or cwd,
            "stack": stack,
            "package_manager": package_manager,
            "test_command": test_command,
            "entry_points": entry_points,
        },
        "file_tree_summary": _build_file_tree(cwd),
        "recent_sessions": [],
        "known_patterns": {},
        "open_issues": [],
        "error_patterns": [],
    }

    readme = os.path.join(cwd, "README.md")
    if os.path.isfile(readme):
        desc = _safe_read(readme, limit=500)
        if desc:
            knowledge["project"]["description"] = desc

    if os.path.isdir(os.path.join(cwd, ".git")):
        log = _git_log(cwd)
        if log:
            knowledge["meta"]["recent_git_log"] = log

    out_path = os.path.join(sentinel_dir, "knowledge.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(knowledge, f, indent=2)

    _append_gitignore(cwd)
    return out_path


def main():
    cwd = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    try:
        path = scan(cwd)
        rel = os.path.relpath(path, cwd)
        print(f"[ZeusPrompter] Knowledge base created at {rel}", file=sys.stderr)
    except Exception as e:
        # Scanning must never break the workflow.
        print(f"[ZeusPrompter] scanner error: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
