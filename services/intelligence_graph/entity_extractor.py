"""
Content Intelligence Graph — Entity Extractor
─────────────────────────────────────────────
Mevcut AI servislerinden (Vision AI, Audio AI, Chat AI) entity çıkarır
ve graph'a dönüştürür.

Her sinyal → bir node, her ilişki → bir edge.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.intelligence_graph.graph_models import (
    EntityType, GraphNode, GraphEdge, EdgeType,
    FrameNode, ObjectNode, SpeechNode, EmotionNode, MovementNode,
    ChatNode, ViewerNode, GameEventNode, SoundNode, SceneNode,
    KeywordNode, PersonNode,
)

logger = logging.getLogger("intelligence_graph")


class EntityExtractor:
    """AI servislerinden graph entity'leri çıkarır."""

    def __init__(self):
        self._person_cache: dict[str, str] = {}  # username -> person_node_id

    # ── Frame → Object + Scene ──

    def extract_from_vision(
        self,
        frame_index: int,
        timestamp: float,
        vision_result: dict[str, Any],
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Vision AI sonucundan node ve edge'ler çıkar."""
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # Frame node
        frame = FrameNode(
            frame_index=frame_index,
            timestamp=timestamp,
            label=f"Frame #{frame_index}",
            confidence=vision_result.get("confidence", 0.9),
        )
        nodes.append(frame)

        # Object detection results
        for obj in vision_result.get("objects", []):
            obj_node = ObjectNode(
                label=obj.get("class", "unknown"),
                timestamp=timestamp,
                object_class=obj.get("class", ""),
                bbox=tuple(obj.get("bbox", [0, 0, 0, 0])),
                tracking_id=obj.get("tracking_id"),
                confidence=obj.get("confidence", 0.5),
                metadata={
                    "class": obj.get("class", ""),
                    "confidence": obj.get("confidence", 0),
                },
            )
            nodes.append(obj_node)
            edges.append(GraphEdge(
                source_id=frame.id,
                target_id=obj_node.id,
                edge_type=EdgeType.CONTAINS,
                confidence=obj.get("confidence", 0.5),
            ))

        # Scene detection
        scene_type = vision_result.get("scene_type", "gameplay")
        if scene_type:
            scene = SceneNode(
                label=f"Scene: {scene_type}",
                timestamp=timestamp,
                scene_type=scene_type,
                confidence=vision_result.get("scene_confidence", 0.8),
                metadata={"scene_type": scene_type},
            )
            nodes.append(scene)
            edges.append(GraphEdge(
                source_id=frame.id,
                target_id=scene.id,
                edge_type=EdgeType.CONTAINS,
                confidence=0.9,
            ))

        # Emotion from face
        face_emotion = vision_result.get("face_emotion")
        if face_emotion:
            emo = EmotionNode(
                label=f"Face: {face_emotion}",
                timestamp=timestamp,
                emotion=face_emotion,
                intensity=vision_result.get("emotion_intensity", 0.5),
                source="face",
                confidence=vision_result.get("emotion_confidence", 0.6),
                metadata={
                    "emotion": face_emotion,
                    "intensity": vision_result.get("emotion_intensity", 0.5),
                    "source": "face",
                },
            )
            nodes.append(emo)
            edges.append(GraphEdge(
                source_id=frame.id,
                target_id=emo.id,
                edge_type=EdgeType.DESCRIBES,
                confidence=0.7,
            ))

        # Movement / gesture
        gesture = vision_result.get("gesture")
        if gesture:
            movement = MovementNode(
                label=f"Gesture: {gesture}",
                timestamp=timestamp,
                action=gesture,
                direction=vision_result.get("gesture_direction", ""),
                speed=vision_result.get("gesture_speed", 0),
                confidence=vision_result.get("gesture_confidence", 0.5),
                metadata={
                    "action": gesture,
                    "direction": vision_result.get("gesture_direction", ""),
                    "speed": vision_result.get("gesture_speed", 0),
                },
            )
            nodes.append(movement)
            edges.append(GraphEdge(
                source_id=frame.id,
                target_id=movement.id,
                edge_type=EdgeType.DESCRIBES,
                confidence=0.6,
            ))

        # OCR / text
        ocr_text = vision_result.get("ocr_text")
        if ocr_text:
            keyword = KeywordNode(
                label=f"OCR: {ocr_text[:50]}",
                timestamp=timestamp,
                word=ocr_text,
                category="visual_text",
                confidence=vision_result.get("ocr_confidence", 0.5),
                metadata={"word": ocr_text, "category": "visual_text"},
            )
            nodes.append(keyword)
            edges.append(GraphEdge(
                source_id=frame.id,
                target_id=keyword.id,
                edge_type=EdgeType.DESCRIBES,
                confidence=0.6,
            ))

        return nodes, edges

    # ── Audio → Speech + Sound + Emotion ──

    def extract_from_audio(
        self,
        chunk_index: int,
        timestamp: float,
        duration: float,
        audio_result: dict[str, Any],
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Audio AI sonucundan node ve edge'ler çıkar."""
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # Speech
        speech_text = audio_result.get("transcription", "")
        if speech_text:
            speech = SpeechNode(
                label=speech_text[:80],
                timestamp=timestamp,
                duration=duration,
                text=speech_text,
                speaker=audio_result.get("speaker", "streamer"),
                language=audio_result.get("language", "tr"),
                word_timestamps=audio_result.get("word_timestamps", []),
                confidence=audio_result.get("speech_confidence", 0.8),
                metadata={
                    "text": speech_text,
                    "speaker": audio_result.get("speaker", "streamer"),
                    "language": audio_result.get("language", "tr"),
                },
            )
            nodes.append(speech)

            # Speech emotion
            speech_emotion = audio_result.get("speech_emotion")
            if speech_emotion:
                emo = EmotionNode(
                    label=f"Voice: {speech_emotion}",
                    timestamp=timestamp,
                    duration=duration,
                    emotion=speech_emotion,
                    intensity=audio_result.get("speech_emotion_intensity", 0.5),
                    source="voice",
                    confidence=audio_result.get("speech_emotion_confidence", 0.6),
                    metadata={
                        "emotion": speech_emotion,
                        "intensity": audio_result.get("speech_emotion_intensity", 0.5),
                        "source": "voice",
                    },
                )
                nodes.append(emo)
                edges.append(GraphEdge(
                    source_id=speech.id,
                    target_id=emo.id,
                    edge_type=EdgeType.DESCRIBES,
                    confidence=0.7,
                ))

        # Sound events
        for sound in audio_result.get("sounds", []):
            sound_class = sound.get("class", "")
            if not sound_class:
                continue
            sound_node = SoundNode(
                label=f"Sound: {sound_class}",
                timestamp=timestamp + sound.get("offset", 0),
                duration=sound.get("duration", 1.0),
                sound_class=sound_class,
                intensity=sound.get("intensity", 0.5),
                confidence=sound.get("confidence", 0.5),
                metadata={
                    "sound_class": sound_class,
                    "intensity": sound.get("intensity", 0.5),
                },
            )
            nodes.append(sound_node)
            edges.append(GraphEdge(
                source_id=sound_node.id,
                target_id=sound_node.id,
                edge_type=EdgeType.DESCRIBES,
                confidence=0.6,
            ))

            # Scream/laugh → emotion connection
            if sound_class in ("scream", "laugh", "cheer", "clap"):
                emo_type = "excitement" if sound_class in ("scream", "cheer") else "joy"
                emo = EmotionNode(
                    label=f"Sound emotion: {emo_type}",
                    timestamp=timestamp + sound.get("offset", 0),
                    emotion=emo_type,
                    intensity=sound.get("intensity", 0.5),
                    source="sound",
                    confidence=sound.get("confidence", 0.5),
                    metadata={
                        "emotion": emo_type,
                        "intensity": sound.get("intensity", 0.5),
                        "source": "sound",
                        "trigger": sound_class,
                    },
                )
                nodes.append(emo)
                edges.append(GraphEdge(
                    source_id=sound_node.id,
                    target_id=emo.id,
                    edge_type=EdgeType.TRIGGERS,
                    confidence=0.7,
                ))

        # Music detection
        if audio_result.get("has_music"):
            music_node = SoundNode(
                label="Background Music",
                timestamp=timestamp,
                duration=duration,
                sound_class="music",
                intensity=audio_result.get("music_intensity", 0.3),
                confidence=audio_result.get("music_confidence", 0.5),
                metadata={
                    "sound_class": "music",
                    "bpm": audio_result.get("bpm"),
                    "genre": audio_result.get("music_genre", ""),
                },
            )
            nodes.append(music_node)

        return nodes, edges

    # ── Chat → Chat + Keyword + Viewer ──

    def extract_from_chat(
        self,
        timestamp: float,
        chat_messages: list[dict[str, Any]],
        viewer_count: int = 0,
        viewer_delta: int = 0,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Chat mesajlarından node ve edge'ler çıkar."""
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # Viewer node
        if viewer_count > 0 or viewer_delta != 0:
            viewer = ViewerNode(
                label=f"Viewers: {viewer_count}",
                timestamp=timestamp,
                viewer_count=viewer_count,
                delta=viewer_delta,
                confidence=0.95,
                metadata={
                    "viewer_count": viewer_count,
                    "delta": viewer_delta,
                },
            )
            nodes.append(viewer)

        # Chat messages
        spam_tracker: dict[str, int] = {}
        for msg in chat_messages:
            username = msg.get("username", "")
            message = msg.get("message", "")
            if not message:
                continue

            # Spam detection
            msg_lower = message.lower().strip()
            spam_tracker[msg_lower] = spam_tracker.get(msg_lower, 0) + 1

            chat_node = ChatNode(
                label=f"{username}: {message[:60]}",
                timestamp=timestamp,
                message=message,
                username=username,
                sentiment=msg.get("sentiment", 0),
                is_emote=msg.get("is_emote", False),
                spam_count=spam_tracker.get(msg_lower, 1),
                confidence=msg.get("confidence", 0.8),
                metadata={
                    "message": message,
                    "username": username,
                    "sentiment": msg.get("sentiment", 0),
                    "is_emote": msg.get("is_emote", False),
                    "spam_count": spam_tracker.get(msg_lower, 1),
                },
            )
            nodes.append(chat_node)

            # Viewer → Chat connection
            if viewer_count > 0:
                edges.append(GraphEdge(
                    source_id=viewer.id,
                    target_id=chat_node.id,
                    edge_type=EdgeType.RESPONDS_TO,
                    confidence=0.7,
                ))

            # Keyword extraction
            words = message.split()
            for word in words:
                if len(word) > 3 and word.lower() not in {"this", "that", "with", "from", "have", "been"}:
                    kw_node = KeywordNode(
                        label=word,
                        timestamp=timestamp,
                        word=word,
                        category="chat",
                        confidence=0.6,
                        metadata={"word": word, "category": "chat"},
                    )
                    nodes.append(kw_node)
                    edges.append(GraphEdge(
                        source_id=chat_node.id,
                        target_id=kw_node.id,
                        edge_type=EdgeType.DESCRIBES,
                        confidence=0.5,
                    ))

        return nodes, edges

    # ── Game Event → GameEvent + Person ──

    def extract_from_game_event(
        self,
        timestamp: float,
        event: dict[str, Any],
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Olay sonucundan node ve edge'ler çıkar."""
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        event_type = event.get("event_type", "")
        if not event_type:
            return nodes, edges

        # Game event node
        game_event = GameEventNode(
            label=f"{event_type}: {event.get('player', '')} → {event.get('target', '')}",
            timestamp=timestamp,
            event_type=event_type,
            game=event.get("game", "valorant"),
            player=event.get("player", ""),
            weapon=event.get("weapon", ""),
            target=event.get("target", ""),
            score_change=event.get("score_change", 0),
            confidence=event.get("confidence", 0.8),
            metadata={
                "event_type": event_type,
                "player": event.get("player", ""),
                "weapon": event.get("weapon", ""),
                "target": event.get("target", ""),
                "score_change": event.get("score_change", 0),
            },
        )
        nodes.append(game_event)

        # Player person node
        player = event.get("player", "")
        if player:
            person = self._get_or_create_person(player, "player", timestamp)
            nodes.append(person)
            edges.append(GraphEdge(
                source_id=person.id,
                target_id=game_event.id,
                edge_type=EdgeType.PERFORMS if hasattr(EdgeType, 'PERFORMS') else EdgeType.USED_BY,
                confidence=0.9,
            ))

        # Weapon object node
        weapon = event.get("weapon", "")
        if weapon:
            weapon_node = ObjectNode(
                label=weapon,
                timestamp=timestamp,
                object_class="weapon",
                confidence=0.85,
                metadata={"class": "weapon", "weapon_name": weapon},
            )
            nodes.append(weapon_node)
            edges.append(GraphEdge(
                source_id=weapon_node.id,
                target_id=game_event.id,
                edge_type=EdgeType.USED_BY,
                confidence=0.8,
            ))

        return nodes, edges

    # ── Combined Extractor ──

    def extract_from_all(
        self,
        timestamp: float,
        vision_result: Optional[dict] = None,
        audio_result: Optional[dict] = None,
        chat_messages: Optional[list[dict]] = None,
        game_events: Optional[list[dict]] = None,
        viewer_count: int = 0,
        viewer_delta: int = 0,
        frame_index: int = 0,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Tüm sinyallerden toplu extraction."""
        all_nodes: list[GraphNode] = []
        all_edges: list[GraphEdge] = []

        if vision_result:
            n, e = self.extract_from_vision(frame_index, timestamp, vision_result)
            all_nodes.extend(n)
            all_edges.extend(e)

        if audio_result:
            n, e = self.extract_from_audio(0, timestamp, 5.0, audio_result)
            all_nodes.extend(n)
            all_edges.extend(e)

        if chat_messages:
            n, e = self.extract_from_chat(timestamp, chat_messages, viewer_count, viewer_delta)
            all_nodes.extend(n)
            all_edges.extend(e)

        if game_events:
            for event in game_events:
                n, e = self.extract_from_game_event(timestamp, event)
                all_nodes.extend(n)
                all_edges.extend(e)

        return all_nodes, all_edges

    # ── Helpers ──

    def _get_or_create_person(self, username: str, role: str, timestamp: float) -> PersonNode:
        """Person node'u bul veya oluştur."""
        if username in self._person_cache:
            cached_id = self._person_cache[username]
            # Timestamp güncelle
            return PersonNode(
                id=cached_id,
                label=username,
                timestamp=timestamp,
                role=role,
                username=username,
                confidence=1.0,
                metadata={"role": role, "username": username},
            )

        person = PersonNode(
            label=username,
            timestamp=timestamp,
            role=role,
            username=username,
            confidence=1.0,
            metadata={"role": role, "username": username},
        )
        self._person_cache[username] = person.id
        return person


# Singleton
entity_extractor = EntityExtractor()
