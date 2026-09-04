---
description: 영어 논문(PDF/DOCX)을 한국어로 완역. 사용법 /translate input/paper.pdf
allowed-tools: Bash, Read, Write, Agent
---

논문 파일 `$ARGUMENTS`를 한국어로 완역한다. 아래 파이프라인을 **순서대로** 실행하고, 각 단계 결과를 한 줄씩 보고한다.

## 0. 준비
- `$ARGUMENTS`가 비어 있으면 사용자에게 파일 경로를 묻고 중단.
- STEM = 파일명(확장자 제외). 이하 `work/STEM/`을 작업 폴더로 쓴다.

## 1. 추출 (결정적 스크립트)
```bash
python scripts/extract.py "$ARGUMENTS"
python scripts/chunk.py work/STEM
```
`chunks/index.json`을 읽어 청크 수 N, 그림 수를 보고한다.

## 2. 용어표 — `glossary-builder` 서브에이전트 1회
프롬프트: "work/STEM/source.md를 읽고 work/STEM/glossary.md를 작성하라."
완료 후 glossary.md의 행 수를 보고한다.

## 3. 번역 — `translator` 서브에이전트 × N (병렬)
청크마다 하나의 translator 에이전트를 띄운다. **한 메시지에 여러 Agent 호출을 넣어 동시에 실행**한다 (최대 5개씩 배치).
각 프롬프트: "work/STEM/chunks/NNN.md를 work/STEM/glossary.md의 용어로 번역하여 work/STEM/translated/NNN.md에 저장하라."

## 4. 기계 검증
```bash
python scripts/verify.py work/STEM
```
FAIL 청크가 있으면 해당 청크만 translator를 재실행(실패 사유를 프롬프트에 포함)한 뒤 다시 verify. 최대 2회.

## 5. 검수 — `reviewer` 서브에이전트 × N (병렬)
각 프롬프트: "work/STEM/chunks/NNN.md와 work/STEM/translated/NNN.md를 대조 검수하고 수정 후 work/STEM/review/NNN.md에 보고하라."
완료 후 `python scripts/verify.py work/STEM`을 한 번 더 실행 (검수 중 구조가 깨지지 않았는지).

## 6. 조립
```bash
python scripts/assemble.py work/STEM
```

## 7. HTML 렌더링
```bash
python scripts/to_html.py output/STEM
```
이미지가 base64로 내장된 단일 HTML(`output/STEM/STEM.html`)이 생성된다. 브라우저에서 바로 열거나 업로드해 볼 수 있다.

## 8. 최종 보고
- 출력 경로 `output/STEM/STEM.ko.md`, HTML `output/STEM/STEM.html`, 그림 폴더 `output/STEM/images/`
- 청크 수, 검수 수정 건수 합계(review/*.md에서 집계), REVISE가 많았던 청크 번호
- 용어표 중 `?` 표시(확신 낮음) 항목이 있으면 사용자 확인 요청

주의: 그림(images/)은 어떤 단계에서도 수정·재생성하지 않는다. 번역 본문은 에이전트가 쓰고, 파일 이동·병합은 스크립트만 한다.
