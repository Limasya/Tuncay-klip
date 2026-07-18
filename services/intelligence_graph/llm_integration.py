"""
Content Intelligence Graph — LLM Prompt Integration
────────────────────────────────────────────────────
AI'ın graph'tan ürettiği context'i LLM prompt'una dönüştürür.

Örnek prompt:

"You are analyzing a livestream clip. Here is the knowledge graph context:

[OBJECT] AK47 | confidence: 0.92
[GAME_EVENT] headshot: Player1 → Target | weapon: AK47
[EMOTION] excitement | intensity: 0.95 | source: face
[SOUND] scream | intensity: 0.88
[CHAT] user1: NİCE | sentiment: 0.8
[CHAT] user2: GÜZEL | sentiment: 0.7
[VIEWER] count: 15420 | delta: +340

Connected signals: object, game_event, emotion, sound, chat, viewer
Causal chain: headshot → excitement → scream → chat spam → viewer spike

Based on this context, generate:
1. A viral clip title
2. Description
3. Hashtags
4. Why this moment is viral"
"""
from __future__ import annotations

from typing import Any

from services.intelligence_graph.graph_models import GraphContext, EntityType


def graph_context_to_prompt(
    context: GraphContext,
    task: str = "analyze",
    language: str = "tr",
) -> str:
    """Graph context'ini LLM prompt'una dönüştür."""

    sections = []

    # System instruction
    if language == "tr":
        sections.append(
            "Sen bir livestream clip analiz uzmanısın. "
            "Aşağıda bilgi grafiğinden çıkarılan bağlam var. "
            "Bu bağlamı kullanarak analiz yap."
        )
    else:
        sections.append(
            "You are a livestream clip analysis expert. "
            "Below is context extracted from a knowledge graph. "
            "Use this context for your analysis."
        )

    # Time info
    ts = context.timestamp
    mins = int(ts // 60)
    secs = int(ts % 60)
    sections.append(f"\n## Moment: {mins:02d}:{secs:02d}")

    # Graph nodes by type
    sections.append("\n## Knowledge Graph Context:")

    by_type: dict[EntityType, list] = {}
    for node in context.nodes:
        if node.entity_type not in by_type:
            by_type[node.entity_type] = []
        by_type[node.entity_type].append(node)

    type_order = [
        EntityType.SCENE, EntityType.OBJECT, EntityType.PERSON,
        EntityType.GAME_EVENT, EntityType.SPEECH, EntityType.EMOTION,
        EntityType.MOVEMENT, EntityType.SOUND, EntityType.KEYWORD,
        EntityType.CHAT, EntityType.VIEWER,
    ]

    for etype in type_order:
        nodes = by_type.get(etype, [])
        if not nodes:
            continue
        type_name = etype.value.upper()
        lines = []
        for n in nodes[:10]:  # max 10 per type
            lines.append(f"  - {n.to_context_string()}")
        sections.append(f"\n[{type_name}]")
        sections.extend(lines)

    # Connected signals
    if context.connected_signals:
        unique_types = list(set(context.connected_signals))
        sections.append(f"\n## Connected Signals: {', '.join(unique_types)}")

    # Viral score
    if context.viral_score > 0:
        sections.append(f"\n## Viral Score: {context.viral_score:.2f}")

    # Reason
    moment_nodes = [n for n in context.nodes if n.entity_type == EntityType.MOMENT]
    if moment_nodes:
        reason = moment_nodes[0].metadata.get("reason", "")
        if reason:
            sections.append(f"\n## Why This Moment Matters: {reason}")

    # Task-specific instructions
    sections.append("\n## Task:")

    if task == "analyze":
        if language == "tr":
            sections.append(
                "Bu clip'i analiz et:\n"
                "1. Bu an neden viral? (bağlamdaki sinyalleri açıkla)\n"
                "2. Başlık öner (dikkat çekici, emoji kullan)\n"
                "3. Kısa açıklama yaz\n"
                "4. Hashtag öner (oyun + duygu + eylem)\n"
                "5. Hangi platform için uygun? (YouTube/TikTok/Instagram)\n"
                "6. viral_skor: 0-1 arası"
            )
        else:
            sections.append(
                "Analyze this clip:\n"
                "1. Why is this moment viral? (explain signals from context)\n"
                "2. Suggest a title (catchy, use emojis)\n"
                "3. Write a short description\n"
                "4. Suggest hashtags (game + emotion + action)\n"
                "5. Which platform is it suitable for? (YouTube/TikTok/Instagram)\n"
                "6. viral_score: 0-1"
            )

    elif task == "title":
        if language == "tr":
            sections.append("Sadece dikkat çekici bir başlık öner. 1-2 kelime.")
        else:
            sections.append("Suggest only a catchy title. 1-2 words.")

    elif task == "description":
        if language == "tr":
            sections.append("Bu clip için kısa bir sosyal medya açıklaması yaz.")
        else:
            sections.append("Write a short social media description for this clip.")

    elif task == "hashtags":
        if language == "tr":
            sections.append("Bu clip için 5-10 hashtag öner.")
        else:
            sections.append("Suggest 5-10 hashtags for this clip.")

    elif task == "why_viral":
        if language == "tr":
            sections.append(
                "Bu anın neden viral olduğunu, graph'taki "
                "bağlantılı sinyalleri referans vererek açıkla."
            )
        else:
            sections.append(
                "Explain why this moment is viral, "
                "referencing connected signals from the graph."
            )

    elif task == "context_only":
        # Sadece context, task talimatı yok
        pass

    return "\n".join(sections)


def graph_context_to_narrative(context: GraphContext) -> str:
    """Graph context'inden basit hikaye üret (human-readable)."""
    if not context.nodes:
        return "No data available for this moment."

    ts = context.timestamp
    parts = [f"At {int(ts // 60):02d}:{int(ts % 60):02d}:"]

    # Group by type
    by_type: dict[str, list[str]] = {}
    for node in context.nodes:
        t = node.entity_type.value
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(node.label)

    if "game_event" in by_type:
        parts.append(f"Game events: {', '.join(by_type['game_event'][:3])}")
    if "speech" in by_type:
        parts.append(f"Streamer says: {' | '.join(by_type['speech'][:2])}")
    if "emotion" in by_type:
        parts.append(f"Emotions: {', '.join(by_type['emotion'][:3])}")
    if "sound" in by_type:
        parts.append(f"Sounds: {', '.join(by_type['sound'][:3])}")
    if "chat" in by_type:
        parts.append(f"Chat: {', '.join(by_type['chat'][:3])}")
    if "viewer" in by_type:
        parts.append(f"Viewers: {', '.join(by_type['viewer'][:2])}")
    if "object" in by_type:
        parts.append(f"Objects: {', '.join(by_type['object'][:3])}")

    if context.viral_score > 0.6:
        parts.append(f"(Viral score: {context.viral_score:.0%})")

    return ". ".join(parts)


def graph_context_to_json(context: GraphContext) -> dict[str, Any]:
    """Graph context'ini API response formatına dönüştür."""
    return {
        "moment_id": context.moment_id,
        "timestamp": context.timestamp,
        "viral_score": context.viral_score,
        "narrative": context.narrative,
        "connected_signals": context.connected_signals,
        "nodes": [
            {
                "id": n.id,
                "type": n.entity_type.value,
                "label": n.label,
                "timestamp": n.timestamp,
                "confidence": n.confidence,
                "metadata": n.metadata,
            }
            for n in context.nodes
        ],
        "edges": [
            {
                "id": e.id,
                "source": e.source_id,
                "target": e.target_id,
                "type": e.edge_type.value,
                "weight": e.weight,
                "confidence": e.confidence,
            }
            for e in context.edges
        ],
    }
