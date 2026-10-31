"""Check the files eligible for publication; print paths, never secret values."""

import json
import re
import subprocess
from pathlib import Path

BLOCKED_PARTS = {
    ".runtime",
    ".reference",
    ".cache",
    ".tools",
    ".venv",
    ".venv-legacy",
    ".python",
    "node_modules",
    "__pycache__",
}
PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{28,}\b"),
    re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
]


def main():
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    )
    names = sorted(set(name.decode() for name in output.split(b"\0") if name))
    issues = []
    checked = 0
    for name in names:
        path = Path(name)
        if not path.is_file():
            continue
        checked += 1
        if (
            BLOCKED_PARTS.intersection(path.parts)
            or path.parts[:2]
            in {("contracts", "broadcast"), ("contracts", "out"), ("contracts", "cache")}
            or path.name == ".env"
            or path.suffix in {".sqlite", ".sqlite3", ".db", ".key", ".pem"}
        ):
            issues.append(
                {
                    "path": name,
                    "reason": "Private runtime or credential file is eligible for publication",
                }
            )
        if path.is_symlink():
            issues.append({"path": name, "reason": "Symlink requires explicit review"})
        data = path.read_bytes()
        if len(data) > 20 * 1024 * 1024:
            issues.append({"path": name, "reason": "File exceeds the 20 MiB public-source limit"})
        if path.suffix.lower() not in {".png", ".jpg", ".gif", ".webp"}:
            for pattern in PATTERNS:
                if pattern.search(data):
                    issues.append(
                        {
                            "path": name,
                            "reason": "Potential credential pattern; value intentionally omitted",
                        }
                    )
                    break
    report = {
        "files_checked": checked,
        "issues": issues,
        "scope": "Git-tracked and unignored candidate files; bounded credential patterns and runtime-path policy. Not a complete security audit.",
    }
    print(json.dumps(report, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
