"""Three-way merge locally patched JSON with an unpacked upstream runtime.

The common base and local side are read from Git, so the script is also safe to
run while the working tree contains an earlier failed text merge.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


_MISSING = object()


def _git_json(revision: str, relative_path: str) -> Any:
    raw = subprocess.check_output(
        ["git", "show", f"{revision}:{relative_path}"],
        text=True,
        encoding="utf-8",
    )
    return json.loads(raw)


def _merge(base: Any, local: Any, upstream: Any, path: str, conflicts: list[str]) -> Any:
    if local == base:
        return upstream
    if upstream == base or local == upstream:
        return local

    values = (base, local, upstream)
    if all(value is _MISSING or isinstance(value, dict) for value in values):
        result: dict[str, Any] = {}
        keys: list[str] = []
        # Prefer the established local ordering, then place new upstream keys
        # beside the merged content without reformatting the whole document.
        for value in (local, upstream, base):
            if isinstance(value, dict):
                for key in value:
                    if key not in keys:
                        keys.append(key)
        for key in keys:
            child = _merge(
                base.get(key, _MISSING) if isinstance(base, dict) else _MISSING,
                local.get(key, _MISSING) if isinstance(local, dict) else _MISSING,
                upstream.get(key, _MISSING) if isinstance(upstream, dict) else _MISSING,
                f"{path}.{key}",
                conflicts,
            )
            if child is not _MISSING:
                result[key] = child
        return result

    # Pipeline lists are predominantly ordered node candidates.  When both
    # sides extend the same base list, keep the locally tested order and append
    # only genuinely new upstream candidates.  Deletions made locally stay
    # deleted instead of being resurrected from the base list.
    if all(isinstance(value, list) for value in values):
        result = list(local)
        for item in upstream:
            if item not in base and item not in result:
                result.append(item)
        return result

    conflicts.append(path)
    return local


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--local", default="HEAD")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    had_conflicts = False
    for relative_path in args.paths:
        if relative_path == "assets/interface.json":
            runtime_relative = "interface.json"
        elif relative_path.startswith(("assets/resource/", "assets/tasks/")):
            runtime_relative = relative_path.removeprefix("assets/")
        else:
            runtime_relative = relative_path
        base = _git_json(args.base, relative_path)
        local = _git_json(args.local, relative_path)
        upstream = json.loads(
            (args.runtime / runtime_relative).read_text(encoding="utf-8")
        )
        conflicts: list[str] = []
        merged = _merge(base, local, upstream, "$", conflicts)
        # The unpacked runtime is authoritative for its release marker.  Local
        # patches may be carried across releases, but must not make a v3.0.6
        # runtime report the previous source snapshot's version.
        if relative_path == "assets/interface.json" and conflicts == ["$.version"]:
            merged["version"] = upstream["version"]
            conflicts.clear()
        if conflicts:
            had_conflicts = True
            print(f"CONFLICT {relative_path}")
            for item in conflicts:
                print(f"  {item}")
            continue
        print(f"MERGED {relative_path}")
        if args.apply:
            target = args.source / relative_path
            target.write_text(
                json.dumps(merged, ensure_ascii=False, indent=4) + "\n",
                encoding="utf-8",
            )

    return 1 if had_conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
