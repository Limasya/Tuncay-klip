import asyncio, time
from shared.event_schemas import EventType
from shared.event_bus import EventBus
from microservices.event_detector.service import EventDetectorService
from microservices.decision_engine.service import DecisionEngineService

async def debug():
    bus = EventBus()
    await bus.start()

    handler_calls = []

    async def on_scored(event):
        handler_calls.append(("SCORED", time.perf_counter(), event.payload.get("score", {}).get("composite_score", -1)))

    async def on_clip(event):
        handler_calls.append(("CLIP", time.perf_counter()))

    bus.subscribe(EventType.EVENT_SCORED.value, on_scored)
    bus.subscribe(EventType.CLIP_CANDIDATE.value, on_clip)

    detector = EventDetectorService(event_bus=bus, score_threshold=0.5, score_interval=0.01, decay_halflife=60.0)
    decision = DecisionEngineService(event_bus=bus, clip_threshold=0.55, cooldown_seconds=15.0, min_evidence_signals=2, confirmation_window=3, confirmation_required=2, threshold_floor=0.35, evidence_threshold=0.2)

    for i in range(5):
        scoring = detector._get_stream_scoring("test")
        scoring.update_signal("audio_spike", 0.8)
        scoring.update_signal("chat_velocity", 0.6)
        scoring.update_signal("emotion_intensity", 0.5)
        detector._stream_last_score_time["test"] = 0.0
        await detector._maybe_emit_score("test")
        await asyncio.sleep(0.05)

    await asyncio.sleep(1.0)

    print("Handler calls:", len(handler_calls))
    for c in handler_calls[:10]:
        if c[0] == "SCORED":
            print(f"  {c[0]}: score={c[2]}")
        else:
            print(f"  {c[0]}")

    status = decision.get_status()
    print(f"Decision engine: clips_created={status['clips_created']}, clips_rejected={status['clips_rejected']}, confirm_rejects={status['confirmation_rejects']}")
    print(f"Confirmation: {status['confirmation_window']}")

    await bus.stop()

asyncio.run(debug())
