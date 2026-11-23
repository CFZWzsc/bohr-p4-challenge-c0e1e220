# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-c0e1e220` (track: `research-data-analysis`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable entry point and all supporting scripts. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `research-stats-assumption-guard`
- Summary: Use when a research data-analysis case supplies grouped measurements and asks for descriptive statistics, group comparison, effect sizes, confidence intervals, or a defensible interpretation; run scripts/run_skill.py for a deterministic assumption-checked result.json.

## Contents

| File |
|------|
| `SKILL.md` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/run_skill.py --case /input/case.json --output /app/output/result.json
```

The entry point is `SKILL.md`; input/output contracts, error handling and a minimal
usage example are documented there.

## Notes

- Pure Python standard library; no network access required.
- The result JSON keeps the input case id, the main results, per-item evidence,
  a run status and an uncertainty section.
