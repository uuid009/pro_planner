"""Streamlit 通过 HTTP 调用本机 API，不直接打开数据库。"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import httpx

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"


class ApiError(Exception):
    def __init__(self, status_code: int, payload: dict):
        message = ((payload.get("error") or {}).get("message")) or "请求失败"
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def api_base_url() -> str:
    return os.environ.get("API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")


def request(method: str, path: str, **kwargs: Any) -> Any:
    with httpx.Client(base_url=api_base_url(), timeout=120) as client:
        response = client.request(method, path, **kwargs)
    if response.status_code >= 400:
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": {"message": response.text[:200]}}
        raise ApiError(response.status_code, payload)
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    return response.content


def list_projects() -> list[dict]:
    return request("GET", "/api/projects")


def create_project(payload: dict) -> dict:
    return request("POST", "/api/projects", json=payload)


def list_runs(project_id: UUID | str) -> list[dict]:
    return request("GET", f"/api/projects/{project_id}/runs")


def start_run(project_id: UUID | str, user_request: str, deliverables: list[str]) -> dict:
    return request(
        "POST",
        f"/api/projects/{project_id}/runs",
        json={"user_request": user_request, "deliverables": deliverables},
    )


def get_run(run_id: UUID | str) -> dict:
    return request("GET", f"/api/runs/{run_id}")


def list_events(run_id: UUID | str) -> list[dict]:
    return request("GET", f"/api/runs/{run_id}/events")


def list_checkpoints(run_id: UUID | str) -> list[dict]:
    return request("GET", f"/api/runs/{run_id}/checkpoints")


def review(run_id: UUID | str) -> dict:
    return request("GET", f"/api/runs/{run_id}/review")


def resume_run(run_id: UUID | str, payload: dict) -> dict:
    return request("POST", f"/api/runs/{run_id}/resume", json=payload)


def fork_run(run_id: UUID | str, payload: dict) -> dict:
    return request("POST", f"/api/runs/{run_id}/fork", json=payload)


def list_documents(project_id: UUID | str | None = None) -> list[dict]:
    params = {} if project_id is None else {"project_id": str(project_id)}
    return request("GET", "/api/documents", params=params)


def upload_document(filename: str, content: bytes, project_id: UUID | str | None) -> dict:
    data = {} if project_id is None else {"project_id": str(project_id)}
    return request(
        "POST",
        "/api/documents/upload",
        data=data,
        files={"file": (filename, content)},
    )


def index_document(document_id: UUID | str) -> dict:
    return request("POST", f"/api/documents/{document_id}/index")


def search_evidence(query: str, project_id: UUID | str | None) -> dict:
    payload: dict[str, Any] = {"query": query}
    if project_id is not None:
        payload["project_id"] = str(project_id)
    return request("POST", "/api/retrieval/search", json=payload)


def list_artifacts(project_id: UUID | str) -> list[dict]:
    return request("GET", f"/api/projects/{project_id}/artifacts")


def download_artifact(artifact_id: UUID | str) -> bytes:
    return request("GET", f"/api/artifacts/{artifact_id}/download")


def compare_artifacts(left_id: UUID | str, right_id: UUID | str) -> dict:
    return request("GET", "/api/artifacts/compare", params={"left": str(left_id), "right": str(right_id)})
