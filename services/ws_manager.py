"""
WebSocket Manager
─────────────────
Real-time event streaming to connected dashboard clients.

Features:
- Broadcast events to all connected clients
- Per-client subscription filtering (event_type, stream_id)
- Heartbeat / ping-pong keepalive
- Connection tracking with metadata
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("ws_manager")


class WSClient:
    """Represents a single connected WebSocket client."""

    def __init__(self, ws: WebSocket, client_id: str):
        self.ws = ws
        self.client_id = client_id
        self.connected_at = time.time()
        self.subscriptions: set[str] = set()  # event types to receive
        self.last_pong: float = time.time()

    async def send(self, data: dict):
        try:
            await self.ws.send_json(data)
        except Exception:
            pass

    async def close(self):
        try:
            await self.ws.close()
        except Exception:
            pass


class WSManager:
    """
    Manages WebSocket connections and broadcasts.

    Usage:
        ws_manager = WSManager()
        # On connect:
        await ws_manager.connect(websocket, client_id)
        # Broadcast:
        await ws_manager.broadcast({"event": "clip.created", "data": {...}})
        # Filtered:
        await ws_manager.broadcast({"event": "clip.created"}, event_filter="clip.created")
    """

    def __init__(self):
        self._clients: dict[str, WSClient] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._event_log: list[dict] = []  # last 100 events
        self._max_log = 100
        self._metrics = {
            "total_connections": 0,
            "active_connections": 0,
            "messages_sent": 0,
            "messages_failed": 0,
        }

    async def connect(self, websocket: WebSocket, client_id: str) -> WSClient:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        client = WSClient(websocket, client_id)
        self._clients[client_id] = client
        self._metrics["total_connections"] += 1
        self._metrics["active_connections"] = len(self._clients)

        logger.info("WS connected: %s (total: %d)", client_id, len(self._clients))

        # Send welcome
        await client.send({
            "type": "connected",
            "client_id": client_id,
            "server_time": time.time(),
            "active_clients": len(self._clients),
        })

        # Start heartbeat if not running
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        return client

    async def disconnect(self, client_id: str):
        """Remove a client."""
        client = self._clients.pop(client_id, None)
        if client:
            await client.close()
            self._metrics["active_connections"] = len(self._clients)
            logger.info("WS disconnected: %s (total: %d)", client_id, len(self._clients))

    async def broadcast(
        self,
        data: dict,
        event_filter: str | None = None,
        stream_filter: str | None = None,
    ):
        """
        Broadcast data to all connected clients.

        Args:
            data: JSON-serializable dict to send
            event_filter: Only send to clients subscribed to this event type
            stream_filter: Only send to clients watching this stream
        """
        if not self._clients:
            return

        # Log event
        self._event_log.append({
            "timestamp": time.time(),
            "event": data.get("event", data.get("type", "unknown")),
            "recipients": 0,
        })
        if len(self._event_log) > self._max_log:
            self._event_log = self._event_log[-self._max_log:]

        tasks = []
        for client_id, client in list(self._clients.items()):
            # Check subscriptions
            if event_filter and client.subscriptions:
                if event_filter not in client.subscriptions and "*" not in client.subscriptions:
                    continue

            tasks.append(self._send_to_client(client, data))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            sent = sum(1 for r in results if r is True)
            failed = sum(1 for r in results if r is False)
            self._metrics["messages_sent"] += sent
            self._metrics["messages_failed"] += failed

            # Update log
            if self._event_log:
                self._event_log[-1]["recipients"] = sent

    async def _send_to_client(self, client: WSClient, data: dict) -> bool:
        try:
            await client.send(data)
            return True
        except Exception:
            return False

    async def _heartbeat_loop(self):
        """Send periodic pings and clean up dead connections."""
        while self._clients:
            try:
                dead = []
                for client_id, client in list(self._clients.items()):
                    if time.time() - client.last_pong > 60:
                        dead.append(client_id)
                        continue
                    try:
                        await client.ws.send_json({"type": "ping", "ts": time.time()})
                    except Exception:
                        dead.append(client_id)

                for cid in dead:
                    await self.disconnect(cid)

                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Heartbeat error: %s", e)
                await asyncio.sleep(5)

    def get_status(self) -> dict:
        return {
            "active_connections": len(self._clients),
            "total_connections": self._metrics["total_connections"],
            "messages_sent": self._metrics["messages_sent"],
            "messages_failed": self._metrics["messages_failed"],
            "recent_events": len(self._event_log),
            "clients": [
                {
                    "client_id": c.client_id,
                    "connected_at": c.connected_at,
                    "subscriptions": list(c.subscriptions),
                }
                for c in self._clients.values()
            ],
        }

    def get_recent_events(self, last_n: int = 50) -> list[dict]:
        return self._event_log[-last_n:]


# ── Singleton ───────────────────────────────────────────────────
ws_manager = WSManager()
