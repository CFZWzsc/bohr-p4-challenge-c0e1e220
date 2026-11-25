---
name: research-stats-assumption-guard
description: Use when a research data-analysis case supplies grouped measurements and asks for descriptive statistics, group comparison, effect sizes, confidence intervals, or a defensible interpretation; run scripts/run_skill.py for a deterministic assumption-checked result.json.
---

# 统计分析与结果解读（假设前置）

## 用途与适用条件

在两组或多组科研数据的描述统计与组间比较中使用：先检查缺失、重复与分布假设，再选择检验方法，输出效应量、置信区间与可读解释。输入为 `/input/case.json`、可选 `/input/task.md` 与 CSV/TSV 数据。

不适用：实验设计、样本量估算、生存分析、混合模型、多重插补。脚本不做因果推断，也不把 p 值转述为「证明有效」。

## Quickstart

包内自带一个合成演示案例，可直接跑通：

```powershell
python scripts/run_skill.py --case examples/demo-case/case.json --out "$env:TEMP\demo_c0e1e220\result.json" --work "$env:TEMP\demo_c0e1e220\work"
```

- 演示输入：`examples/demo-case/case.json` + `examples/demo-case/input/dose_response.csv`（3 组；`high_dose` 仅 1 个观测，`low_dose` 含 1 条完全重复行，用于演示降级与去重告警）。
- 输出：`$env:TEMP\demo_c0e1e220\result.json`；因一组 n<3 不运行推断检验，`tests.method="none"` 并写明原因，`assumptions.variance.method="not_applicable"`；`descriptive` 给出每组 n/均值/SD/中位数/四分位，`confidence_intervals.group_mean_ci95` 给出可估组的均值区间，`interpretation` 说明为何未检验及「显著不等于因果关系」，`status="partial"`。
- `output_contract` 的 `descriptive`、`tests`、`effect_sizes`、`interpretation` 四个键均非空；同一输入连续两次运行的 result.json 字节一致。

> 数据为合成样本，不代表任何真实实验或官方评测数据。

## 输入

- `case.json`：`case_id`、`output_contract`；可选 `group_column`、`value_column`、`alpha`、`paired`。
- 未指定列时自动推断：优先取 2–10 个取值的分类列作分组、可解析数值列作测量值；表头中没有分类列而只有单一数值列时按单序列描述，并在 `evidence` 记录推断依据。
- 输出：`/app/output/result.json`。

## 处理流程（对应评分维度）

1. **数据准备（任务完成度）**：读取表头、编码与分隔符；缺失值不入组、不填补，记录剔除行数与比例；`case.json` 给出且存在于表头的 `key_columns` 按键去重（保留首次出现，记录 `cleaning.rows_removed` 与 `dedup_rule`），否则完全重复行计数保留并在 `cleaning` 告警「duplicate observations inflate n」。
2. **描述统计（正确性）**：每组给出 n、均值、样本标准差、中位数、Q1/Q3、最小/最大；口径与单位来源写入 `evidence`。
3. **假设检查（规范性）**：用偏度与样本量做分布提示（明确标注为启发式，非 Shapiro-Wilk）；仅当组数 ≥2 且每组 n≥2 时用 Brown-Forsythe 检验方差齐性，否则 `assumptions.variance.method="not_applicable"` 并给原因；假设不满足时降级并在 `interpretation` 说明。
4. **推断统计（正确性）**：两组用 Welch t 检验（不假设方差齐性）；多组用单因素方差分析；样本量不足、组内方差为零、组数不足时**不给 p 值**，只给描述统计。
5. **效应量与区间（完整性）**：两组给 Cohen's d 与 Hedges g；多组给 eta²；每组 n≥2 时给均值 95% 置信区间（t 临界值由不完全 beta 函数数值求解），区间与检验口径一致；确实不可估时写 `not_estimable` 及原因，不留空对象。
6. **结果解释（可读性）**：每条分支（含无数据、列无法解析、n<3、零方差）都写出比较对象、各组 n、描述差异、检验取舍原因与限制；区分统计显著与实际意义，标注 α、单/双侧、样本量限制、多重比较未校正等，不写因果结论。
7. **可复跑（可核验性）**：输出输入哈希、方法选择规则、公式版本；无随机过程与时间戳。

## 输出契约

| 字段 | 含义 |
|-|-|
| `case_id` | 与输入一致 |
| `output_contract` 各字段 | 按名称/关键词映射到 `descriptive`/`tests`/`effect_sizes`/`confidence_intervals`/`interpretation`/`cleaning`；无法映射时保留 `null` 并在 `contract_extras` 给最佳努力值与原因 |
| `status` | `success` / `partial` / `insufficient_input` / `failed` |
| `result` | `descriptive`、`assumptions`、`tests`、`effect_sizes`、`confidence_intervals`、`interpretation` |
| `evidence` | 数据文件哈希、列映射、方法规则、α |
| `uncertainty` | 启发式正态性、未校正多重比较、非随机样本 |
| `errors` / `stats` | 真实错误与计数 |

