# paper-translator

이 폴더의 모든 작업은 **`명령서.md`를 따른다.** 작업 전에 반드시 읽는다.

- 규칙·임계값·처리 방침의 단일 출처는 `명령서.md`다. 코드와 명령서가 어긋나면 사용자에게 알리고 함께 고친다.
- 원문 충실도가 최우선이다. 원문에 없는 내용을 만들지 않는다.
- 파일 이동·병합·검증은 스크립트가, 문장 작성은 서브에이전트가 한다. 이 경계를 넘지 않는다.
- 테스트는 `python scripts/selftest.py`로 돌린다. pytest를 도입하지 않는다.
- 설계 문서: `docs/superpowers/specs/`, 구현 계획: `docs/superpowers/plans/`
