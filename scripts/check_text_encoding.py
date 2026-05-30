import sys
from pathlib import Path


DEFAULT_PATHS = [
    "README.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "docs",
    "frontend/src",
    "api",
    "core",
    "tests",
    "scripts",
    ".github",
]

TEXT_SUFFIXES = {".md", ".py", ".jsx", ".css", ".json", ".jsonl", ".yml", ".yaml", ".toml", ".txt"}
BAD_MARKERS = ("?" * 4, "\ufffd")


def iter_text_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob("*") if item.suffix.lower() in TEXT_SUFFIXES))
        elif path.exists() and path.suffix.lower() in TEXT_SUFFIXES:
            files.append(path)
    return files


def main(argv: list[str]) -> int:
    paths = argv or DEFAULT_PATHS
    failures: list[tuple[Path, str]] = []

    files = iter_text_files(paths)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            failures.append((path, f"not valid UTF-8: {exc}"))
            continue
        for marker in BAD_MARKERS:
            if marker in text:
                failures.append((path, f"contains marker {marker!r}"))

    if failures:
        print("Text encoding check failed:")
        for source, reason in failures:
            print(f"- {source}: {reason}")
        return 1

    print(f"Checked {len(files)} text files; UTF-8 and marker checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
