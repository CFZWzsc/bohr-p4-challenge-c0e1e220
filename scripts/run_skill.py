#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic descriptive/inferential statistics with assumption checks. Stdlib only."""

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

MAX_FILES = 200
MAX_ROWS = 200000
PATH_KEYS = ("input_dir", "input_root", "materials_dir", "materials", "data_dir", "dataset_dir", "directory", "path", "root")
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".cache"}
MISSING = {"", "na", "n/a", "nan", "none", "null", "nil", "-", "--", "-999", "-9999", "未检测", "缺失"}
ALIASES = {
    "case_id": ["case_id", "caseid", "id"],
    "descriptive": ["descriptive", "descriptive_stats", "summary_stats", "group_stats"],
    "assumptions": ["assumptions", "assumption_checks", "normality", "variance_check"],
    "tests": ["tests", "test_results", "inferential", "statistical_tests", "p_values"],
    "effect_sizes": ["effect_sizes", "effect_size", "effects"],
    "confidence_intervals": ["confidence_intervals", "ci", "intervals"],
    "interpretation": ["interpretation", "conclusion", "findings", "answer", "summary"],
    "cleaning": ["cleaning", "data_cleaning", "preprocessing"],
    "status": ["status", "run_status"],
    "result": ["result", "results", "data"],
    "evidence": ["evidence", "provenance", "sources"],
    "uncertainty": ["uncertainty", "limitations"],
    "errors": ["errors", "error"],
    "stats": ["stats", "statistics", "counts"],
}


def norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def contract_fields(case):
    oc = case.get("output_contract")
    out = []
    if isinstance(oc, dict):
        if isinstance(oc.get("properties"), dict):
            out = list(oc["properties"].keys())
        elif isinstance(oc.get("fields"), dict):
            out = list(oc["fields"].keys())
        elif isinstance(oc.get("fields"), list):
            out = [x for x in oc["fields"] if isinstance(x, str)]
        elif isinstance(oc.get("required"), list):
            out = [x for x in oc["required"] if isinstance(x, str)]
        else:
            out = list(oc.keys())
    elif isinstance(oc, list):
        out = [x for x in oc if isinstance(x, str)]
    seen, uniq = set(), []
    for f in out:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


