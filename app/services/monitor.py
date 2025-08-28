import asyncio
import contextlib
import logging
from typing import Any, Callable, Dict, Optional

from app.clients.fragment import FragmentNumbersClient

logger = logging.getLogger(__name__)


class NumbersMonitor:
    def __init__(
        self,
        client: FragmentNumbersClient,
        on_new_listing: Callable[[Dict[str, Any]], None],
        interval_sec: int = 5,
    ):
        self.client = client
        self.on_new_listing = on_new_listing
        self.interval_sec = interval_sec
        self._seen: set[str] = set()
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            logger.warning("Monitor is already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(f"Monitor started with interval: {self.interval_sec}s")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            logger.info("Monitor stopped")

    async def _run(self) -> None:
        while self._running:
            try:
                listings = await self.client.list_sales()
                new_items_count = 0

                for item in listings:
                    key = f"{item.get('id')}|{item.get('price_ton_int')}|{item.get('status')}"
                    if key not in self._seen:
                        self._seen.add(key)
                        self.on_new_listing(item)
                        new_items_count += 1

                if new_items_count > 0:
                    logger.info(f"Found {new_items_count} new items")

            except asyncio.CancelledError:
                logger.info("Monitor task cancelled")
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")

            await asyncio.sleep(self.interval_sec)
