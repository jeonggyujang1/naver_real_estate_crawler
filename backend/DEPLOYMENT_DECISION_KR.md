# 배포 아키텍처 의사결정 문서 (쉬운 버전, 2026-02-11)

## 0) 이 문서가 답하는 질문
- 왜 지금 우리 프로젝트에 `VPS + Docker Compose + Caddy(HTTPS)`가 맞는가?
- `Vercel / Render / Railway / Serverless`와 비교하면 뭐가 다른가?
- 수익화까지 고려하면 이 선택이 괜찮은가?

이 문서는 "빠른 베타 출시 + 기술 리스크 통제 + 이후 확장 가능성"에 초점을 둔다.

---

## 1) 용어 먼저 정리 (핵심만)
아래는 헷갈리기 쉬운 용어를 "한 줄 정의 + 시스템 관점 비유"로 정리한 것이다.

### VPS
- 한 줄 정의: 인터넷에 있는 "내 전용 리눅스 서버 1대"를 빌려 쓰는 방식.
- 비유: 보드/머신을 직접 들고 있는 임베디드 개발 환경과 비슷하다. 자유도는 높고, 운영 책임도 직접 진다.

### Docker Compose (Compose)
- 한 줄 정의: 컨테이너 여러 개(`app`, `db`)를 한 번에 띄우고 연결하는 실행 스펙.
- 비유: 여러 데몬 프로세스와 의존 순서를 `systemd` 유닛 묶음으로 관리하는 느낌.

### Caddy
- 한 줄 정의: 리버스 프록시 + HTTPS 인증서 자동 발급/갱신을 해주는 서버.
- 비유: 앱 앞단의 네트워크 게이트웨이. TLS/도메인/포트 라우팅을 깔끔하게 맡긴다.

### Cron
- 한 줄 정의: "정해진 시간에 작업 실행"하는 스케줄러.
- 비유: 펌웨어/런타임에서 주기 태스크를 예약하는 타이머 워커.

### 내부 스케줄러
- 한 줄 정의: 앱 프로세스 내부 루프가 시간을 보고 크롤링 작업을 실행하는 방식.
- 현재 코드: `backend/app/services/scheduler.py`
- 비유: 메인 서비스 프로세스 안에 타이머 스레드를 함께 둔 구조.

### Serverless (서버리스)
- 한 줄 정의: 요청이 올 때만 잠깐 실행되는 함수 기반 런타임.
- 비유: 항상 상주하는 데몬이 아니라, 인터럽트 시에만 짧게 켜졌다 꺼지는 실행 모델.

### PaaS
- 한 줄 정의: 서버 운영을 플랫폼이 대신해주는 배포 서비스.
- 예시: Render, Railway
- 비유: BSP/OS 관리 일부를 벤더에게 맡기고, 앱 코드에 집중하는 모델.

### Render / Railway
- 한 줄 정의: Web/Worker/Cron/DB를 UI로 구성해 운영 부담을 낮춰주는 PaaS.
- 장점: 운영 쉬움
- 단점: 비용/제약/벤더 종속

---

## 2) 우리 프로젝트 런타임 성격 (현재 코드 기준)
현재 프로젝트는 "정적 웹페이지"보다 "상시 동작 백엔드 시스템"에 가깝다.

- API + DB가 항상 살아 있어야 함
  - `backend/docker-compose.yml`
- 정해진 시각에 크롤링해야 함
  - `backend/app/services/scheduler.py`
  - `SCHEDULER_ENABLED`, `SCHEDULER_TIMES_CSV`
- 네이버 인증 헤더/쿠키 관리가 필요함
  - `NAVER_LAND_AUTHORIZATION`, `NAVER_LAND_COOKIE`
- 이메일/텔레그램 알림 I/O가 있음
  - `backend/app/services/notifier.py`

핵심 포인트:
- "짧은 요청 처리"만 하는 앱이 아니라,
- "상태, 스케줄, 외부 연동, 재시도, 운영 관측"이 필요한 서비스다.

---

## 3) 선택지 비교 (직관표)

| 항목 | VPS + Compose + Caddy | Vercel 중심(Serverless) | Render/Railway(PaaS) |
|---|---|---|---|
| 현재 코드 재사용 | 매우 높음 | 낮음(구조 재설계 필요) | 중간(서비스 분리 필요) |
| 스케줄 작업 적합성 | 높음(상시 프로세스) | 낮음~중간(제한 존재) | 높음(Worker/Cron 지원) |
| 운영 난이도 | 중간~높음 | 낮음 | 낮음~중간 |
| 비용 예측성(초기) | 좋음(고정비) | 낮음(호출량/제약 기반) | 중간(플랜 요금) |
| 장애/로그 통제력 | 높음 | 중간 | 중간 |
| 확장 시 설계 자유도 | 높음 | 중간 | 중간 |
| 베타 출시 속도(현 코드 기준) | 가장 빠름 | 느림(리팩터링 필요) | 빠름(설정 작업 필요) |

