# 신청 불가 공급유형 기본 접기 검증

2026-10-09 검증. 실제 개인정보나 API 키 없이 공개 API 응답 모양의 합성 공고와 브라우저 안의 합성 입력만 사용했다.

`내 조건으로 신청 불가` 공급유형은 요약과 유형별 근거 모두 닫힌 네이티브 `<details>`로 시작한다. 공급유형·판정·주택형은 계속 보이며, 펼치면 불일치 값과 원문 링크를 확인할 수 있다. 실패한 경로에만 적용되는 공통·공유 근거는 접힌 본문 안에 남긴다. 가능한 경로나 입력이 필요한 경로의 근거는 열린 상태를 유지한다.

- `EligibilitySupplyCollapse.test.tsx` 5개 사례 및 관련 렌더링·가족 사실·지역 검토 테스트: 5개 파일, 48개 통과.
- TypeScript 검사와 Vite 프로덕션 빌드 통과.
- `web/tests/supply_collapse_browser_qa.py`: 실제 Chromium 375px/1280px에서 18개 검사 통과. 마우스/Enter 토글, 실패 근거의 중복 노출 없음, 원문 링크, 입력 부족 경로 유지, 가로 넘침 없음, JavaScript 예외 없음 확인.
- 펼치기·접기·유형별 근거 열기는 API 요청을 추가하지 않았으며 입력 정보 전송도 없었다.

동시 개발의 HMR 재로딩이 요청 수 검사를 방해하지 않도록 `/tmp`에 빌드한 정적 스냅샷을 사용했다. 검증 후 정적 서버를 종료했다.

결과와 합성 화면: [result.json](qa/supply-collapse/result.json), [375px 기본 접힘](qa/supply-collapse/closed-brief-375.png), [375px 원문 근거 펼침](qa/supply-collapse/open-detail-375.png). 1280px 화면도 같은 폴더에 보관했다.
