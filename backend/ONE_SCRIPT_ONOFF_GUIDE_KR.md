# 원클릭 on/off 가이드 (단일 스크립트)

이 프로젝트는 아래 **하나의 스크립트**로 서비스 시작/중지/상태확인을 할 수 있습니다.

- 스크립트 경로: `/Users/jeonggyu/workspace/naver_apt_briefing/backend/service.sh`

---

## 1) 가장 자주 쓰는 명령 2개

개발용(dev) 기준:

```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
./service.sh on dev
./service.sh off dev
```

운영용(prod) 기준:

```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
./service.sh on prod
./service.sh off prod
```

---

## 2) 스크립트가 내부적으로 하는 일

`on`:
- `docker compose up -d --build` 실행
- 컨테이너 상태 출력
- `dev` 모드에서는 `http://127.0.0.1:${APP_PORT}/health` 헬스체크까지 자동 확인

`off`:
- `docker compose down` 실행

---

## 3) 추가 명령 (선택)

```bash
./service.sh status dev   # 실행 상태 보기
./service.sh logs dev     # app/worker 로그 보기
./service.sh restart dev  # 재시작
```

prod도 동일하게 `dev` 대신 `prod` 사용:

```bash
./service.sh status prod
./service.sh logs prod
./service.sh restart prod
```

---

## 4) 초보자용 체크리스트

1. Docker Desktop 실행 확인  
2. `backend/.env` (dev) 또는 `backend/.env.production` (prod) 준비  
3. `./service.sh on dev` 실행  
4. `[OK] Health check passed` 메시지 확인  
5. 브라우저에서 `http://127.0.0.1:18080/` 접속

---

## 5) 문제 해결

### A. `permission denied: ./service.sh`
```bash
chmod +x /Users/jeonggyu/workspace/naver_apt_briefing/backend/service.sh
```

### B. 헬스체크 실패
```bash
./service.sh logs dev
docker compose -f docker-compose.yml ps
```

원인 대부분:
- `.env` 설정 누락
- DB 초기 기동 지연
- 포트 충돌

### C. 포트 충돌(18080 사용 중)
`.env`에서 `APP_PORT`를 다른 값으로 변경 후:

```bash
./service.sh off dev
./service.sh on dev
```

