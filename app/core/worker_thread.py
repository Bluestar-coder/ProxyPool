from __future__ import annotations
import asyncio
from PyQt6.QtCore import QThread, pyqtSignal


class AsyncWorkerThread(QThread):
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Default event used when main() is called directly (e.g. in tests).
        # run() replaces this with a fresh instance bound to the worker loop.
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # unpaused by default

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        # Replace the default event with one created in this thread's loop.
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # starts unpaused
        self._main_task = self.loop.create_task(self.main())
        try:
            self.loop.run_until_complete(self._main_task)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            pending = asyncio.all_tasks(self.loop)
            for t in pending:
                t.cancel()
            self.loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    def stop(self):
        if hasattr(self, "loop") and not self.loop.is_closed() and hasattr(self, "_main_task"):
            try:
                self.loop.call_soon_threadsafe(self._main_task.cancel)
            except RuntimeError:
                pass

    def pause(self):
        if hasattr(self, "loop") and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self._pause_event.clear)
            except RuntimeError:
                pass

    def resume(self):
        if hasattr(self, "loop") and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self._pause_event.set)
            except RuntimeError:
                pass

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def main(self):
        raise NotImplementedError
