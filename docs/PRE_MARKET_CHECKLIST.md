# 모의투자 시작 전 체크리스트 (2025-11-24)

## 오늘 완료한 시스템 점검 (2025-11-24 19:47 KST)

### ✅ 완료된 검증 항목
- [x] 설정 파일 검증 완료
- [x] 시뮬레이터 API 연결 테스트 성공
- [x] .env 설정 확인 (모의투자 설정 완료)
- [x] Golden Cross 전략 파라미터 검토 완료
- [x] Prometheus + Grafana 모니터링 시작됨
- [x] Discord 웹훅 알림 테스트 성공

### 📋 현재 시스템 설정
```
API: https://mockapi.kiwoom.com (키움 모의투자)
거래 모드: 모의투자 (virtual)
계좌: 81153937
초기 자금: 10,000,000원
전략: Golden Cross (5일/20일 MA)
감시 종목: 4개 (005930, 000660, 035420, 051910)
손절: -3% / 익절: +5%
리스크 한도: 일일 손실 5%, 종목당 30%, 총 노출 80%
API 레이트 리밋: 1초당 1회
```

---

## 🌅 내일 장 시작 전 체크리스트 (2025-11-25)

### Phase 1: 사전 준비 (08:30 - 08:50)

#### 1. 시스템 환경 확인
```bash
# 터미널 1: 프로젝트 디렉토리로 이동
cd D:\side-project\auto-trading

# 가상환경 활성화 (필요 시)
# source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate     # Windows

# Python 환경 확인
python --version
```

#### 2. 모니터링 시스템 확인
```bash
# Docker 컨테이너 상태 확인
docker ps --filter "name=auto-trading"

# 만약 중지되어 있다면 재시작
docker-compose -f docker-compose.monitoring.yml up -d
```

- [ ] Grafana 접속 확인: http://localhost:3000 (admin/admin)
- [ ] Prometheus 접속 확인: http://localhost:9091

#### 3. API 연결 테스트 (08:40)
```bash
# 키움 모의투자 API 연결 테스트
python -m src.cli.main test-api --mode live

# 예상 출력:
# [SUCCESS] API connectivity test passed
# - Account balance: 10,000,000 KRW (또는 이전 잔액)
# - Positions: X
```

**✅ 확인 사항:**
- [ ] API 연결 성공
- [ ] 계좌 잔고가 표시됨
- [ ] 오류 메시지 없음

---

### Phase 2: 시스템 시작 (08:50)

#### 4. 로그 모니터링 준비
```bash
# 터미널 2: 로그 실시간 확인 (별도 터미널)
tail -f logs/trading.log
```

#### 5. 자동매매 시스템 시작
```bash
# 터미널 1: 시스템 시작
python -m src.cli.main start --mode live

# 예상 출력:
# [INFO] Starting trading system in live mode...
# [INFO] Kiwoom API client initialized
# [INFO] Strategy engine started
# [INFO] Data collector started
# ...
```

**⏰ 시작 타이밍:**
- 08:50 - 시스템 시작
- 09:00 - 장 개시

**⚠️ 주의:**
- Ctrl+C를 누르면 안전하게 종료됨
- 긴급 중단 필요 시: 터미널 3에서 `python -m src.cli.main emergency-stop`

---

### Phase 3: 장 중 모니터링 (09:00 - 15:30)

#### 6. 모니터링 포인트

**터미널 1 (메인 프로세스):**
- 시스템 정상 실행 여부
- 에러 메시지 확인

**터미널 2 (로그):**
- 실시간 로그 확인
- 주문 생성/체결 로그
- 에러 발생 시 즉시 확인

**Discord 채널:**
- [ ] 시스템 시작 알림 수신 확인
- [ ] 주문 알림 수신 확인
- [ ] 에러 알림 수신 확인

