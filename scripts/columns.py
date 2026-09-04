#!/usr/bin/env python3
"""PyMuPDF 줄 좌표로 2단 조판의 읽기 순서를 직접 복원한다.

KorDocAI는 순수한 2단 페이지에서는 정확하지만, 전면 폭 제목·초록과 2단이 섞인
페이지(논문 첫 본문 쪽)에서 좌우 단을 한 줄에 합쳐 내놓는다. 그런 문서를 위해
같은 모양의 출력(PDF 한 줄 = 한 단위, 빈 줄로 구분)을 내는 대체 경로를 둔다.

줄 순서는 post.ordered_lines를 그대로 쓴다 — 정답지와 본문이 어긋나면
문단 판정이 위치를 잃는다. 어느 경로를 쓸지는 quality 게이트가 점수로 결정한다.
"""
import post

SEP = "\n\n"


def raw_markdown(doc) -> str:
    """KorDocAI와 같은 모양의 마크다운을 만든다 — 한 줄이 한 단위, 빈 줄로 구분."""
    lines, _body_size = post.ordered_lines(doc)
    return SEP.join(l["text"] for _pno, l, _edge, _right, _height in lines if l["text"])
