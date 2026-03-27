from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".env",
    ".venv",
    ".pytest_cache",
    ".dist",
    "noworrycv.egg-info",
    "__pycache__",
    ".git",
}
TEXT_EXTENSIONS = {
    ".md",
    ".py",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".txt",
    ".css",
    ".js",
    ".html",
}
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"(QWEN_API_KEY|DASHSCOPE_API_KEY|LLM_API_KEY)\s*=\s*(?!your_|<|example|changeme)[^\s#]+"),
]


def should_scan(path: Path) -> bool:
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    if path.name.startswith(".env") and path.name != ".env.example":
        return False
    if path.name == ".gitignore":
        return True
    return path.is_file() and (path.suffix in TEXT_EXTENSIONS or path.name == ".env.example")


def main() -> int:
    findings = []
    for path in ROOT.rglob("*"):
        if not should_scan(path):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SECRET_PATTERNS:
            for match in pattern.finditer(content):
                findings.append((path.relative_to(ROOT), match.group(0)))

    if findings:
        print("Potential public secrets found:")
        for path, match in findings:
            print("- {0}: {1}".format(path, match[:80]))
        return 1

    print("No obvious public secrets found in repo files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
