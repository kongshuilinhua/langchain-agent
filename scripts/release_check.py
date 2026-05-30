import argparse
import os
import subprocess
import sys
from pathlib import Path


PYTHON_TARGETS = [
    "api",
    "core",
    "scripts",
    "tests",
]


def run_step(name: str, command: list[str], *, cwd: Path | None = None, env: dict | None = None) -> int:
    location = cwd or Path.cwd()
    print(f"\n==> {name}")
    print(f"cwd: {location}")
    print(f"cmd: {' '.join(command)}")
    completed = subprocess.run(command, cwd=location, env=env)
    if completed.returncode:
        print(f"\n{name} failed with exit code {completed.returncode}.")
    return completed.returncode


def has_command(command: str) -> bool:
    check = "where" if os.name == "nt" else "which"
    return subprocess.run(
        [check, command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run Lingshu Agent release checks.")
    parser.add_argument("--with-frontend", action="store_true", help="run frontend npm build")
    parser.add_argument("--with-rag-eval", action="store_true", help="deprecated; kept for CLI compatibility")
    parser.add_argument("--skip-pytest", action="store_true", help="skip pytest for faster local iteration")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    python = sys.executable
    steps: list[tuple[str, list[str], Path | None]] = []

    if not args.skip_pytest:
        if os.getenv("TEST_DATABASE_URL"):
            steps.append(("pytest", [python, "-m", "pytest"], root))
        else:
            print("Skipping pytest: set TEST_DATABASE_URL to an isolated PostgreSQL database. The test fixture resets the public schema.")
    steps.extend(
        [
            ("compileall", [python, "-m", "compileall", *PYTHON_TARGETS], root),
            ("markdown links", [python, "scripts/check_markdown_links.py"], root),
            ("text encoding", [python, "scripts/check_text_encoding.py"], root),
        ]
    )

    if args.with_rag_eval:
        print("--with-rag-eval is deprecated in v2. Workflow/chat tests cover the current platform path.")

    if args.with_frontend:
        npm = npm_command()
        if not has_command(npm):
            print("npm is required for --with-frontend.")
            return 1
        steps.append(("frontend build", [npm, "run", "build"], root / "frontend"))

    for name, command, cwd in steps:
        returncode = run_step(name, command, cwd=cwd)
        if returncode:
            return returncode

    print("\nRelease checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