한 줄 결론:
- 지금 즉시 외부 테스트를 시작하려면 `VPS + Compose + Caddy`가 가장 빠르고 리스크가 낮다.

---

## 4) 왜 Vercel이 "지금 당장" 최적이 아닌가
Vercel이 나쁜 게 아니라, "현재 워크로드와 코드 구조"에 맞지 않는 부분이 있다.

- 현재는 앱 내부 스케줄러 구조다.
  - 서버리스는 기본적으로 요청/트리거 기반 단기 실행에 맞는다.
- 크롤링/알림은 상태 관리, 재시도, 간헐적 실패 복구가 중요하다.
  - 함수형 런타임에서는 워커 분리/큐 도입 등 재설계가 필요해진다.

그래서 현실적인 전략:
- 지금: VPS로 검증 속도 확보
- 이후: 트래픽/매출이 검증되면 워커 분리 + PaaS/매니지드 전환 검토

---

## 5) 이번 프로젝트에 맞는 추천 구성
### 권장 V1 (지인 테스트/베타)
- VPS 1대
- Docker Compose로 `app + db`
- Caddy로 HTTPS 종단
- 일일 백업 + 기본 모니터링

기대효과
- 코드 변경 최소
- 빠른 릴리스
- 디버깅/운영 포인트가 단순
- 비용 예측 쉬움

주의점
- 서버 보안패치/백업/로그 관리는 우리가 책임진다.

---

## 6) 수익화 관점 평가
결론:
- 현재 구조는 "초기 유료화 검증"에 충분히 적합하다.
- 단, 결제/플랜/쿼터/운영관리 계층은 추가해야 한다.

### 가능한 수익화 모델
1. 개인 구독형
- 무료: 관심 단지/알림 횟수 제한
- 유료: 비교 차트, 고급 필터, 빠른 알림, 더 긴 히스토리

2. 전문가형 (중개/실사용자 파워유저)
- 다중 단지 대시보드
- 팀 공유 리포트
- 알림 룰 커스터마이징

3. 데이터 리포트/API
- 익명화/집계 지표 제공
- 주간/월간 보고서 자동 발송

### 수익화 전에 필요한 기술 항목
- 결제/구독: Stripe 등
- 사용량 제한: 플랜별 쿼터, 초과 정책
- 운영: 백업 자동화 + 복구 리허설 + 장애 알림
- 보안: 비밀키 관리, 접근제어, 감사 로그
- 정책: 데이터/개인정보/약관 검토

---

## 7) 의사결정 트리 (빠른 판단용)
아래 3개 질문에 답하면 선택이 쉬워진다.

1. "이번 달 안에 지인 베타를 열어야 하는가?"
- 예: VPS + Compose + Caddy
- 아니오: PaaS 재설계도 고려 가능

2. "서버 운영을 직접 할 인력이 있는가?"
- 예: VPS 지속 가능
- 아니오: Render/Railway 우선 고려

3. "현재 코드 변경을 최소화해야 하는가?"
- 예: VPS 우선
- 아니오: Worker/Cron 분리 후 PaaS/Serverless 하이브리드 고려

---

## 8) 단계별 로드맵 (현실적인 운영 성장)
### 단계 1: 지금 (베타)
- VPS 1대, Compose, Caddy
- 목표: 기능 정확도, 알림 신뢰도, 잔존율 검증

### 단계 2: 유료 베타
- 결제/플랜/쿼터 도입
- 내부 스케줄러를 별도 워커로 분리 (장애 격리)

### 단계 3: 확장
- 앱/워커/DB 분리
- Redis/큐 도입
- 필요시 DB 매니지드 서비스, 일부 PaaS 이전

---

## 9) 최종 결론 (한 문장)
현재 제품 단계에서는 `VPS + Docker Compose + Caddy`가
"개발 속도, 운영 통제, 비용, 기존 코드 재사용"의 균형이 가장 좋다.

이 선택은 최종 고정 아키텍처가 아니라,
"베타 검증 후 분리/확장"을 위한 가장 안전한 출발점이다.

---

## 참고 자료 (공식 문서)
- Vercel Functions Limits: https://vercel.com/docs/functions/limitations
- Vercel Cron Usage/Pricing: https://vercel.com/docs/cron-jobs/usage-and-pricing
- Vercel Cron Accuracy: https://vercel.com/docs/cron-jobs/manage-cron-jobs
- Docker Compose production guidance: https://docs.docker.com/compose/how-tos/production/
- Docker Compose service restart policy: https://docs.docker.com/reference/compose-file/services/
- Caddy reverse proxy quick start: https://caddyserver.com/docs/quick-starts/reverse-proxy
- Caddy automatic HTTPS: https://caddyserver.com/docs/automatic-https
- Render Background Workers: https://render.com/docs/background-workers
- Render Cron Jobs: https://render.com/docs/cronjobs
- Railway Cron Jobs: https://docs.railway.com/guides/cron-jobs
- Railway Services: https://docs.railway.com/reference/services
