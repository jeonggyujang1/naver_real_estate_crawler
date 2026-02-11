# Naver Apt Briefing Backend (한국어 가이드)

네이버 부동산 매물 데이터를 수집/저장하고, 관심 단지 기준으로 추세/급매 후보/알림을 제공하는 백엔드 서비스입니다.

## 1) 이 프로젝트로 할 수 있는 것
- 계정 관리: 회원가입, 로그인, 토큰 재발급, 로그아웃
- 관심 단지 관리: 단지명 검색 자동완성, 관심 단지 등록/조회
- 매물 수집: 단지별 매물 스냅샷 수집(수동/스케줄)
- 분석: 단지 추세 차트, 단지 비교 차트, 급매 후보 탐지
- 알림: 이메일/텔레그램 급매 알림 발송

## 2) 문서 맵
- 배포 의사결정 문서: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/DEPLOYMENT_DECISION_KR.md`
- 기술 아키텍처 문서: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/TECHNICAL_ARCHITECTURE_KR.md`
- 웹 테스트 가이드: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/WEB_TEST_GUIDE_KR.md`

## 3) 빠른 시작 (Docker Compose 권장)
가장 쉬운 실행 방법입니다.

### 3-1) 준비물
- Docker Desktop 최신 버전
- macOS/Linux 터미널

### 3-2) 실행
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
cp .env.example .env
```

`.env` 파일을 먼저 수정한 뒤:

```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
docker compose up -d --build
```

확인:
```bash
curl http://127.0.0.1:18080/health
```

정상 응답 예:
```json
{"status":"ok","env":"prod"}
```

열기:
- 대시보드: `http://127.0.0.1:18080/`
- API 문서: `http://127.0.0.1:18080/docs`

중지:
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
docker compose down
```

## 4) `.env` 설정 가이드 (초보자용)
경로: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/.env`

### 4-1) 최소 필수값
아래 4개는 먼저 채우세요.

```env
APP_ENV=prod
APP_PORT=18080
AUTH_SECRET_KEY=길고_랜덤한_비밀값_반드시_변경
DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/naver_apt_briefing
```

주의:
- Docker Compose로 실행할 때 `DATABASE_URL` 호스트는 `localhost`가 아니라 `db`를 써야 합니다.

### 4-2) 네이버 크롤링 필수값
429(요청 한도) 회피를 위해 아래 두 값을 넣는 것을 권장합니다.

```env
NAVER_LAND_AUTHORIZATION=Bearer ...
NAVER_LAND_COOKIE=NNB=...; NID_AUT=...; ...
CRAWLER_MAX_RETRY=1
```

핵심 규칙:
- `NAVER_LAND_AUTHORIZATION`에는 `Bearer` 포함 전체 문자열을 넣습니다.
- `NAVER_LAND_COOKIE`에는 Request Headers의 `Cookie` 전체 문자열을 넣습니다.
- 둘 다 세션 만료 시 다시 갱신해야 합니다.

### 4-3) 네이버 값 추출 방법
1. Chrome 로그인 후 `https://new.land.naver.com` 접속
2. 단지 페이지를 연 뒤 `F12 -> Network`
3. `api/search` 또는 `api/articles/complex` 요청 클릭
4. `Request Headers`에서 복사
   - `Authorization` -> `NAVER_LAND_AUTHORIZATION`
   - `Cookie` -> `NAVER_LAND_COOKIE`
5. 반영 후 컨테이너 재생성:

```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
docker compose up -d --force-recreate app
```

### 4-4) 스케줄러 설정
```env
SCHEDULER_ENABLED=true
SCHEDULER_TIMEZONE=Asia/Seoul
SCHEDULER_TIMES_CSV=09:00,18:00
SCHEDULER_COMPLEX_NOS_CSV=2977,23620
SCHEDULER_POLL_SECONDS=20
```

설명:
- `SCHEDULER_ENABLED=true`면 API 프로세스 내부 스케줄러가 동작합니다.
- 운영에서 앱이 내려가면 스케줄도 함께 멈춥니다.

### 4-5) 이메일/텔레그램 알림 설정
이메일:
```env
SMTP_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_SENDER_EMAIL=...
SMTP_USE_TLS=true
```

텔레그램:
```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<BOT_TOKEN>
TELEGRAM_API_BASE_URL=https://api.telegram.org
```

chat_id는 로그인 후 대시보드의 알림 설정 화면에서 입력합니다.

## 5) 로컬 개발 실행 (Python venv)
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 18080
```

## 6) 테스트
### 6-1) 백엔드 단위/통합 테스트
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
source .venv/bin/activate
pytest -q
```

### 6-2) Playwright E2E
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend/e2e
npm install
npx playwright install chromium
npx playwright test --config=playwright.config.ts
```

## 7) 핵심 API 요약
인증:
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /me`

관심 단지/프리셋:
- `GET /me/watch-complexes`
- `GET /me/watch-complexes/live`
- `POST /me/watch-complexes`
- `GET /me/presets`
- `POST /me/presets`

크롤링/분석:
- `GET /crawler/search/complexes`
- `GET /crawler/articles/{complex_no}`
- `POST /crawler/ingest/{complex_no}`
- `GET /analytics/trend/{complex_no}`
- `GET /analytics/compare`
- `GET /analytics/bargains/{complex_no}`

알림:
- `GET /me/notification-settings`
- `PUT /me/notification-settings`
- `GET /me/alerts/bargains`
- `POST /me/alerts/bargains/dispatch`

## 8) 초보자용 점검 시나리오 (10분)
1. 회원가입/로그인
2. 단지명 검색(`래미안`) 후 관심 단지 등록
3. `POST /crawler/ingest/{complex_no}`로 1회 수집
4. 추세/비교/급매 API 호출
5. 알림 설정 저장 후 `지금 알림 발송`

## 9) 자주 발생하는 문제
### 문제 A: `"네이버 부동산 요청 한도에 도달했습니다"`
조치:
1. `NAVER_LAND_AUTHORIZATION`, `NAVER_LAND_COOKIE` 재발급
2. `CRAWLER_MAX_RETRY=1`로 낮춰 테스트
3. `docker compose up -d --force-recreate app`

### 문제 B: `Invalid HTTP request received`
원인:
- `curl` 인코딩/따옴표 깨짐
조치:
```bash
curl -G "http://127.0.0.1:18080/crawler/search/complexes" \
  --data-urlencode "keyword=래미안" \
  --data-urlencode "limit=5"
```

### 문제 C: 422 Unprocessable Entity
원인:
- 필수 파라미터 누락 (예: `keyword`)
조치:
- API 문서(`/docs`)에서 파라미터 형식 확인

## 10) 운영 메모
- 로그 확인:
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
docker compose logs -f app
```

- 운영 시 필수:
  - `AUTH_SECRET_KEY` 반드시 변경
  - DB 백업(일 1회 이상)
  - HTTPS(리버스 프록시) 적용

- 현재 스케줄러는 앱 내부 동작:
  - 운영 안정화 단계에서 크롤링 워커 분리를 권장
