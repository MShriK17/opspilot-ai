from opspilot.detection.detectors import (
    error_rate_signal, latency_signal, memory_signal, robust_baseline,
)

HEALTHY = robust_baseline([0.0, 0.0, 0.001, 0.0, 0.002])
LAT = robust_baseline([85.0, 88.0, 82.0, 90.0, 84.0])


def test_baseline_needs_history():
    assert robust_baseline([0.1, 0.2]) is None
    med, sigma = robust_baseline([1, 2, 3, 4, 100])
    assert med == 3 and sigma > 0       # one outlier does not move the median


def test_normal_traffic_is_quiet():
    assert error_rate_signal(300, 0, HEALTHY) is None
    assert error_rate_signal(300, 3, HEALTHY) is None        # below minimum error count
    assert error_rate_signal(300, 9, HEALTHY) is None        # 3% is under the 5% floor


def test_error_rate_severity_levels():
    assert error_rate_signal(300, 15, HEALTHY).severity == "SEV3"
    assert error_rate_signal(300, 63, HEALTHY).severity == "SEV2"   # 21%, like bad_deploy
    assert error_rate_signal(300, 213, HEALTHY).severity == "SEV1"  # 71%, like bad_env_var


def test_error_rate_works_without_baseline():
    assert error_rate_signal(300, 63, None).severity == "SEV2"


def test_too_few_requests_is_ignored():
    assert error_rate_signal(10, 8, HEALTHY) is None


def test_latency_needs_baseline_and_volume():
    assert latency_signal(300, 3000, None) is None
    assert latency_signal(5, 3000, LAT) is None


def test_latency_spike_detected_and_normal_is_not():
    assert latency_signal(300, 95, LAT) is None
    assert latency_signal(300, 200, LAT) is None            # under the 250 ms floor
    assert latency_signal(300, 600, LAT).severity == "SEV3"
    assert latency_signal(300, 3000, LAT).severity == "SEV2"


def test_memory_growth():
    base = [80.0] * 10
    assert memory_signal(85.0, base) is None
    assert memory_signal(130.0, base).detector == "memory_growth"
    assert memory_signal(130.0, [80.0] * 3) is None          # not enough history
    assert memory_signal(None, base) is None
