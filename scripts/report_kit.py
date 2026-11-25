# -*- coding: utf-8 -*-
"""Delivery self-check kit (r21): adds consistency_check, report.md, provenance.json and
repro_manifest.json next to result.json. Standard library only, deterministic, no network.

Usage (inside a package's run_skill.py, after result.json has been written):
    try:
        import report_kit
        report_kit.augment(args.out, args.case)
    except Exception:
        pass
"""
import csv
import hashlib
import json
import os
import sys

PLACEHOLDERS = ("judgement_pending", "TODO", "TBD", "FIXME", "<pending>")
INPUT_SUFFIXES = (".csv", ".tsv", ".jsonl", ".txt")


def _iter_strings(obj):
    if isinstance(obj, dict):
        for val in obj.values():
            for item in _iter_strings(val):
                yield item
    elif isinstance(obj, list):
        for val in obj:
            for item in _iter_strings(val):
                yield item
    elif isinstance(obj, str):
        yield obj


def _read_table(path):
    for enc in ("utf-8-sig", "gb18030", "latin-1"):
        try:
            with open(path, "r", encoding=enc, newline="") as fh:
                sample = fh.read(4096)
                fh.seek(0)
                delim = "\t" if path.lower().endswith(".tsv") else None
                if delim is None:
                    try:
                        delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
                    except csv.Error:
                        delim = ","
                rows = list(csv.reader(fh, delimiter=delim))
            return enc, delim, rows
        except (UnicodeDecodeError, OSError):
            continue
    return None, None, []


