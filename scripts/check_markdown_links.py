import re
import sys
from pathlib import Path
from urllib.parse import unquote


DEFAULT_PATHS = [
    "README.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "docs",
]


LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def iter_markdown_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
        elif path.exists():
            files.append(path)
    return files


def is_external(target: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target))


def normalize_target(raw_target: str) -> str:
    target = raw_target.strip().split("#", 1)[0]
    return unquote(target)


def main(argv: list[str]) -> int:
    paths = argv or DEFAULT_PATHS
    failures: list[tuple[Path, str]] = []

    for markdown_file in iter_markdown_files(paths):
        text = markdown_file.read_text(encoding="utf-8")
        for match in LINK_PATTERN.finditer(text):
            target = normalize_target(match.group(1))
            if not target or is_external(target):
                continue
            if not (markdown_file.parent / target).resolve().exists():
                failures.append((markdown_file, match.group(1)))

    if failures:
        print("Broken local Markdown links:")
        for source, target in failures:
            print(f"- {source}: {target}")
        return 1

    print(f"Checked {len(iter_markdown_files(paths))} Markdown files; all local links resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
