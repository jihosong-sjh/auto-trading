# Phase 7: Performance Monitoring

Prometheus + Grafana를 사용한 자동매매 시스템 성능 모니터링 및 자동 튜닝 시스템입니다.

## 주요 기능

### 1. Prometheus Metrics Collection
- **API Rate Limiter**: 요청 수, 대기 시간, 큐 크기
- **Order Pipeline**: 처리량, 지연시간, 성공률, 큐 깊이, 워커 수
- **Risk Manager**: 손절/익절 트리거, 일일 손실률, 포지션 집중도
- **Data Pipeline**: 분봉 수집, 캐시 히트율, 캐시 크기
- **Event Sourcing**: 이벤트 수, 저장 지연시간
- **Strategy**: 전략별 신호 생성, 승률
- **System**: CPU, Memory, Disk 사용률

### 2. Grafana Dashboard
- 17개 패널로 구성된 통합 대시보드
- 실시간 메트릭 시각화
- 임계값 기반 알림 시각화
- 10초 자동 리프레시

### 3. Auto Performance Tuning
- 실시간 메트릭 분석
- 규칙 기반 자동 튜닝
  - Pipeline 모드 자동 전환 (SEQUENTIAL → PARALLEL → BATCH → OPTIMIZED)
  - Worker Pool 자동 스케일링 (Scale Up/Down)
  - Batch 크기 자동 조정
- 튜닝 히스토리 추적

## 설치

### 1. Python 패키지 설치

```bash
pip install prometheus-client aiohttp psutil
```

### 2. Docker 설치 (Prometheus + Grafana)

```bash
# Docker 설치 확인
docker --version
docker-compose --version

# Monitoring 스택 시작
docker-compose -f docker-compose.monitoring.yml up -d
```

## 사용법

### 1. Metrics Collector 통합

```python
from src.monitoring.metrics_collector import MetricsCollector
from src.monitoring.prometheus_exporter import PrometheusExporter

# 메트릭 수집기 초기화
collector = MetricsCollector()

# HTTP Exporter 시작
exporter = PrometheusExporter(collector, host="0.0.0.0", port=9090)
await exporter.start()

# 메트릭 기록
collector.record_api_request("kiwoom")
collector.set_pipeline_throughput(15.5)
collector.record_stop_loss_trigger("005930")
```

### 2. Auto Tuning 활성화

```python
from src.monitoring.performance_tuner import PerformanceTuner

# Auto-Tuner 초기화
tuner = PerformanceTuner(
    metrics_collector=collector,
    pipeline=pipeline,
    check_interval=30.0  # 30초마다 체크
)

# 자동 튜닝 시작
await tuner.start()

# ... 시스템 운영 ...

# 튜닝 종료
await tuner.stop()

# 튜닝 요약
summary = tuner.get_tuning_summary()
print(f"Total actions: {summary['total_actions']}")
```

### 3. 데모 실행

```bash
# 메트릭 시뮬레이션 + Auto-Tuning 데모
python examples/monitoring_demo.py
```

## 접속 정보

### Prometheus
- **URL**: http://localhost:9091
- **Metrics Endpoint**: http://localhost:9090/metrics
- **Health Check**: http://localhost:9090/health

### Grafana
- **URL**: http://localhost:3000
- **Username**: `admin`
- **Password**: `admin`
- **Dashboard**: Auto-Trading Performance Dashboard

## 디렉토리 구조

```
monitoring/
├── prometheus.yml                      # Prometheus 설정
├── grafana/
│   └── provisioning/
│       ├── datasources/
│       │   └── prometheus.yml          # Datasource 자동 프로비저닝
│       └── dashboards/
│           ├── dashboard.yml           # Dashboard 프로비저닝 설정
│           └── auto-trading-dashboard.json  # 대시보드 정의
└── README.md

src/monitoring/
├── __init__.py
├── metrics_collector.py                # 메트릭 수집기
├── prometheus_exporter.py              # HTTP Exporter
└── performance_tuner.py                # 자동 튜닝 시스템

examples/
└── monitoring_demo.py                  # 통합 데모
```

## 메트릭 목록

### Counters (누적 카운터)
- `api_requests_total{api_type}`: API 총 요청 수
- `pipeline_orders_processed_total{status}`: 파이프라인 처리 주문 수
- `risk_stop_loss_triggered_total{stock_code}`: 손절 트리거 수
- `risk_take_profit_triggered_total{stock_code}`: 익절 트리거 수
- `data_minute_bars_collected_total{stock_code}`: 분봉 수집 수
- `events_stored_total{event_type}`: 저장된 이벤트 수
- `strategy_signals_total{strategy_name,signal_type}`: 전략 신호 수

