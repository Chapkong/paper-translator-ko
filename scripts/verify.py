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


CITE = re.compile(r"\(([A-Z][A-Za-z&.\- ]+?),\s*(\d{4}[a-z]?)\)")
# \b를 쓰면 '1993년', '3.14였다'처럼 한글이 바로 붙은 숫자를 놓친다.
# 한글은 \w에 포함되어 경계가 생기지 않기 때문이다. 숫자·소수점 인접만 배제한다.
YEAR_OR_DECIMAL = re.compile(r"(?<![\d.])\d{4}(?![\d.])|(?<![\d.])\d+\.\d+(?![\d.])")
INTEGER = re.compile(r"(?<![\d.])\d+(?![\d.])")


def check_images(src: str, tr: str, wd) -> list:
    """링크 문자열이 아니라 파일이 실제로 있는지 본다.

    문자열만 확인하던 구멍이 지난 실행에서 이미지 유실을 통과시켰다.
    """
    probs = []
    for img in IMG.findall(src):
        if img not in tr:
            probs.append(f"missing image link {img}")
        elif not (Path(wd) / img).exists():
            probs.append(f"image file not found: {img}")
    return probs


def check_numbers(src: str, tr: str):
    """연도·소수는 FAIL, 그 밖의 정수는 WARN.

    'four conditions → 네 가지 조건'처럼 정수가 정상적으로 한글 수사가 되는 경우가 있어
    정수 누락을 FAIL로 잡으면 오탐이 쏟아진다.
    """
    fail = [f"missing number {n}" for n in
            sorted(set(YEAR_OR_DECIMAL.findall(src)) - set(YEAR_OR_DECIMAL.findall(tr)))]
    src_i = set(INTEGER.findall(src)) - set(YEAR_OR_DECIMAL.findall(src))
    warn = [f"number not found (확인 필요): {n}" for n in sorted(src_i - set(INTEGER.findall(tr)))]
    return fail, warn


def check_citations(src: str, tr: str) -> list:
    missing = set(CITE.findall(src)) - set(CITE.findall(tr))
    return [f"missing citation ({a}, {y})" for a, y in sorted(missing)]


def check_paragraphs(src: str, tr: str) -> list:
    ns = len([p for p in src.split("\n\n") if p.strip()])
    nt = len([p for p in tr.split("\n\n") if p.strip()])
    return [f"paragraph count {ns}→{nt}"] if ns != nt else []


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
        probs = check_images(src, tr, wd)
        nfail, nwarn = check_numbers(src, tr)
        probs += nfail + check_citations(src, tr) + check_paragraphs(src, tr)
        for w in nwarn:
            print(f"WARN {e['id']}  {w}")
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
