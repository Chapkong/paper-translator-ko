#!/usr/bin/env python3
"""output/<stem>/<stem>.html을 PDF로 굽는다.

브라우저 헤드리스 인쇄를 쓴다. `to_html.py`가 만든 HTML이 이미 A4 인쇄 CSS를 갖고 있어
화면에 보이는 그대로 나오고, 글자는 이미지가 아니라 선택·검색되는 텍스트로 남는다.
그림은 base64로 내장돼 있으므로 외부 파일 참조 없이 그대로 실린다.

파이썬 PDF 라이브러리를 쓰지 않는 이유: WeasyPrint는 윈도우에서 GTK 의존성이 필요하고,
Playwright는 크로미움 150MB를 따로 받아야 한다. 윈도우에는 Edge가 기본 설치돼 있어
추가 설치 없이 같은 결과를 얻을 수 있다.

사용법: python scripts/to_pdf.py output/<stem>
"""
import shutil
import subprocess
import sys
from pathlib import Path

# 윈도우 기본 설치 경로. PATH에 없을 때 여기서 찾는다.
INSTALL_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
TIMEOUT = 300


def find_browser():
    """PDF를 구울 브라우저 경로. 없으면 None."""
    for name in ("msedge", "chrome", "chromium", "google-chrome", "brave"):
        found = shutil.which(name)
        if found:
            return found
    for path in INSTALL_PATHS:
        if Path(path).exists():
            return path
    return None


def html_to_pdf(html: Path, pdf: Path, timeout: int = TIMEOUT) -> bool:
    """HTML을 PDF로 굽는다. 성공하면 True.

    예외를 던지지 않는다 — 브라우저가 없는 환경에서도 파이프라인이 죽으면 안 된다.
    """
    html, pdf = Path(html), Path(pdf)
    browser = find_browser()
    if not browser or not html.exists():
        return False

    pdf.parent.mkdir(parents=True, exist_ok=True)
    # 브라우저는 상대 경로를 자기 작업 디렉터리 기준으로 해석해 엉뚱한 곳에 쓴다
    pdf = pdf.resolve()
    # 구버전은 `--headless=new`를 모른다. 실패하면 옛 플래그로 한 번 더 시도한다.
    for headless in ("--headless=new", "--headless"):
        cmd = [browser, headless, "--disable-gpu", "--no-pdf-header-footer",
               f"--print-to-pdf={pdf}", html.resolve().as_uri()]
        try:
            subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"PDF 생성 실패: {e}", file=sys.stderr)
            return False
        if pdf.exists() and pdf.stat().st_size > 0:
            return True
    return False


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/to_pdf.py output/<stem>")
    outdir = Path(sys.argv[1])
    html = outdir / f"{outdir.name}.html"
    pdf = outdir / f"{outdir.name}.pdf"
    if not html.exists():
        sys.exit(f"HTML이 없다: {html}")
    if not html_to_pdf(html, pdf):
        sys.exit("PDF를 만들지 못했다 — Edge 또는 Chrome이 필요하다. "
                 "브라우저에서 HTML을 열어 Ctrl+P → 'PDF로 저장'으로도 받을 수 있다.")
    print(f"→ {pdf}  ({pdf.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
