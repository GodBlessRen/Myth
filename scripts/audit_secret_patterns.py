"""已知秘钥格式的本地审计，不打印匹配值。
扫描当前受 Git 管理/待提交文件及可达历史 blob；只有命中类型、路径、对象摘要进入结果，未命中不证明不存在其他秘钥。
"""

import hashlib
import json
from pathlib import Path
import re
import subprocess


# 只读 Git 元数据命令；参数是脚本固定列表，不能拼接 shell 或输出秘钥正文。
def git_bytes(*arguments):
    return subprocess.check_output(["git", *arguments], stderr=subprocess.DEVNULL)


# 返回模式标签而非匹配文本；构造摘要供定位，输出不能回显凭据。
def findings(data, path, identity, patterns):
    return [{"type": label, "path": path, "object": identity}
        for label, pattern in patterns.items() if pattern.search(data)]


# 同一历史 blob 只扫描一次；分块 cat-file 有界读取，不从系统凭据库取得任何真实账号。
def main():
    root = Path(__file__).resolve().parents[1]
    patterns = {
        "openai_key": re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}"),
        "jwt": re.compile(rb"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        "private_key": re.compile(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
        "aws_access_key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
        "github_token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})"),
    }
    matches = []
    working = git_bytes("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    for path in working:
        if path and (root / path).is_file():
            data = (root / path).read_bytes()
            matches.extend(findings(data, path, hashlib.sha256(data).hexdigest(), patterns))
    objects = git_bytes("rev-list", "--objects", "--all").decode().splitlines()
    count = 0
    total = 0
    with subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        for row in objects:
            oid, _, path = row.partition(" ")
            process.stdin.write((oid + "\n").encode())
            process.stdin.flush()
            header = process.stdout.readline().decode().split()
            if len(header) != 3:
                raise RuntimeError("Git object header is invalid")
            size = int(header[2])
            if size > 20 * 1024 * 1024:
                raise RuntimeError("Git object exceeds this audit's byte limit")
            data = process.stdout.read(size)
            process.stdout.read(1)
            if header[1] == "blob":
                count += 1
                total += size
                matches.extend(findings(data, path, oid, patterns))
        process.stdin.close()
        if process.wait():
            raise RuntimeError("Git object audit failed")
    print(json.dumps({"working_files": sum(bool(path) for path in working), "history_blobs": count,
        "history_bytes": total, "patterns": list(patterns), "findings": matches}, ensure_ascii=False))
    if matches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
