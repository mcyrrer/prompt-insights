"""Read-only inventory of hooks and permission rules in Claude Code settings files.

Only the "hooks" and "permissions" keys are read. Everything else in a settings file (env vars, API
helpers, MCP config) is never loaded into the summary, because it can hold secrets.
"""
from __future__ import annotations

import json
from pathlib import Path

from redact import redact, tilde, truncate


def _files(cwds):
    home = Path.home() / ".claude"
    out = [(home / "settings.json", "user", "global"), (home / "settings.local.json", "user-local", "global")]
    for cwd in cwds:
        base = Path(cwd) / ".claude"
        out += [(base / "settings.json", "project", cwd), (base / "settings.local.json", "project-local", cwd)]
    return out


def scan_settings(cwds, project_name, extra=None) -> list:
    found, seen = [], set()
    for path, scope, owner in _files(cwds):
        try:
            rp = path.resolve()
        except Exception:
            continue
        if rp in seen or not rp.is_file():
            continue
        seen.add(rp)
        try:
            data = json.loads(rp.read_text(errors="replace"))
        except Exception:
            found.append({"path": tilde(str(rp)), "scope": scope, "error": "not valid JSON"})
            continue
        if not isinstance(data, dict):
            continue
        hooks = []
        for event, groups in (data.get("hooks") or {}).items() if isinstance(data.get("hooks"), dict) else []:
            for g in groups if isinstance(groups, list) else []:
                if not isinstance(g, dict):
                    continue
                for h in g.get("hooks") or []:
                    if isinstance(h, dict):
                        what = h.get("command") or h.get("prompt") or h.get("url") or ""
                        hooks.append({"event": event, "matcher": truncate(str(g.get("matcher", "")), 60),
                                      "type": h.get("type", "command"), "command": redact(truncate(str(what), 140), extra)})
        perms = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}

        def rules(k):
            v = perms.get(k)
            return [redact(truncate(str(x), 100), extra) for x in v] if isinstance(v, list) else []

        allow, deny, ask = rules("allow"), rules("deny"), rules("ask")
        found.append({
            "path": tilde(str(rp)), "scope": scope, "project": project_name(owner) if owner != "global" else "global",
            "hooks": hooks[:40], "hook_count": len(hooks),
            "permissions": {"allow": len(allow), "deny": len(deny), "ask": len(ask),
                            "default_mode": perms.get("defaultMode"),
                            "allow_rules": allow[:25], "deny_rules": deny[:15], "ask_rules": ask[:15]},
        })
    return found
