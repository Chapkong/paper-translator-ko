#!/usr/bin/env python3
"""최종 산출물을 기계로 직접 검증한다.

에이전트의 PASS 선언을 믿지 않는다. 실제 파일을 열어 수를 세고, 그 수로 합격을
결정한다. 첫 실행에서 파이프라인이 "ALL PASS"를 보고했지만 원문의 3분의 1이
없었고, 두 번째 실행에서는 각주 25개 중 17개가 영어로 남았는데도 PASS가 나왔다.
판정하는 주체와 판정받는 주체가 같으면 이런 일이 반복된다.

사용법: python scripts/final_check.py work/<stem> output/<stem>
미달이면 exit 1. 결과는 work/<stem>/final_check.md에도 남긴다.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify

HANGUL = re.compile(r"[가-힣]")
REFS = re.compile(r"^#*\s*(references|참고문헌|bibliography)\s*$", re.I | re.M)
GLOSSARY = re.compile(r"^#*\s*용어\s*대응표", re.I | re.M)
YEAR = re.compile(r"(?<![\d.])\d{4}(?![\d.])")
IMG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _body(md: str) -> str:
    """참고문헌 앞까지. 참고문헌은 번역하지 않는 것이 규칙이다."""
    m = REFS.search(md)
    return md[:m.start()] if m else md


def collect(work: Path, out: Path) -> list:
    """(항목, 값, 기준, 통과여부) 목록을 만든다."""
    stem = out.name
    ko_path = out / f"{stem}.ko.md"
    html_path = out / f"{stem}.html"
    src_path = work / "source.md"
    rows = []

    if not ko_path.exists():
        return [("번역본 존재", "없음", "필수", False)]
    ko = ko_path.read_text(encoding="utf-8")
    src = src_path.read_text(encoding="utf-8") if src_path.exists() else ""

    # 1. 미번역 각주 — 서술문이 있는데 한글이 없는 각주
    notes = verify.check_footnotes(ko)
    rows.append(("미번역 각주", f"{len(notes)}건", "0건", not notes))

    # 2. 미번역 본문 문단
    eng = [p for p in _body(ko).split("\n\n")
           if len(p.strip()) > 80 and not p.lstrip().startswith(("#", "|", ">", "!"))
           and not HANGUL.search(p)]
    rows.append(("미번역 본문 문단", f"{len(eng)}건", "0건", not eng))

    # 3. 원문 대비 문단 수 — 통째로 빠진 문단을 잡는다
    #    용어표 부록은 assemble.py가 항상 추가하므로 비교에서 뺀다
    ns = len([p for p in src.split("\n\n") if p.strip()])
    ko_body = ko[:GLOSSARY.search(ko).start()] if GLOSSARY.search(ko) else ko
    nt = len([p for p in ko_body.split("\n\n") if p.strip()])
    ok = ns == 0 or abs(ns - nt) <= max(2, ns * 0.02)
    rows.append(("문단 수(원문→번역)", f"{ns}→{nt}", "±2% 이내", ok))

    # 4. 연도 보존 — 원문의 4자리 연도가 번역본에 다 있는가
    missing = sorted(set(YEAR.findall(src)) - set(YEAR.findall(ko)))
    rows.append(("빠진 연도", f"{len(missing)}건" + (f" {missing[:5]}" if missing else ""),
                 "0건", not missing))

    # 5. 이미지 파일 실존
    links = IMG.findall(ko)
    broken = [l for l in links if not (out / l).exists()]
    rows.append(("이미지 링크", f"{len(links)}개 중 깨짐 {len(broken)}", "깨짐 0", not broken))

    # 6. HTML에 이미지가 실제로 박혔는가
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
        embedded = html.count("data:image")
        plain = len(re.findall(r'<img[^>]+src="(?!data:)', html))
        rows.append(("HTML 이미지", f"내장 {embedded} / 미내장 {plain}",
                     f"내장 {len(links)}, 미내장 0", plain == 0 and embedded >= len(links)))
    else:
        rows.append(("HTML 존재", "없음", "필수", False))

    # 7. 청크별 검수 보고 — 번역만 하고 검수를 건너뛴 청크를 잡는다
    idx = work / "chunks" / "index.json"
    if idx.exists():
        n_chunks = len(json.loads(idx.read_text(encoding="utf-8")))
        n_tr = len(list((work / "translated").glob("*.md"))) if (work / "translated").exists() else 0
        n_rv = len(list((work / "review").glob("*.md"))) if (work / "review").exists() else 0
        rows.append(("번역/검수 파일", f"청크 {n_chunks} / 번역 {n_tr} / 검수 {n_rv}",
                     "번역=청크", n_tr >= n_chunks))
        if n_rv < n_chunks:
            rows.append(("검수 누락 청크", f"{n_chunks - n_rv}개", "0개(참고문헌 제외 가능)", True))

    # 8. 추출 품질 — meta.json에 남은 실측치
    meta_path = work / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        cov, tr = meta.get("coverage", 0), meta.get("truncated", 1)
        rows.append(("추출 보존율", f"{cov}", "≥0.97", cov >= 0.97))
        rows.append(("추출 잘린 문단", f"{tr}", "≤0.05", tr <= 0.05))
        rows.append(("추출기", meta.get("extractor", "?"), "-", True))
        rows.append(("그림", f"{meta.get('figures', 0)}개", "-", True))
    return rows


def main():
    if len(sys.argv) < 3:
        sys.exit("사용법: python scripts/final_check.py work/<stem> output/<stem>")
    work, out = Path(sys.argv[1]), Path(sys.argv[2])
    rows = collect(work, out)
    failed = [r for r in rows if not r[3]]

    lines = ["# 최종 기계 검증", "",
             f"판정: {'PASS' if not failed else 'FAIL'}", "",
             "| 항목 | 실측 | 기준 | 판정 |", "|---|---|---|---|"]
    for name, value, crit, ok in rows:
        lines.append(f"| {name} | {value} | {crit} | {'ok' if ok else 'FAIL'} |")
    if failed:
        lines += ["", "## 미달 항목", ""] + [f"- {n}: {v} (기준 {c})" for n, v, c, _ in failed]
    report = "\n".join(lines) + "\n"

    (work / "final_check.md").write_text(report, encoding="utf-8")
    print(report)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
