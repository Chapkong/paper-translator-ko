#!/usr/bin/env python3
"""Step 4 — Merge translated chunks into output/<stem>.ko.md and copy images.

Usage: python scripts/assemble.py work/<stem>  [--out output]
Fails loudly if any chunk is missing its translation.
"""
import argparse, json, shutil, sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--out", default="output")
    a = ap.parse_args()
    wd = Path(a.workdir)
    index = json.loads((wd / "chunks" / "index.json").read_text(encoding="utf-8"))
    missing = [e["id"] for e in index if not (wd / "translated" / e["id"]).exists()]
    if missing:
        sys.exit(f"missing translations: {missing}")

    body = "\n\n".join((wd / "translated" / e["id"]).read_text(encoding="utf-8").strip() for e in index)
    glossary = wd / "glossary.md"
    if glossary.exists():
        body += "\n\n---\n\n## 용어 대응표 (Glossary)\n\n" + glossary.read_text(encoding="utf-8").strip() + "\n"

    outdir = Path(a.out) / wd.name
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{wd.name}.ko.md").write_text(body + "\n", encoding="utf-8")
    if (wd / "images").exists():
        shutil.copytree(wd / "images", outdir / "images", dirs_exist_ok=True)
    print(f"→ {outdir / (wd.name + '.ko.md')}  ({len(body)} chars)")


if __name__ == "__main__":
    main()
