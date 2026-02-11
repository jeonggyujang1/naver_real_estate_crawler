# 배포 아키텍처 의사결정 문서 (2026-02-11)

## 문서 목적
- 현재 코드 기준에서, 왜 `VPS + Docker Compose + Caddy(HTTPS)`가 1차 운영에 맞는지 설명
- Vercel/Render/Railway 같은 대안과 비교해 장단점 정리
- 추후 수익화(유료화)까지 고려했을 때의 적합성 평가

## 1) 현재 프로젝트의 런타임 특성 (코드 기준)
아래는 현재 코드가 실제로 요구하는 운영 특성이다.

- API 서버와 DB를 함께 운영하는 컨테이너 구조
  - `backend/docker-compose.yml`
- API 프로세스 내부에서 주기 실행 스케줄러가 돌아감
  - `backend/app/services/scheduler.py`
  - `SCHEDULER_ENABLED`, `SCHEDULER_TIMES_CSV`, `SCHEDULER_POLL_SECONDS` 기반
- 크롤링은 외부 API 인증 헤더/쿠키 만료 영향을 받으므로, 장기 운영 중 관측/재시도/키 갱신 운영이 중요
  - `backend/app/crawler/naver_client.py`
  - `NAVER_LAND_AUTHORIZATION`, `NAVER_LAND_COOKIE`
- 알림은 이메일/텔레그램을 포함한 외부 연동 I/O가 있음
  - `backend/app/services/notifier.py`

즉, 이 프로젝트는 "정적 웹 호스팅"보다 "항상 떠 있는 상태 기반 백엔드 + 스케줄 잡 + DB + 알림 I/O"가 핵심이다.

## 2) 배포 옵션 비교

### 옵션 A: VPS + Docker Compose + Caddy
특징
- 단일 서버(또는 소수 서버)에 컨테이너(`app`, `db`)를 항상 실행
- Caddy가 HTTPS 종단 및 리버스 프록시 담당
- 현재 레포 구조를 거의 그대로 사용 가능

장점
- 코드 변경 최소: 현재 구조와 1:1 매핑
- 운영 단순성: 서버 1대에서 빠른 베타 출시 가능
- 비용 예측 가능: 고정비 기반으로 시작하기 쉬움
- 스케줄러/크롤러 같은 상시 프로세스 운영에 적합

단점
- 서버 운영 책임(보안 패치, 백업, 모니터링)을 우리가 직접 가져감
- 장애 복구(HA)는 초기에 수동 대응 요소가 큼
- 수평 확장 시 설계 보강(워커 분리, 큐 도입)이 필요

### 옵션 B: Vercel (주력) + 별도 DB
특징
- API를 함수 기반으로 운영, 프런트 호스팅은 매우 강함

장점
- 프런트 배포/도메인/미리보기 편의성 우수
- 빠른 DX

단점 (현재 프로젝트와의 충돌)
- 함수 실행 시간 상한이 존재해 장시간/상시 작업과 상충
- 취미 요금제 Cron은 하루 1회 제한 + 시각 정밀도 제한
- 현재 "상시 스케줄러 내장 API 프로세스" 구조를 함수형으로 재설계해야 함

정리
- Vercel은 이 프로젝트에서 "프런트 전용"으로는 좋지만, 현재 백엔드/크롤러 주력 런타임으로는 부적합하다.

### 옵션 C: Render/Railway (PaaS)
특징
- Web/Worker/Cron/DB를 플랫폼에서 관리

장점
- 서버 운영 난이도가 크게 낮아짐
- 백업/로그/네트워크가 통합 관리되어 온보딩이 쉬움

단점
- 월 고정비가 VPS 대비 높아질 가능성
- 플랫폼 제약(스케줄/실행 방식)에 맞춘 서비스 분리 필요
- 장기적으로 벤더 종속 비용이 생길 수 있음

## 3) 왜 지금은 VPS + Compose + Caddy가 최적화된 선택인가
현재 코드 관점에서, 아래 3개가 결정적 이유다.

1. 런타임 정합성
- 이미 "항상 떠 있는 app + DB + 내부 스케줄러"로 구현됨.
- 구조를 바꾸지 않고 바로 공개 테스트 가능.