**Grafana 대시보드 (http://localhost:3000):**
- [ ] API 호출 빈도 (1초당 1회 이하)
- [ ] 데이터 수집 상태
- [ ] 전략 신호 생성 여부
- [ ] 리스크 지표 (손실률, 포지션 비중)

#### 7. 주요 체크 타임

**09:00 - 09:10 (장 초반)**
- [ ] 시스템이 정상적으로 데이터 수집 중인지 확인
- [ ] API 호출 오류가 없는지 확인
- [ ] 장 초반 급변동 시 시스템 반응 확인

**11:00 - 11:30**
- [ ] 중간 점검: 로그 확인, 에러 없는지 체크
- [ ] Grafana에서 메트릭 확인

**12:00 - 13:00 (점심시간)**
- [ ] 시스템이 계속 실행 중인지 확인
- [ ] 거래량 감소 시 시스템 동작 확인

**15:00 - 15:20 (장 마감 전)**
- [ ] 시스템 정상 작동 확인
- [ ] 새로운 주문 생성되지 않도록 확인 (15:20 이후)

**15:30 (장 마감)**
- [ ] 시스템이 자동으로 거래를 멈추는지 확인
- [ ] 미체결 주문 확인

---

### Phase 4: 장 마감 후 작업 (15:30 이후)

#### 8. 시스템 안전 종료
```bash
# 터미널 1 또는 별도 터미널에서
python -m src.cli.main stop

# 또는 터미널 1에서 Ctrl+C (안전 종료)
```

#### 9. 모니터링 시스템 종료 (선택)
```bash
# Grafana/Prometheus 중단 (필요 시)
docker-compose -f docker-compose.monitoring.yml down
```

#### 10. 결과 분석

**로그 파일 확인:**
```bash
# 오늘 로그 파일 열기
notepad logs/trading.log  # Windows
# cat logs/trading.log | less  # Linux/Mac
```

**확인 사항:**
- [ ] 총 실행 시간
- [ ] 생성된 주문 수
- [ ] 체결된 주문 수
- [ ] 발생한 에러 수 및 내용
- [ ] API 호출 실패 횟수

**Discord 알림 정리:**
- [ ] 모든 알림 메시지 확인 및 정리
- [ ] 에러 알림이 있었다면 원인 파악

**Grafana 대시보드 분석:**
- [ ] 하루 동안의 API 호출 패턴
- [ ] 데이터 수집 성공률
- [ ] 전략 신호 생성 횟수
- [ ] 시스템 리소스 사용량

#### 11. 문제점 기록

**발견된 문제 (있다면):**
```
1. 문제: _______________
   발생 시간: _______________
   원인: _______________
   해결 방안: _______________

2. 문제: _______________
   발생 시간: _______________
   원인: _______________
   해결 방안: _______________
```

**성능 지표:**
```
- 평균 API 응답 시간: _______ms
- 데이터 수집 성공률: _______%
- 전략 신호 생성 횟수: _______건
- 주문 체결률: _______%
```

---

## 🚨 비상 대응 절차

### 문제 상황별 대응

#### 1. 시스템이 시작되지 않을 때
```bash
# 1) 설정 검증
python -m src.cli.main validate-config

# 2) API 테스트
python -m src.cli.main test-api --mode live

# 3) 로그 확인
tail -n 50 logs/trading.log
```

#### 2. API 연결 오류가 지속될 때
- [ ] 인터넷 연결 확인
- [ ] 키움증권 API 서버 상태 확인
- [ ] API 키/시크릿 재확인 (.env 파일)
- [ ] Rate limit 초과 여부 확인 (1초당 1회)

**대응:**
```bash
# 시스템 중단
python -m src.cli.main emergency-stop

# 5분 대기 후 재시작
python -m src.cli.main start --mode live
```

#### 3. 예상치 못한 주문이 발생할 때
```bash
# 즉시 시스템 중단
python -m src.cli.main emergency-stop

# 또는 터미널에서 Ctrl+C
```

**확인 사항:**
- [ ] 로그에서 주문 생성 원인 확인
- [ ] 전략 로직 재검토
- [ ] 리스크 관리 설정 재확인

#### 4. 손실이 한도에 근접할 때 (4% 이상)
- [ ] Discord에서 손실 경고 알림 확인
- [ ] Grafana에서 리스크 지표 확인
- [ ] 필요 시 수동 개입 고려

**5% 손실 도달 시:**
- 시스템이 자동으로 거래 중단함
- 로그에 "Daily loss limit reached" 메시지 표시

#### 5. 시스템이 응답하지 않을 때
```bash
# 프로세스 확인
ps aux | grep python

# 강제 종료 (최후 수단)
python -m src.cli.main emergency-stop
```

---

## 📊 성공 기준

### 첫날 목표 (학습 위주)
- [ ] 시스템이 장 시간 동안 중단 없이 실행됨
- [ ] API 호출이 안정적으로 이루어짐
- [ ] 최소 1개 이상의 전략 신호 생성
- [ ] 로그에 치명적 에러가 없음

### 수익/손실은 목표가 아님
- 모의투자이므로 실제 손익보다 **시스템 안정성**이 중요
- 손실이 발생해도 괜찮음 → 문제점 파악이 목적
- 첫날은 관찰과 학습에 집중

---

## 📝 다음 날 개선 계획

**오늘 결과를 바탕으로 결정:**
1. [ ] 시스템이 안정적이었다면 → 며칠 더 모의투자 지속
2. [ ] 문제가 발견되었다면 → 우선순위 높은 문제부터 수정
3. [ ] 전략 성능이 부족하다면 → 전략 파라미터 조정 고려

**개선 후보:**
- API 폴링 간격 조정
- 전략 파라미터 최적화 (MA 기간, 손절/익절 비율)
- 리스크 관리 설정 조정
- 감시 종목 추가/제거
- 로깅 상세도 조정

---

## 🎯 최종 체크

**오늘 밤 (2025-11-24) 확인:**
- [ ] 이 체크리스트를 읽고 이해했음
- [ ] Discord에 테스트 알림이 왔는지 확인
- [ ] Grafana 대시보드에 접속 가능한지 확인
- [ ] 터미널을 3개 열어둘 준비 (메인, 로그, 예비)
- [ ] 긴급 상황 대응 절차 숙지

**내일 아침 (2025-11-25) 08:30:**
- [ ] 커피 한 잔 준비 ☕
- [ ] 체크리스트 출력 또는 별도 모니터에 표시
- [ ] 타이머 설정 (09:00 장 시작 알림)
- [ ] 편안한 자세로 모니터링 준비

---

## 📞 연락처 및 참고 자료

**키움증권 고객센터:** 1544-9000
**키움 OpenAPI 공식 문서:** https://apiportal.kiwoom.com

**프로젝트 문서:**
- 메인 README: `README.md`
- 개발 가이드: `CLAUDE.md`
- 설정 파일: `.env`

**유용한 명령어 요약:**
```bash
# 시스템 시작
python -m src.cli.main start --mode live

# 상태 확인
python -m src.cli.main status

# 안전 종료
python -m src.cli.main stop

# 긴급 중단
python -m src.cli.main emergency-stop

# 로그 확인
tail -f logs/trading.log

# Docker 상태
docker ps
```

---

## ✨ 격려의 말

**첫 실전 테스트를 축하합니다!**

7개 Phase를 거쳐 만든 시스템이 드디어 실제 시장에서 작동하게 됩니다. 비록 모의투자지만, 이것은 매우 중요한 순간입니다.

**기억하세요:**
- 완벽한 시스템은 없습니다. 문제가 생기는 것이 정상입니다.
- 오늘의 목표는 수익이 아니라 학습입니다.
- 실패는 개선의 기회입니다.
- 천천히, 신중하게, 단계별로 진행하세요.

**행운을 빕니다! 🍀**

---

*Last updated: 2025-11-24 19:55 KST*
*Next review: 2025-11-25 16:00 KST (장 마감 후)*
