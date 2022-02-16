import asyncio
import dataclasses
import itertools
import logging
import traceback
from typing import Awaitable, Callable, Dict, Iterator


@dataclasses.dataclass
class WorkerPool:
    name: str
    log: logging.Logger
    worker_async_callable: Callable[[int], Awaitable[object]]
    desired_worker_count: int
    _workers: Dict[asyncio.Task, int] = dataclasses.field(init=False, default_factory=dict)
    _worker_id_counter: Iterator[int] = dataclasses.field(init=False, default_factory=itertools.count)

    async def run(self) -> None:
        try:
            while True:
                while len(self._workers) < self.desired_worker_count:
                    new_worker_id = next(self._worker_id_counter)
                    new_worker = asyncio.create_task(self.worker_async_callable(new_worker_id))
                    self.log.debug(f"{self.name}: adding worker {new_worker_id}")
                    self._workers[new_worker] = new_worker_id

                self.log.debug(f"{self.name}: waiting with {len(self._workers)} workers: {list(self._workers.values())}")
                done_workers, pending_workers = await asyncio.wait(
                    self._workers,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                self._workers = {task: self._workers[task] for task in pending_workers}
                for done_worker in done_workers:
                    await self.handle_done_worker(worker=done_worker)
        finally:
            # TODO: would be nice to not need a list to avoid modifying while iterating
            for worker in list(self._workers.keys()):
                try:
                    worker.cancel()
                    await self.handle_done_worker(worker=worker)
                except asyncio.CancelledError:
                    # https://docs.python.org/3.7/library/asyncio-exceptions.html#asyncio.CancelledError
                    raise
                except Exception:
                    error_trace = traceback.format_exc()
                    self.log.debug(f"{self.name}: exception while canceling worker: {error_trace}")

    async def handle_done_worker(self, worker: asyncio.Task) -> None:
        worker_id = self._workers.pop(worker)
        try:
            result = await worker
        except asyncio.CancelledError:
            # https://docs.python.org/3.7/library/asyncio-exceptions.html#asyncio.CancelledError
            raise
        except Exception:
            error_trace = traceback.format_exc()
            self.log.debug(f"{self.name}: worker {worker_id} raised exception: {error_trace}")
        else:
            self.log.debug(f"{self.name}: worker {worker_id} unexpectedly returned: {result}")
