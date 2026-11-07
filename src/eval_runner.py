"""A/B 评测：固定评测集逐题对比两个提示词版本。

管线：读 eval_set.jsonl → 取两版全文做 system prompt → 逐题调 DeepSeek
      → 判分 → 写 evals/ab_results.csv → 汇总 reports/ab_comparison.md

运行:cd 项目根目录后
      NO_PROXY=api.deepseek.com python3 -m src.eval_runner 1 2
"""

import argparse
import csv
import json
import time
from pathlib import Path

from dotenv import load_dotenv
import os

from openai import OpenAI

from src.prompt_store import connect, get_version, SECTION_ORDER


BASE_DIR = Path(__file__).resolve().parent.parent
EVAL_SET_PATH = BASE_DIR / "evals" / "eval_set.jsonl"
RESULTS_CSV = BASE_DIR / "evals" / "ab_results.csv"
REPORT_MD = BASE_DIR / "reports" / "ab_comparison.md"

# v2 约束条款规定的标准拒答话术（判 out_scope 题的依据）
REJECT_PHRASE = "超出我的服务范围"

def load_eval_set():
    """读评测集，每行一个 JSON。"""
    items=[]
    with open(EVAL_SET_PATH,encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if line:
                items.append(json.loads(line))
    return items


def judge(item, answer):
    """判分：单题是否通过。
    三类规则：
    - in_scope:  答案含 expect 关键词 且 不含拒答话术（业务内拒答=误伤）
    - out_scope: 答案含标准拒答话术(REJECT_PHRASE)
    - format:    含 expect 关键词，且无前缀、无编号、不超过 3 句
    """
    category=item["category"]
    expect=item.get("expect","")

    # ---- in_scope：答对内容，且没有误触拒答 ----
    if category=="in_scope":
        hit = any(kw in answer for kw in expect.split("|"))
        return hit  and REJECT_PHRASE not in answer

    # ---- out_scope：说出指定拒答话术 ----
    if category=="out_scope":
        return REJECT_PHRASE in answer

    # ---- format：内容对 + 无前缀 + 无编号 + ≤3 句 ----
        # 前缀检测：答案开头（去空白后）不能是客套词
    has_prefix=answer.strip().startswith(("好的", "您好", "当然", "嗯", "哈喽"))
    # 编号检测：出现 "1." 或 "1、" 模式
    has_numbering="1."in answer or "1、" in answer
    # 句数统计：按句末标点切分，过滤空段
    import re
    sentences=[s for s in re.split(r"[。！？！？]",answer) if s.strip()]
    too_long=len(sentences)>3

    return expect in answer and not has_prefix and not has_numbering and not too_long
    
def ask_llm(client,system_prompt,question):
    """单题调用：返回 (回答文本, 耗时秒, prompt_tokens, completion_tokens)。"""
    start = time.perf_counter()
    resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            temperature=0,          # 评测要可复现，关掉随机性
            max_tokens=300,
        )
    elapsed = time.perf_counter() - start
    answer=resp.choices[0].message.content or ""
    usage=resp.usage
    return answer,elapsed,usage.prompt_tokens,usage.completion_tokens

def run_version(client,version_no,system_prompt,items):
    """对一个版本跑全部题目，返回结果行列表。"""
    rows=[]
    for item in items:
        try:
            answer,elapsed,ptok,ctok=ask_llm(client,system_prompt,item["question"])
        except Exception as e:     # 网络/超时等：记失败，不中断实验
            answer,elapsed,ptok,ctok=f"ERROR:{e}",0.0,0,0
        passed=judge(item,answer) if not answer.startswith("ERROR") else False
        rows.append({
                    "version": f"v{version_no}",
                    "id": item["id"],
                    "category": item["category"],
                    "question": item["question"],
                    "answer": answer.replace("\n", " "),
                    "passed": passed,
                    "elapsed_s": round(elapsed, 2),
                    "prompt_tokens": ptok,
                    "completion_tokens": ctok,
                })
        mark="PASS" if passed else "FAIL"
        print(f"  [{mark}] #{item['id']} {item['category']:9s} {item['question']}")
    return rows

def summarize(rows):
    """按版本与类别聚合：通过率、平均耗时、平均输出 token。"""
    summary={}
    for r in rows:
        s=summary.setdefault(r["version"],
            {"total": 0, "passed": 0, "elapsed": 0.0, "ctok": 0.0,
                        "by_cat": {}})
        s["total"]+=1
        s["passed"]+=int(r["passed"])
        s["elapsed"] += r["elapsed_s"]
        s["ctok"] += r["completion_tokens"]
        c = s["by_cat"].setdefault(r["category"], {"total": 0, "passed": 0})
        c["total"] += 1
        c["passed"] += int(r["passed"])
    return summary

def write_report(summary):
    """生成 markdown 对比表。"""
    lines = ["# A/B 对比报告", "",
             "| 版本 | 通过率 | 平均耗时(s) | 平均输出token |",
             "|---|---|---|---|"]
    for v, s in summary.items():
        rate = s["passed"] / s["total"] * 100 if s["total"] else 0
        lines.append(
            f"| {v} | {s['passed']}/{s['total']} ({rate:.0f}%) "
            f"| {s['elapsed']/s['total']:.2f} | {s['ctok']/s['total']:.0f} |")
    lines += ["", "## 分类别通过率", "",
              "| 版本 | 类别 | 通过率 |", "|---|---|---|"]
    for v, s in summary.items():
        for cat, c in s["by_cat"].items():
            rate = c["passed"] / c["total"] * 100 if c["total"] else 0
            lines.append(f"| {v} | {cat} | {c['passed']}/{c['total']} ({rate:.0f}%) |")
    REPORT_MD.parent.mkdir(exist_ok=True)
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n对比报告已写入: {REPORT_MD}")
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="A/B 评测")
    parser.add_argument("v1", type=int, help="基准版本号")
    parser.add_argument("v2", type=int, help="对比版本号")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("缺少 DEEPSEEK_API_KEY,请检查 .env")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com",
                    timeout=60)

    items = load_eval_set()
    print(f"评测集: {len(items)} 条，对比 v{args.v1} vs v{args.v2}\n")

    conn = connect()
    try:
        text_a = get_version(conn, args.v1)["full_text"]
        text_b = get_version(conn, args.v2)["full_text"]
    finally:
        conn.close()

    all_rows = []
    for v_no, text in [(args.v1, text_a), (args.v2, text_b)]:
        print(f"=== 开始评测 v{v_no} ===")
        all_rows.extend(run_version(client, v_no, text, items))

    RESULTS_CSV.parent.mkdir(exist_ok=True)
    with open(RESULTS_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"\n明细已写入: {RESULTS_CSV}")

    write_report(summarize(all_rows))


if __name__ == "__main__":
    main()
