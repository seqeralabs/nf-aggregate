from unittest.mock import patch

import pytest

from benchmark_report_fetch import fetch_all_tasks, fetch_run_data, resolve_workspace_id


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
        with patch("benchmark_report_fetch._api_get") as mock_get:
            with patch("benchmark_report_fetch.fetch_all_tasks", return_value=[{"task": {"id": 1}}]):
                mock_get.side_effect = [
                    {"workflow": {"id": "run1"}},
                    {"metrics": []},
                    {"progress": {"workflowProgress": {}}},
                ]
                data = fetch_run_data("run1", "org/ws", "https://api.example.com", "tok")
                assert set(data.keys()) == {"workflow", "metrics", "tasks", "progress"}
