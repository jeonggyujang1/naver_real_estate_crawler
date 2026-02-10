# Naver Apt Briefing Backend

## 1) Requirements
- Python 3.11+
- PostgreSQL 14+

## 2) Install
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 3) Environment
Create `.env` in `/Users/jeonggyu/workspace/naver_apt_briefing/backend`:

```env
APP_ENV=dev
APP_NAME=Naver Apt Briefing API
APP_VERSION=0.1.0

DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/naver_apt_briefing
REDIS_URL=redis://localhost:6379/0

AUTO_CREATE_TABLES=false
AUTH_SECRET_KEY=replace-with-long-random-secret
AUTH_JWT_ALGORITHM=HS256
AUTH_JWT_ISSUER=naver-apt-briefing
AUTH_ACCESS_TOKEN_TTL_MINUTES=15
AUTH_REFRESH_TOKEN_TTL_DAYS=30

NAVER_LAND_BASE_URL=https://new.land.naver.com
NAVER_LAND_AUTHORIZATION=

# Email (SMTP)
SMTP_ENABLED=false
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_SENDER_EMAIL=
SMTP_USE_TLS=true

# Telegram
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_API_BASE_URL=https://api.telegram.org

SCHEDULER_ENABLED=false
SCHEDULER_TIMEZONE=Asia/Seoul
SCHEDULER_TIMES_CSV=09:00,18:00
SCHEDULER_COMPLEX_NOS_CSV=12345,23456
SCHEDULER_POLL_SECONDS=20
```

## 4) Run
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload
```

Open:
- API docs: `http://127.0.0.1:8000/docs`
- Dashboard: `http://127.0.0.1:8000/`

## 5) Test
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
source .venv/bin/activate
pytest -q
```

## 5-1) DB Migration
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
source .venv/bin/activate

# apply latest schema
alembic upgrade head

# check current revision
alembic current

# create new revision (when model changes)
alembic revision -m "add_xxx"
```

## 6) Core Endpoints
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /me`
- `POST /me/watch-complexes`
- `GET /me/watch-complexes`
- `POST /me/presets`
- `GET /me/presets`
- `GET /me/notification-settings`
- `PUT /me/notification-settings`
- `GET /me/alerts/bargains`
- `POST /me/alerts/bargains/dispatch`
- `POST /crawler/ingest/{complex_no}`
- `GET /analytics/trend/{complex_no}`
- `GET /analytics/compare?complex_nos=123&complex_nos=456`
- `GET /analytics/bargains/{complex_no}`

## 7) Telegram Bot Setup Guide
1. Telegram 앱에서 `@BotFather`를 열고 `/newbot` 실행
2. 봇 이름/아이디를 입력하고 발급된 Bot Token 저장
3. 만든 봇과 대화를 열어 `/start` 1회 전송
4. 아래 URL을 브라우저로 호출:
   - `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
5. 응답 JSON에서 `message.chat.id` 값을 확인해 `telegram_chat_id`로 저장
6. `.env`에 아래 값 설정:
   - `TELEGRAM_ENABLED=true`
   - `TELEGRAM_BOT_TOKEN=<YOUR_BOT_TOKEN>`
7. 로그인 후 대시보드에서:
   - `텔레그램 사용` 체크
   - `chat_id` 입력
   - `설정 저장`
   - `지금 알림 발송`으로 테스트

## 8) Email Setup Guide
1. SMTP 계정을 준비 (Gmail, Naver Works, SendGrid, SES 등)
2. `.env`에 SMTP 값 입력:
   - `SMTP_ENABLED=true`
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER_EMAIL`
3. 로그인 후 대시보드에서:
   - `이메일 사용` 체크
   - 알림 이메일 입력
   - `설정 저장`
   - `지금 알림 발송`으로 테스트

## 9) Notes
- Scheduler works only while API server is running.
- For production, run a dedicated scheduler worker.
- `AUTO_CREATE_TABLES` is intended for local dev only (`APP_ENV=dev`).
- Alert deduplication key: `bargain:{complex_no}:{article_no}:{deal_price_manwon}`.
