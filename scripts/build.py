"""Validate bot/ and package it as the competition submission zip.

    python scripts/build.py              # validate + write dist/submission.zip
    python scripts/build.py --check      # validate only

Checks (Rulebook 5.1-5.10, Protocol Spec 2):
  * bot/bot.py exists (it becomes bot.py at the top level of the zip)
  * every import is stdlib, numpy, scipy, or a module shipped inside bot/
  * no print() call writes to stdout (every print must pass file=...),
    except in bot.py's protocol replies, which are marked with  # protocol
  * zip size <= 5 MB
"""
import argparse
import ast
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOT_DIR = ROOT / "bot"
DIST = ROOT / "dist"
MAX_BYTES = 5 * 1024 * 1024
ALLOWED_THIRD_PARTY = {"numpy", "scipy"}
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def submission_files(bot_dir=BOT_DIR):
    for path in sorted(bot_dir.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(bot_dir)
        if EXCLUDE_DIRS & set(rel.parts) or path.suffix in EXCLUDE_SUFFIXES:
            continue
        yield path, rel


def local_modules(bot_dir=BOT_DIR):
    names = set()
    for path in bot_dir.iterdir():
        if path.suffix == ".py":
            names.add(path.stem)
        elif path.is_dir() and (path / "__init__.py").exists():
            names.add(path.name)
    return names


def check_source(path, rel, local):
    errors = []
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src, filename=str(rel))
    allowed = set(sys.stdlib_module_names) | ALLOWED_THIRD_PARTY | local
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [] if node.level else [node.module or ""]
        else:
            mods = []
        for mod in mods:
            top = mod.split(".")[0]
            if top not in allowed:
                errors.append(f"{rel}:{node.lineno}: disallowed import '{mod}'")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "print"
                and not any(k.arg == "file" for k in node.keywords)):
            line = lines[node.lineno - 1]
            if "# protocol" not in line:
                errors.append(f"{rel}:{node.lineno}: print() to stdout "
                              "(use file=sys.stderr, or mark protocol replies '# protocol')")
    return errors


def validate(bot_dir=BOT_DIR):
    errors = []
    if not (bot_dir / "bot.py").is_file():
        errors.append(f"{bot_dir}/bot.py is missing")
        return errors
    local = local_modules(bot_dir)
    for path, rel in submission_files(bot_dir):
        if path.suffix == ".py":
            try:
                errors += check_source(path, rel, local)
            except SyntaxError as e:
                errors.append(f"{rel}:{e.lineno}: syntax error: {e.msg}")
    return errors


def build(out, bot_dir=BOT_DIR):
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, rel in submission_files(bot_dir):
            zf.write(path, rel.as_posix())
    size = out.stat().st_size
    if size > MAX_BYTES:
        raise SystemExit(f"FAIL: {out} is {size / 1e6:.2f} MB (limit 5 MB)")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    shown = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
    print(f"OK: wrote {shown} ({size / 1024:.1f} KB, {len(names)} files)")
    for n in names:
        print(f"  {n}")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true", help="validate only, don't write the zip")
    p.add_argument("--out", type=Path, default=DIST / "submission.zip")
    p.add_argument("--src", type=Path, default=BOT_DIR, help="bot folder to package (default: bot/)")
    args = p.parse_args()
    src = args.src.resolve()

    errors = validate(src)
    if errors:
        print("FAIL: submission checks", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        raise SystemExit(1)
    print("OK: submission checks passed")
    if not args.check:
        build(args.out.resolve(), src)


if __name__ == "__main__":
    main()
