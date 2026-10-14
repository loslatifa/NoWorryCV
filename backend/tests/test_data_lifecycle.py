import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.core.config import reset_settings_cache
from backend.app.main import create_app
from backend.app.services.runs.store import get_run_store, reset_run_store_cache


def _headers(token: str) -> dict:
    return {"X-Run-Token": token}


def test_run_access_requires_its_unguessable_token() -> None:
    client = TestClient(create_app())
    job = get_run_store().create("任务已创建。")
    path = "/api/v1/tailor-runs/{0}/status".format(job.run_id)

    assert client.get(path).status_code == 404
    assert client.get(path, headers=_headers("wrong-token")).status_code == 404
    authorized = client.get(path, headers=_headers(job.access_token))

    assert authorized.status_code == 200
    assert authorized.json()["run_id"] == job.run_id
    assert authorized.json()["access_token"] is None


def test_delete_removes_result_and_token_hash_from_persistent_store() -> None:
    client = TestClient(create_app())
    store = get_run_store()
    job = store.create("任务已创建。")
    path = "/api/v1/tailor-runs/{0}".format(job.run_id)

    denied = client.delete(path, headers=_headers("wrong-token"))
    deleted = client.delete(path, headers=_headers(job.access_token))

    assert denied.status_code == 404
    assert deleted.status_code == 204
    assert client.get(path + "/status", headers=_headers(job.access_token)).status_code == 404

    persisted = json.loads(store._path.read_text(encoding="utf-8"))
    assert job.run_id not in persisted["jobs"]
    assert job.run_id not in persisted["access_token_hashes"]


def test_expired_anonymous_run_is_cleaned_on_access() -> None:
    client = TestClient(create_app())
    store = get_run_store()
    job = store.create("任务已创建。")
    store.update(
        job.run_id,
        expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    )

    response = client.get(
        "/api/v1/tailor-runs/{0}/status".format(job.run_id),
        headers=_headers(job.access_token),
    )

    assert response.status_code == 404
    assert store.get(job.run_id) is None


def test_plaintext_access_token_is_never_persisted() -> None:
    store = get_run_store()
    job = store.create("任务已创建。")

    persisted_text = store._path.read_text(encoding="utf-8")

    assert job.access_token not in persisted_text
    assert job.run_id in persisted_text


def test_upload_size_and_file_type_are_restricted(monkeypatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "16")
    reset_settings_cache()
    reset_run_store_cache()
    client = TestClient(create_app())

    too_large = client.post(
        "/api/v1/resume/parse-upload",
        files={"resume_file": ("resume.txt", b"x" * 17, "text/plain")},
    )
    unsupported = client.post(
        "/api/v1/resume/parse-upload",
        files={"resume_file": ("resume.html", b"resume", "text/html")},
    )

    assert too_large.status_code == 413
    assert unsupported.status_code == 400


def test_expensive_endpoints_are_rate_limited(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    reset_settings_cache()
    reset_run_store_cache()
    client = TestClient(create_app())
    files = {"resume_file": ("resume.md", "张三\n技能\nSQL".encode("utf-8"), "text/markdown")}

    first = client.post("/api/v1/resume/parse-upload", files=files)
    second = client.post("/api/v1/resume/parse-upload", files=files)

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) >= 1
