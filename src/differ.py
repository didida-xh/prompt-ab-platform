"""版本 diff:对比两个版本提示词的差异。"""
import argparse
import difflib

from src.prompt_store import connect, get_version, SECTION_ORDER, SECTION_HEADERS

def cmd_diff(args):
    conn=connect()
    try:
        a=get_version(conn,args.v1)["full_text"].splitlines()
        b=get_version(conn,args.v2)["full_text"].splitlines()
    finally:
        conn.close()

    for line in difflib.unified_diff(a, b,
                                     fromfile=f"v{args.v1}",
                                     tofile=f"v{args.v2}",
                                     lineterm=""):
        print(line)

        # 指出改动落在哪段
    seg_a = split_sections("\n".join(a))
    seg_b = split_sections("\n".join(b))
    for key in SECTION_ORDER:
        if seg_a[key] != seg_b[key]:
            print(f"[改动] {SECTION_HEADERS[key]}")


def split_sections(full_text):
    """把拼装全文切回四段字典。"""
    lines = full_text.splitlines()                 
    positions = {}                                
    for key in SECTION_ORDER:
        for i, line in enumerate(lines):
            if line.strip() == SECTION_HEADERS[key]:
                positions[key] = i
                break

    segments = {}                                 
    for idx, key in enumerate(SECTION_ORDER):
        start = positions[key] + 1
        end = positions[SECTION_ORDER[idx + 1]] if idx + 1 < len(SECTION_ORDER) else len(lines)
        content = "\n".join(lines[start:end]).strip()
        segments[key] = content
    return segments


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="版本 diff 工具")
    parser.add_argument("v1", type=int, help="旧版本号")
    parser.add_argument("v2", type=int, help="新版本号")
    args = parser.parse_args()
    cmd_diff(args)              # 把整包 args 交给处理函数