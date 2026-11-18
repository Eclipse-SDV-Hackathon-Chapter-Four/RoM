# SPDX-FileCopyrightText: 2026 Contributors to the Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0
"""Every third-party dependency as a ClearlyDefined id, one per line, for the Eclipse Dash License Tool.

    python3 scripts/dash_ids.py pip-freeze.txt Cargo.lock ... package-lock.json ... > dash-ids.txt

Inputs by file name: *.lock = Cargo.lock (crates.io only; git and path crates are Eclipse / own code),
package-lock.json = npm, anything else = `pip freeze --exclude-editable` output.
"""
import json
import re
import sys
import tomllib
from pathlib import Path


def ids(path: Path) -> set[str]:
    if path.suffix == ".lock":
        pkgs = tomllib.loads(path.read_text()).get("package", [])
        return {f"crate/cratesio/-/{p['name']}/{p['version']}"
                for p in pkgs if p.get("source", "").startswith("registry+")}
    if path.name == "package-lock.json":
        out = set()
        for key, p in json.loads(path.read_text())["packages"].items():
            if "node_modules/" not in key or p.get("link"):
                continue
            name = key.rsplit("node_modules/", 1)[1]
            scope, _, base = name.rpartition("/")
            out.add(f"npm/npmjs/{scope or '-'}/{base}/{p['version']}")
        return out
    return {f"pypi/pypi/-/{re.sub(r'[-_.]+', '-', name.strip().lower())}/{ver.strip()}"
            for name, sep, ver in (line.partition("==") for line in path.read_text().splitlines()) if sep}


if __name__ == "__main__":
    found = sorted(set().union(*(ids(Path(a)) for a in sys.argv[1:])))
    if not found:
        sys.exit("no dependencies found: wrong input files?")
    print("\n".join(found))
