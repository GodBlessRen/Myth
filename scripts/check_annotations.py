"""项目宪法的中文说明覆盖守卫。

只读取源码 AST/相邻注释，不导入生产模块、不访问 Runtime 状态。检查文件、类、
函数和生产属性的中文说明是否存在；专家级准确性仍须代码审阅，不能由字符检测证明。
"""

from __future__ import annotations

import ast
from pathlib import Path
import re

# 只检出中文字符，不能据此判定事实准确、术语正确或解释充分。
CHINESE = re.compile(r"[\u4e00-\u9fff]")


# 检查 docstring 或紧邻声明的中文注释；跨空行说明不算当前声明的合同。
def has_guidance(node: ast.AST, lines: list[str]) -> bool:
    if isinstance(
        node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    ):
        doc = ast.get_docstring(node)
        if doc and CHINESE.search(doc):
            return True
    decorators = getattr(node, "decorator_list", [])
    start = min([node.lineno] + [item.lineno for item in decorators]) - 2
    while start >= 0 and lines[start].lstrip().startswith("#"):
        if CHINESE.search(lines[start]):
            return True
        start -= 1
    return False


# 返回一份文件的未覆盖声明；属性只检查生产类声明及构造时的持有字段，局部变量不是类属性。
def inspect_python(path: Path, *, properties: bool) -> tuple[list[str], dict[str, int]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    errors = []
    counts = {"files": 1, "classes": 0, "functions": 0, "properties": 0}
    if not ast.get_docstring(tree) or not CHINESE.search(ast.get_docstring(tree)):
        errors.append(f"{path}:1 缺少中文文件职责说明")
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            category = "classes" if isinstance(node, ast.ClassDef) else "functions"
            counts[category] += 1
            if not has_guidance(node, lines):
                errors.append(f"{path}:{node.lineno} {node.name} 缺少中文指导说明")
        if properties and isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.Assign, ast.AnnAssign)):
                    counts["properties"] += 1
                    if not has_guidance(member, lines):
                        errors.append(f"{path}:{member.lineno} 类属性缺少中文说明")
                if isinstance(member, ast.FunctionDef) and member.name == "__init__":
                    seen = set()
                    for statement in ast.walk(member):
                        targets = (
                            statement.targets
                            if isinstance(statement, ast.Assign)
                            else (
                                [statement.target]
                                if isinstance(statement, ast.AnnAssign)
                                else []
                            )
                        )
                        for target in targets:
                            for attribute in ast.walk(target):
                                if (
                                    isinstance(attribute, ast.Attribute)
                                    and isinstance(attribute.value, ast.Name)
                                    and attribute.value.id == "self"
                                    and attribute.attr not in seen
                                ):
                                    seen.add(attribute.attr)
                                    counts["properties"] += 1
                                    if not has_guidance(statement, lines):
                                        errors.append(
                                            f"{path}:{statement.lineno} self.{attribute.attr} 缺少中文说明"
                                        )
    return errors, counts


# 扫描生产源码、当前测试和维护脚本；历史工具有独立归档说明，不作为当前维护入口。
def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = []
    counts = {"files": 0, "classes": 0, "functions": 0, "properties": 0}
    for folder, properties in (
        (root / "src/myth", True),
        (root / "tests", False),
        (root / "scripts", False),
    ):
        for path in sorted(folder.rglob("*.py")):
            findings, covered = inspect_python(path, properties=properties)
            errors.extend(findings)
            for key in counts:
                counts[key] += covered[key]
    web = root / "src/myth/webui"
    for path in sorted(web.glob("*.js")):
        lines = path.read_text(encoding="utf-8").splitlines()
        if not CHINESE.search("\n".join(lines[:5])):
            errors.append(f"{path}:1 缺少中文文件说明")
        for index, line in enumerate(lines):
            if re.match(r"(?:async )?function \w+\(", line) and (
                index == 0
                or not lines[index - 1].startswith("//")
                or not CHINESE.search(lines[index - 1])
            ):
                errors.append(f"{path}:{index + 1} 命名函数缺少中文说明")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"中文说明覆盖检查通过：{counts}；内容准确性仍由审阅负责。")
    return 0


# 开发命令返回明确退出码，CI 才能阻止无说明的新声明进入主分支。
if __name__ == "__main__":
    raise SystemExit(main())
