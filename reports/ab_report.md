# 提示词 A/B 台：端到端验收报告

项目：提示词版本化管理与对比回滚（五天实战）
日期：2026-11-08
作者：xh

---

## 一、项目做了什么

自研一套轻量提示词治理工作台，覆盖提示词生命周期的四个环节：

```text
登记（new/add）→ 对比（diff）→ 评测（A/B eval）→ 发布与回滚（deploy/rollback）
```

全部核心机制手写完成：SQLite 三表版本库（versions/changes/meta）、四段骨架
提示词的解析与拼装、sha256 全文指纹、unified_diff 差异视图、20 条固定评测集
的 A/B 对比管线、带指纹校验的一键回滚。

## 二、A/B 评测结果（20 条固定评测集，DeepSeek，temperature=0）

| 版本 | 通过率 | 平均耗时(s) | 平均输出token |
|---|---|---|---|
| v1（宽松基线） | 10/20 (50%) | 1.32 | 78 |
| v2（收紧版） | 20/20 (100%) | 0.96 | 23 |

### 分类别通过率

| 版本 | in_scope（8题） | out_scope（8题） | format（4题） |
|---|---|---|---|
| v1 | 8/8 (100%) | 0/8 (0%) | 2/4 (50%) |
| v2 | 8/8 (100%) | 8/8 (100%) | 4/4 (100%) |

### 结论

v2 在不损失业务能力的前提下（in_scope 保持 100%）：

1. **拒答能力从 0 到 100%**：8 道超范围陷阱题（天气、写诗、竞品对比等）全部
   按约束回复标准拒答话术，不再失控作答；
2. **格式合规从 50% 到 100%**：无寒暄前缀、无编号、≤3 句，全部达标；
3. **成本与速度双优化**：平均输出 token 降 70%（78→23），平均耗时降 27%
   （1.32s→0.96s）。

**实验归因**：v1→v2 的改动集中在约束段（新增拒答话术/长度上限/禁编造）与
输出格式段（禁止前缀编号）。分类别数据与改动点一一对应，差异可归因。

### 判分器已知局限

关键词判分存在误伤案例：v2 首轮评测中"笔记同步失败"一题回答内容正确，但因
≤3 句约束压缩了措辞、未出现预期关键词而误判 FAIL。修复方式：expect 字段支持
`|` 分隔的多关键词，命中任一即通过。此案例说明关键词判分的边界——适合回归
测试，不适合语义级评估（改进方向：LLM-as-judge）。

## 三、端到端验收（scripts/acceptance.py）

两个 100% 指标全部达成：

```text
=== 版本化率 ===
  [OK]   v1 登记完整
  [OK]   v2 登记完整
=== 回滚一致率 ===
  [OK]   v1 档案指纹一致
  [OK]   v2 档案指纹一致
  [OK]   线上文件 == v2 全文（指纹一致）

=== 验收结论 ===
版本化率:   2/2 (100%)
回滚一致率: 3/3 (100%)
ACCEPTANCE PASSED
```

- **版本化率**：每版登记三件套（改动人/原因/评测结论）齐全，无黑操作改动
- **回滚一致率**：档案层（正文 vs 库内指纹）+ 线上层（线上文件 vs 指针版本
  指纹）全部一致

### 验收过程插曲：抓到一处真实漏账

首轮验收即报 `[FAIL] v1: 评测结论未回写`——Day 3 的结论回写 UPDATE 只覆盖了
v2，v1 仍是 pending。验收脚本首次运行就抓到了真实流程遗漏，修复后回绿。
这验证了"版本化率"检查的实际价值：流程合规靠机器巡检，不靠自觉。

### 负向测试：篡改注入攻防

```text
[攻击]   echo "被人手动改坏的内容" >> online/current_prompt.txt
[报警]   [FAIL] 线上文件与 v2 不一致（可能被篡改）
         回滚一致率: 2/3 (67%)  ACCEPTANCE FAILED  退出码 1
[恢复]   rollback 2（指纹校验通过）
[复盘]   验收复跑全绿，回滚一致率回到 3/3 (100%)
```

结论：线上文件被篡改时，验收体系能**当场发现**，回滚机制能**一键恢复**，
构成"检测 → 告警 → 恢复"的完整闭环。

## 四、回滚演练摘要

双向演练各一次（v2→v1、v1→v2），每次均含"写入 → 回读 → sha256 比对"三道
校验，指纹校验 2/2 通过。详见 registry/回滚演练记录.md。

## 五、复现命令

```bash
# 版本管理
python3 -m src.prompt_store init
python3 -m src.prompt_store new --file templates/draft_v1_宽松版.txt \
    --name 客服初版 --author xh --reason "基线版本"
python3 -m src.prompt_store list / show 2

# 差异对比
python3 -m src.differ 1 2

# A/B 评测（需 .env 配置 DEEPSEEK_API_KEY）
NO_PROXY=api.deepseek.com python3 -m src.eval_runner 1 2
# 产出: evals/ab_results.csv + reports/ab_comparison.md

# 发布与回滚
python3 -m src.prompt_store deploy 2
python3 -m src.prompt_store rollback 1

# 端到端验收
python3 -m scripts.acceptance        # 全绿退出码 0，任一失败退出码 1
```

## 六、遗留与改进方向

1. change_registry.md 仍为手工镜像，可自动化为脚本生成；
2. judge 为关键词规则，语义级评估可升级 LLM-as-judge（promptflow 的评测流
   即此思路）；
3. rollback 校验后可追加自动复跑 acceptance，进一步缩短"告警→恢复"链路。
