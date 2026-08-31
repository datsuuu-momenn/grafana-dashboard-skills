#!/usr/bin/env python3
"""
Validate Grafana dashboard JSON before it reaches a human reviewer or Grafana.

    python3 validate.py dashboards/*.json
    python3 validate.py --svc-label job dashboards/jvm.json

Checks structural mistakes that are invisible in review but visibly broken in
Grafana: overlapping panels, duplicate ids, hardcoded datasource UIDs,
unresolved placeholders, missing legends.

Exit code 0 = clean or warnings only. 1 = errors. Standard library only.
"""

import argparse
import json
import re
import sys
from collections import defaultdict

GRID_WIDTH = 24
PLACEHOLDER_RE = re.compile(r"__[A-Z][A-Z0-9_]*__")
AGGREGATABLE = {"timeseries", "stat", "gauge", "barchart", "heatmap", "piechart"}

# Units that are almost always wrong when paired with a 0-1 Prometheus ratio.
RATIO_HINTS = ("ratio", "rate", "percent", "utilization", "usage")


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, path, msg):
        self.errors.append(f"{path}: {msg}")

    def warn(self, path, msg):
        self.warnings.append(f"{path}: {msg}")


def flatten_panels(panels):
    """Yield (panel, container) for top-level and row-nested panels."""
    for p in panels:
        yield p
        if p.get("type") == "row":
            for child in p.get("panels", []) or []:
                yield child


def check_structure(doc, name, rep):
    for field in ("uid", "title", "panels"):
        if not doc.get(field):
            rep.error(name, f"missing required field: {field}")

    if not doc.get("panels"):
        return

    if doc.get("editable") is not False:
        rep.warn(name, "editable is not false — central dashboards should be UI read-only")

    if "id" in doc:
        rep.warn(name, "'id' present — strip it at deploy time or risk overwriting another dashboard")

    for k in ("__inputs", "__requires"):
        if k in doc:
            rep.error(name, f"'{k}' present — this is an export template, the API will reject it")

    if not doc.get("tags"):
        rep.warn(name, "no tags — dashboards become unfindable past ~30 of them")


def check_variables(doc, name, rep):
    variables = doc.get("templating", {}).get("list", []) or []
    names = {v.get("name") for v in variables}

    if not any(v.get("type") == "datasource" for v in variables):
        rep.warn(name, "no datasource variable — dashboard will not port between environments")

    body = json.dumps(doc, ensure_ascii=False)
    used = set(re.findall(r"\$(\w+)|\$\{(\w+)[:}]", body))
    used = {a or b for a, b in used}
    # __ prefixed names are Grafana built-ins (__interval, __rate_interval, ...)
    used = {u for u in used if not u.startswith("__")}

    for u in sorted(used - names):
        # $1 style label_replace references are not dashboard variables
        if u.isdigit():
            continue
        rep.error(name, f"query references undefined variable: ${u}")

    for v in sorted(names - used):
        rep.warn(name, f"variable '{v}' is defined but never used")


def check_panels(doc, name, rep):
    panels = list(flatten_panels(doc.get("panels", [])))

    ids = defaultdict(int)
    for p in panels:
        pid = p.get("id")
        if pid is None:
            rep.error(name, f"panel '{p.get('title', '?')}' has no id")
        else:
            ids[pid] += 1
    for pid, count in sorted(ids.items()):
        if count > 1:
            rep.error(name, f"panel id {pid} used {count} times")

    for p in panels:
        title = p.get("title") or f"id={p.get('id')}"
        ptype = p.get("type")

        gp = p.get("gridPos")
        if not gp:
            rep.error(name, f"panel '{title}' has no gridPos")
        else:
            if gp.get("x", 0) + gp.get("w", 0) > GRID_WIDTH:
                rep.error(name, f"panel '{title}' extends past the {GRID_WIDTH}-unit grid")
            if gp.get("w", 0) <= 0 or gp.get("h", 0) <= 0:
                rep.error(name, f"panel '{title}' has zero width or height")

        if ptype == "row":
            continue

        targets = p.get("targets") or []
        if not targets:
            rep.error(name, f"panel '{title}' has no targets")

        for t in targets:
            if not t.get("expr"):
                rep.error(name, f"panel '{title}' has a target with no expr")
            if ptype in AGGREGATABLE and not t.get("legendFormat"):
                rep.warn(name, f"panel '{title}' target {t.get('refId', '?')} has no legendFormat")

        if ptype == "table":
            missing = [t.get("refId", "?") for t in targets if not t.get("instant")]
            if missing:
                rep.warn(
                    name,
                    f"table '{title}' targets {missing} are not instant — "
                    "the table will fill with history instead of current values",
                )

        defaults = (p.get("fieldConfig") or {}).get("defaults") or {}
        unit = defaults.get("unit")
        if ptype in ("timeseries", "stat", "gauge") and not unit:
            rep.warn(name, f"panel '{title}' has no unit — raw numbers are hard to read")

        if unit == "percent" and any(h in title.lower() for h in RATIO_HINTS):
            rep.warn(
                name,
                f"panel '{title}' uses unit 'percent' — Prometheus ratios are 0-1 "
                "and need 'percentunit'",
            )

        if ptype == "stat":
            color_mode = (defaults.get("color") or {}).get("mode")
            steps = (defaults.get("thresholds") or {}).get("steps") or []
            if len(steps) > 1 and color_mode != "thresholds":
                rep.warn(
                    name,
                    f"stat '{title}' defines thresholds but color.mode is "
                    f"'{color_mode}' — the thresholds will be ignored",
                )

        if ptype == "timeseries":
            steps = (defaults.get("thresholds") or {}).get("steps") or []
            style = ((defaults.get("custom") or {}).get("thresholdsStyle") or {}).get("mode")
            if len(steps) > 1 and style in (None, "off"):
                rep.warn(
                    name,
                    f"timeseries '{title}' has thresholds but no thresholdsStyle — "
                    "the reference line will not be drawn",
                )


