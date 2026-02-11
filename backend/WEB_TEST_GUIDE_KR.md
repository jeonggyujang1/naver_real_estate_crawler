# Naver Apt Briefing 웹 테스트 가이드 (지인 테스트용)

이 문서는 로컬/서버에 배포된 앱을 실제로 사용 테스트할 때, 어디부터 어떻게 확인하면 되는지 빠르게 안내합니다.

## 1) 접속 확인

1. 서비스 상태 확인

```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
docker compose ps
curl http://127.0.0.1:18080/health
```

2. 브라우저 접속

- 대시보드: `http://127.0.0.1:18080/`
- API 문서: `http://127.0.0.1:18080/docs`

## 2) 사전 설정 확인 (.env)

아래 값이 있어야 네이버 데이터 수집/검색이 안정적으로 동작합니다.

- `NAVER_LAND_AUTHORIZATION`
- `NAVER_LAND_COOKIE`
- `CRAWLER_MAX_RETRY=1` (지인 테스트 중에는 권장)
- `SCHEDULER_ENABLED=false` (수동 테스트 중에는 권장)

반영 후 재시작:

```bash
docker compose up -d --force-recreate app
```

## 3) API 스모크 테스트 (터미널)

1. 단지 검색 자동완성 백엔드 확인

```bash
curl -G "http://127.0.0.1:18080/crawler/search/complexes" \
  --data-urlencode "keyword=래미안" \
  --data-urlencode "limit=5"
```

기대 결과:
- HTTP 200
- `items` 배열에 단지 목록

2. 단지 수집(ingest) 확인

```bash
curl -X POST "http://127.0.0.1:18080/crawler/ingest/2977?page=1&max_pages=1"
```

기대 결과:
- HTTP 200
- `listing_count`가 1 이상

## 4) 웹 기능 테스트 시나리오

### 시나리오 A: 회원 기능

1. `회원가입` -> 성공 메시지 확인  
2. `로그인` -> 사용자 배지(`로그인됨`) 확인  
3. `내 정보` -> 내 계정 이메일 표시 확인  
4. `로그아웃` -> `로그인 필요` 표시 확인

### 시나리오 B: 관심 단지 등록

1. `단지명 검색`에 `래미안` 입력  
2. 검색 결과 버튼 클릭  
3. `complex_no`, `단지명` 자동 입력 확인  
4. `등록` 클릭  
5. `목록 조회`에서 등록된 단지 확인

### 시나리오 C: URL 기반 등록

1. 네이버 단지 URL 입력  
   예: `https://new.land.naver.com/complexes/2977?...`
2. `URL에서 번호 추출` 클릭  
3. `complex_no` 자동 채움 확인  
4. `등록` 클릭

### 시나리오 D: 실시간 매물/수집

1. `실시간 매물 조회` 클릭 -> 매물 목록 표시  
2. `수동 수집`에서 `complex_no=2977`, `page=1`  
3. `지금 수집` 클릭 -> 수집 완료 메시지 확인

### 시나리오 E: 차트

1. `단지 추세 차트` 조회  
2. `단지 비교 차트` 조회(2개 이상 complex_no)  
3. `급매 후보` 조회

## 5) 문제가 생기면 먼저 보는 포인트

1. 503 (`요청 한도`)가 나오면

- `NAVER_LAND_AUTHORIZATION`, `NAVER_LAND_COOKIE` 재발급/재입력
- 재시작: `docker compose up -d --force-recreate app`
- 10~20분 후 재시도

2. 수집 중 500이 나오면

- 로그 확인:

```bash
docker compose logs --tail=200 app
```

3. 앱이 안 뜨면

- Docker Desktop 상태 확인
- 다시 실행:

```bash
docker compose up -d app
docker compose ps -a
```

## 6) 지인 공유용 접속 방법

- 같은 PC에서 테스트: `http://127.0.0.1:18080/`
- 같은 네트워크(사내/집)에서 테스트:
  - 서버 PC IP 확인 후 `http://<서버IP>:18080/`
  - 방화벽/포트(18080) 허용 필요

## 7) 현재 검증된 상태 (요약)

- 단지 검색 API: 200 확인
- ingest API: 200 확인
- 회원/로그인/로그아웃/자동완성 E2E 테스트: 통과
- `article_no` bigint 마이그레이션 적용 완료