def iter_paths(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from iter_paths(item)
    elif isinstance(value, dict):
        for key in ("path", "dir", "file", "files", "root"):
            if key in value:
                yield from iter_paths(value[key])


def candidate_roots(case, case_path):
    base = case_path.parent
    roots = []
    for key in PATH_KEYS + ("data_files",):
        if key in case:
            for raw in iter_paths(case[key]):
                p = Path(raw)
                if not p.is_absolute():
                    p = base / p
                roots.append(p)
    if base.name.lower() == "input" or (base / "materials").is_dir():
        roots.append(base)
    if Path("/input").is_dir():
        roots.append(Path("/input"))
    seen, uniq = set(), []
    for r in roots:
        try:
            key = str(r.resolve())
        except OSError:
            key = str(r)
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def collect(roots, errors, skipped, exclude):
    files, seen = [], set()
    try:
        exclude_key = str(exclude.resolve()) if exclude else None
    except OSError:
        exclude_key = None
    for root in roots:
        if not root.exists():
            errors.append("material root not found: %s" % (root.name or str(root)))
            continue
        if root.is_file():
            paths, root_dir = [root], root.parent
        else:
            root_dir, paths = root, []
            try:
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
                    for fn in sorted(filenames):
                        paths.append(Path(dirpath) / fn)
            except OSError as exc:
                errors.append("walk failed on %s: %s" % (root.name, exc))
                continue
        for path in paths:
            if len(files) >= MAX_FILES:
                skipped.append({"path": path.name, "reason": "file cap reached"})
                continue
            try:
                rp = str(path.resolve())
                if path.is_symlink() or not path.is_file() or rp == exclude_key:
                    continue
            except OSError:
                continue
            if rp in seen:
                continue
            seen.add(rp)
            try:
                rel = path.relative_to(root_dir).as_posix()
            except ValueError:
                rel = path.name
            files.append((path, rel))
    files.sort(key=lambda x: x[1])
    return files


def decode(data):
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def to_float(value):
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def mean(xs):
    return sum(xs) / float(len(xs))


def var(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1.0)


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def quantile(xs, q):
    s = sorted(xs)
    if not s:
        return None
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def betacf(a, b, x):
    maxit, eps, fpmin = 200, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betai(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                  + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * betacf(a, b, x) / a
    return 1.0 - bt * betacf(b, a, 1.0 - x) / b


def t_p_two(t, df):
    if df <= 0:
        return None
    return betai(df / 2.0, 0.5, df / (df + t * t))


def f_p_upper(f, df1, df2):
    if f <= 0 or df1 <= 0 or df2 <= 0:
        return None
    return betai(df2 / 2.0, df1 / 2.0, df2 / (df2 + df1 * f))


def t_crit(df, conf=0.95):
    target = 1.0 - conf
    lo, hi = 0.0, 50.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if t_p_two(mid, df) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def one_way(groups):
    k = len(groups)
    n = sum(len(g) for g in groups)
    df1, df2 = k - 1, n - k
    if df1 <= 0 or df2 <= 0:
        return None
    grand = mean([x for g in groups for x in g])
    ssb = sum(len(g) * (mean(g) - grand) ** 2 for g in groups)
    ssw = sum(sum((x - mean(g)) ** 2 for x in g) for g in groups)
    if ssw <= 0:
        return None
    f = (ssb / df1) / (ssw / df2)
    return {"F": f, "df1": df1, "df2": df2, "p": f_p_upper(f, df1, df2),
            "ssb": ssb, "ssw": ssw, "eta_squared": ssb / (ssb + ssw) if (ssb + ssw) else None}


def welch(a, b):
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return None
    m1, m2 = mean(a), mean(b)
    v1, v2 = var(a), var(b)
    se = math.sqrt(v1 / n1 + v2 / n2)
    if se <= 0:
        return None
    t = (m1 - m2) / se
    denom = (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
    df = (v1 / n1 + v2 / n2) ** 2 / denom if denom > 0 else n1 + n2 - 2
    pooled = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)) if n1 + n2 > 2 else 0.0
    d = (m1 - m2) / pooled if pooled > 0 else None
    g = d * (1 - 3.0 / (4 * (n1 + n2) - 9)) if d is not None and (4 * (n1 + n2) - 9) > 0 else d
    diff = m1 - m2
    tc = t_crit(df)
    ci = [diff - tc * se, diff + tc * se]
    return {"t": t, "df": df, "p": t_p_two(t, df), "mean_diff": diff, "se": se,
            "cohen_d": d, "hedges_g": g, "diff_ci95": ci}


def skew(xs):
    n = len(xs)
    if n < 3:
        return None
    m = mean(xs)
    m2 = sum((x - m) ** 2 for x in xs) / n
    if m2 <= 0:
        return 0.0
    m3 = sum((x - m) ** 3 for x in xs) / n
    return m3 / (m2 ** 1.5)


def brown_forsythe(groups):
    if len(groups) < 2:
        return None
    z = [[abs(x - median(g)) for x in g] for g in groups]
    return one_way(z)


def sig(x, digits=4):
    if x is None:
        return "n/a"
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return "n/a"
    except (TypeError, ValueError):
        return "n/a"
    return "%.*g" % (digits, x)


def group_mean_ci(d, conf=0.95):
    if d.get("n", 0) < 2 or d.get("sd") is None:
        return None
    half = t_crit(d["n"] - 1, conf) * d["sd"] / math.sqrt(d["n"])
    return [d["mean"] - half, d["mean"] + half]


def magnitude_label(d):
    if d is None:
        return None
    a = abs(d)
    return "small" if a < 0.5 else "medium" if a < 0.8 else "large"


def eta_magnitude(eta):
    if eta is None:
        return None
    return "small" if eta < 0.06 else "medium" if eta < 0.14 else "large"


def two_group_effect(a, b):
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return {"d": None, "g": None, "reason": "a group has n<2, so a pooled SD is undefined"}
    v1, v2 = var(a), var(b)
    pooled = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    if pooled <= 0:
        return {"d": None, "g": None, "reason": "pooled SD is zero, so Cohen's d and Hedges' g are undefined"}
    d = (mean(a) - mean(b)) / pooled
    return {"d": d, "g": d * (1.0 - 3.0 / (4 * (n1 + n2) - 9))}


def prepare_rows(rows, header, case):
    """Deduplicate before statistics; never drop exact duplicates without key columns."""
    cleaning = {"rows_read": len(rows), "dropped_missing": 0, "duplicate_rows": 0,
                "rows_removed": 0, "dedup_rule": "none"}
    key_cols = case.get("key_columns")
    key_idx, key_names = [], []
    if isinstance(key_cols, list):
        for name in key_cols:
            if isinstance(name, str) and name in header:
                key_idx.append(header.index(name))
                key_names.append(name)
    if key_idx:
        seen, kept = set(), []
        for r in rows:
            key = tuple(r[i].strip() for i in key_idx)
            if key in seen:
                cleaning["rows_removed"] += 1
                continue
            seen.add(key)
            kept.append(r)
        cleaning["dedup_rule"] = "key_columns:first_occurrence"
        cleaning["key_columns"] = key_names
        rows = kept
    else:
        if isinstance(key_cols, list) and key_cols:
            cleaning["dedup_rule"] = "none:key_columns_not_found"
            cleaning["warnings"] = ["declared key_columns not present in header; no deduplication applied"]
        seen, dup = set(), 0
        for r in rows:
            key = tuple(c.strip() for c in r)
            if key in seen:
                dup += 1
            else:
                seen.add(key)
        if dup:
            cleaning["duplicate_rows"] = dup
            cleaning["duplicate_check"] = {"duplicate_rows": dup, "action": "kept",
                                           "warning": "duplicate observations inflate n"}
            cleaning.setdefault("warnings", []).append("duplicate observations inflate n")
            if cleaning["dedup_rule"] == "none":
                cleaning["dedup_rule"] = "none:exact_duplicates_kept"
    return rows, cleaning


def keyword_family(field):
    k = norm_key(field)
    if k.startswith("stats") or k.startswith("descriptive") or k.startswith("desc_") or k.endswith("_stats"):
        return "descriptive"
    if k.startswith("test") or k.startswith("infer") or k.startswith("p_value") or k.startswith("pval"):
        return "tests"
    if k.startswith("effect"):
        return "effect_sizes"
    if k.startswith("conf") or k.startswith("interval") or k == "ci" or k.startswith("ci_") or k.endswith("_ci"):
        return "confidence_intervals"
    if k.startswith("interpret") or k.startswith("conclusion") or k.startswith("answer") or k.startswith("summary"):
        return "interpretation"
    if k.startswith("clean"):
        return "cleaning"
    return None


def resolve_contract(field, payload):
    canon = keyword_family(field)
    if canon is not None and canon in payload:
        return canon, payload[canon]
    key = norm_key(field)
    for canonical, names in ALIASES.items():
        if key == canonical or key in names:
            return canonical, payload.get(canonical)
    return None, None


def best_effort_value(field, payload):
    k = norm_key(field)
    if any(w in k for w in ("limit", "risk", "caveat", "uncertainty")):
        return payload.get("uncertainty") or payload.get("interpretation")
    if "method" in k or "formula" in k:
        return payload.get("evidence", {}).get("methods") or payload.get("interpretation")
    if any(w in k for w in ("file", "source", "hash", "data")):
        return payload.get("evidence", {}).get("source") or payload.get("interpretation")
    return payload.get("interpretation") or payload.get("summary")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Assumption-checked statistics (stdlib only)")
    parser.add_argument("--case", default="/input/case.json")
    parser.add_argument("--out", "--output", default="/app/output/result.json")
    parser.add_argument("--work", default="/app/work")
    args = parser.parse_args(argv)
    os.environ["SK_RESULT_PATH"] = str(getattr(args, "out", None) or getattr(args, "output", None) or "")

    case_path = Path(args.case)
    errors, skipped, case, status = [], [], {}, "success"
    interpretation = ""
    try:
        with open(case_path, "r", encoding="utf-8-sig") as fh:
            case = json.load(fh)
        if not isinstance(case, dict):
            raise ValueError("case.json root is not an object")
    except OSError as exc:
        errors.append("cannot read case.json: %s" % (exc.strerror or "I/O error"))
        case, status = {}, "failed"
        interpretation = (
            "case.json could not be opened (%s), so no data were read and no descriptive statistic, test, "
            "effect size or confidence interval was computed. Limitations: nothing is estimable until a "
            "readable case.json with output_contract and an input data file is supplied."
            % (exc.strerror or type(exc).__name__))
    except ValueError as exc:
        errors.append("cannot read case.json: invalid JSON (%s)" % exc)
        case, status = {}, "failed"
        interpretation = (
            "case.json is not valid JSON (%s), so no data were read and no descriptive statistic, test, "
            "effect size or confidence interval was computed. Limitations: fix the case file and rerun; "
            "nothing is estimable from a malformed contract." % exc)

    case_id = case.get("case_id") if isinstance(case.get("case_id"), str) else "unknown"
    fields = contract_fields(case)
    alpha = case.get("alpha") if isinstance(case.get("alpha"), (int, float)) else 0.05
    group_col = case.get("group_column")
    value_col = case.get("value_column")

    header, rows, source = [], [], None
    if status != "failed":
        for path, rel in collect(candidate_roots(case, case_path), errors, skipped, case_path):
            ext = path.suffix.lower()
            if ext not in (".csv", ".tsv", ".txt"):
                skipped.append({"path": rel, "reason": "unsupported extension"})
                continue
            try:
                raw = path.read_bytes()
                text, enc = decode(raw)
            except OSError as exc:
                skipped.append({"path": rel, "reason": "unreadable: %s" % exc})
                continue
            line = text.splitlines()[0] if text else ""
            delim = "\t" if ext == ".tsv" else max([",", "\t", ";"], key=lambda d: line.count(d))
            parsed = list(csv.reader(text.splitlines(), delimiter=delim))
            parsed = [r for r in parsed if any(c.strip() for c in r)]
            if not parsed:
                skipped.append({"path": rel, "reason": "empty table"})
                continue
            header = [h.strip() or "col_%d" % (i + 1) for i, h in enumerate(parsed[0])]
            width = len(header)
            rows = [(r + [""] * (width - len(r)))[:width] for r in parsed[1:MAX_ROWS]]
            source = {"file": rel, "sha256": hashlib.sha256(raw).hexdigest(), "encoding": enc,
                      "delimiter": "tab" if delim == "\t" else delim}
            break

    descriptive = []
    assumptions = {"normality": {"method": "skewness heuristic (not Shapiro-Wilk)", "per_group": []},
                   "variance": {"method": "not_applicable", "reason": "no input data"},
                   "sample_size_ok": False}
    tests = {"method": "none", "test_run": False, "p_value": None, "reason": "no input data"}
    effect_sizes = {"status": "not_estimable", "reason": "no data were available"}
    intervals = {"status": "not_estimable", "reason": "no data were available"}
    cleaning = {"rows_read": len(rows), "dropped_missing": 0, "duplicate_rows": 0,
                "rows_removed": 0, "dedup_rule": "none"}
    groups_map = {}

    if status != "failed":
        if not rows:
            status = "insufficient_input"
            interpretation = (
                "No data rows were found in the declared input locations (header %s), so no descriptive "
                "statistic, test, effect size or confidence interval is estimable. Supply a CSV/TSV table "
                "with one row per observation plus a group column and a numeric value column; the status "
                "stays insufficient_input until then."
                % ("was parsed" if header else "was not found"))
        else:
            rows, cleaning = prepare_rows(rows, header, case)
            cleaning["rows_analyzed"] = len(rows)

            group_ok = bool(group_col) and group_col in header
            group_note = None
            if not group_ok:
                group_note = ("declared group_column %s is absent from the header (%s)"
                              % (group_col, ", ".join(header))) if group_col else \
                             "case.json declared no group_column"
                candidates = []
                for name in header:
                    vals = {r[header.index(name)].strip() for r in rows}
                    if 2 <= len(vals) <= 10:
                        candidates.append(name)
                group_col = candidates[0] if candidates else None
                group_ok = bool(group_col) and group_col in header

            value_ok = bool(value_col) and value_col in header
            value_note = None
            if not value_ok:
                value_note = ("declared value_column %s is absent from the header" % value_col) if value_col else \
                             "case.json declared no value_column"
                for name in header:
                    if name == group_col:
                        continue
                    idx = header.index(name)
                    vals = [v for v in (to_float(r[idx]) for r in rows
                                        if r[idx].strip().lower() not in MISSING) if v is not None]
                    if vals and len(vals) / float(max(1, len(rows))) >= 0.8:
                        value_col = name
                        break
                value_ok = bool(value_col) and value_col in header

            if group_ok and not value_ok:
                gi_try = header.index(group_col)
                ratio = sum(1 for r in rows if to_float(r[gi_try]) is not None) / float(max(1, len(rows)))
                if ratio >= 0.8:
                    value_col, value_ok = group_col, True
                    group_col, group_ok = None, False
                    group_note = ("no column had 2-10 categorical values for grouping, so %s was described "
                                  "as a single numeric series" % value_col)

            if not group_ok or not value_ok:
                idx = header.index(value_col) if value_ok else 0
                vals = [to_float(r[idx]) for r in rows if to_float(r[idx]) is not None]
                if vals:
                    descriptive = [{"group": "all", "n": len(vals), "mean": mean(vals),
                                    "sd": math.sqrt(var(vals)) if len(vals) > 1 else None,
                                    "median": median(vals), "q1": quantile(vals, 0.25),
                                    "q3": quantile(vals, 0.75), "min": min(vals), "max": max(vals),
                                    "skewness": skew(vals)}]
                    groups_map = {"all": vals}
                missing_bits = []
                if not group_ok:
                    missing_bits.append(group_note or "the group column could not be resolved")
                if not value_ok:
                    missing_bits.append(value_note or "the value column could not be resolved")
                if vals:
                    half = (t_crit(len(vals) - 1) * math.sqrt(var(vals)) / math.sqrt(len(vals))
                            if len(vals) > 1 else None)
                    intervals = {"group_mean_ci95": [{"group": "all", "n": len(vals), "mean": mean(vals),
                                                      "ci95": [mean(vals) - half, mean(vals) + half],
                                                      "method": "two-sided t interval, sample SD"}],
                                 "note": "single pooled series only; no group contrast exists"}
                    interpretation = (
                        "No between-group comparison was run because %s. A single-series summary is reported "
                        "instead: n=%d, mean=%s, SD=%s, median=%s, min=%s, max=%s. "
                        "Effect sizes need a group contrast, so none is estimable. Limitations: without a valid "
                        "grouping factor no test, effect size or group-difference interval is defined, and this "
                        "summary mixes every row into one series."
                        % ("; ".join(missing_bits), len(vals), sig(mean(vals)),
                           sig(math.sqrt(var(vals)) if len(vals) > 1 else None), sig(median(vals)),
                           sig(min(vals)), sig(max(vals))))
                else:
                    intervals = {"status": "not_estimable",
                                 "reason": "no numeric observations in the inspected column"}
                    interpretation = (
                        "No analysis was run because %s, and no numeric value could be parsed. Limitations: "
                        "descriptive statistics, tests, effect sizes and intervals all require a numeric value "
                        "column and a categorical group column, so nothing is estimable yet."
                        % "; ".join(missing_bits))
                assumptions = {"normality": {"method": "skewness heuristic (not Shapiro-Wilk)",
                                             "per_group": [{"group": str(d["group"]),
                                                            "skewness": d["skewness"], "n": d["n"],
                                                            "flag": False} for d in descriptive]},
                               "variance": {"method": "not_applicable",
                                            "reason": "no valid group/value column pair"},
                               "sample_size_ok": False}
                effect_sizes = {"status": "not_estimable",
                                "reason": "no group contrast exists without a resolved group column"}
                tests = {"method": "none", "test_run": False, "p_value": None,
                         "reason": "; ".join(missing_bits)}
                status = "partial"
            else:
                gi, vi = header.index(group_col), header.index(value_col)
                for r in rows:
                    g = r[gi].strip() or "missing_group"
                    v = to_float(r[vi])
                    if r[vi].strip().lower() in MISSING or v is None:
                        cleaning["dropped_missing"] += 1
                        continue
                    groups_map.setdefault(g, []).append(v)
                groups_map = {name: vals for name, vals in groups_map.items() if vals}
                for name in sorted(groups_map):
                    vals = groups_map[name]
                    descriptive.append({"group": name, "n": len(vals), "mean": mean(vals),
                                        "sd": math.sqrt(var(vals)) if len(vals) > 1 else None,
                                        "median": median(vals), "q1": quantile(vals, 0.25),
                                        "q3": quantile(vals, 0.75), "min": min(vals), "max": max(vals),
                                        "skewness": skew(vals)})
                k = len(groups_map)
                n_list = [(name, len(groups_map[name])) for name in sorted(groups_map)]
                min_n = min([n for _, n in n_list]) if n_list else 0
                n_txt = ", ".join("%s=%d" % (name, n) for name, n in n_list)
                normality = {
                    "method": "skewness heuristic (not Shapiro-Wilk)",
                    "per_group": [{"group": str(d["group"]), "skewness": d["skewness"], "n": d["n"],
                                   "flag": bool(d["skewness"] is not None and abs(d["skewness"]) > 1
                                                and d["n"] < 30)} for d in descriptive],
                }

                if k == 0:
                    assumptions = {"normality": normality,
                                   "variance": {"method": "not_applicable",
                                                "reason": "no analysable group remains"},
                                   "sample_size_ok": False}
                    tests = {"method": "none", "test_run": False, "p_value": None,
                             "reason": "no numeric observation remained after excluding missing values"}
                    effect_sizes = {"status": "not_estimable", "reason": "no numeric observations"}
                    intervals = {"status": "not_estimable", "reason": "no numeric observations"}
                    interpretation = (
                        "The group column %s and value column %s resolved, but every value was missing or "
                        "non-numeric (%d row(s) excluded), so no descriptive, test, effect size or interval is "
                        "estimable. Limitations: check the value column choice and the missing-value encoding."
                        % (group_col, value_col, cleaning["dropped_missing"]))
                    status = "partial"
                else:
                    if k >= 2 and min_n >= 2:
                        bf = brown_forsythe([groups_map[name] for name, _ in n_list])
                        if bf is None:
                            variance = {"method": "Brown-Forsythe (median-centered Levene)",
                                        "reason": "not computable: zero spread of median absolute deviations"}
                        else:
                            variance = {"method": "Brown-Forsythe (median-centered Levene)",
                                        "F": bf["F"], "p": bf["p"],
                                        "equal_variance_rejected": bool(bf["p"] is not None and bf["p"] < alpha)}
                    elif k >= 2:
                        variance = {"method": "not_applicable", "reason": "group with n<2"}
                    else:
                        variance = {"method": "not_applicable", "reason": "fewer than 2 groups"}
                    assumptions = {"normality": normality, "variance": variance,
                                   "sample_size_ok": bool(k >= 2 and min_n >= 3)}

                    group_ci, no_ci = [], []
                    for d in descriptive:
                        ci = group_mean_ci(d)
                        if ci is None:
                            no_ci.append(str(d["group"]))
                        else:
                            group_ci.append({"group": str(d["group"]), "n": d["n"], "mean": d["mean"],
                                             "ci95": ci, "method": "two-sided t interval, sample SD"})
                    if group_ci:
                        intervals = {"group_mean_ci95": group_ci}
                        if no_ci:
                            intervals["groups_without_ci"] = no_ci
                            intervals["note"] = "groups with n=1 cannot have a mean interval"
                    else:
                        intervals = {"status": "not_estimable",
                                     "reason": "no group has n>=2, so a mean confidence interval is undefined"}

                    effect_sizes = {}
                    tests = {}
                    test_reason = None
                    if k < 2:
                        test_reason = ("only %d analysable group exists (%s), so no between-group test is defined"
                                       % (k, n_txt))
                    elif min_n < 3:
                        small = ["%s (n=%d)" % (name, n) for name, n in n_list if n < 3]
                        test_reason = ("group(s) %s have fewer than 3 observations, so no inferential test was run"
                                       % ", ".join(small))
                    if test_reason is None and k == 2:
                        names = [name for name, _ in n_list]
                        a, b = groups_map[names[0]], groups_map[names[1]]
                        contrast = "%s minus %s" % (names[0], names[1])
                        res = welch(a, b)
                        eff = two_group_effect(a, b)
                        if eff.get("d") is None:
                            effect_sizes = {"cohen_d": None, "hedges_g": None,
                                            "reason": eff.get("reason", "effect size not estimable")}
                        else:
                            effect_sizes = {"cohen_d": eff["d"], "hedges_g": eff["g"],
                                            "magnitude": magnitude_label(eff["d"]),
                                            "contrast": contrast}
                        if res is None:
                            tests = {"method": "Welch two-sample t-test", "test_run": False,
                                     "statistic": None, "p_value": None, "contrast": contrast,
                                     "reason": "the standard error is zero (both groups have zero variance), "
                                               "so the t statistic is undefined"}
                            intervals["mean_difference_ci95"] = None
                            intervals["mean_difference_ci95_reason"] = "zero standard error"
                        else:
                            tests = {"method": "Welch two-sample t-test", "test_run": True,
                                     "statistic": res["t"], "df": res["df"], "p_value": res["p"],
                                     "alpha": alpha, "alternative": "two-sided",
                                     "mean_difference": res["mean_diff"], "contrast": contrast}
                            intervals["mean_difference_ci95"] = res["diff_ci95"]
                            intervals["mean_difference_ci95_method"] = "Welch SE with t critical value"
                    elif test_reason is None:
                        names = [name for name, _ in n_list]
                        an = one_way([groups_map[name] for name in names])
                        if an is None:
                            tests = {"method": "one-way ANOVA", "test_run": False, "statistic": None,
                                     "p_value": None, "df1": len(names) - 1,
                                     "df2": sum(len(groups_map[n]) for n in names) - len(names),
                                     "reason": "within-group sum of squares is zero, so F is undefined"}
                            effect_sizes = {"eta_squared": None,
                                            "reason": "one-way ANOVA is not estimable because "
                                                      "within-group variance is zero"}
                        else:
                            tests = {"method": "one-way ANOVA", "test_run": True, "statistic": an["F"],
                                     "df1": an["df1"], "df2": an["df2"], "p_value": an["p"],
                                     "alpha": alpha, "alternative": "greater"}
                            effect_sizes = {"eta_squared": an["eta_squared"],
                                            "magnitude": eta_magnitude(an["eta_squared"]),
                                            "contrast": "all %d groups (between vs within variance)" % k}
                    if not effect_sizes:
                        reason = "no effect size is estimable: %s" % (test_reason or "no contrast is defined")
                        effect_sizes = ({"eta_squared": None, "reason": reason} if k > 2
                                        else {"status": "not_estimable", "reason": reason})
                    if not tests:
                        tests = {"method": "none", "test_run": False, "p_value": None,
                                 "reason": test_reason or "no test was applicable"}

                    desc_txt = "; ".join(
                        "%s n=%d mean=%s SD=%s median=%s range=%s-%s"
                        % (str(d["group"]), d["n"], sig(d["mean"]),
                           "n/a" if d["sd"] is None else sig(d["sd"]), sig(d["median"]),
                           sig(d["min"]), sig(d["max"])) for d in descriptive)
                    parts = ["Compared %d group(s) of %s grouped by %s (%s)."
                             % (k, value_col, group_col, n_txt),
                             "Descriptives: %s." % desc_txt]
                    if k >= 2:
                        ordered = sorted(descriptive, key=lambda d: (d["mean"], str(d["group"])))
                        low, high = ordered[0], ordered[-1]
                        parts.append("The largest mean separation is %s (%s) minus %s (%s) = %s."
                                     % (str(high["group"]), sig(high["mean"]), str(low["group"]),
                                        sig(low["mean"]), sig(high["mean"] - low["mean"])))
                    p = tests.get("p_value")
                    if p is not None:
                        df_txt = ("df1=%d, df2=%d" % (tests["df1"], tests["df2"]) if "df1" in tests
                                  else "df=%s" % sig(tests.get("df")))
                        parts.append("%s gives statistic=%s (%s) with p=%s at alpha=%s, so the group "
                                     "difference is %s."
                                     % (tests["method"], sig(tests.get("statistic")), df_txt, sig(p),
                                        sig(alpha), "statistically significant" if p < alpha
                                        else "not statistically significant"))
                    else:
                        parts.append("No p value is reported because %s."
                                     % tests.get("reason", "the test was not evaluated"))
                    if effect_sizes.get("cohen_d") is not None:
                        parts.append("Effect size: Cohen's d=%s and Hedges' g=%s (%s magnitude) for %s."
                                     % (sig(effect_sizes["cohen_d"]), sig(effect_sizes["hedges_g"]),
                                        effect_sizes["magnitude"], effect_sizes["contrast"]))
                    elif effect_sizes.get("eta_squared") is not None:
                        parts.append("Effect size: eta squared=%s (%s magnitude) over all %d groups."
                                     % (sig(effect_sizes["eta_squared"]), effect_sizes["magnitude"], k))
                    else:
                        parts.append("Effect size: not estimable (%s)."
                                     % effect_sizes.get("reason", "no contrast is defined"))
                    if group_ci:
                        parts.append("95%% confidence intervals for the group means are reported for %s."
                                     % ", ".join(item["group"] for item in group_ci))
                        if no_ci:
                            parts.append("%s cannot have a mean interval because n<2." % ", ".join(no_ci))
                    if variance.get("method") == "not_applicable":
                        parts.append("Variance homogeneity was not tested (%s)." % variance["reason"])
                    elif variance.get("equal_variance_rejected"):
                        parts.append("Brown-Forsythe rejects equal variances (p=%s); equal-variance "
                                     "assumptions are avoided, and a Welch ANOVA is not implemented for "
                                     "more than two groups." % sig(variance.get("p")))
                    if cleaning.get("rows_removed"):
                        parts.append("Removed %d later duplicate row(s) using key columns %s, keeping the "
                                     "first occurrence."
                                     % (cleaning["rows_removed"],
                                        ", ".join(cleaning.get("key_columns") or [])))
                    elif cleaning.get("duplicate_rows"):
                        parts.append("Kept %d exact duplicate row(s) because no key_columns were supplied; "
                                     "duplicate observations inflate n and were not removed."
                                     % cleaning["duplicate_rows"])
                    if cleaning.get("dropped_missing"):
                        parts.append("Excluded %d row(s) with missing or non-numeric values (no imputation)."
                                     % cleaning["dropped_missing"])
                    parts.append("Limitations: normality is only a skewness heuristic (not Shapiro-Wilk); "
                                 "p values are unadjusted for multiple comparisons; observations are assumed "
                                 "independent; statistical significance does not prove a causal or practically "
                                 "important effect.")
                    interpretation = " ".join(parts)

                    degraded = bool(p is None or k < 2 or min_n < 3
                                    or any(item["flag"] for item in normality["per_group"])
                                    or cleaning.get("dropped_missing") or cleaning.get("rows_removed")
                                    or cleaning.get("duplicate_rows") or variance.get("equal_variance_rejected"))
                    status = "partial" if degraded else "success"

    if not interpretation.strip():
        interpretation = ("No interpretation text was produced for this run; inspect status, tests.reason and "
                          "errors. This fallback message is a degraded placeholder, not a result.")

    evidence = {"source": source, "group_column": group_col, "value_column": value_col,
                "alpha": alpha, "methods": "Welch t-test for 2 groups, one-way ANOVA for >2 groups",
                "p_value_method": "regularized incomplete beta (t and F distributions)",
                "missing_policy": "rows with missing or non-numeric values excluded; never imputed",
                "randomness": "none"}
    uncertainty = [
        "Normality is assessed by a skewness heuristic, not Shapiro-Wilk or Q-Q plots.",
        "Multiple comparisons are not corrected; treat p values as unadjusted.",
        "Observations are assumed independent; pairing and clustering are not modelled.",
    ]
    if case.get("paired"):
        uncertainty.append("paired=true was requested but paired analysis is not implemented.")
    result = {"descriptive": descriptive, "assumptions": assumptions, "tests": tests,
              "effect_sizes": effect_sizes, "confidence_intervals": intervals,
              "interpretation": interpretation, "cleaning": cleaning}
    stats = {"groups": len(descriptive), "rows_read": cleaning["rows_read"],
             "rows_removed": cleaning["rows_removed"],
             "dropped_missing": cleaning["dropped_missing"],
             "duplicate_rows": cleaning["duplicate_rows"],
             "tests_run": 1 if tests.get("p_value") is not None else 0,
             "skipped": len(skipped), "errors": len(errors)}
    summary = interpretation
    payload = {"descriptive": descriptive, "assumptions": assumptions, "tests": tests,
               "effect_sizes": effect_sizes, "confidence_intervals": intervals,
               "interpretation": interpretation, "cleaning": cleaning, "summary": summary,
               "status": status, "case_id": case_id, "result": result, "evidence": evidence,
               "uncertainty": uncertainty, "errors": errors, "stats": stats}

    output = {"case_id": case_id, "status": status, "result": result, "evidence": evidence,
              "uncertainty": uncertainty, "errors": errors, "stats": stats,
              "descriptive": descriptive, "assumptions": assumptions, "tests": tests,
              "effect_sizes": effect_sizes, "confidence_intervals": intervals,
              "interpretation": interpretation, "cleaning": cleaning}
    notes, extras = [], {}
    for field in fields:
        canonical, value = resolve_contract(field, payload)
        if canonical is None:
            output[field] = None
            extras[field] = {"value": best_effort_value(field, payload),
                             "reason": "no producer matched this field name; best-effort value is returned here"}
            notes.append("%s: unmapped field kept as null; see contract_extras" % field)
        else:
            output[field] = None if isinstance(value, str) and not value.strip() else value
    if extras:
        output["contract_extras"] = extras
    if notes:
        output["contract_notes"] = notes

    try:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(output, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError as exc:
        sys.stderr.write("cannot write result: %s\n" % exc)
        return 2
    try:
        work = Path(args.work)
        work.mkdir(parents=True, exist_ok=True)
        with open(work / "stats_report.json", "w", encoding="utf-8") as fh:
            json.dump({"descriptive": descriptive, "assumptions": assumptions, "tests": tests,
                       "effect_sizes": effect_sizes, "intervals": intervals}, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError:
        pass
    try:
        import report_kit
        report_kit.augment(args.out or str(out_path), getattr(args, "case", None), ["figure.svg"])
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.environ.get("SK_RESULT_PATH") or "result.json"
            _d = os.path.dirname(os.path.abspath(_p))
            if _d:
                os.makedirs(_d, exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    _fallback = os.environ.get("SK_RESULT_PATH", "")
    if _fallback and not os.path.isfile(_fallback):
        try:
            _parent = os.path.dirname(os.path.abspath(_fallback))
            if _parent:
                os.makedirs(_parent, exist_ok=True)
            with open(_fallback, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0 if _fallback else _rc)
