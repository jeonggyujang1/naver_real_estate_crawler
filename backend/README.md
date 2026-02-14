# Naver Apt Briefing Backend (한국어 가이드)

네이버 부동산 매물 데이터를 수집/저장하고, 관심 단지 기준으로 추세/급매 후보/알림을 제공하는 백엔드 서비스입니다.

## 1) 이 프로젝트로 할 수 있는 것
- 계정 관리: 회원가입, 로그인, 토큰 재발급, 로그아웃
- 관심 단지 관리: 단지명 검색 자동완성, 관심 단지 등록/조회
- 매물 수집: 단지별 매물 스냅샷 수집(수동/스케줄)
- 분석: 단지 추세 차트, 단지 비교 차트, 급매 후보 탐지
- 알림: 이메일/텔레그램 급매 알림 발송
- 유료화: 더미 결제(체크아웃 생성/완료) 후 PRO 플랜 기능 활성화

## 2) 문서 맵
- 배포 의사결정 문서: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/DEPLOYMENT_DECISION_KR.md`
- 기술 아키텍처 문서: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/TECHNICAL_ARCHITECTURE_KR.md`
- 웹 테스트 가이드: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/WEB_TEST_GUIDE_KR.md`
- 웹 UI 기능 가이드: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/WEB_UI_FEATURE_GUIDE_KR.md`
- 원클릭 on/off 가이드: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/ONE_SCRIPT_ONOFF_GUIDE_KR.md`

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
- 스케줄러는 전용 `worker` 컨테이너에서 동작합니다.
- `app`과 `worker`가 분리되어 앱 재시작이 수집 루프에 주는 영향을 줄였습니다.

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

결제/플랜:
- `GET /billing/me`
- `POST /billing/checkout-sessions`
- `POST /billing/checkout-sessions/{checkout_token}/complete`

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
docker compose logs -f worker
```

- 운영 시 필수:
  - `AUTH_SECRET_KEY` 반드시 변경
  - DB 백업(일 1회 이상)
  - HTTPS(리버스 프록시) 적용

- 현재 스케줄러는 `worker` 컨테이너에서 동작:
  - 배포 시 `app`과 `worker`가 모두 `Up` 상태인지 함께 확인하세요.

## 11) VPS + Docker Compose + Caddy 배포 절차 (권장)
아래 절차는 이 프로젝트의 현재 구조에 맞춘 "가장 빠른 실서비스 배포" 경로입니다.

### 11-1) 서버 준비
권장 스펙(베타):
- 2 vCPU / 4GB RAM / 60GB SSD
- Ubuntu 22.04 LTS

필수 포트:
- `22` (SSH)
- `80` (HTTP)
- `443` (HTTPS)

### 11-2) 코드 및 환경파일 준비
```bash
cd /opt
git clone git@github.com:jeonggyujang1/naver_real_estate_crawler.git
cd /opt/naver_real_estate_crawler/backend
cp env.production.example .env.production
```

`.env.production`에서 최소 아래 값을 수정:
- `DOMAIN`
- `ACME_EMAIL`
- `POSTGRES_PASSWORD`
- `DATABASE_URL`의 비밀번호 부분
- `AUTH_SECRET_KEY`
- `NAVER_LAND_AUTHORIZATION`, `NAVER_LAND_COOKIE`

### 11-3) 배포 실행
```bash
cd /opt/naver_real_estate_crawler/backend
docker compose -f docker-compose.prod.yml up -d --build
```

상태 확인:
```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f app
```

헬스체크:
```bash
curl https://<YOUR_DOMAIN>/health
```

### 11-4) 참고 파일
- 운영용 compose: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/docker-compose.prod.yml`
- Caddy 설정: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/Caddyfile`
- 운영 env 샘플: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/env.production.example`

## 12) 유료 서비스 확장을 고려한 현재 운영 원칙
현재 구조로 시작하되, 아래 원칙을 지키면 유료화 전환 시 리팩터링 비용을 줄일 수 있습니다.

1. 워크로드 분리 전제
- 지금은 API + 내부 스케줄러 결합 구조
- 유료 단계에서는 "API 서버"와 "크롤링/알림 워커"를 분리

2. 데이터 경계 명확화
- `listing_snapshots`는 수집 원본 기반 사실 데이터
- 유료 기능(리포트/추천/프리미엄 지표)은 별도 파생 테이블로 분리

3. 과금 포인트 사전 정의
- 플랜별 제한 항목을 미리 고정:
  - 관심 단지 수
  - 하루 알림 횟수
  - 고급 차트/비교 기능 접근

4. 운영 지표 우선
- 유료화 전에 최소 지표를 확보:
  - 크롤링 성공률
  - 429 비율
  - 알림 도달률
  - 주간 활성 사용자/재방문율

## 13) 유료화 전 필수 체크리스트
- 결제 시스템(예: Stripe) 연동
- 플랜/권한/쿼터 정책 구현
- 장애 알림 및 온콜 룰
- DB 백업 자동화 + 복구 리허설
- 이용약관/개인정보 처리방침/데이터 수집 정책 검토
