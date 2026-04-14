#!/usr/bin/env python3
"""Seqera Platform API fetch helpers."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


def _api_get(url: str, headers: dict[str, str], params: dict[str, str] | None = None) -> dict:
    if params:
        parsed = urlparse(url)
        existing = parse_qs(parsed.query)
        existing.update({k: [v] for k, v in params.items()})
        flat = {k: v[0] for k, v in existing.items()}
        url = urlunparse(parsed._replace(query=urlencode(flat)))

    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read())


def resolve_workspace_id(workspace: str, api_endpoint: str, headers: dict[str, str]) -> int:
    org_name, workspace_name = workspace.split("/", 1)

    data = _api_get(f"{api_endpoint}/orgs", headers=headers)
    orgs = data.get("organizations", [])
    org_id = None
    for org in orgs:
        if org["name"] == org_name:
            org_id = org["orgId"]
            break
    if org_id is None:
        raise RuntimeError(f"Organization '{org_name}' not found")

    data = _api_get(f"{api_endpoint}/orgs/{org_id}/workspaces", headers=headers)
    workspaces = data.get("workspaces", [])
    ws_id = None
    for ws in workspaces:
        if ws["name"] == workspace_name:
            ws_id = ws["id"]
            break
    if ws_id is None:
        raise RuntimeError(f"Workspace '{workspace_name}' not found in org '{org_name}'")

    return ws_id


def fetch_all_tasks(base_url: str, headers: dict[str, str]) -> list[dict]:
    tasks: list[dict] = []
    offset = 0
    page_size = 100

    while True:
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}max={page_size}&offset={offset}"
        data = _api_get(url, headers=headers)
        page = data.get("tasks", [])
        tasks.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    return tasks


def fetch_run_data(run_id: str, workspace: str, api_endpoint: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    ws_id = resolve_workspace_id(workspace, api_endpoint, headers)

    workflow_data = _api_get(
        f"{api_endpoint}/workflow/{run_id}",
        headers=headers,
        params={"workspaceId": str(ws_id)},
    )

    metrics_data = _api_get(
        f"{api_endpoint}/workflow/{run_id}/metrics",
        headers=headers,
        params={"workspaceId": str(ws_id)},
    )

    tasks_data = fetch_all_tasks(f"{api_endpoint}/workflow/{run_id}/tasks?workspaceId={ws_id}", headers)

    progress_data = _api_get(
        f"{api_endpoint}/workflow/{run_id}/progress",
        headers=headers,
        params={"workspaceId": str(ws_id)},
    )

    return {
        "workflow": workflow_data.get("workflow"),
        "metrics": metrics_data.get("metrics", []),
        "tasks": tasks_data,
        "progress": progress_data.get("progress"),
    }
