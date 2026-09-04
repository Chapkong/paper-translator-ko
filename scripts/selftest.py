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

# 픽스처 본문 — 후처리 결과가 이 문장들과 정확히 일치해야 한다.
# 실제 논문처럼 문단 첫 줄을 들여써서 PyMuPDF 블록이 문단 단위로 갈리게 한다.
P1_HEAD = ["INTRODUCTION"]
P1_PARA1 = ["The model is developed in this",
            "section. Firms rely on communi-",
            "cation among their units."]
P1_PARA2 = ["A second paragraph starts here",
            "and ends on this line."]
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


def _draw(page, x0, y0, lines, size, indent=0):
    """줄바꿈 위치를 우리가 정하기 위해 한 줄씩 직접 찍는다.

    indent를 주면 첫 줄만 들여쓴다 — 실제 논문의 문단 첫 줄과 같고,
    PyMuPDF가 이 지점에서 블록을 나눈다.
    """
    for i, line in enumerate(lines):
        x = x0 + (indent if i == 0 else 0)
        page.insert_text((x, y0 + i * (size + 3)), line, fontsize=size, fontname="helv")


def build_fixture() -> Path:
    """2단 본문 + 각주 + 러닝헤드 + 반복 푸터 + 그림/로고가 든 3쪽 PDF를 만든다."""
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    body = [(None, P1_RIGHT), (P2_LEFT, P2_RIGHT), (P3_LEFT, P3_RIGHT)]
    for pno, (left, right) in enumerate(body):
        page = doc.new_page(width=530, height=800)
        _draw(page, 48, 45, [f"{180 + pno} A. Author"], 9.8)      # 러닝헤드
        if pno == 0:                                               # 제목 + 문단 2개
            _draw(page, 48, 80, P1_HEAD, 9.5)
            _draw(page, 48, 105, P1_PARA1, 8.0, indent=8)
            _draw(page, 48, 145, P1_PARA2, 8.0, indent=8)
        else:
            _draw(page, 48, 80, left, 8.0, indent=8)
        _draw(page, 285, 80, right, 8.0, indent=8)
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


@test
def kordoc_adapter_degrades_gracefully():
    import kordoc
    assert kordoc.to_markdown(ROOT / "input" / "없는파일.pdf") is None, \
        "실패 시 예외가 아니라 None이어야 폴백할 수 있다"
    if kordoc.available():          # CLI가 있는 환경에서만 본 검증
        md = kordoc.to_markdown(build_fixture())
        assert md and "INTRODUCTION" in md, (md or "")[:200]
    else:
        print("     (kordoc CLI 없음 — 폴백 경로만 검증)")


@test
def oracle_knows_paragraph_starts_and_sizes():
    from post import build_oracle, key
    doc = pymupdf.open(build_fixture())
    o = build_oracle(doc)
    assert key("The model is developed in this") in o.starts, "블록 첫 줄은 문단 시작이다"
    assert key("section. Firms rely on communi-") not in o.starts, "이어지는 줄은 문단 시작이 아니다"
    assert 7.5 < o.body_size < 8.5, o.body_size
    assert o.sizes[key("1 See Nelson (1991) for a")] < o.body_size * 0.85, "각주는 작은 폰트다"
    assert o.page_last[2], "페이지별 마지막 줄이 있어야 이미지를 그 자리에 넣는다"
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
