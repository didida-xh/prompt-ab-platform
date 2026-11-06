"""提示词版本库:SQLite 存储四段骨架提示词的版本历史与变更登记。

表结构
- versions  版本正文（四段分存 + 拼装全文 + sha256 指纹）
- changes   变更登记（谁改的 / 为何改 / 评测结论）
- meta      键值元数据(current_version 指针）

纯本地操作，不发起任何模型调用。
"""

import argparse
import hashlib
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "prompts.db"

# 四段在草稿文件中必须按此顺序出现
SECTION_ORDER = ["role_seg", "task_seg", "constraint_seg", "format_seg"]
SECTION_HEADERS = {
    "role_seg": "## 角色",
    "task_seg": "## 任务",
    "constraint_seg": "## 约束",
    "format_seg": "## 输出格式",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_no INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    role_seg TEXT NOT NULL,
    task_seg TEXT NOT NULL,
    constraint_seg TEXT NOT NULL,
    format_seg TEXT NOT NULL,
    full_text TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS changes (
    version_no INTEGER NOT NULL,
    author TEXT NOT NULL,
    reason TEXT NOT NULL,
    eval_conclusion TEXT NOT NULL DEFAULT 'pending',
    changed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

def connect():
    if not DB_PATH.exists():
        raise SystemExit("版本库不存在，请先执行: python -m src.prompt_store init")
    conn=sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn=sqlite3.connect(DB_PATH)#初始化时先直接建立链接，不用上面connect函数
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"版本库已就绪: {DB_PATH}")

def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def assemble(segments):
    """四段拼装为完整提示词全文，段间以空行分隔。"""
    parts=[]
    for key in SECTION_ORDER:
        parts.append(SECTION_HEADERS[key]+"\n"+segments[key].strip())
    return "\n\n".join(parts)

def parse_draft(path):
    """解析草稿文件为四段字典，校验四段齐全且顺序正确。"""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()

    positions={}    #四个段头各自的行号（下标） ，装进`positions` 字典
    for key in SECTION_ORDER:
        for i,line in enumerate(lines):
            if line.strip()==SECTION_HEADERS[key]:
                positions[key]=i
                break
    missing=[SECTION_HEADERS[k] for k in SECTION_ORDER if k not in positions]
    if missing:
        raise SystemExit(f"草稿缺失段落:{missing}")
  # 校验顺序：段头行号必须递增
    ordered=[positions[k] for k in SECTION_ORDER]
    if ordered!=sorted(ordered):
        raise SystemExit("草稿四段顺序错误，必须为 角色→任务→约束→输出格式")

    segments={}
    for idx,key in enumerate(SECTION_ORDER):
        start=positions[key]+1
        end=positions[SECTION_ORDER[idx+1]] if idx+1<len(lines) else len(lines)
        content="\n".join(lines[start:end]).strip()
        if not content:
            raise SystemExit(f"段落 {SECTION_HEADERS[key]} 内容为空")
        segments[key]=content

    return segments


#给新版本发号——查一下库里最大的版本号是几，然后 +1 作为新版本号
def next_version_no(conn):
    row = conn.execute("SELECT MAX(version_no) AS m FROM versions").fetchone()
    return (row["m"] or 0) + 1


#把一个新版本正式写进 versions 表
def insert_version(conn, name, segments):
    full_text = assemble(segments)
    v_no = next_version_no(conn)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO versions (version_no, name, role_seg, task_seg, constraint_seg,"
        " format_seg, full_text, sha256, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (v_no, name, segments["role_seg"], segments["task_seg"],
         segments["constraint_seg"], segments["format_seg"],
         full_text, sha256_text(full_text), now),
    )
    return v_no, full_text


def insert_change(conn, v_no, author, reason, eval_conclusion="pending"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO changes (version_no, author, reason, eval_conclusion, changed_at)"
        " VALUES (?,?,?,?,?)",
        (v_no, author, reason, eval_conclusion, now),
    )


#更新版本库的“当前指针”——记录现在生效的版本是几号
def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?,?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )

#按号取版本
def get_version(conn, v_no):
    row = conn.execute("SELECT * FROM versions WHERE version_no=?", (v_no,)).fetchone()
    if row is None:
        raise SystemExit(f"版本 v{v_no} 不存在")
    return row


 #---------------- CLI 子命令 ----------------

def cmd_init(_args):
    init_db()

