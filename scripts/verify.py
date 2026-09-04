#!/usr/bin/env python3
"""Step 5 — Mechanical QA of translated chunks (structure, not meaning).

Checks per chunk:
  * every ![](images/..) link in the source appears verbatim in the translation
  * heading count matches
  * table row count matches (lines starting with |)
  * Hangul ratio is high enough (catches untranslated chunks)
  * no leftover English paragraphs of >200 chars without Hangul (except code/refs)

Usage: python scripts/verify.py work/<stem>
Exit 1 if any FAIL.
"""
import json, re, sys
from pathlib import Path

IMG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HEAD = re.compile(r"^#{1,6}\s", re.M)
HANGUL = re.compile(r"[가-힣]")


def hangul_ratio(t: str) -> float:
    letters = re.findall(r"[A-Za-z가-힣]", t)
    return (len(HANGUL.findall(t)) / len(letters)) if letters else 1.0


def main():
    wd = Path(sys.argv[1])
    index = json.loads((wd / "chunks" / "index.json").read_text())
    fails = 0
    for e in index:
        src = (wd / "chunks" / e["id"]).read_text(encoding="utf-8")
        tp = wd / "translated" / e["id"]
        if not tp.exists():
            print(f"FAIL {e['id']}: no translation"); fails += 1; continue
        tr = tp.read_text(encoding="utf-8")
        probs = []
        for img in IMG.findall(src):
            if img not in tr:
                probs.append(f"missing image {img}")
        hs, ht = len(HEAD.findall(src)), len(HEAD.findall(tr))
        if hs != ht:
            probs.append(f"heading count {hs}→{ht}")
        ts = sum(1 for l in src.splitlines() if l.startswith("|"))
        tt = sum(1 for l in tr.splitlines() if l.startswith("|"))
        if ts != tt:
            probs.append(f"table rows {ts}→{tt}")
        is_refs = bool(re.search(r"^#+\s*(References|참고문헌)", src, re.M | re.I))
        r = hangul_ratio(tr)
        if not is_refs and r < 0.5:
            probs.append(f"hangul ratio {r:.2f} (untranslated?)")
        if not is_refs:
            for p in tr.split("\n\n"):
                if len(p) > 200 and not HANGUL.search(p) and not p.startswith(("|", "!", "$", "```")):
                    probs.append("english paragraph left: " + p[:60].replace("\n", " ") + "…")
        status = "FAIL" if probs else "ok  "
        fails += bool(probs)
        print(f"{status} {e['id']}  hangul={r:.2f}  " + ("; ".join(probs) if probs else ""))
    print("ALL PASS" if not fails else f"{fails} chunk(s) failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
