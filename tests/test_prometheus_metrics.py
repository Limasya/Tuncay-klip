"""
Tests for the Prometheus /metrics endpoint.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app, raise_server_exceptions=False)


class TestPrometheusMetrics:
    def test_metrics_endpoint_returns_200(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type(self, client):
        resp = client.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_metrics_contains_pipeline_gauge(self, client):
        resp = client.get("/metrics")
        assert "klip_pipeline_running" in resp.text

    def test_metrics_contains_event_bus_counters(self, client):
        resp = client.get("/metrics")
        text = resp.text
        assert "klip_events_published_total" in text
        assert "klip_events_dispatched_total" in text
        assert "klip_events_failed_total" in text
        assert "klip_events_dlq_total" in text

    def test_metrics_contains_detector_metrics(self, client):
        resp = client.get("/metrics")
        text = resp.text
        assert "klip_detector_current_score" in text
        assert "klip_detector_events_processed_total" in text

    def test_metrics_contains_decision_engine_metrics(self, client):
        resp = client.get("/metrics")
        text = resp.text
        assert "klip_decision_clips_created_total" in text
        assert "klip_decision_clips_rejected_total" in text
        assert "klip_decision_confirmation_rejects_total" in text

    def test_metrics_prometheus_format(self, client):
        """Metrics should follow Prometheus exposition format."""
        resp = client.get("/metrics")
        lines = resp.text.strip().split("\n")
        for line in lines:
            if line.startswith("#"):
                # HELP or TYPE comments
                assert line.startswith("# HELP") or line.startswith("# TYPE")
            else:
                # Metric line: name{labels} value  OR  name value
                parts = line.split(" ")
                assert len(parts) >= 2, f"Invalid metric line: {line}"

    def test_metrics_type_annotations(self, client):
        """Each metric should have TYPE annotation."""
        resp = client.get("/metrics")
        text = resp.text
        assert "# TYPE klip_pipeline_running gauge" in text
        assert "# TYPE klip_events_published_total counter" in text
