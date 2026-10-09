# PC 업데이트 없이 무료 웹으로 사용

Render Free 웹 서비스에 화면·API를 배포하고, Neon Free PostgreSQL에 공고·가격·경쟁률·API 연결 설정을 저장합니다. 수집은 GitHub Actions의 표준 `ubuntu-latest` 공개 저장소 실행기에서 별도로 실행합니다. PC에서 `git pull`, Docker 재빌드 또는 `.env` 편집을 할 필요가 없습니다.

이 문서는 준비된 배포 구성을 설명합니다. 계정 연결·데이터베이스 설정·워크플로 활성화를 완료하기 전에는 공개 앱과 자동 수집이 실행된 상태로 간주하지 않습니다. 무료 서비스의 제한 때문에 정확한 3시간 실행과 항상 즉시 열리는 화면을 보장하지 않습니다.

## 1. 무료 PostgreSQL 연결

[Neon Console](https://console.neon.tech/)에서 **Free** 프로젝트를 만들고 **Connect**의 PostgreSQL 연결 문자열을 복사합니다. TLS 설정(`sslmode=require`)을 유지합니다. Neon Free는 카드 등록 없이 사용할 수 있고 무료 한도 초과분을 청구하지 않습니다. 한도에 도달하면 연결이나 쓰기가 제한될 수 있습니다.

연결 문자열에는 데이터베이스 비밀번호가 있습니다. 아래 Render 환경 설정과 GitHub Actions 비밀값 입력 화면에만 붙여 넣습니다. 저장소 파일, 이슈 또는 채팅에 올리지 않습니다. API 키 원문도 이 데이터베이스에 저장되므로 프로젝트 접근 권한과 백업은 소유자가 관리합니다.

기존 localhost PostgreSQL의 공고·설정·관리자 인증은 새 프로젝트로 자동 이동하지 않습니다. 기존 데이터를 유지하려면 기존 DB를 별도로 백업·복원해야 합니다. Neon의 무료 저장 공간·컴퓨트·전송량 한도도 확인합니다.

## 2. Render Free 웹 배포

[Render 배포 화면](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fseokjeongeum%2Fcheongyak-calendar%2Ftree%2Fwork)을 열고 GitHub 저장소를 연결합니다. 배포 브랜치가 **work**인지 확인합니다. Blueprint 파일은 [render.yaml](../render.yaml)이며 서비스의 브랜치도 `work`로 지정되어 있습니다. 배포 화면에서 브랜치를 다시 선택해야 한다면 **work**를 선택합니다.

구성을 확인할 항목은 다음과 같습니다.

- 웹 서비스 요금제: **Free**.
- Dockerfile: `Dockerfile.render`.
- `DATABASE_URL`: 1단계에서 복사한 내구성 있는 외부 PostgreSQL 연결 문자열.
- `INTEGRATIONS_ADMIN_BOOTSTRAP_TOKEN`: Render가 생성하는 비공개 관리자 인증키.

Render에서는 **결제 수단을 등록하지 않은 Free 계정·워크스페이스**를 사용합니다. 무료 전송량·빌드 한도를 넘으면 서비스나 빌드가 중지됩니다. 결제 수단이 등록된 계정은 초과 사용량을 청구할 수 있으므로, Free 웹 서비스 표시만으로 전체 계정의 청구가 없다고 판단하지 않습니다.

이 Blueprint는 웹 서비스 하나만 만듭니다. Render 유료 worker·cron·disk 또는 30일 후 만료되는 Render Free PostgreSQL을 추가하지 않습니다. 정기 수집은 GitHub Actions가 실행합니다. 화면에서 저장·수동 수집을 요청하면 같은 Free 서비스의 별도 임시 프로세스가 한 번 수집하고 종료하므로 API는 계속 응답합니다. 중복 요청과 예약 수집은 DB의 같은 실행권한을 공유합니다. 서버 종료·휴면으로 중단되면 중단 상태를 표시하고 기존 자료를 유지합니다.

배포가 성공하면 Render가 표시하는 HTTPS 주소를 북마크합니다. **Environment** 화면의 `INTEGRATIONS_ADMIN_BOOTSTRAP_TOKEN`을 소유자만 확인하고, 앱의 **데이터 출처 → API 연결 설정**에 관리자 인증키로 입력합니다. 최초 실행은 이 키의 해시를 DB에 저장합니다. 이미 관리자 인증이 있는 DB에는 기존 인증을 유지하므로 새 환경값으로 덮어쓰지 않습니다.

같은 브라우저에서 기존 localhost와 새 HTTPS 주소의 개인 조건은 별개입니다. 개인 조건은 해당 웹 주소의 브라우저 저장소에 남으며 수집 작업이나 서버에 전송되지 않습니다.

## 3. 무료 3시간 수집 활성화

[GitHub Actions 비밀값 설정](https://github.com/seokjeongeum/cheongyak-calendar/settings/secrets/actions)을 열고 **New repository secret**에 이름 **DATABASE_URL**, 값은 Render에 입력한 것과 같은 연결 문자열을 저장합니다. 이 링크에는 저장소 설정 권한이 필요합니다. 공공데이터·LH·iH·Gemini API 키는 Actions 비밀값에 복제하지 않습니다. 수집기가 같은 DB의 화면에서 저장한 설정을 읽습니다.

[수집 워크플로](../.github/workflows/collect-notices.yml)는 `python -m app.ingest.worker --once`를 실행합니다. Python 3.12와 LibreOffice Writer를 설치해 PDF·HWP 수집 기능을 유지하고, API와 같은 **work** 브랜치의 코드를 사용합니다. 수집 작업끼리는 겹치지 않도록 직렬화하며 한 작업의 제한은 60분입니다. API 키나 DB 연결 문자열을 로그로 출력하거나 실행 결과 파일에 저장하지 않습니다.

**현재 저장소의 기본 브랜치는 main입니다.** 예약 실행은 기본 브랜치에 존재하는 워크플로에만 적용되므로, 이 파일이 `work`에만 있으면 예약 수집은 활성화되지 않습니다. 검토한 워크플로 파일을 PR로 **main**에 반영한 뒤 [Actions 화면](https://github.com/seokjeongeum/cheongyak-calendar/actions/workflows/collect-notices.yml)에서 활성화합니다. 기본 브랜치를 바꿀 필요는 없습니다. 실행할 애플리케이션 코드는 계속 `work`에서 가져옵니다. 수동 **Run workflow** 버튼도 기본 브랜치에 파일이 반영된 뒤 사용할 수 있습니다.

처음에는 **Run workflow**로 한 번 실행하고 앱의 **데이터 출처**에서 기관별 마지막 성공 시각과 실패 사유를 확인합니다. Actions 실행이 성공했더라도 특정 기관의 인증·접속·원문 처리에 실패한 상태는 별도로 남으므로, 화면의 기관별 상태를 함께 확인합니다. 코드 수정 후에는 검증된 변경을 `work`에 반영하면 Render는 자동 배포하고 다음 수집 작업도 새 코드를 사용합니다. 사용자의 PC 업데이트는 없습니다.

예약식은 `17 */3 * * *`(UTC)이며 한국 시간으로 대략 **00:17, 03:17, 06:17, 09:17, 12:17, 15:17, 18:17, 21:17**입니다. GitHub의 실행기 혼잡이나 대기열에 따라 시작이 지연되거나 예약 실행이 생략될 수 있습니다. 공개 저장소에 60일 동안 활동이 없으면 예약 워크플로가 자동 중지될 수 있으므로 Actions에서 다시 활성화합니다. 비밀값 미설정이나 DB 정지 시 작업은 실패하고 화면에는 마지막 저장 자료와 상태가 남습니다.

## 4. API 키는 앱 화면에서 연결

북마크한 앱의 **데이터 출처 → API 연결 설정**을 엽니다. **관리자 인증키 확인** 링크로 Render 설정을 열어 `INTEGRATIONS_ADMIN_BOOTSTRAP_TOKEN` 값을 입력합니다. 서비스별 **활용신청·키 발급** 링크를 열어 승인을 확인하고 일반 인증키(Decoding)를 **공공데이터 공통 인증키**에 한 번 입력합니다. 공통 키는 다섯 공공데이터 서비스에 함께 적용되며, 기관에 다른 키가 필요한 경우 **기관별 다른 키 사용**을 엽니다. Gemini는 별도 선택 입력입니다.

**연결 설정 저장** 성공은 DB에 반영된 연결 상태를 표시하고 즉시 수집을 요청합니다. 화면을 다시 열어도 연결 상태는 유지되며 저장된 키 원문은 다시 전송하지 않습니다. 빈 입력은 기존 키를 유지하고, **삭제** 버튼으로 표시한 항목만 삭제합니다. 수집 요청 실패와 설정 저장 실패는 별도로 표시합니다. **지금 수집 시작**으로 재시도하고 **수집 상태 새로고침**으로 실제 진행·기관별 결과·확인 시각을 조회합니다. API 키나 개인 조건은 수집 요청에 첨부하지 않으며, 수집기는 DB의 저장 설정을 읽습니다.

첫 수집은 공고 목록·주택형을 가져온 뒤 원문을 검토하므로 시간이 걸립니다. 현재 또는 앞으로 접수하는 공고를 먼저 저장하고, 과거 공고도 이어서 처리합니다. 기관 전체 수집이 끝나기 전에도 `n/N건 저장` 진행 상황을 공개하며, 저장된 공고는 화면의 30초 상태 조회에서 목록·달력에 반영됩니다. 이 진행 건수는 원문 검토 전체의 완료를 뜻하지 않으며, 최종 기관 상태와 공고별 근거를 함께 확인합니다.

| 서비스 | 직접 발급·활용신청 |
| --- | --- |
| 청약홈·공공데이터 공통 | [한국부동산원 분양정보](https://www.data.go.kr/data/15098547/openapi.do) |
| 마이홈 | [마이홈 공고 조회](https://www.data.go.kr/data/15108420/openapi.do) |
| LH | [LH 분양임대 공고문](https://www.data.go.kr/data/15058530/openapi.do) |
| iH | [인천도시공사 분양임대 공고문](https://www.data.go.kr/data/15149725/openapi.do) |
| 경쟁률 | [청약접수 경쟁률 및 특별공급 신청현황](https://www.data.go.kr/data/15098905/openapi.do) |
| Gemini · 선택 | [Google AI Studio API keys](https://aistudio.google.com/apikey) |

키가 없는 기관은 연결 미설정으로 남고 SH·GH 공개 게시판은 수집합니다. Gemini는 선택 사항이며 청구를 사용하지 않는 프로젝트임을 화면에서 확인해야 호출합니다. 무료 한도 초과 시 대기하고 유료 모델로 전환하지 않습니다.

## 무료 운영의 범위

Render Free는 유휴 시 웹 서비스를 중지하므로 다음 접속의 기동 시간이 길어질 수 있습니다. 무료 DB의 사용량·저장 공간 한도나 기관의 실행기 IP 접근 제한도 수집에 영향을 줍니다. [Render Free 안내](https://render.com/docs/free), [Neon 요금제](https://neon.com/pricing), [무료 한도 초과 시 Neon 동작](https://neon.com/faqs/free-plan-limits-and-quotas), [GitHub 예약 실행 안내](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)를 계정에서 확인합니다.

무료 서비스의 저장 이력을 내보내 백업하고, 앱의 출처 상태를 확인합니다. 이 구성에는 유료 cron·상시 worker·상위 DB 요금제로 자동 전환하는 설정이 없습니다. 수집 지연·정지 시 원본·가격·경쟁률·기존 설정을 지우거나 예시 공고로 대체하지 않습니다.
