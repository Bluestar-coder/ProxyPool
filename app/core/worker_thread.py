from __future__ import annotations
import asyncio
from PyQt6.QtCore import QThread, pyqtSignal


class AsyncWorkerThread(QThread):
    error_occurred = pyqtSignal(str)

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
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
        if hasattr(self, "loop") and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._main_task.cancel)

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def main(self):
        raise NotImplementedError
