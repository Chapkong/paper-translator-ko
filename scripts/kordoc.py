#!/usr/bin/env python3
"""KorDocAI CLI 어댑터.

레이아웃 재구성(2단 읽기 순서, 머리글·바닥글 제거)을 CLI에 맡긴다.
실측: Peteraf 논문 보존율 0.972 (pymupdf4llm 0.686), JSTOR 푸터 14회 → 0회.

MCP가 아니라 CLI로 부른다. MCP 결과는 대화 컨텍스트를 통과해 논문 1편당
2만 토큰 이상을 쓰지만, CLI는 토큰이 들지 않고 재현 가능하다.
"""
import shutil, subprocess, sys, tempfile
from pathlib import Path

NPX = shutil.which("npx.cmd") or shutil.which("npx")


def available() -> bool:
    return NPX is not None


def to_markdown(src, timeout: int = 600, tables: bool = False):
    """PDF를 마크다운 문자열로 돌려준다. 실패하면 None.

    기본값은 표 감지를 끈다(`--no-tables`). 켜두면 2단 조판의 테두리를 표로
    오인해 좌우 단이 한 줄에 섞인다. 실제로 표가 있는 문서에서만 tables=True를 쓴다.

    예외를 던지지 않는다. 폴백 여부는 호출부가 결정한다.
    """
    src = Path(src)
    if not available() or not src.exists():
        return None
    # kordoc이 출력 옆에 images/를 함께 쓰는데, 윈도우에서 그 파일이 잠겨
    # 임시 폴더 정리가 실패할 수 있다. 정리 실패로 추출을 망치지 않는다.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        out = Path(td) / "out.md"
        cmd = [NPX, "-y", "kordoc", str(src), "--silent", "-o", str(out)]
        if not tables:
            cmd.insert(4, "--no-tables")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"kordoc 실행 실패: {e}", file=sys.stderr)
            return None
        if r.returncode != 0 or not out.exists():
            print(f"kordoc 실패(코드 {r.returncode}): {(r.stderr or '')[:300]}", file=sys.stderr)
            return None
        return out.read_text(encoding="utf-8")