def cmd_new(args):
    segments=parse_draft(args.file)
    conn=connect()
    try:
        v_no,_=insert_version(conn,args.name,segments)
        insert_change(conn,v_no,args.author,args.reason)
        set_meta(conn,"current_version",v_no)
        conn.commit()
        print(f"已创建 v{v_no}({args.name})，当前版本指针 -> v{v_no}")
    finally:
        conn.close()


def cmd_add(args):
    conn = connect()
    try:
        base = get_version(conn, args.base)
        if args.file:
            segments = parse_draft(args.file)
        else:
            # 不带 --file 时基于旧版本原样复制，用于演练纯登记流程
            segments = {k: base[k] for k in SECTION_ORDER}
        v_no, _ = insert_version(conn, args.name, segments)
        insert_change(conn, v_no, args.author, args.reason)
        set_meta(conn, "current_version", v_no)
        conn.commit()
        print(f"基于 v{args.base} 创建 v{v_no}（{args.name}），当前版本指针 -> v{v_no}")
    finally:
        conn.close()


def cmd_list(_args):
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT v.version_no, v.name, v.created_at, v.sha256,"
            " c.author, c.reason, c.eval_conclusion"
            " FROM versions v LEFT JOIN changes c ON c.version_no = v.version_no"
            " ORDER BY v.version_no"
        ).fetchall()
        if not rows:
            print("版本库为空")
            return
        print(f"{'版本':<6}{'名称':<14}{'创建时间':<22}{'评测结论':<10}改动人与原因")
        for r in rows:
            print(f"v{r['version_no']:<5}{r['name']:<14}{r['created_at']:<22}"
                  f"{r['eval_conclusion']:<10}{r['author']}: {r['reason']}")
    finally:
        conn.close()


def cmd_show(args):
    conn = connect()
    try:
        row = get_version(conn, args.version)
        change = conn.execute(
            "SELECT * FROM changes WHERE version_no=?", (args.version,)
        ).fetchone()
        print(f"=== v{row['version_no']} {row['name']} ===")
        print(f"创建时间: {row['created_at']}")
        print(f"sha256: {row['sha256'][:16]}...")
        if change:
            print(f"改动人: {change['author']} | 原因: {change['reason']}"
                  f" | 评测结论: {change['eval_conclusion']}")
        print("--- 提示词全文 ---")
        print(row["full_text"])
    finally:
        conn.close()


def cmd_deploy(args):
    """发布：把指定版本的全文写入线上文件，并把指针指向该版本。"""
    conn = connect()
    try:
        row = get_version(conn, args.version)
        online_dir = BASE_DIR / "online"
        online_dir.mkdir(exist_ok=True)          # 目录不存在则创建（已存在不报错）
        online_file = online_dir / "current_prompt.txt"
        online_file.write_text(row["full_text"], encoding="utf-8")
        set_meta(conn, "current_version", args.version)
        conn.commit()
        print(f"已发布 v{args.version} 到线上文件 {online_file}")
        print(f"指针已指向 v{args.version}（指纹 {row['sha256'][:16]}...）")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="提示词版本库 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="初始化版本库（幂等）").set_defaults(func=cmd_init)

    p_new = sub.add_parser("new", help="从草稿文件创建新版本")
    p_new.add_argument("--file", required=True, help="草稿文件路径（含四段骨架）")
    p_new.add_argument("--name", required=True, help="版本名称")
    p_new.add_argument("--author", required=True, help="改动人")
    p_new.add_argument("--reason", required=True, help="改动原因")
    p_new.set_defaults(func=cmd_new)

    p_add = sub.add_parser("add", help="基于指定旧版本创建新版本")
    p_add.add_argument("--base", type=int, required=True, help="基准版本号")
    p_add.add_argument("--file", default=None, help="新草稿路径，缺省时原样复制基准版")
    p_add.add_argument("--name", required=True, help="版本名称")
    p_add.add_argument("--author", required=True, help="改动人")
    p_add.add_argument("--reason", required=True, help="改动原因")
    p_add.set_defaults(func=cmd_add)

    sub.add_parser("list", help="查看版本历史").set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="查看指定版本详情")
    p_show.add_argument("version", type=int, help="版本号")
    p_show.set_defaults(func=cmd_show)

    p_deploy = sub.add_parser("deploy", help="发布指定版本到线上文件")
    p_deploy.add_argument("version", type=int, help="要发布的版本号")
    p_deploy.set_defaults(func=cmd_deploy)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()



















