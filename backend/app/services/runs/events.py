"""Authenticated full status snapshots over SSE, without an event history table."""
import asyncio
import time

from fastapi.concurrency import run_in_threadpool


async def status_events(request, read_status, interval=0.5, heartbeat=15):
    previous = None
    sequence = 0
    last_send = time.monotonic()
    while not await request.is_disconnected():
        job = await run_in_threadpool(read_status)
        if job is None:
            yield 'event: end\ndata: {"reason":"unavailable"}\n\n'
            return
        snapshot = job.model_dump_json(exclude={'access_token'})
        if snapshot != previous:
            sequence += 1
            yield f'id: {sequence}\nevent: status\ndata: {snapshot}\n\n'
            previous = snapshot
            last_send = time.monotonic()
        if job.status in {'completed', 'failed', 'cancelled'}:
            yield 'event: end\ndata: {}\n\n'
            return
        if time.monotonic() - last_send >= heartbeat:
            yield ': ping\n\n'
            last_send = time.monotonic()
        await asyncio.sleep(interval)
