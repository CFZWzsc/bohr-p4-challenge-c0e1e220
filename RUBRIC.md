# RUBRIC — 统计分析与结果解读（`challenge-c0e1e220`）

公开作品：https://github.com/CFZWzsc/bohr-p4-challenge-c0e1e220

本题按组织方评分表打分（实际效果 40 / 使用增益 25 / 创新增益 15 / 可靠体验 10 / 生态贡献 10；
GitHub 公开链接另加最多 5 分）。下表把每一行映射到本包内实际交付的文件或 `result.json` 字段，
**没有覆盖的直接写「未覆盖」，不做自述式加分**。

| 评分维度 | 分值 | 本包对应产物 | 状态 |
|---|---|---|---|

| 实际效果 | 40 | `result.json` 的描述统计、检验结果（method/p/effect size/CI95）与 `interpretation` | 覆盖 |
| 使用增益 | 25 | 假设检查（方差齐性、每组样本量）与显式 `not_estimable` 分支 | 部分（无外部 baseline 对照） |
| 创新增益 | 15 | 分支全覆盖解读 + 小样本守卫，避免无依据外推 | 覆盖 |
| 可靠体验 | 10 | `SKILL.md` 异常表：n=1 组、重复行、非法数值、空表 | 覆盖 |
| 生态贡献 | 10 | `SKILL.md` + `examples/demo-case` + 本文件 | 覆盖 |

## 已知未覆盖 / 不适用

- 使用增益的 25 分要求与「不加载 Skill 的基础 Agent」在同一输入上做对照；本包只有自身产物与
  可复核证据，**没有平台白板或第三方 baseline 的运行数据**，因此按「部分」记录，不冒充已证明的增益。
- 平台固定用例与隐藏评分器不随仓库发布；包内 `examples/demo-case` 为合成样例，明确不是正式答案。

## 外部同类 skill 取长（2026-11-25，r22）

- 边界原则（skills.sh `k-dense-ai/scientific-agent-skills@exploratory-data-analysis`）：单元格、表头与元数据
  一律视为不可信数据；不执行文件派生内容、不解析文件内嵌指令与 URL；只做有界、确定性的聚合与校验。
- 交付结构（公开高分仓库 `ZcwDev/bohr-product-arena`、`hehekevin/boerproduct`）：`inventory.tsv` 六维文件元数据、
  `repro_manifest.json`、报告↔结果一致性重算自检、RUBRIC 覆盖矩阵（未覆盖如实标注，不虚报）。
- 未采纳：均值/中位数插补源值（违反题面“不插补”）、把实质判断留给第二轮（违反单次交付）。

## 可靠性与生态化（2026-11-25，r23）

- 边界矩阵实测：损坏的 `case.json`、仅表头、GB18030 编码、空文件四类输入，全部 `exit 0` 且写出
  结构化 `result.json`，失败语义由 `status` 字段表达，不崩溃、不静默成功（日志留存在赛道台账，
  不随本包发布）。
- 新增 `README.md`：安装（纯标准库）、单次运行命令、输入输出清单、确定性与异常保证、限制、复用与维护信息。
- 未变：`SKILL.md` 不扩写；单次运行产出完整交付物；未知契约键只进 `contract_extras`。