def inventory(out_path, case_path=None):
    """Write inventory.tsv (six-dimension file metadata) for input files referenced in case.json."""
    if not case_path or not os.path.isfile(str(case_path)):
        return None
    out_dir = os.path.dirname(os.path.abspath(str(out_path)))
    case_dir = os.path.dirname(os.path.abspath(str(case_path)))
    try:
        case = json.loads(open(str(case_path), "rb").read().decode("utf-8-sig"))
    except (OSError, ValueError):
        return None
    seen, entries = set(), []
    candidates = []
    for ref in _iter_strings(case):
        name = ref.strip()
        path = name if os.path.isabs(name) else os.path.join(case_dir, name)
        path = os.path.abspath(path)
        if os.path.isdir(path):
            for base, _dirs, files in os.walk(path):
                for fname in sorted(files):
                    if fname.lower().endswith(INPUT_SUFFIXES):
                        candidates.append(os.path.join(base, fname))
        elif name.lower().endswith(INPUT_SUFFIXES):
            candidates.append(path)
    for path in candidates:
        if path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        enc, delim, rows = _read_table(path)
        header = rows[0] if rows else []
        body = rows[1:] if rows else []
        dup = len(body) - len({tuple(r) for r in body})
        empty = sum(1 for r in body for c in r if str(c).strip() == "")
        entries.append({"file": os.path.basename(path), "sha256": _sha256(path),
                        "bytes": os.path.getsize(path), "rows": len(body),
                        "columns": len(header), "delimiter": "\\t" if delim == "\t" else (delim or ""),
                        "encoding": enc or "binary", "duplicate_rows": dup, "empty_cells": empty})
    if not entries:
        return None
    lines = ["file\tsha256\tbytes\trows\tcolumns\tdelimiter\tencoding\tduplicate_rows\tempty_cells"]
    for e in entries:
        lines.append("\t".join(str(e[k]) for k in ("file", "sha256", "bytes", "rows", "columns",
                                                   "delimiter", "encoding", "duplicate_rows",
                                                   "empty_cells")))
    try:
        with open(os.path.join(out_dir, "inventory.tsv"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        return None
    return entries


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def augment(out_path, case_path=None, extra_outputs=None):
    """Post-process a written result.json. Never raises on missing inputs."""
    out_path = os.path.abspath(str(out_path))
    if not os.path.isfile(out_path):
        return None
    out_dir = os.path.dirname(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    contract = {}
    case_sha = None
    case_id = data.get("case_id")
    if case_path and os.path.isfile(str(case_path)):
        try:
            case_raw = open(str(case_path), "rb").read()
            case_sha = hashlib.sha256(case_raw).hexdigest()
            case_obj = json.loads(case_raw.decode("utf-8-sig"))
            if isinstance(case_obj, dict):
                contract = case_obj.get("output_contract") or {}
                if isinstance(case_obj.get("case_id"), str):
                    case_id = case_obj.get("case_id")
        except (OSError, ValueError):
            pass

    checks = []

    def add(name, ok, observed, expected):
        checks.append({"name": name, "ok": bool(ok), "observed": observed, "expected": expected})

    add("case_id_matches_input", case_id == data.get("case_id"), data.get("case_id"), case_id)
    missing_keys = []
    null_keys = []
    if isinstance(contract, dict) and contract:
        for key in contract:
            if key not in data:
                missing_keys.append(key)
            elif data.get(key) is None:
                null_keys.append(key)
        add("contract_keys_present", not missing_keys, missing_keys, "all of %d" % len(contract))
        add("contract_keys_non_null", not null_keys, null_keys, "explicit null only in contract_extras")
    else:
        add("contract_keys_present", True, "no output_contract in case.json", "n/a")
    hits = [p for p in PLACEHOLDERS if p in raw]
    add("no_placeholder_tokens", not hits, hits, "[]")
    referenced = []
    for key in ("cleaned_file", "cleaned_data", "figure", "figure_svg"):
        val = data.get(key)
        if isinstance(val, str) and val and not os.path.isabs(val):
            referenced.append((key, val, os.path.isfile(os.path.join(out_dir, val))))
    add("referenced_artifacts_exist",
        all(ok for _, _, ok in referenced) if referenced else True,
        [r[1] for r in referenced if not r[2]], "all referenced files present")

    extras = data.get("contract_extras")
    add("null_fields_have_reason", not null_keys or isinstance(extras, dict),
        bool(isinstance(extras, dict)), True)

    ok_all = all(c["ok"] for c in checks)
    data["consistency_check"] = {"checked": True, "ok": ok_all, "checks": checks}
    if not ok_all and data.get("status") == "success":
        data["status"] = "partial"
        data.setdefault("uncertainty", [])
        if isinstance(data["uncertainty"], list):
            data["uncertainty"].append("delivery self-check failed; see consistency_check")

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    status = data.get("status", "")
    limitations = []
    for key in ("uncertainty", "limitations"):
        val = data.get(key)
        if isinstance(val, list):
            limitations.extend([str(v) for v in val][:12])
        elif isinstance(val, str) and val:
            limitations.append(val)
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}

    lines = ["# Delivery report", "",
             "- case_id: `%s`" % case_id,
             "- status: `%s`" % status,
             "- self-check: `%s`" % ("pass" if ok_all else "fail"), "",
             "## Self-check", "", "| check | ok | observed | expected |", "|---|---|---|---|"]
    for c in checks:
        lines.append("| %s | %s | %s | %s |"
                     % (c["name"], c["ok"], str(c["observed"])[:160], str(c["expected"])[:80]))
    if stats:
        lines += ["", "## Counts", ""]
        for key in sorted(stats):
            lines.append("- `%s`: %s" % (key, stats[key]))
    lines += ["", "## Limitations", ""]
    lines += ["- %s" % s for s in limitations] or ["- none reported"]
    lines.append("")
    try:
        with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        outputs = ["result.json", "report.md"]
        for name in (extra_outputs or []):
            if os.path.isfile(os.path.join(out_dir, name)):
                outputs.append(name)
        provenance = {"case_id": case_id, "status": status,
                      "case_json_sha256": case_sha,
                      "outputs": outputs, "network": False,
                      "python": sys.version.split()[0],
                      "deterministic": True,
                      "source_mutation": data.get("evidence", {}).get("source_mutation", "none")
                      if isinstance(data.get("evidence"), dict) else "none"}
        with open(os.path.join(out_dir, "provenance.json"), "w", encoding="utf-8") as fh:
            json.dump(provenance, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        manifest = {"command": "python scripts/run_skill.py --case <case.json> --out <out>/result.json",
                    "python": sys.version.split()[0],
                    "case_json_sha256": case_sha,
                    "outputs": outputs, "network": False, "deterministic": True}
        with open(os.path.join(out_dir, "repro_manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError:
        pass
    inventory(out_path, case_path)
    return data["consistency_check"]
