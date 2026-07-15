"""
Chat Source — bridges Kick chat messages into the microservice pipeline.

Uses kick_api.poll_chat() (HTTP polling) as data source, feeds each
message into ChatAnalysisService which publishes CHAT_SPIKE / CHAT_SENTIMENT
events on the EventBus.

Architecture:
  Kick API (polling) → ChatSource → ChatAnalysisService → EventBus
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from shared.event_bus import EventBus, get_event_bus

logger = logging.getLogger("chat_source")


class KickChatSource:
    """
    Connects Kick chat polling to the ChatAnalysis microservice.

    Usage:
        source = KickChatSource(event_bus, chat_analysis)
        await source.start(channel_slug="xqc")
        ...
        await source.stop()
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        chat_analysis=None,
        poll_interval: float = 2.0,
    ):
        self.event_bus = event_bus or get_event_bus()
        self.chat_analysis = chat_analysis
        self.poll_interval = poll_interval

        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        self._messages_processed = 0
        self._last_cursor: Optional[str] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start(self, channel_slug: str = ""):
        """Start polling Kick chat and feeding messages to analysis."""
        if self._is_running:
            logger.warning("Chat source already running")
            return

        self._is_running = True
        self._task = asyncio.create_task(self._poll_loop(channel_slug))
        logger.info(f"Chat source started (poll_interval={self.poll_interval}s)")

    async def stop(self):
        """Stop the chat polling loop."""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"Chat source stopped. Messages processed: {self._messages_processed}")

    async def _poll_loop(self, channel_slug: str):
        """Main polling loop using kick_api."""
        from services.kick_api import kick_service

        cursor = self._last_cursor

        while self._is_running:
            try:
                data = await kick_service.get_chat_messages(cursor=cursor)
                messages = data.get("data", [])
                cursor = data.get("meta", {}).get("cursor")
                self._last_cursor = cursor

                for msg in messages:
                    await self._process_message(msg)

            except Exception as e:
                logger.error(f"Chat polling error: {e}")

            await asyncio.sleep(self.poll_interval)

    async def _process_message(self, msg: dict):
        """Process a single Kick chat message."""
        text = msg.get("content", msg.get("text", ""))
        user = msg.get("sender", {}).get("username", "")

        if not text:
            return

        if self.chat_analysis:
            await self.chat_analysis.process_message(text, user=user)

        self._messages_processed += 1

    async def inject_message(self, text: str, user: str = ""):
        """Manually inject a message (for testing)."""
        if self.chat_analysis:
            await self.chat_analysis.process_message(text, user=user)
        self._messages_processed += 1

    def get_status(self) -> dict:
        return {
            "is_running": self._is_running,
            "messages_processed": self._messages_processed,
            "poll_interval": self.poll_interval,
        }
