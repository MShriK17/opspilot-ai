from opspilot.ingestion.collector import parse_log_line

GOOD = (
    '{"ts": "2026-10-18T10:00:00.123456+00:00", "level": "ERROR", "service": "target-app", '
    '"version": "v2.0.0", "message": "TypeError: boom", "trace_id": "abc", '
    '"attributes": {"path": "/checkout", "status": 500}}'
)


def test_parses_valid_line():
    row = parse_log_line(GOOD)
    assert row["service"] == "target-app"
    assert row["level"] == "ERROR"
    assert row["trace_id"] == "abc"
    assert row["attributes"]["path"] == "/checkout"
    assert row["attributes"]["version"] == "v2.0.0"
    assert row["ts"].tzinfo is not None


def test_line_without_trace_or_attributes():
    row = parse_log_line(
        '{"ts": "2026-10-18T10:00:00+00:00", "level": "INFO", "service": "s", "version": "v1", "message": "hi"}'
    )
    assert row["trace_id"] is None


def test_rejects_garbage():
    assert parse_log_line("not json") is None
    assert parse_log_line('{"level": "INFO"}') is None
