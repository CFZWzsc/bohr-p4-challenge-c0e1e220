# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-c0e1e220` (track: `research-data-analysis`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable pipeline and all supporting documents. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `research-stats-assumption-guard`
- Summary: Use when a research data-analysis case supplies grouped measurements and asks for descriptive statistics, group comparison, effect sizes, confidence intervals, or a defensible interpretation; run scripts/run_skill.py for a deterministic assumption-checked result.json.

## Contents

| File |
|------|
| `RUBRIC.md` |
| `SKILL.md` |
| `examples/demo-case/case.json` |
| `examples/demo-case/input/dose_response.csv` |
| `scripts/report_kit.py` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

A single deterministic pass reads `/input`, computes the deliverable and writes a
contract-complete `/app/output/result.json` plus the human-readable review files
described in `SKILL.md`. The same input always produces byte-identical output; no
network access is used, and fields the materials cannot support are reported
explicitly instead of being left empty.

## Notes

- Pure Python standard library; no network access required.
- Every claim is anchored to paragraph-level evidence; unknown items are reported
  in `uncertainty` instead of being fabricated.
