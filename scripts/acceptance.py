"""验收脚本：一键输出版本化率与回滚一致率，全部通过才以退出码 0 结束。

用法（项目根目录下）：
    python3 -m scripts.acceptance
"""

from src.prompt_store import BASE_DIR, connect, get_version, sha256_text

ONLINE_FILE = BASE_DIR / "online" / "current_prompt.txt"


def check_registry(conn):
    """版本化率：每个版本都有登记，且登记字段齐全、评测结论已回写。"""
    rows = conn.execute(
        "SELECT v.version_no, c.author, c.reason, c.eval_conclusion"
        " FROM versions v LEFT JOIN changes c ON c.version_no = v.version_no"
        " ORDER BY v.version_no"
    ).fetchall()
    ok = 0
    for r in rows:
        problems = []
        if not r["author"]:
            problems.append("缺改动人")
        if not r["reason"]:
            problems.append("缺改动原因")
        if r["eval_conclusion"] in (None, "", "pending"):
            problems.append("评测结论未回写")
        if problems:
            print(f"  [FAIL] v{r['version_no']}: {', '.join(problems)}")
        else:
            ok += 1
            print(f"  [OK]   v{r['version_no']} 登记完整")
    total = len(rows)
    return ok, total, (ok / total * 100 if total else 0)


def check_fingerprints(conn):
    """回滚一致率（档案层）：每个版本全文现场重算指纹，与入库时存的比对。"""
    rows = conn.execute(
        "SELECT version_no, full_text, sha256 FROM versions ORDER BY version_no"
    ).fetchall()
    ok = 0
    for r in rows:
        if sha256_text(r["full_text"]) == r["sha256"]:
            ok += 1
            print(f"  [OK]   v{r['version_no']} 档案指纹一致")
        else:
            print(f"  [FAIL] v{r['version_no']} 档案指纹不一致！")
    total = len(rows)
    return ok, total, (ok / total * 100 if total else 0)


def check_online(conn):
    """回滚一致率（线上层）：线上文件内容与指针指向版本的全文指纹一致。"""
    pointer = conn.execute(
        "SELECT value FROM meta WHERE key='current_version'"
    ).fetchone()
    if pointer is None:
        print("  [FAIL] meta 表没有 current_version 指针")
        return 0, 1, 0.0
    target_no = int(pointer["value"])

    if not ONLINE_FILE.exists():
        print("  [FAIL] 线上文件不存在（从未 deploy 过）")
        return 0, 1, 0.0

    online_text = ONLINE_FILE.read_text(encoding="utf-8")
    archive_text = get_version(conn, target_no)["full_text"]
    if sha256_text(online_text) == sha256_text(archive_text):
        print(f"  [OK]   线上文件 == v{target_no} 全文（指纹一致）")
        return 1, 1, 100.0
    print(f"  [FAIL] 线上文件与 v{target_no} 不一致（可能被篡改）")
    return 0, 1, 0.0


def main():
    conn = connect()
    try:
        print("=== 版本化率 ===")
        a_ok, a_total, a_rate = check_registry(conn)

        print("=== 回滚一致率 ===")
        b_ok, b_total, _ = check_fingerprints(conn)
        c_ok, c_total, _ = check_online(conn)
        r_ok, r_total = b_ok + c_ok, b_total + c_total
        r_rate = r_ok / r_total * 100 if r_total else 0
    finally:
        conn.close()

    print("\n=== 验收结论 ===")
    print(f"版本化率:   {a_ok}/{a_total} ({a_rate:.0f}%)")
    print(f"回滚一致率: {r_ok}/{r_total} ({r_rate:.0f}%)")

    passed = a_rate == 100 and r_rate == 100
    print(f"\n{'ACCEPTANCE PASSED' if passed else 'ACCEPTANCE FAILED'}")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
