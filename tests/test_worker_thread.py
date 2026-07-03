import asyncio
import pytest
from app.core.worker_thread import AsyncWorkerThread


class _ConcreteWorker(AsyncWorkerThread):
    """Minimal concrete subclass for testing pause/resume."""

    def __init__(self):
        super().__init__()
        self.ran = False

    async def main(self) -> None:
        await self._pause_event.wait()
        self.ran = True


def _init_pause_event(thread: AsyncWorkerThread):
    """Simulate what run() does: create the pause event on the running loop."""
    thread.loop = asyncio.get_event_loop()
    thread._pause_event = asyncio.Event()
    thread._pause_event.set()  # starts as unpaused


@pytest.mark.asyncio
async def test_is_paused_false_by_default():
    """Before pause(), is_paused must be False."""
    t = _ConcreteWorker()
    _init_pause_event(t)
    assert not t.is_paused


@pytest.mark.asyncio
async def test_pause_sets_is_paused():
    """pause() must make is_paused return True."""
    t = _ConcreteWorker()
    _init_pause_event(t)

    t.pause()
    await asyncio.sleep(0)  # let call_soon_threadsafe callback run
    assert t.is_paused


@pytest.mark.asyncio
async def test_resume_clears_is_paused():
    """resume() after pause() must make is_paused return False again."""
    t = _ConcreteWorker()
    _init_pause_event(t)

    t.pause()
    await asyncio.sleep(0)
    assert t.is_paused

    t.resume()
    await asyncio.sleep(0)
    assert not t.is_paused


@pytest.mark.asyncio
async def test_pause_blocks_awaiter_until_resume():
    """A coroutine awaiting _pause_event.wait() must stay blocked while paused,
    then complete immediately after resume()."""
    t = _ConcreteWorker()
    _init_pause_event(t)

    t.pause()
    await asyncio.sleep(0)

    reached_after_wait = False

    async def waiter():
        nonlocal reached_after_wait
        await t._pause_event.wait()
        reached_after_wait = True

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0)  # give waiter a chance to run
    assert not reached_after_wait  # still blocked

    t.resume()
    await asyncio.sleep(0)  # let callback set the event
    await task               # waiter should complete now
    assert reached_after_wait


@pytest.mark.asyncio
async def test_is_paused_false_when_not_started():
    """is_paused must return False before the thread is started (no _pause_event)."""
    t = _ConcreteWorker()
    assert not t.is_paused