def check_overlap(doc, name, rep):
    """Rows reset the coordinate space, so only compare within a row section."""
    sections, current = [], []
    for p in doc.get("panels", []):
        if p.get("type") == "row":
            if current:
                sections.append(current)
            current = []
            if p.get("collapsed"):
                nested = [c for c in (p.get("panels") or []) if c.get("gridPos")]
                if nested:
                    sections.append(nested)
        elif p.get("gridPos"):
            current.append(p)
    if current:
        sections.append(current)

    for section in sections:
        for i, a in enumerate(section):
            ga = a["gridPos"]
            for b in section[i + 1:]:
                gb = b["gridPos"]
                overlap_x = ga["x"] < gb["x"] + gb["w"] and gb["x"] < ga["x"] + ga["w"]
                overlap_y = ga["y"] < gb["y"] + gb["h"] and gb["y"] < ga["y"] + ga["h"]
                if overlap_x and overlap_y:
                    rep.error(
                        name,
                        f"panels '{a.get('title')}' and '{b.get('title')}' overlap",
                    )


def check_datasources(doc, name, rep):
    body = json.dumps(doc, ensure_ascii=False)
    uids = set(re.findall(r'"uid"\s*:\s*"([^"]+)"', body))
    for uid in sorted(uids):
        if uid.startswith("${") or uid.startswith("--") or uid == doc.get("uid"):
            continue
        rep.error(
            name,
            f"hardcoded datasource uid '{uid}' — use ${{datasource}} so the "
            "dashboard ports between environments",
        )


def check_placeholders(doc, name, rep, svc_label):
    body = json.dumps(doc, ensure_ascii=False)

    if "CHANGEME" in body:
        rep.error(name, "contains CHANGEME — the skeleton was not fully filled in")

    found = sorted(set(PLACEHOLDER_RE.findall(body)))
    if not found:
        return
    if svc_label:
        remaining = [f for f in found if f != "__SVC_LABEL__"]
        if remaining:
            rep.error(name, f"unresolved placeholders after substitution: {remaining}")
    else:
        rep.warn(name, f"contains placeholders (substitute at deploy time): {found}")


def validate_file(path, svc_label, rep):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except json.JSONDecodeError as exc:
        rep.error(path, f"invalid JSON: {exc}")
        return None
    except OSError as exc:
        rep.error(path, f"cannot read: {exc}")
        return None

    name = path.split("/")[-1]
    check_structure(doc, name, rep)
    if doc.get("panels"):
        check_variables(doc, name, rep)
        check_panels(doc, name, rep)
        check_overlap(doc, name, rep)
        check_datasources(doc, name, rep)
        check_placeholders(doc, name, rep, svc_label)
    return doc


def main():
    ap = argparse.ArgumentParser(description="Validate Grafana dashboard JSON.")
    ap.add_argument("files", nargs="+")
    ap.add_argument(
        "--svc-label",
        help="Service label to substitute for __SVC_LABEL__; makes leftover placeholders errors",
    )
    args = ap.parse_args()

    rep = Report()
    uids = defaultdict(list)

    for path in args.files:
        doc = validate_file(path, args.svc_label, rep)
        if doc and doc.get("uid"):
            uids[doc["uid"]].append(path)

    for uid, paths in sorted(uids.items()):
        if len(paths) > 1:
            rep.error("<global>", f"uid '{uid}' reused by: {', '.join(paths)}")

    for w in rep.warnings:
        print(f"WARN  {w}")
    for e in rep.errors:
        print(f"ERROR {e}")

    total = len(args.files)
    print(
        f"\n{total} file(s) checked — {len(rep.errors)} error(s), "
        f"{len(rep.warnings)} warning(s)"
    )
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