### Gauges (현재 값)
- `pipeline_throughput_per_second`: 파이프라인 처리량 (orders/sec)
- `pipeline_average_latency_seconds`: 평균 지연시간
- `pipeline_success_rate`: 성공률 (0-1)
- `pipeline_queue_depth`: 큐 깊이
- `pipeline_active_workers`: 활성 워커 수
- `pipeline_batch_size`: 평균 배치 크기
- `api_queue_size{api_type}`: API 큐 크기
- `risk_daily_loss_ratio`: 일일 손실률 (0-1)
- `risk_position_concentration{stock_code}`: 포지션 집중도 (0-1)
- `data_cache_hit_ratio`: 캐시 히트율 (0-1)
- `data_cache_size`: 캐시 크기
- `strategy_win_rate{strategy_name}`: 전략 승률 (0-1)
- `system_cpu_usage_percent`: CPU 사용률 (%)
- `system_memory_usage_mb`: 메모리 사용량 (MB)
- `system_disk_usage_percent`: 디스크 사용률 (%)

### Histograms (분포)
- `api_wait_time_seconds{api_type}`: API 대기 시간 분포
- `event_store_latency_seconds{operation}`: 이벤트 저장 지연시간 분포

## Auto-Tuning 규칙

### 1. low_throughput_to_parallel
- **조건**: 처리량 < 5 orders/sec AND 모드 = SEQUENTIAL
- **액션**: PARALLEL 모드로 전환
- **쿨다운**: 120초

### 2. high_queue_to_batch
- **조건**: 큐 깊이 > 100 AND 모드 != BATCH
- **액션**: BATCH 모드로 전환
- **쿨다운**: 120초

### 3. high_latency_to_optimized
- **조건**: 평균 지연시간 > 2초 AND 모드 != OPTIMIZED
- **액션**: OPTIMIZED 모드로 전환
- **쿨다운**: 120초

### 4. scale_up_workers
- **조건**: 큐 깊이 > 50 AND 활성 워커 = 최대 워커
- **액션**: 최대 워커 수 +2 (최대 20)
- **쿨다운**: 180초

### 5. scale_down_workers
- **조건**: 큐 깊이 < 10 AND 활성 워커 < 최대 워커 * 0.3
- **액션**: 최대 워커 수 -1 (최소 2)
- **쿨다운**: 180초

### 6. increase_batch_size
- **조건**: 배치 크기 < 최대 배치 크기 * 0.5
- **액션**: 배치 타임아웃 +0.5초 (최대 5초)
- **쿨다운**: 90초

## 트러블슈팅

### Prometheus 메트릭이 수집되지 않음
1. Exporter가 실행 중인지 확인: `curl http://localhost:9090/metrics`
2. Prometheus 설정 확인: `monitoring/prometheus.yml`
3. Docker 네트워크 확인: `docker network inspect auto-trading_monitoring`

### Grafana 대시보드가 비어있음
1. Datasource 연결 확인: Grafana > Configuration > Data Sources
2. Prometheus URL 확인: `http://prometheus:9091`
3. 대시보드 재로드: Grafana > Dashboards > Auto-Trading Performance Dashboard

### Auto-Tuning이 작동하지 않음
1. Pipeline이 설정되었는지 확인
2. 메트릭이 수집되고 있는지 확인
3. 로그에서 튜닝 액션 확인: `[AUTO-TUNE]` 로그 검색

## 모니터링 베스트 프랙티스

### 1. 메트릭 수집 위치
```python
# API 호출 시
collector.record_api_request("kiwoom")

# Order Pipeline 처리 후
collector.set_pipeline_throughput(throughput)
collector.record_pipeline_order("success")

# Risk 이벤트 발생 시
collector.record_stop_loss_trigger(stock_code)
```

### 2. 정기적인 시스템 메트릭 수집
```python
# 매 10초마다 시스템 메트릭 수집
async def system_metrics_loop():
    while True:
        await collector.collect_system_metrics()
        await asyncio.sleep(10)
```

### 3. 대시보드 모니터링 주요 지표
- **처리량**: 15+ orders/sec (정상)
- **지연시간**: < 1초 (양호), < 2초 (경고)
- **성공률**: > 95% (정상)
- **큐 깊이**: < 50 (정상), < 100 (경고), > 100 (위험)
- **일일 손실률**: < 1.6% (경고), < 2% (위험)

## 확장

### 커스텀 메트릭 추가
```python
# metrics_collector.py에 메트릭 추가
self.gauges["custom_metric"] = Gauge(
    "custom_metric",
    "Custom metric description",
    ["label1", "label2"],
    registry=self.registry,
)

# 메트릭 기록
def record_custom_metric(self, label1: str, label2: str, value: float):
    if self.enabled:
        self.gauges["custom_metric"].labels(
            label1=label1, label2=label2
        ).set(value)
```

### 커스텀 튜닝 규칙 추가
```python
# performance_tuner.py의 _initialize_rules()에 규칙 추가
TuningRule(
    name="custom_rule",
    condition="조건 설명",
    action="액션 설명",
    cooldown_seconds=120,
)

# _check_and_tune()에 규칙 로직 추가
if rule.name == "custom_rule":
    if <조건>:
        should_execute = True
        action_description = "액션 설명"
```

## 참고 자료

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Prometheus Python Client](https://github.com/prometheus/client_python)
- [PromQL 쿼리 언어](https://prometheus.io/docs/prometheus/latest/querying/basics/)

## 라이선스

MIT License
