#!/usr/bin/env python3
"""의존성 없는 자체 테스트.

사용법:
    python scripts/selftest.py            # 전체 실행
    python scripts/selftest.py 이름 이름   # 지정한 테스트만 실행
"""
import sys, traceback
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

TESTS = {}


def test(fn):
    TESTS[fn.__name__] = fn
    return fn


FIXTURE = ROOT / "work" / "_fixture" / "fixture.pdf"

# 픽스처 본문 — 후처리 결과가 이 문장들과 정확히 일치해야 한다
P1_LEFT = ["INTRODUCTION",
           "The model is developed in this",
           "section. Firms rely on communi-",
           "cation among their units."]
P1_RIGHT = ["This right column follows the",
            "left one in reading order."]
P2_LEFT = ["Heterogeneity is the first",
           "condition of the model."]
P2_RIGHT = ["Rents are bound to the firm",
            "under imperfect mobility."]
P2_NOTE = ["1 See Nelson (1991) for a",
           "discussion of firm capabilities."]
P3_LEFT = ["The final section applies the",
           "model to strategy formulation."]
P3_RIGHT = ["Implications for research are",
            "discussed at the end."]


def _draw(page, x0, y0, lines, size):
    """줄바꿈 위치를 우리가 정하기 위해 한 줄씩 직접 찍는다."""
    for i, line in enumerate(lines):
        page.insert_text((x0, y0 + i * (size + 3)), line, fontsize=size, fontname="helv")


def build_fixture() -> Path:
    """2단 본문 + 각주 + 러닝헤드 + 반복 푸터 + 그림/로고가 든 3쪽 PDF를 만든다."""
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    body = [(P1_LEFT, P1_RIGHT), (P2_LEFT, P2_RIGHT), (P3_LEFT, P3_RIGHT)]
    for pno, (left, right) in enumerate(body):
        page = doc.new_page(width=530, height=800)
        _draw(page, 48, 45, [f"{180 + pno} A. Author"], 9.8)      # 러닝헤드
        _draw(page, 48, 80, left, 8.0)
        _draw(page, 285, 80, right, 8.0)
        if pno == 1:
            _draw(page, 285, 620, P2_NOTE, 6.5)                    # 각주
        _draw(page, 120, 750, ["This content downloaded on Tue, 01 Sep 2026"], 8.0)
    page = doc[2]                                                   # 그림 7% + 로고 0.4%
    fig = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 150))
    fig.set_rect(fig.irect, (30, 90, 200))
    page.insert_image(pymupdf.Rect(60, 300, 260, 450), pixmap=fig)
    logo = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40))
    logo.set_rect(logo.irect, (200, 30, 30))
    page.insert_image(pymupdf.Rect(300, 300, 340, 340), pixmap=logo)
    doc.save(FIXTURE)
    doc.close()
    return FIXTURE


@test
def fixture_builds():
    p = build_fixture()
    doc = pymupdf.open(p)
    assert doc.page_count == 3, doc.page_count
    text = doc[0].get_text()
    assert "INTRODUCTION" in text
    assert "communi-" in text, "하이픈 분철이 픽스처에 들어가야 한다"
    doc.close()


def main():
    names = sys.argv[1:] or list(TESTS)
    unknown = [n for n in names if n not in TESTS]
    if unknown:
        sys.exit(f"없는 테스트: {unknown}\n가능: {list(TESTS)}")
    failed = []
    for n in names:
        try:
            TESTS[n]()
            print(f"ok   {n}")
        except Exception:
            failed.append(n)
            print(f"FAIL {n}")
            traceback.print_exc()
    print(f"\n{len(names) - len(failed)}/{len(names)} 통과")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
