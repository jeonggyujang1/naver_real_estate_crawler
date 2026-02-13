# Naver Apt Briefing 웹 UI 기능 가이드

이 문서는 **현재 대시보드 UI에서 실제 동작하는 기능**과 **사용 방법**을 빠르게 확인하기 위한 가이드입니다.

대상 화면:
- `http://127.0.0.1:18080/`

---

## 1) 시작 전 체크
1. 컨테이너 상태 확인
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
docker compose ps
```

2. 헬스 체크
```bash
curl http://127.0.0.1:18080/health
```

3. 핵심 환경 변수 확인 (`.env`)
- `NAVER_LAND_AUTHORIZATION`
- `NAVER_LAND_COOKIE`
- (권장) `CRAWLER_MAX_RETRY=1`

---

## 2) UI 기능별 사용법

## 2-1) 계정
버튼:
- `회원가입`
- `로그인`
- `내 정보`
- `로그아웃`

사용 순서:
1. 이메일/비밀번호 입력 후 `회원가입`
2. `로그인`
3. `내 정보`로 계정 확인
4. 필요 시 `로그아웃`

기대 결과:
- 상단 배지에 로그인 상태 표시
- 로그아웃 후 토큰 폐기 처리

---

## 2-2) 관심 단지 등록
버튼/입력:
- `단지명 검색`
- `URL에서 번호 추출`
- `등록`
- `목록 조회`
- `실시간 매물 조회`

사용 순서 A(검색 기반):
1. `단지명 검색` 입력란에 예: `래미안`
2. 검색 결과 클릭
3. `complex_no`, 단지명 자동 채움 확인
4. `등록`
5. `목록 조회`

사용 순서 B(URL 기반):
1. 네이버 단지 URL 붙여넣기 (예: `.../complexes/2977?...`)
2. `URL에서 번호 추출`
3. `등록`

실시간 조회:
1. `page`, `단지당 최대 매물 수` 설정
2. `실시간 매물 조회`

---

## 2-3) 수동 수집
버튼:
- `지금 수집`
- `메타 확인`

사용 순서:
1. `complex_no` 입력 (예: `2977`)
2. `지금 수집`
3. 상태 메시지에서 `run`, `count` 확인

---

## 2-4) 요금제 / 더미 결제
버튼:
- `내 플랜 조회`
- `PRO 결제 시작(더미)`
- `결제 완료 처리`

사용 순서:
1. 로그인 상태에서 `내 플랜 조회`
2. `PRO 결제 시작(더미)` 클릭
3. 자동 채워진 `checkout_token` 확인
4. `결제 완료 처리` 클릭
5. `플랜: PRO` 배지 확인

설명:
- 현재 결제는 실제 PG가 아닌 **더미 결제 플로우**입니다.
- 기능 게이팅 검증 목적입니다.

---

## 2-5) 알림 채널 설정 (이메일/텔레그램)
버튼:
- `설정 조회`
- `설정 저장`
- `지금 알림 발송`

사용 순서:
1. 이메일/텔레그램 정보 입력
2. 채널 체크박스 활성화
3. `설정 저장`
4. `지금 알림 발송`으로 즉시 테스트

주의:
- 무료 플랜은 `지금 알림 발송`이 제한됩니다.
- PRO 활성화 후 테스트하세요.

---

## 2-6) 차트/분석
기능:
- 단지 시세 추세
- 선택 단지 비교
- 급매 후보 탐지

사용 순서:
1. 추세: `complex_no`, `days` 입력 후 조회
2. 비교: `complex_no` 2개 이상 콤마로 입력 후 조회
3. 급매: `complex_no`, 기간, 임계값 입력 후 조회

---

## 3) FREE vs PRO 기능 차이 (현재 구현 기준)
- 관심 단지 등록
  - FREE: 최대 3개
  - PRO: 제한 없음
- 프리셋 저장
  - FREE: 최대 3개
  - PRO: 제한 없음
- 비교 차트 단지 수
  - FREE: 최대 2개
  - PRO: 제한 없음
- 수동 급매 알림 발송 (`지금 알림 발송`)
  - FREE: 불가
  - PRO: 가능

---

## 4) 텔레그램 연동 가이드 (초보자용)

## 4-1) 텔레그램 봇 만들기
1. 텔레그램 앱에서 `@BotFather` 검색
2. `/newbot` 입력
3. 봇 이름/아이디 설정
4. 발급된 Bot Token 복사

예시 토큰 형태:
- `123456789:AA...`

## 4-2) chat_id 확인
1. 만든 봇 채팅방 열기
2. `/start` 한 번 전송
3. 브라우저에서 아래 URL 호출
```text
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
```
4. 응답 JSON의 `message.chat.id` 값 복사

## 4-3) `.env` 설정
경로:
- `/Users/jeonggyu/workspace/naver_apt_briefing/backend/.env`

아래 값 설정:
```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<YOUR_BOT_TOKEN>
TELEGRAM_API_BASE_URL=https://api.telegram.org
```

적용:
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
docker compose up -d --force-recreate app worker
```

## 4-4) 대시보드에서 활성화
1. 로그인
2. `알림 채널 설정` 섹션 이동
3. `텔레그램 chat_id` 입력
4. `텔레그램 사용` 체크
5. `설정 저장`
6. (PRO 플랜에서) `지금 알림 발송`

## 4-5) 연동 문제 해결
1. 발송 실패 시 로그 확인
```bash
cd /Users/jeonggyu/workspace/naver_apt_briefing/backend
docker compose logs --tail=200 app
```

2. 자주 발생하는 원인
- Bot Token 오입력
- chat_id 오입력
- 봇과 대화 시작(`/start`) 미실행
- FREE 플랜 상태에서 수동 발송 시도

---

## 5) 빠른 검증 시나리오 (5분)
1. 회원가입/로그인
2. `내 플랜 조회` -> FREE 확인
3. `PRO 결제 시작(더미)` -> `결제 완료 처리` -> PRO 확인
4. 단지 검색 후 관심 단지 등록
5. 텔레그램 설정 저장 후 `지금 알림 발송`
