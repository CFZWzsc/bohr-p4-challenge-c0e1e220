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


def resolve_field(field, payload):
    key = norm_key(field)
    for canonical, names in ALIASES.items():
        if key == canonical or key in names:
            return canonical, payload.get(canonical)
    return None, None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Assumption-checked statistics (stdlib only)")
    parser.add_argument("--case", default="/input/case.json")
    parser.add_argument("--out", "--output", default="/app/output/result.json")
    parser.add_argument("--work", default="/app/work")
    args = parser.parse_args(argv)

    case_path = Path(args.case)
    errors, skipped, case, status = [], [], {}, "success"
    try:
        with open(case_path, "r", encoding="utf-8-sig") as fh:
            case = json.load(fh)
        if not isinstance(case, dict):
            raise ValueError("case.json root is not an object")
    except (OSError, ValueError) as exc:
        errors.append("cannot read case.json: %s" % exc)
        case, status = {}, "failed"

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

    descriptive, assumptions, tests, effect_sizes, intervals = [], {}, {}, {}, {}
    cleaning = {"rows_read": len(rows), "dropped_missing": 0, "duplicate_rows": 0}
    interpretation = ""
    groups_map = {}

    if status != "failed":
        if not rows:
            status = "insufficient_input"
        else:
            if not group_col or group_col not in header:
                candidates = []
                for name in header:
                    vals = {r[header.index(name)].strip() for r in rows}
                    if 2 <= len(vals) <= 10:
                        candidates.append(name)
                group_col = candidates[0] if candidates else None
            if not value_col or value_col not in header:
                for name in header:
                    if name == group_col:
                        continue
                    idx = header.index(name)
                    vals = [to_float(r[idx]) for r in rows if r[idx].strip().lower() not in MISSING]
                    if vals and len(vals) / float(max(1, len(rows))) >= 0.8:
                        value_col = name
                        break
            if not group_col or not value_col:
                numeric = []
                idx = header.index(value_col) if value_col in header else 0
                vals = [to_float(r[idx]) for r in rows if to_float(r[idx]) is not None]
                if vals:
                    descriptive = [{"group": "all", "n": len(vals), "mean": mean(vals),
                                    "sd": math.sqrt(var(vals)), "median": median(vals),
                                    "q1": quantile(vals, 0.25), "q3": quantile(vals, 0.75),
                                    "min": min(vals), "max": max(vals)}]
                    groups_map = {"all": vals}
                status = "partial"
                interpretation = "Group or value column could not be resolved; only a single-series description is reported."
            else:
                gi, vi = header.index(group_col), header.index(value_col)
                seen_rows, dedup = set(), 0
                for r in rows:
                    key = tuple(c.strip() for c in r)
                    if key in seen_rows:
                        dedup += 1
                    else:
                        seen_rows.add(key)
                    g = r[gi].strip() or "missing_group"
                    v = to_float(r[vi])
                    if r[vi].strip().lower() in MISSING or v is None:
                        cleaning["dropped_missing"] += 1
                        continue
                    groups_map.setdefault(g, []).append(v)
                cleaning["duplicate_rows"] = dedup
                groups_map = {k: v for k, v in groups_map.items() if v}
                for name in sorted(groups_map):
                    vals = groups_map[name]
                    descriptive.append({"group": name, "n": len(vals), "mean": mean(vals),
                                        "sd": math.sqrt(var(vals)) if len(vals) > 1 else None,
                                        "median": median(vals), "q1": quantile(vals, 0.25),
                                        "q3": quantile(vals, 0.75), "min": min(vals), "max": max(vals),
                                        "skewness": skew(vals)})
                k = len(groups_map)
                min_n = min(len(v) for v in groups_map.values()) if groups_map else 0
                bf = brown_forsythe(list(groups_map.values()))
                assumptions = {
                    "normality": {
                        "method": "skewness heuristic (not Shapiro-Wilk)",
                        "per_group": [{"group": str(d["group"]), "skewness": d["skewness"],
                                       "n": d["n"],
                                       "flag": bool(d["skewness"] is not None and abs(d["skewness"]) > 1 and d["n"] < 30)}
                                      for d in descriptive],
                    },
                    "variance": {"method": "Brown-Forsythe (median-centered Levene)",
                                 "F": bf["F"] if bf else None, "p": bf["p"] if bf else None,
                                 "equal_variance_rejected": bool(bf and bf["p"] is not None and bf["p"] < alpha)} if bf else
                                {"method": "Brown-Forsythe", "note": "not computable"},
                    "sample_size_ok": min_n >= 3 and k >= 2,
                }
                if k < 2 or min_n < 3:
                    tests = {"method": "none", "reason": "insufficient groups or group size below 3",
                             "p_value": None}
                    status = "partial"
                else:
                    alpha_used = alpha
                    vals_by_group = [groups_map[g] for g in sorted(groups_map)]
                    if k == 2:
                        res = welch(vals_by_group[0], vals_by_group[1])
                        if res is None:
                            tests = {"method": "Welch t-test", "statistic": None,
                                     "reason": "zero standard error; test not evaluable", "p_value": None}
                            status = "partial"
                        else:
                            tests = {"method": "Welch two-sample t-test", "statistic": res["t"],
                                     "df": res["df"], "p_value": res["p"], "alpha": alpha_used,
                                     "alternative": "two-sided",
                                     "mean_difference": res["mean_diff"]}
                            effect_sizes = {"cohen_d": res["cohen_d"], "hedges_g": res["hedges_g"],
                                            "magnitude": ("small" if abs(res["cohen_d"] or 0) < 0.5 else
                                                          "medium" if abs(res["cohen_d"] or 0) < 0.8 else "large")}
                            intervals = {"mean_difference_ci95": res["diff_ci95"],
                                         "method": "Welch standard error with t critical value"}
                    else:
                        an = one_way(vals_by_group)
                        if an is None:
                            tests = {"method": "one-way ANOVA", "statistic": None,
                                     "reason": "within-group variance is zero", "p_value": None}
                            status = "partial"
                        else:
                            tests = {"method": "one-way ANOVA", "statistic": an["F"],
                                     "df1": an["df1"], "df2": an["df2"], "p_value": an["p"],
                                     "alpha": alpha_used, "alternative": "greater"}
                            effect_sizes = {"eta_squared": an["eta_squared"],
                                            "magnitude": ("small" if an["eta_squared"] < 0.06 else
                                                          "medium" if an["eta_squared"] < 0.14 else "large")}
                            intervals = {"note": "ANOVA does not provide a single mean-difference interval",
                                         "group_mean_ci95": [
                                             {"group": str(d["group"]),
                                              "ci95": [d["mean"] - t_crit(max(1, d["n"] - 1)) * (d["sd"] or 0) / math.sqrt(max(1, d["n"])),
                                                       d["mean"] + t_crit(max(1, d["n"] - 1)) * (d["sd"] or 0) / math.sqrt(max(1, d["n"]))]
                                              if d["sd"] is not None else None}
                                             for d in descriptive]}
                    p = tests.get("p_value")
                    sig = (p is not None and p < alpha_used)
                    interp = ("A Welch two-sample comparison" if k == 2 else "A one-way ANOVA")
                    if p is None:
                        interpretation = "Test could not be evaluated; descriptive statistics are reported without a p value."
                    else:
                        interpretation = ("%s gives p=%.4g at alpha=%.2f; this is %s. "
                                          "The effect size is %s; statistical significance is not proof of a causal or practically important effect."
                                          % (interp, p, alpha_used,
                                             "statistically significant" if sig else "not statistically significant",
                                             effect_sizes.get("magnitude", "not reported")))
                        if any(a.get("flag") for a in assumptions["normality"]["per_group"]):
                            status = "partial"
                            interpretation += " Some groups are skewed with small n, so a nonparametric check is advisable."
                        if assumptions["variance"].get("equal_variance_rejected"):
                            status = "partial"
                            if k > 2:
                                interpretation += " Variance homogeneity is rejected; a Welch ANOVA is not implemented here."
                if cleaning["dropped_missing"] or cleaning["duplicate_rows"]:
                    status = "partial" if status == "success" else status

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
             "dropped_missing": cleaning["dropped_missing"],
             "duplicate_rows": cleaning["duplicate_rows"],
             "tests_run": 1 if tests.get("p_value") is not None else 0,
             "skipped": len(skipped), "errors": len(errors)}
    summary = interpretation or "No statistical analysis was produced."
    payload = {"descriptive": descriptive, "assumptions": assumptions, "tests": tests,
               "effect_sizes": effect_sizes, "confidence_intervals": intervals,
               "interpretation": interpretation, "cleaning": cleaning, "summary": summary,
               "status": status, "case_id": case_id, "result": result, "evidence": evidence,
               "uncertainty": uncertainty, "errors": errors, "stats": stats}

    output = {"case_id": case_id, "status": status, "result": result, "evidence": evidence,
              "uncertainty": uncertainty, "errors": errors, "stats": stats,
              "descriptive": descriptive, "assumptions": assumptions, "tests": tests,
              "effect_sizes": effect_sizes, "confidence_intervals": intervals,
              "interpretation": interpretation}
    notes = []
    for field in fields:
        canonical, value = resolve_field(field, payload)
        if canonical is None:
            output[field] = None
            notes.append("%s: no supported producer in this skill; null retained" % field)
        else:
            output[field] = value
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
    return 0


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.path.join("/app/output", "result.json")
            os.makedirs("/app/output", exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    if not os.path.isfile("/app/output/result.json"):
        try:
            os.makedirs("/app/output", exist_ok=True)
            with open("/app/output/result.json", "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0)