## 异常处理表

| 情况 | 处置 | 状态 |
|-|-|-|
| case.json 缺失/非法 | 结构化失败结果 + 错误说明 | `failed` |
| 无数据文件 | 各产出字段显式 `not_estimable` 并说明 | `insufficient_input` |
| 找不到分组/数值列 | 只做单变量描述并说明 | `partial` |
| 组数 < 2 | 不检验，仅描述 | `partial` |
| 任一组 n < 3（含 n < 2） | 不检验，给描述与说明；n < 2 时方差齐性标 `not_applicable` | `partial` |
| 组内方差为零 | 不计算 t/F，标注退化 | `partial` |
| 缺失比例 > 50% | 报告并标注结果不稳 | `partial` |
| 方差齐性不成立 | 两组仍用 Welch；多组标注未做 Welch ANOVA | `partial` |

## 限制

- 正态性判断是偏度启发式，不能替代 Shapiro-Wilk / Q-Q 图。
- 未实现 Welch ANOVA、非参数检验、配对检验与多重比较校正；`paired=true` 时只在 `uncertainty` 说明未处理。
- 只读数据，不改写源文件；不做单位换算。

## 最小调用示例（示例，非官方案例结果）

```bash
python /skills/weekly-skill/scripts/run_skill.py --case /input/case.json --out /app/output/result.json --work /app/work
```

示意输入 `{"case_id":"synthetic-demo","output_contract":{"tests":"object","effect_sizes":"object"}}`；示意输出保留 `case_id`、`tests`、`effect_sizes`、`status`，无数据时为 `insufficient_input`。仅为接口示例。


## 交付保证与评分对齐

调用顺序（固定）：

1. 先运行包内脚本（若存在）：`python scripts/run_skill.py`（默认读 `/input/case.json`，写 `/app/output/result.json`）；路径不同时用 `--case` / `--output` 指定。
2. 再完成脚本无法自动完成的实质工作（译文、论述、图表、修订、结论等），把结果写回 `result.json` 对应字段。
3. 最后自检：`case_id` 与输入一致；`output_contract` 每个字段都存在；`status` 按契约取 `success`/`partial`/`insufficient_input`/`failed`（缺输入或证据不足时用 `insufficient_input`/`partial`）；无 `pending` 占位；数字、引用、来源可逐条回溯。

运行保证：

- 输入缺失、JSON 损坏、字段异常、输出目录不存在时，仍须写出结构化 `result.json` 并正常结束，不得崩溃或非零退出。
- 不联网、不伪造数据、不声称平台评分或官方案例结果。
- 交付物必须是可直接编辑与复核的成品，而不是流程说明。

评分对齐（本题五个维度）：

- 实际效果（40）：完整产出任务要求的最终成品，覆盖全部输入条目，可直接进入修改流程。
- 使用增益（25）：体现相对基础 Agent 的可验证改进（结构化、术语/数字/引用核对、可编辑性）。
- 创新增益（15）：保留方法学增量（分块、对齐、二次校验、版本比对等），并用结果证明其价值。
- 可靠体验（10）：异常输入有明确降级与说明，不同长度/文体/重复运行下稳定产出。
- 生态贡献（10）：用途、调用、输入输出、限制、示例、维护信息齐全，资源可被他人复用。

## 最终交付强制要求

1. **调用 Agent 必须交付成品，不是流程说明**：脚本产出只是索引、核对或规格骨架；调用 Agent 必须在同一 `result.json` 中补齐本题要求的最终产物（正文/译文/审稿意见/综述/分析结论/图表源文件与导出件/幻灯片页内容与讲稿/实验方案等）。交付字段为空、只有标题骨架，或含 `pending`、`TODO` 之类占位，一律视为未完成。
2. **必须覆盖全部输入条目**：输入中的每个章节、问题、文献、图、页面、指标都要有对应条目，不得只处理示例或首条；确实缺失的条目写入 `uncertainty` / `limitations` 并说明原因，不得静默跳过。
3. **必须自检后再交付**：`case_id` 与输入一致；`output_contract` 每个字段都存在；状态值取本题契约规定的枚举；数字、单位、引用、来源可逐条回溯；结果内部无自相矛盾。
4. **参数等价**：`python scripts/run_skill.py --case <输入> --out <输出>` 与 `--output <输出>` 等价；默认 `/input/case.json` → `/app/output/result.json`。
5. **平台用 3 个固定案例分别运行**：逻辑要由输入驱动，不针对某一份示例硬编码；字段命名差异走别名匹配与显式降级，并在 `uncertainty` 记录假设。
