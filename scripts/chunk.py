#!/usr/bin/env python3
"""Step 2 — Split source.md into translation chunks that a subagent can handle.

Rules
  * split at headings (#, ##, ###); merge tiny sections; hard-split very long ones at paragraph boundaries
  * image lines  ![](images/...)  are kept verbatim inside the chunk (translator must copy them unchanged)
  * chunk target ~ MAX_CHARS (default 6000 chars ≈ 1500 tokens of English)

Usage: python scripts/chunk.py work/<stem>  [--max 6000]
Writes work/<stem>/chunks/NNN.md and chunks/index.json
"""
import argparse, json, re, shutil
from pathlib import Path

HEAD = re.compile(r"^(#{1,3})\s+\S")


def split_sections(md: str):
    sections, cur = [], []
    for line in md.splitlines(keepends=True):
        if HEAD.match(line) and cur:
            sections.append("".join(cur)); cur = []
        cur.append(line)
    if cur:
        sections.append("".join(cur))
    return sections


def hard_split(text: str, max_chars: int):
    paras, out, cur = text.split("\n\n"), [], ""
    for p in paras:
        if cur and len(cur) + len(p) + 2 > max_chars:
            out.append(cur); cur = p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur:
        out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--max", type=int, default=6000)
    a = ap.parse_args()
    wd = Path(a.workdir)
    md = (wd / "source.md").read_text(encoding="utf-8")

    chunks, buf = [], ""
    for sec in split_sections(md):
        if len(sec) > a.max:
            if buf:
                chunks.append(buf); buf = ""
            chunks.extend(hard_split(sec, a.max))
        elif len(buf) + len(sec) > a.max:
            chunks.append(buf); buf = sec
        else:
            buf += sec
    if buf:
        chunks.append(buf)

    cdir = wd / "chunks"
    if cdir.exists():
        shutil.rmtree(cdir)
    cdir.mkdir()
    (wd / "translated").mkdir(exist_ok=True)
    index = []
    for i, c in enumerate(chunks, 1):
        name = f"{i:03d}.md"
        (cdir / name).write_text(c, encoding="utf-8")
        index.append({"id": name, "chars": len(c),
                      "images": re.findall(r"!\[[^\]]*\]\(([^)]+)\)", c),
                      "heading": next((l.strip() for l in c.splitlines() if HEAD.match(l)), "")})
    (cdir / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    print(f"{len(chunks)} chunks → {cdir}")
    for e in index:
        print(f"  {e['id']}  {e['chars']:>6} chars  imgs={len(e['images'])}  {e['heading'][:60]}")


if __name__ == "__main__":
    main()
