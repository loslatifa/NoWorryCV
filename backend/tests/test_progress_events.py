import asyncio

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.schemas.run_state import TailorRunJobStatus
from backend.app.services.runs.events import status_events
from backend.app.services.runs.store import get_run_store


def test_completed_stream_has_snapshot_end_and_header_auth():
    client = TestClient(create_app())
    job = get_run_store().create('queued')
    get_run_store().update(job.run_id, status='cancelled', current_stage='cancelled')
    path = f'/api/v1/tailor-runs/{job.run_id}/events'
    assert client.get(path).status_code == 404
    assert client.get(path, headers={'X-Run-Token': 'wrong'}).status_code == 404
    response = client.get(path, headers={'X-Run-Token': job.access_token})
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    assert response.headers['x-accel-buffering'] == 'no'
    assert 'event: status' in response.text and 'event: end' in response.text
    assert '"status":"cancelled"' in response.text
    assert job.access_token not in response.text


def test_events_changes_heartbeat_and_disconnect():
    class Request:
        def __init__(self): self.calls = 0
        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 5
    base = TailorRunJobStatus(run_id='test', status='running', current_stage='parse_resume')
    states = iter([base, base, base.model_copy(update={'progress_percent': 60}), base.model_copy(update={'status':'completed'})])
    async def collect():
        return [event async for event in status_events(Request(), lambda: next(states), interval=0, heartbeat=0)]
    events = asyncio.run(collect())
    assert sum('event: status' in event for event in events) == 3
    assert any(': ping' in event for event in events)
    assert events[-1].startswith('event: end')
    assert 'id: 3' in events[-2]
    async def disconnected():
        request = Request(); request.calls = 5
        return [event async for event in status_events(request, lambda: base, interval=0)]
    assert asyncio.run(disconnected()) == []


def test_expired_or_deleted_stream_closes_without_payload():
    class Request:
        async def is_disconnected(self): return False
    async def collect():
        return [event async for event in status_events(Request(), lambda: None, interval=0)]
    assert asyncio.run(collect()) == ['event: end\ndata: {"reason":"unavailable"}\n\n']
