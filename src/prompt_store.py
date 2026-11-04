"""提示词版本库：SQLite 存储四段骨架提示词的版本历史与变更登记。

表结构：
- versions  版本正文（四段分存 + 拼装全文 + sha256 指纹）
- changes   变更登记（谁改的 / 为何改 / 评测结论）
- meta      键值元数据（current_version 指针）

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

def assemble(segments):
    """四段拼装为完整提示词全文，段间以空行分隔。"""
    parts=[]
    for key in SECTION_ORDER:
        parts.append(SECTION_HEADERS[key]+"\n"+segments[key].strip())
    return "\n\n".join(parts)





















