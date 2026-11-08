# 提示词 A/B 台：提示词版本化管理与对比回滚

一套轻量的提示词治理工作台，覆盖提示词生命周期的完整闭环：

```text
登记（new/add）→ 对比（diff）→ 评测（A/B eval）→ 发布（deploy）→ 回滚（rollback）→ 验收（acceptance）
```

所有核心机制零框架手写：SQLite 三表版本库、四段骨架提示词解析、sha256 全文
指纹、unified_diff 差异视图、20 条固定评测集 A/B 对比、带指纹校验的一键回滚。

## 项目背景

提示词是 LLM 应用的"源代码"，但常被随手改在某个 txt 文件里——改了什么、
为什么改、效果如何、出事怎么退回，全无痕迹。本项目把软件工程的版本管理
方法论搬到提示词上：**改有据、存有证、滚可信**。

## 目录结构

```text
├── src/
│   ├── prompt_store.py    版本库核心：三表存储 + init/new/add/list/show/deploy/rollback CLI
│   ├── differ.py          版本 diff：unified_diff 全文对比 + 分段落定位改动
│   └── eval_runner.py     A/B 评测：加载评测集 → 调 LLM → 判分 → 出对比报告
├── evals/
│   └── eval_set.jsonl     20 条固定评测集（in_scope 8 / out_scope 8 / format 4）
├── scripts/
│   └── acceptance.py      端到端验收：版本化率 + 回滚一致率，双 100% 才通过
├── templates/             四段骨架模板与两版草稿
├── registry/              变更登记表（changes 表的人工镜像）+ 回滚演练记录
├── reports/               ab_comparison.md（自动生成）+ ab_report.md（验收报告）
└── online/                线上文件 current_prompt.txt（当前生效版投影）
```

## 快速上手

```bash
# 1. 初始化版本库
python3 -m src.prompt_store init

# 2. 登记版本（四段骨架草稿）
python3 -m src.prompt_store new --file templates/draft_v1_宽松版.txt \
    --name 客服初版 --author xh --reason "基线版本"

# 3. 版本对比
python3 -m src.differ 1 2

# 4. A/B 评测（需在 .env 配置 DEEPSEEK_API_KEY）
pip3 install openai python-dotenv
NO_PROXY=api.deepseek.com python3 -m src.eval_runner 1 2
# 产出 evals/ab_results.csv 与 reports/ab_comparison.md

# 5. 发布 / 回滚（均带 sha256 指纹校验）
python3 -m src.prompt_store deploy 2
python3 -m src.prompt_store rollback 1

# 6. 端到端验收
python3 -m scripts.acceptance
# 全绿打印 ACCEPTANCE PASSED 并以退出码 0 结束；
# 任一检查失败打印 ACCEPTANCE FAILED 并以退出码 1 结束
```

## 实验结果

20 条评测集、temperature=0、DeepSeek：

| 版本 | 通过率 | in_scope | out_scope | format | 平均输出token |
|---|---|---|---|---|---|
| v1 宽松基线 | 50% | 100% | 0% | 50% | 78 |
| v2 收紧版 | **100%** | 100% | **100%** | **100%** | **23** |

v2 在业务能力无损的前提下补齐拒答与格式，成本降 70%。详见
[reports/ab_report.md](reports/ab_report.md)。

## 验收指标

| 指标 | 含义 | 结果 |
|---|---|---|
| 版本化率 | 每版登记三件套齐全（改动人/原因/评测结论） | 2/2 (100%) |
| 回滚一致率 | 档案指纹自洽 + 线上文件与指针版本一致 | 3/3 (100%) |

并完成篡改注入负向测试：改坏线上文件 → 验收报 FAIL（退出码 1）→
rollback 一键恢复 → 验收回绿。

## 设计要点

- **三态分离**：草稿（工作区）/ 版本库（SQLite 档案室）/ 线上文件（生效版
  投影），线上坏了随时重新投影；
- **先落实后宣布**：rollback 先写文件、指纹验货通过，最后才动 meta 指针，
  永不出现"指针说 v1、文件是残次品"的分裂态；
- **公平评测**：同一份考卷、同一模型、temperature=0，v1/v2 唯一变量是提示词
  本身；
- **验收只检测不修复**：acceptance.py 忠实报告问题，修复由人经 rollback
  完成，避免验收脚本越权。

## 环境要求

- Python 3.9+
- SQLite3（macOS/Linux 自带）
- `.env` 中配置 `DEEPSEEK_API_KEY`（仅评测步骤需要）

## License

MIT
