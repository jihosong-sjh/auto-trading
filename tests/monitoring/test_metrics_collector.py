"""Tests for MetricsCollector.

Phase 7: Performance Monitoring
"""

import pytest

from src.monitoring.metrics_collector import MetricsCollector


@pytest.fixture
def collector():
    """Create MetricsCollector instance."""
    return MetricsCollector()


@pytest.mark.unit
def test_collector_initialization(collector):
    """Test MetricsCollector initialization."""
    assert collector is not None
    summary = collector.get_metrics_summary()
    assert "enabled" in summary


@pytest.mark.unit
def test_record_api_request(collector):
    """Test recording API requests."""
    collector.record_api_request("kiwoom")
    collector.record_api_request("kiwoom")
    collector.record_api_request("kiwoom")

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        # Simulated metrics
        assert collector.simulated_metrics["api_requests_kiwoom"] == 3


@pytest.mark.unit
def test_set_api_queue_size(collector):
    """Test setting API queue size."""
    collector.set_api_queue_size("kiwoom", 42)

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["api_queue_size_kiwoom"] == 42.0


@pytest.mark.unit
def test_record_api_wait_time(collector):
    """Test recording API wait time."""
    collector.record_api_wait_time("kiwoom", 1.5)

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["api_wait_time_kiwoom"] == 1.5


@pytest.mark.unit
def test_set_pipeline_metrics(collector):
    """Test setting pipeline metrics."""
    collector.set_pipeline_throughput(15.5)
    collector.set_pipeline_latency(0.5)
    collector.set_pipeline_success_rate(0.95)
    collector.set_pipeline_queue_depth(50)
    collector.set_pipeline_active_workers(4)
    collector.set_pipeline_batch_size(5.0)

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["pipeline_throughput"] == 15.5
        assert collector.simulated_metrics["pipeline_latency"] == 0.5
        assert collector.simulated_metrics["pipeline_success_rate"] == 0.95
        assert collector.simulated_metrics["pipeline_queue_depth"] == 50.0
        assert collector.simulated_metrics["pipeline_active_workers"] == 4.0
        assert collector.simulated_metrics["pipeline_batch_size"] == 5.0


@pytest.mark.unit
def test_record_pipeline_order(collector):
    """Test recording pipeline order."""
    collector.record_pipeline_order("success")
    collector.record_pipeline_order("success")
    collector.record_pipeline_order("failure")

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["pipeline_orders_success"] == 2
        assert collector.simulated_metrics["pipeline_orders_failure"] == 1


@pytest.mark.unit
def test_record_stop_loss_trigger(collector):
    """Test recording stop-loss triggers."""
    collector.record_stop_loss_trigger("005930")
    collector.record_stop_loss_trigger("005930")

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["stop_loss_005930"] == 2


@pytest.mark.unit
def test_record_take_profit_trigger(collector):
    """Test recording take-profit triggers."""
    collector.record_take_profit_trigger("005930")

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["take_profit_005930"] == 1


@pytest.mark.unit
def test_set_risk_metrics(collector):
    """Test setting risk metrics."""
    collector.set_daily_loss_ratio(0.015)
    collector.set_position_concentration("005930", 0.25)

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["daily_loss_ratio"] == 0.015
        assert collector.simulated_metrics["position_concentration_005930"] == 0.25


@pytest.mark.unit
def test_record_minute_bar(collector):
    """Test recording minute bar collection."""
    collector.record_minute_bar_collected("005930")
    collector.record_minute_bar_collected("005930")
    collector.record_minute_bar_collected("035720")

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["minute_bars_005930"] == 2
        assert collector.simulated_metrics["minute_bars_035720"] == 1


@pytest.mark.unit
def test_set_cache_metrics(collector):
    """Test setting cache metrics."""
    collector.set_cache_hit_ratio(0.85)
    collector.set_cache_size(500)

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["cache_hit_ratio"] == 0.85
        assert collector.simulated_metrics["cache_size"] == 500.0


@pytest.mark.unit
def test_record_event_stored(collector):
    """Test recording event storage."""
    collector.record_event_stored("OrderPlaced")
    collector.record_event_stored("OrderPlaced")
    collector.record_event_stored("OrderFilled")

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["events_stored_OrderPlaced"] == 2
        assert collector.simulated_metrics["events_stored_OrderFilled"] == 1


@pytest.mark.unit
def test_record_event_store_latency(collector):
    """Test recording event store latency."""
    collector.record_event_store_latency("write", 0.005)

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["event_latency_write"] == 0.005


@pytest.mark.unit
def test_record_strategy_signal(collector):
    """Test recording strategy signals."""
    collector.record_strategy_signal("golden_cross", "buy")
    collector.record_strategy_signal("golden_cross", "buy")
    collector.record_strategy_signal("golden_cross", "sell")

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["strategy_golden_cross_buy"] == 2
        assert collector.simulated_metrics["strategy_golden_cross_sell"] == 1


@pytest.mark.unit
def test_set_strategy_win_rate(collector):
    """Test setting strategy win rate."""
    collector.set_strategy_win_rate("golden_cross", 0.65)

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["win_rate_golden_cross"] == 0.65


@pytest.mark.unit
def test_set_system_metrics(collector):
    """Test setting system metrics."""
    collector.set_system_cpu_usage(45.5)
    collector.set_system_memory_usage(512.0)
    collector.set_system_disk_usage(70.0)

    summary = collector.get_metrics_summary()
    if not summary["enabled"]:
        assert collector.simulated_metrics["system_cpu_usage"] == 45.5
        assert collector.simulated_metrics["system_memory_usage"] == 512.0
        assert collector.simulated_metrics["system_disk_usage"] == 70.0


@pytest.mark.unit
def test_export_metrics(collector):
    """Test exporting metrics."""
    collector.record_api_request("kiwoom")
    collector.set_pipeline_throughput(10.0)

    metrics_data = collector.export_metrics()
    assert isinstance(metrics_data, bytes)
    assert len(metrics_data) > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_collect_system_metrics(collector):
    """Test collecting system metrics."""
    await collector.collect_system_metrics()

    summary = collector.get_metrics_summary()
    # System metrics should be collected (or simulated)
    assert summary is not None
