from pathlib import Path
from unittest.mock import patch

import httpx

from scripts import benchmark_latency


def test_failed_requests_are_not_reported_as_zero_latency(tmp_path):
    image = tmp_path / "input.jpg"
    image.write_bytes(b"test")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request)))
    with patch.object(benchmark_latency.httpx, "Client", return_value=client):
        result = benchmark_latency.benchmark_scenario("http://test", image, num_runs=2)
    assert result["successful_runs"] == 0
    assert result["failed_runs"] == 2
    assert result["p50"] is None
    assert result["p95"] is None


def test_benchmark_sends_auth_without_putting_it_in_metrics(tmp_path):
    image = tmp_path / "input.jpg"
    image.write_bytes(b"test")
    captured = {}
    def make_client(**kwargs):
        captured.update(kwargs)
        return original_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})), **kwargs)
    original_client = httpx.Client
    with patch.object(benchmark_latency.httpx, "Client", side_effect=make_client):
        result = benchmark_latency.benchmark_scenario("http://test", image, num_runs=1, api_token="test-only-token")
    assert captured["headers"] == {"Authorization": "Bearer test-only-token"}
    assert result["successful_runs"] == 1
    assert "test-only-token" not in str(result)


def test_empty_benchmark_fails_instead_of_claiming_success(tmp_path, monkeypatch):
    monkeypatch.setenv("LIBEREYE_API_TOKEN", "test-only-token")
    monkeypatch.setattr("sys.argv", ["benchmark_latency", "--fixtures-dir", str(tmp_path / "missing"), "--output-dir", str(tmp_path / "results")])
    assert benchmark_latency.main() == 1
    report = next((tmp_path / "results").glob("*.json")).read_text()
    assert '"physical_output_measured": false' in report
    assert "test-only-token" not in report
