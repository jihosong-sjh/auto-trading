# 키움 자동매매 실전 사용 가이드

## 목차
1. [사전 준비](#사전-준비)
2. [빠른 시작](#빠른-시작)
3. [실전 운영 (모의투자)](#실전-운영-모의투자)
4. [모니터링 및 관리](#모니터링-및-관리)
5. [주의사항](#주의사항)

---

## 사전 준비

### 1. 환경 확인
```bash
# Python 버전 확인 (3.10 이상 필요)
python --version

# 의존성 설치
pip install -r requirements.txt
```

### 2. 설정 확인
현재 `.env` 파일에 다음 정보가 설정되어 있는지 확인하세요:

```bash
# .env 파일 내용 확인
cat .env | grep -E "KIWOOM_API_KEY|KIWOOM_ACCOUNT_NUMBER|SIMULATOR_INITIAL_BALANCE"
```

중요한 설정:
- `KIWOOM_API_KEY`: 키움증권 모의투자 API 키
- `KIWOOM_API_SECRET`: 키움증권 모의투자 API 시크릿
- `KIWOOM_ACCOUNT_NUMBER`: 모의투자 계좌번호
- `SIMULATOR_INITIAL_BALANCE`: 시뮬레이터 초기 자금 (기본: 1,000,000원)

---

## 빠른 시작

### 1. API 연결 테스트
실제 거래 전에 API 연결을 테스트하세요:

```bash
# 시뮬레이터 모드 테스트 (메모리에서만 작동, 실제 API 호출 없음)
python -m src.cli.main test-api --mode simulator

# 실제 API 연결 테스트 (모의투자 계좌)
python -m src.cli.main test-api --mode live
```

예상 출력:
```
[SUCCESS] API client initialized successfully
  - Account balance: 1,000,000 KRW
  - Positions: 0
[SUCCESS] API connectivity test passed
```

### 2. 설정 검증
시스템 설정이 올바른지 검증:

```bash
python -m src.cli.main validate-config
```

예상 출력:
```
[SUCCESS] Configuration is valid
  - Kiwoom API configured: True
  - Initial balance: 10,000,000 KRW
  - Strategies defined: 1
  - Watch symbols: 4
```

---

## 실전 운영 (모의투자)

### 1. 시뮬레이터 모드로 시작 (권장)
실제 API를 사용하지 않고 메모리에서만 작동합니다. 로직 테스트용:

```bash
python -m src.cli.main start --mode simulator
```

이 모드는:
- 실제 API 호출 없음
- 메모리에서 가상 거래 시뮬레이션
- 로직 검증 및 전략 테스트용

### 2. 실전 모드로 시작 (모의투자 계좌)
**내일 평일 장시간에 사용할 모드입니다:**

```bash
python -m src.cli.main start --mode live
```

이 모드는:
- 실제 키움 모의투자 API 사용
- 실시간 시세 데이터 수집
- 실제 주문 전송 (모의투자 계좌)
- 전략에 따른 자동 매매 실행

### 3. 백그라운드 실행 (추천)
터미널을 닫아도 계속 실행되도록:

**Windows:**
```powershell
# PowerShell에서
Start-Process python -ArgumentList "-m", "src.cli.main", "start", "--mode", "live" -NoNewWindow -RedirectStandardOutput logs\trading.log -RedirectStandardError logs\trading.error.log
```

**Linux/Mac:**
```bash
nohup python -m src.cli.main start --mode live > logs/trading.log 2>&1 &
```

---

## 모니터링 및 관리

### 1. 시스템 상태 확인
```bash
python -m src.cli.main status
```

예상 출력:
```
[STATUS] Trading system is RUNNING
  - PID: 12345
  - PID file: logs/trading_system.pid
```

### 2. 로그 확인
실시간으로 로그를 모니터링:

```bash
# Windows
Get-Content logs\trading.log -Wait

# Linux/Mac
tail -f logs/trading.log
```

주요 로그 내용:
- 시스템 시작/종료
- 전략 신호 발생
- 주문 실행 결과
- API 에러 및 재시도

### 3. 안전한 종료
```bash
# 정상 종료 (진행 중인 주문 완료 후 종료)
python -m src.cli.main stop

# 긴급 종료 (즉시 종료, 비상시에만 사용)
python -m src.cli.main emergency-stop
```

---

## 주의사항

### 운영 시간
- **한국 주식시장**: 평일 09:00 - 15:30 (KST)
- 장 시작 전에 시스템을 켜두세요 (08:50 권장)
- 장 마감 10분 전부터는 신규 매수 차단됨

### 전략 설정
현재 기본으로 **골든크로스 전략**이 활성화되어 있습니다:
- 5일 이동평균선이 20일 이동평균선을 상향 돌파하면 매수
- 5일 이동평균선이 20일 이동평균선을 하향 돌파하면 매도
- 한 번에 예수금의 20% 사용

감시 종목:
- 005930 (삼성전자)
- 000660 (SK하이닉스)
- 035420 (NAVER)
- 051910 (LG화학)

### 위험 관리
`.env` 파일에서 설정된 안전장치:
- **일일 손실 한도**: 5% (RISK_DAILY_LOSS_LIMIT=0.05)
- **종목별 최대 비중**: 30% (RISK_MAX_POSITION_CONCENTRATION=0.30)
- **최대 투자 비율**: 80% (RISK_MAX_EXPOSURE_RATIO=0.80)

### 알림 설정 (선택사항)
Discord 웹훅을 설정하면 주요 이벤트를 받을 수 있습니다:

1. Discord에서 웹훅 URL 생성
2. `.env` 파일의 `DISCORD_WEBHOOK_URL` 업데이트
3. 시스템 재시작

---

## 문제 해결

### API 연결 실패
```bash
# 에러 로그 확인
cat logs/trading.log | grep ERROR

# API 연결 재테스트
python -m src.cli.main test-api --mode live
```

### 시스템이 응답하지 않음
```bash
# 강제 종료
python -m src.cli.main emergency-stop

# 로그 확인
cat logs/trading.log
```

### 예상치 못한 주문 발생
1. 즉시 시스템 종료: `python -m src.cli.main stop`
2. 키움 HTS에서 미체결 주문 취소
3. 로그 확인 및 전략 검토

---

## 다음 단계

### 백테스팅 (과거 데이터로 전략 성능 검증)
```bash
python -m src.cli.main backtest \
  --strategy golden_cross \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --initial-balance 10000000
```

참고: 현재 백테스팅은 과거 데이터 로딩이 구현되지 않았습니다.

### 커스텀 전략 추가
1. `src/strategies/` 디렉토리에 새 전략 파일 생성
2. `BaseStrategy` 클래스 상속
3. `config/config.yaml` 생성 및 전략 등록

---

## 실전 체크리스트

내일 주식시장 시작 전:
- [ ] API 연결 테스트 완료
- [ ] 설정 검증 완료
- [ ] 로그 디렉토리 준비 (`logs/` 존재 확인)
- [ ] 시스템 시작 (08:50)
- [ ] 로그 모니터링 시작
- [ ] 첫 신호 발생 시 주문 확인

장 중:
- [ ] 주기적으로 상태 확인 (1시간마다)
- [ ] 예상치 못한 주문 없는지 확인

장 마감 후:
- [ ] 시스템 정상 종료
- [ ] 금일 거래 내역 확인
- [ ] 로그 검토

---

## 지원

문제가 발생하면:
1. `logs/trading.log` 확인
2. GitHub Issues에 로그와 함께 문의
3. 긴급 시 시스템 즉시 종료

**투자 책임**: 모든 투자 결과에 대한 책임은 사용자에게 있습니다.
