"""项目宪法的中文说明覆盖守卫。

只读取源码 AST/相邻注释，不导入生产模块、不访问 Runtime 状态。检查文件、类、
函数和生产属性的中文说明是否存在，检查参数说明是否失效、复杂流程是否缺少步骤说明。
专家级准确性仍须代码审阅，不能由字符检测证明。
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
import sys

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


# 函数自己的控制流才计入复杂度，嵌套函数另行检查，避免外层被替身/回调误判。
def own_nodes(node: ast.AST):
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield from own_nodes(child)


# 参数名可机械核对；复杂流程至少解释一个实际步骤，但不能据此宣称解释正确。
def inspect_quality(node: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]) -> list[str]:
    errors = []
    doc = ast.get_docstring(node) or ""
    arguments = {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
    arguments.update(arg.arg for arg in (node.args.vararg, node.args.kwarg) if arg)
    for documented in re.findall(r":param\s+([A-Za-z_]\w*)\s*:", doc):
        if documented not in arguments:
            errors.append(f"{node.name} 注释引用不存在参数 {documented}")
    branches = sum(isinstance(item, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match)) for item in own_nodes(node))
    if branches >= 5 and node.end_lineno - node.lineno >= 35:
        # AST 第一条语句不包含其前方步骤注释；从函数声明后扫描，保留入口处说明。
        body = lines[node.lineno:node.end_lineno]
        has_steps = any(line.lstrip().startswith("#") and CHINESE.search(line) for line in body)
        if not has_steps and not re.search(r"(?:步骤|先.{2,}再|[123一二三][、.])", doc):
            errors.append(f"{node.name} 有 {branches} 个控制分支却无中文步骤说明")
    return errors


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
            if properties and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                errors.extend(f"{path}:{node.lineno} {finding}" for finding in inspect_quality(node, lines))
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
    # 英文 Windows runner 的重定向默认 cp1252；中文合同报告固定 UTF-8，不能因本机代码页误判失败。
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