2. 리팩터링 리스크 최소화
- 서버리스/PaaS 최적화로 가면 워커 분리, 잡 큐, 스케줄 분리 등 아키텍처 변경이 커진다.
- 지금 단계는 기능 검증이 우선이므로, 운영 리스크보다 제품 검증 속도가 중요.

3. 베타 비용 효율
- 초기 사용자는 트래픽/데이터가 제한적이라 단일 VPS로 충분.
- "작게 시작하고, 지표가 나오면 분리"가 합리적.

## 4) 수익화 관점에서 이 구성이 적절한가
결론부터: "초기 수익화 검증 단계"에는 적절하다. 다만 결제/권한/과금 계층을 붙여야 한다.

### 가능한 수익화 모델
1. 개인 구독형 (B2C)
- 관심 단지 수 제한, 알림 횟수, 고급 차트/비교 기능으로 티어 분리

2. 전문가/중개사형 (B2B Lite)
- 다중 단지 모니터링, 팀 공유 대시보드, 주간 리포트 자동 발송

3. 데이터 API/리포트 판매
- 익명화/집계 데이터 기반 인사이트 제공 (규정 준수 전제)

4. 리드/제휴 모델
- 금융/중개/이사 등 파트너 연결형

### 현재 구성의 수익화 적합 포인트
- 계정/인증/관심단지/필터/알림 기반이 이미 존재해 유료 기능 게이팅이 쉬움
- Docker 기반이라 같은 이미지를 스테이징/운영에 일관되게 올리기 쉬움

### 수익화 전에 반드시 추가할 항목
- 결제/구독 관리 (예: Stripe)
- 플랜별 사용량 제한(쿼터) 및 초과 정책
- 감사 로그, 관리자 운영 화면, 장애 알림 체계
- DB 백업 자동화 + 복구 훈련
- 법적/정책 검토 (데이터 수집/이용 약관, 개인정보 처리)

## 5) 추천 실행 시나리오 (현실적인 단계)
### 단계 1: 지인 베타 (지금)
- VPS 1대 + Docker Compose + Caddy
- 도메인 + HTTPS + 일일 백업 + 기본 모니터링
- 목표: 기능/알림 정확도/재방문율 검증

### 단계 2: 유료 베타
- 결제/플랜/쿼터 도입
- 스케줄러를 별도 워커로 분리(앱과 장애 격리)
- 장애 대응 룰(온콜, 에러 버짓) 간단 도입

### 단계 3: 확장
- 앱/워커/DB 계층 분리
- 캐시/큐 도입 (Redis + task queue)
- 필요 시 PaaS 또는 매니지드 DB로 일부 이전

## 6) 다른 방식 대비 요약 결론
- Vercel 단독: 현재 백엔드 구조와 맞지 않아 "재설계 비용"이 크다.
- Render/Railway: 운영 편의성은 좋지만 초기 비용/구조 분리 부담이 있다.
- VPS + Compose + Caddy: 현재 코드와 가장 정합성이 높고, 베타 출시 속도/비용 균형이 가장 좋다.

## 7) 최종 판단
현재 목표가 "빠르게 외부 사용자 테스트 + 기능 검증 + 초기 수익화 가능성 확인"이라면,
`VPS + Docker Compose + Caddy`는 매우 실용적인 선택이다.

단, "최종 아키텍처"로 고정하기보다,
"검증 후 분리(워크로드별)"를 전제로 운영해야 기술 부채를 통제할 수 있다.

---

## 참고 자료 (공식 문서)
- Vercel Functions Limits: https://vercel.com/docs/functions/limitations
- Vercel Cron Usage/Pricing: https://vercel.com/docs/cron-jobs/usage-and-pricing
- Vercel Cron Accuracy: https://vercel.com/docs/cron-jobs/manage-cron-jobs
- Docker Compose production guidance: https://docs.docker.com/compose/how-tos/production/
- Docker Compose service restart policy: https://docs.docker.com/reference/compose-file/services/
- Caddy reverse proxy quick start: https://caddyserver.com/docs/quick-starts/reverse-proxy
- Render Background Workers: https://render.com/docs/background-workers
- Render Cron Jobs: https://render.com/docs/cronjobs
- Railway Cron Jobs: https://docs.railway.com/guides/cron-jobs
- Railway Services (persistent vs scheduled): https://docs.railway.com/reference/services
