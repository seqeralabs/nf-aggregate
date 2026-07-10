from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from benchmark_report_fetch import fetch_all_tasks, fetch_run_data, resolve_workspace_id, validate_api_access


def test_resolve_workspace_id():
    with patch("benchmark_report_fetch._api_get") as mock_get:
        mock_get.side_effect = [
            {"organizations": [{"name": "org", "orgId": 1}]},
            {"workspaces": [{"name": "ws", "id": 9}]},
        ]
        assert resolve_workspace_id("org/ws", "https://api.example.com", {}) == 9


def test_resolve_workspace_missing_org():
    with patch("benchmark_report_fetch._api_get", return_value={"organizations": []}):
        with pytest.raises(RuntimeError):
            resolve_workspace_id("org/ws", "https://api.example.com", {})


def test_fetch_all_tasks_paginates():
    with patch("benchmark_report_fetch._api_get") as mock_get:
        mock_get.side_effect = [
            {"tasks": [{"task": {"id": i}} for i in range(100)]},
            {"tasks": [{"task": {"id": i}} for i in range(20)]},
        ]
        tasks = fetch_all_tasks("https://api.example.com/workflow/1/tasks?workspaceId=1", {})
        assert len(tasks) == 120
        assert mock_get.call_count == 2


def test_fetch_run_data_keys():
    with patch("benchmark_report_fetch.resolve_workspace_id", return_value=10):
        with patch("benchmark_report_fetch.validate_api_access") as mock_validate:
            with patch("benchmark_report_fetch._api_get") as mock_get:
                with patch("benchmark_report_fetch.fetch_all_tasks", return_value=[{"task": {"id": 1}}]):
                    mock_get.side_effect = [
                        {"workflow": {"id": "run1"}},
                        {"metrics": []},
                        {"progress": {"workflowProgress": {}}},
                    ]
                    data = fetch_run_data("run1", "org/ws", "https://api.example.com", "tok")
                    assert set(data.keys()) == {
                        "workflow",
                        "schedEnabled",
                        "schedConfig",
                        "platform",
                        "metrics",
                        "tasks",
                        "progress",
                    }
                    mock_validate.assert_called_once_with("https://api.example.com", headers={"Authorization": "Bearer tok"})


def test_validate_api_access_bad_token():
    error = HTTPError("https://api.example.com/user-info", 401, "Unauthorized", hdrs=None, fp=None)

    with patch("benchmark_report_fetch._api_get") as mock_get:
        mock_get.side_effect = [{}, error]

        with pytest.raises(RuntimeError, match="Authentication failed at 'https://api.example.com/user-info'"):
            validate_api_access("https://api.example.com", headers={"Authorization": "Bearer tok"})


def test_validate_api_access_bad_endpoint():
    error = HTTPError("https://bad.example.com/service-info", 404, "Not Found", hdrs=None, fp=None)

    with patch("benchmark_report_fetch._api_get", side_effect=error):
        with pytest.raises(RuntimeError, match="preflight failed at 'https://bad.example.com/service-info'"):
            validate_api_access("https://bad.example.com", headers={"Authorization": "Bearer tok"})


def test_fetch_run_data_captures_sched_and_platform(monkeypatch):
    import benchmark_report_fetch as f

    def fake_api_get(url, headers, params=None):
        if url.endswith("/orgs"):
            return {"organizations": [{"name": "myorg", "orgId": 1}]}
        if url.endswith("/workspaces"):
            return {"workspaces": [{"name": "myworkspace", "id": 42}]}
        if url.endswith("/metrics"):
            return {"metrics": []}
        if url.endswith("/progress"):
            return {"progress": {"workflowProgress": {"cost": 0.01}}}
        return {
            "workflow": {"id": "icRUN0000000001", "status": "SUCCEEDED"},
            "schedEnabled": True,
            "schedConfig": {"predictionModel": "qr/v2"},
            "platform": {"id": "aws-cloud", "name": "AWS Cloud"},
        }

    monkeypatch.setattr(f, "_api_get", fake_api_get)
    monkeypatch.setattr(f, "validate_api_access", lambda *a, **k: None)
    monkeypatch.setattr(f, "fetch_all_tasks", lambda base_url, headers: [])

    out = f.fetch_run_data("icRUN0000000001", "myorg/myworkspace", "https://api.example.test", "tok")
    assert out["schedEnabled"] is True
    assert out["schedConfig"]["predictionModel"] == "qr/v2"
    assert out["platform"]["id"] == "aws-cloud"
    assert out["workflow"]["id"] == "icRUN0000000001"
