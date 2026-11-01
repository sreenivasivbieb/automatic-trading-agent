"""Generate a source-linked public backend reference without importing services or reading secrets."""

import argparse
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs/SOURCE_REFERENCE.md"
METHODS = {"get", "post", "put", "patch", "delete"}


def link(path, line):
    return f"../{path.relative_to(ROOT).as_posix()}#L{line}"


def symbols(nodes, path, prefix=""):
    result = []
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            name = prefix + node.name
            result.append(f"- [{name}]({link(path, node.lineno)}) — class")
            result.extend(symbols(node.body, path, name + "."))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signature = f"{node.name}({ast.unparse(node.args)})"
            if len(signature) > 170:
                signature = signature[:167] + "..."
            signature = signature.replace("`", "'")
            kind = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
            result.append(
                f"- [{prefix + node.name}]({link(path, node.lineno)}) — `{kind}{signature}`"
            )
            result.extend(symbols(node.body, path, prefix + node.name + "."))
    return result


def generate():
    paths = sorted((ROOT / "backend").glob("*.py"))
    trees = {p: ast.parse(p.read_text()) for p in paths}
    lines = [
        "# Generated backend source reference",
        "",
        "Generated from the active source. Regenerate with `.venv/bin/python -m scripts.generate_code_reference`; verify with `--check`.",
        "",
        "This tool reads source only. It does not load environment files, databases, AWS credentials, models or providers. [Development](DEVELOPMENT.md) explains the module layout; this index supplies exact code locations.",
        "",
        "## Local HTTP routes",
        "",
        "Use the local session/CSRF client or configured bearer authentication. Health/readiness/session/schema routes have their documented local exceptions. `/api/*` is separate from cloud `/platform/*`.",
        "",
    ]
    path = ROOT / "backend/api.py"
    for node in ast.walk(trees[path]):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr not in METHODS or not decorator.args:
                continue
            route = decorator.args[0]
            if isinstance(route, ast.Constant) and isinstance(route.value, str):
                lines.append(
                    f"- `{decorator.func.attr.upper()} {route.value}` → [{node.name}]({link(path, node.lineno)})"
                )
    lines += [
        "",
        "## Cloud HTTP routes",
        "",
        "Cognito access-token identity and tenant-aware repositories protect application resources. Authentication endpoints establish or clear sessions; `/platform/health` is public and does not attest AWS account availability.",
        "",
    ]
    pattern = re.compile(r"app\.(get|post|put|patch|delete)\(\s*[\"']([^\"']+)")
    for path in [ROOT / "backend/src/server.ts", ROOT / "backend/src/auth/cognito.ts"]:
        source = path.read_text()
        for match in pattern.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            lines.append(
                f"- `{match[1].upper()} {match[2]}` → [{path.name}:{line}]({link(path, line)})"
            )
    lines += ["", "## Python classes and functions", ""]
    for path, tree in trees.items():
        entries = symbols(tree.body, path)
        if entries:
            lines += [f"### {path.relative_to(ROOT).as_posix()}", "", *entries, ""]
    lines += ["## TypeScript exported entry points and contracts", ""]
    exported = re.compile(r"export\s+(?:async\s+)?(?:class|function|interface|type)\s+(\w+)")
    for path in sorted((ROOT / "backend/src").rglob("*.ts")):
        source = path.read_text()
        entries = []
        for match in exported.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            entries.append(f"- [{match[1]}]({link(path, line)})")
        if entries:
            lines += [f"### {path.relative_to(ROOT).as_posix()}", "", *entries, ""]
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = generate()
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != content:
            raise SystemExit("Source reference is stale; run scripts.generate_code_reference")
        print("Source reference matches current backend code")
    else:
        TARGET.write_text(content)
        print("Generated docs/SOURCE_REFERENCE.md")


if __name__ == "__main__":
    main()
