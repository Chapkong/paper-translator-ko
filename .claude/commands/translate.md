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

`extract.py`가 0이 아닌 코드로 끝나면 **번역 단계로 넘어가지 않는다.** 추출 품질 미달이라는 뜻이다.
`work/STEM/extract_report.md`를 읽어 어느 문단이 잘렸는지 사용자에게 보고하고 멈춘다.
깨진 원문을 번역하면 토큰만 쓰고 결과도 쓸 수 없다.

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

## 7. 전문 통독 — `final-reviewer` 서브에이전트 1회
프롬프트: "output/STEM/STEM.ko.md 전문을 통독하고, 수정은 work/STEM/translated/NNN.md에 적용한 뒤 work/STEM/final_review.md에 보고하라."

## 8. 재검증·재조립·HTML
```bash
python scripts/verify.py work/STEM
python scripts/assemble.py work/STEM
python scripts/to_html.py output/STEM
```
`verify.py`가 0이 아닌 코드로 끝나면 **다음 단계로 넘어가지 않는다.** FAIL로 표시된 청크를
`translator` 또는 `reviewer`로 되돌려 고친 뒤 다시 돌린다. 참고문헌·감사의 글처럼 원문 유지가
정상인 청크는 사유를 최종 보고에 적고 넘어간다 — 다만 **그 판단 근거를 반드시 적는다.**

이미지가 base64로 내장된 단일 HTML(`output/STEM/STEM.html`)이 생성된다.

## 9. 결과물 검증 — 기계 검증 + `output-verifier`

**먼저 기계로 직접 잰다.** 에이전트의 판정을 그대로 믿지 않는다.

```bash
python scripts/final_check.py work/STEM output/STEM
```

미번역 각주, 미번역 본문 문단, 원문 대비 문단 수, 빠진 연도, 이미지 링크·HTML 내장,
추출 보존율을 실제 파일에서 세어 표로 내놓는다. 결과는 `work/STEM/final_check.md`에 남는다.

그다음 `output-verifier` 서브에이전트를 띄운다.
프롬프트: "output/STEM/STEM.ko.md를 work/STEM/source.md와 대조해 판정하고 work/STEM/verdict.md에 기록하라."

**두 결과가 모두 PASS여야 통과다.** 둘이 어긋나면 기계 검증을 따른다 — 판정하는 주체와
판정받는 주체가 같으면 놓치는 것이 생긴다(실제로 각주 17개가 미번역인 채 PASS가 나왔다).

FAIL이면 `final_check.md`의 미달 항목과 `verdict.md`의 수정 지시에 해당하는 청크만
`translator`/`reviewer`로 되돌린 뒤 `assemble.py` → `to_html.py` → 9절을 다시 실행한다.
**최대 2회.** 2회 후에도 FAIL이면 사유와 남은 문제를 사용자에게 보고하고 멈춘다.
통과했다고 보고하지 않는다.

## 10. 최종 보고
- 출력 경로 `output/STEM/STEM.ko.md`, HTML `output/STEM/STEM.html`, 그림 폴더 `output/STEM/images/`
- **`final_check.md`의 표를 그대로 옮겨 적는다.** 판정만 옮기지 않는다 — 사용자가 수치를 직접 본다
- 청크 수, 검수 수정 건수 합계(review/*.md), 통독 수정 건수(final_review.md)
- `final_review.md`의 **사용자 확인 요청 목록을 그대로 옮겨 적는다**
- 용어 변경을 원하면 glossary 갱신 후 일괄 교체·재조립이 가능함을 안내한다

주의: 그림(images/)은 어떤 단계에서도 수정·재생성하지 않는다. 번역 본문은 에이전트가 쓰고, 파일 이동·병합은 스크립트만 한다.
