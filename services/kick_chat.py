"""
Kick.com WebSocket Chat Servisi
kickbot projesinden adaptasyon - gercek zamanli chat monitor + komut tetikleme.

Kick.com'un Pusher WebSocket protokolune baglanarak chat mesajlarini izler,
belirli komutlari algilar ve callback fonksiyonlarini tetikler.
"""
import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional, Awaitable, Dict, List

logger = logging.getLogger(__name__)

KICK_WS_URI = "wss://ws-us2.pusher.com/app/eb1d5f283081a78b932c?protocol=7&client=js&version=7.6.0&flash=false"


@dataclass
class KickChatMessage:
    """Parsed Kick.com chat message."""
    id: Optional[str] = None
    chatroom_id: Optional[int] = None
    content: Optional[str] = None
    sender_username: Optional[str] = None
    sender_id: Optional[int] = None
    created_at: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_ws_data(cls, data: dict) -> "KickChatMessage":
        msg = data.get("data")
        if not msg:
            return cls()
        if isinstance(msg, str):
            msg = json.loads(msg)
        sender = msg.get("sender", {})
        return cls(
            id=msg.get("id"),
            chatroom_id=msg.get("chatroom_id"),
            content=msg.get("content", ""),
            sender_username=sender.get("username"),
            sender_id=sender.get("id"),
            created_at=msg.get("created_at"),
            raw=msg,
        )


class ChatSpikeDetector:
    """
    Sliding-window chat activity spike detection.
    Adapted from autoclipper twitch.py pattern.
    """

    def __init__(
        self,
        baseline: int = 10,
        threshold: float = 2.5,
        window_seconds: float = 30.0,
    ):
        self.baseline = baseline
        self.threshold = threshold
        self.window_seconds = window_seconds
        self._timestamps: deque = deque()
        self._cooldown_until: float = 0

    @property
    def spike_detected(self) -> bool:
        now = time.time()
        self._evict(now)
        return len(self._timestamps) > self.baseline * self.threshold

    def record_message(self) -> Optional[float]:
        """Record a message and return spike_start time if spike detected."""
        now = time.time()
        self._timestamps.append(now)
        self._evict(now)

        if now < self._cooldown_until:
            return None

        if len(self._timestamps) > self.baseline * self.threshold:
            self._cooldown_until = now + 60.0
            return now - 15.0
        return None

    def _evict(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()


class KickChatService:
    """
    Kick.com real-time chat monitor via WebSocket.
    Connects to Pusher WS, subscribes to chatroom, dispatches commands.

    Usage:
        service = KickChatService()
        service.add_command("!clip", on_clip_command)
        await service.start("streamer_slug")
    """

    def __init__(self):
        self._ws = None
        self._socket_id: Optional[str] = None
        self._chatroom_id: Optional[int] = None
        self._streamer_slug: Optional[str] = None
        self._commands: Dict[str, Callable[..., Awaitable]] = {}
        self._message_handlers: Dict[str, Callable[..., Awaitable]] = {}
        self._on_message_callbacks: List[Callable[[KickChatMessage], Awaitable]] = []
        self._is_active = False
        self._spike_detector = ChatSpikeDetector()
        self._reconnect_delay = 5.0
        self._max_reconnect_delay = 60.0

    def add_command(self, command: str, handler: Callable[..., Awaitable]) -> None:
        self._commands[command.lower()] = handler

    def add_message_handler(self, text: str, handler: Callable[..., Awaitable]) -> None:
        self._message_handlers[text.lower()] = handler

    def on_message(self, handler: Callable[[KickChatMessage], Awaitable]) -> None:
        self._on_message_callbacks.append(handler)

    async def start(self, streamer_slug: str) -> None:
        """Start the WebSocket chat monitor."""
        self._streamer_slug = streamer_slug
        self._is_active = True
        delay = self._reconnect_delay

        while self._is_active:
            try:
                import websockets
                async with websockets.connect(KICK_WS_URI) as ws:
                    self._ws = ws
                    delay = self._reconnect_delay
                    await self._handle_connection(ws)
            except Exception as e:
                if not self._is_active:
                    break
                logger.warning("WebSocket baglantisi kesildi: %s — %s sn sonra yeniden deneniyor", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)

    async def stop(self) -> None:
        self._is_active = False
        if self._ws:
            await self._ws.close()

    async def send_text(self, message: str) -> bool:
        """Send a message to the chatroom (requires HTTP auth — placeholder)."""
        logger.info("Chat mesaji gonderildi: %s", message)
        return True

    async def _handle_connection(self, ws) -> None:
        raw = await ws.recv()
        resp = json.loads(raw)

        if resp.get("event") != "pusher:connection_established":
            raise RuntimeError("Pusher connection handshake basarisiz")

        self._socket_id = json.loads(resp.get("data", "{}")).get("socket_id")
        logger.info("Pusher WS baglandi, socket_id=%s", self._socket_id)

        await self._fetch_chatroom_id()
        if not self._chatroom_id:
            raise RuntimeError(f"Chatroom ID bulunamadi: {self._streamer_slug}")

        join_cmd = {
            "event": "pusher:subscribe",
            "data": {"auth": "", "channel": f"chatrooms.{self._chatroom_id}.v2"},
        }
        await ws.send(json.dumps(join_cmd))
        join_resp = json.loads(await ws.recv())
        if join_resp.get("event") != "pusher_internal:subscription_succeeded":
            raise RuntimeError(f"Chatroom katilim hatasi: {join_resp}")

        logger.info("Chatroom %d katilindi (%s)", self._chatroom_id, self._streamer_slug)

        while self._is_active:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
            except asyncio.TimeoutError:
                continue
            resp = json.loads(raw)
            if resp.get("event") == "App\\Events\\ChatMessageEvent":
                await self._dispatch_message(resp)

    async def _dispatch_message(self, event_data: dict) -> None:
        msg = KickChatMessage.from_ws_data(event_data)
        if not msg.content:
            return

        for cb in self._on_message_callbacks:
            try:
                await cb(msg)
            except Exception as e:
                logger.error("Chat callback hatasi: %s", e)

        spike_start = self._spike_detector.record_message()
        if spike_start is not None:
            logger.info("Chat spike algilandi! Spike baslangici: %s", spike_start)

        content_lower = msg.content.lower().strip()
        if content_lower in self._message_handlers:
            try:
                await self._message_handlers[content_lower](msg)
            except Exception as e:
                logger.error("Message handler hatasi: %s", e)
            return

        parts = content_lower.split()
        if parts and parts[0] in self._commands:
            try:
                await self._commands[parts[0]](msg)
            except Exception as e:
                logger.error("Command handler hatasi: %s", e)

    async def _fetch_chatroom_id(self) -> None:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://kick.com/api/v2/channels/{self._streamer_slug}",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    chatroom = data.get("chatroom", {})
                    self._chatroom_id = chatroom.get("id")
        except Exception as e:
            logger.error("Chatroom ID cekilemedi: %s", e)


kick_chat_service = KickChatService()
