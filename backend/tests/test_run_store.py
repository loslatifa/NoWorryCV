from fastapi.testclient import TestClient

from backend.app.core.config import reset_settings_cache
from backend.app.main import create_app
from backend.app.services.runs.store import get_run_store, reset_run_store_cache


def test_run_status_persists_across_store_cache_reset() -> None:
    app = create_app()
    client = TestClient(app)
    store = get_run_store()
    job = store.create("任务已创建。")
    store.mark_running(job.run_id, stage="analyze_jd", percent=20, message="正在分析 JD。")

    reset_settings_cache()
    reset_run_store_cache()

    app_reloaded = create_app()
    client_reloaded = TestClient(app_reloaded)
    response = client_reloaded.get(
        "/api/v1/tailor-runs/{0}/status".format(job.run_id),
        headers={"X-Run-Token": job.access_token},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == job.run_id
    assert payload["status"] == "running"
    assert payload["current_stage"] == "analyze_jd"
    assert payload["progress_percent"] == 20
