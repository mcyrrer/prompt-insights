"""Create the output folder and keep it out of git.

Every file the skill writes goes into one folder (default ./prompt-insights/ in the directory the
agent runs from). Two guards stop it from ending up in a user's repository:
  1. a .gitignore inside the folder that ignores everything in it, and
  2. a line in the enclosing git repository's .gitignore (when the folder sits inside one).
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_DIR = "prompt-insights"


def git_root(start: Path):
    for d in [start, *start.parents]:
        if (d / ".git").exists():
            return d
    return None


def ensure_output_dir(out_dir: Path) -> str:
    """Create out_dir, add the ignore guards, and return a one-line note about what was done."""
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    notes = []
    inner = out_dir / ".gitignore"
    if not inner.exists():
        inner.write_text("# Reports can contain redacted quotes from your sessions: never commit them.\n*\n", encoding="utf-8")
    root = git_root(out_dir)
    if root and root != out_dir:
        # Anchored with a leading slash: a bare "prompt-insights/" would also match an installed skill
        # folder such as .claude/skills/prompt-insights/ and hide it from git.
        line = "/" + out_dir.relative_to(root).as_posix() + "/"
        gi = root / ".gitignore"
        existing = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
        wanted = {line, line.lstrip("/"), line.rstrip("/"), line.strip("/")}
        if not any(x.strip() in wanted for x in existing):
            prefix = "" if not existing or gi.read_text(encoding="utf-8").endswith("\n") else "\n"
            with gi.open("a", encoding="utf-8") as fh:
                fh.write(f"{prefix}# prompt-insights reports (may contain redacted session quotes)\n{line}\n")
            notes.append(f"added '{line}' to {gi}")
    return "; ".join(notes) if notes else "output folder is git-ignored"
