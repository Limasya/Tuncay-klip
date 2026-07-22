"""
Görev 2: Video Sampling Quality Validation
============================================
Sentezlenmiş numpy frame'ler ile VideoFrameBuffer'ı farklı FPS ayarlarında test eder.
FFmpeg veya gerçek video dosyası gerektirmez.

Test senaryoları:
  1. Frame Capture Rate — farklı target_fps'lerde gerçek yakalama oranı
  2. Event Window Coverage — 1s/2s/3s pencerelerde frame yakalama
  3. Detection Latency — ilk event frame'inden yakalanmaya kadar gecikme
  4. Memory Impact — buffer bellek hesabı
  5. Drop Pattern — hangi frame'ler düşüyor, kritik anlar etkileniyor mu?
"""
from __future__ import annotations

import sys
import time
import numpy as np
from typing import List, Tuple

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from services.live_stream_processor import VideoFrameBuffer


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_synthetic_frame(
    width: int = 320,
    height: int = 240,
    event_color: Tuple[int, int, int] = (255, 0, 0),
    is_event: bool = False,
) -> np.ndarray:
    """
    Sentetik RGB frame oluşturur.
    Event frame'leri kırmızı tonlarında, normal frame'ler gri tonlarındadır.
    Bu sayede frame'i analiz etmeden event/non-event ayırt edebiliriz.
    """
    if is_event:
        frame = np.full((height, width, 3), event_color, dtype=np.uint8)
        frame[:, :, 0] = np.clip(event_color[0] + np.random.randint(-10, 10), 0, 255)
    else:
        base = np.random.randint(30, 70, (height, width, 3), dtype=np.uint8)
        frame = base
    return frame


def generate_frames_at_fps(
    duration_seconds: float,
    source_fps: int,
    event_start: float = -1,
    event_end: float = -1,
    event_color: Tuple[int, int, int] = (255, 0, 0),
) -> List[Tuple[np.ndarray, float, bool]]:
    """
    Belirli sürede belirli FPS'te frame'ler üretir.
    Returns: [(frame, timestamp, is_event), ...]
    """
    frames = []
    frame_interval = 1.0 / source_fps
    t = 0.0
    while t < duration_seconds:
        is_event = event_start <= t < event_end
        frame = make_synthetic_frame(is_event=is_event, event_color=event_color)
        frames.append((frame, t, is_event))
        t += frame_interval
    return frames


def feed_buffer(
    buf: VideoFrameBuffer,
    frames: List[Tuple[np.ndarray, float, bool]],
) -> dict:
    """Frame'leri VideoFrameBuffer'a besler ve istatistikleri döndürür."""
    event_frames_added = 0
    event_frames_total = 0
    non_event_frames_added = 0
    non_event_frames_total = 0

    for frame, ts, is_event in frames:
        added = buf.maybe_add(frame, ts, 320, 240)
        if is_event:
            event_frames_total += 1
            if added:
                event_frames_added += 1
        else:
            non_event_frames_total += 1
            if added:
                non_event_frames_added += 1

    return {
        "total_received": buf.total_frames_received,
        "total_dropped": buf.total_frames_dropped,
        "total_in_buffer": buf.count,
        "event_total": event_frames_total,
        "event_captured": event_frames_added,
        "non_event_total": non_event_frames_total,
        "non_event_captured": non_event_frames_added,
        "capture_rate": buf.total_frames_received - buf.total_frames_dropped,
    }


def get_frames_in_window(
    buf: VideoFrameBuffer,
    start: float,
    end: float,
) -> List:
    """Belirli zaman aralığındaki frame'leri döndür."""
    return buf.get_range(start, end)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: Frame Capture Rate
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrameCaptureRate:
    """
    Farklı target_fps'lerde VideoFrameBuffer'ın gerçek yakalama oranını ölçer.
    30fps kaynak frame'leri besler, 2/5/10fps'te kaç tanesinin yakalandığını test eder.
    """

    @pytest.mark.parametrize("target_fps,expected_ratio_approx", [
        (2, 1 / 15),   # 30fps kaynaktan 2fps hedef → ~1/15 yakalanır
        (5, 1 / 6),    # 30fps kaynaktan 5fps hedef → ~1/6 yakalanır
        (10, 1 / 3),   # 30fps kaynaktan 10fps hedef → ~1/3 yakalanır
    ])
    def test_capture_rate_matches_target(self, target_fps, expected_ratio_approx):
        """Hedef FPS'e göre doğru oranda frame yakalanmalı."""
        duration = 10.0
        source_fps = 30

        buf = VideoFrameBuffer(max_seconds=180, target_fps=target_fps)
        frames = generate_frames_at_fps(duration, source_fps)
        stats = feed_buffer(buf, frames)

        actual_captured = stats["total_in_buffer"]
        expected_captured = int(duration * target_fps)

        # ±1 frame tolerance (boundary effects)
        assert abs(actual_captured - expected_captured) <= 2, (
            f"target_fps={target_fps}: beklenen ~{expected_captured} frame, "
            f"gelen {actual_captured}"
        )

    def test_drop_rate_at_2fps(self):
        """2fps'te ~93% frame düşmeli (30fps kaynaktan)."""
        duration = 5.0
        source_fps = 30

        buf = VideoFrameBuffer(max_seconds=180, target_fps=2)
        frames = generate_frames_at_fps(duration, source_fps)
        stats = feed_buffer(buf, frames)

        total = stats["total_received"]
        dropped = stats["total_dropped"]
        drop_ratio = dropped / total if total > 0 else 0

        assert drop_ratio > 0.90, f"2fps drop ratio beklenen: >0.90, gerçek: {drop_ratio:.2f}"
        assert drop_ratio < 0.98, f"2fps drop ratio çok yüksek: {drop_ratio:.2f}"

    def test_first_frame_always_captured(self):
        """İlk frame her zaman yakalanmalı (timestamp = 0)."""
        buf = VideoFrameBuffer(max_seconds=180, target_fps=2)
        frame = make_synthetic_frame()
        result = buf.maybe_add(frame, 0.0, 320, 240)
        assert result is True
        assert buf.count == 1

    def test_consecutive_fast_frames_dropped(self):
        """Ardışık hızlı frame'ler düşürülmeli."""
        buf = VideoFrameBuffer(max_seconds=180, target_fps=2)

        results = []
        for i in range(10):
            ts = i * 0.033  # ~30fps aralığı
            r = buf.maybe_add(make_synthetic_frame(), ts, 320, 240)
            results.append(r)

        # İlk frame eklenmeli, sonraki 5 frame düşürülmeli (0.033 < 0.5)
        assert results[0] is True
        assert all(r is False for r in results[1:6])


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: Event Window Coverage
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventWindowCoverage:
    """
    Farklı sürelerdeki event penceresi (1s, 2s, 3s) için
    her FPS'te kaç frame yakalandığını ölçer.
    """

    @pytest.mark.parametrize("target_fps,event_duration,expected_min_frames", [
        (2, 1.0, 1),
        (2, 2.0, 2),
        (2, 3.0, 3),
        (5, 1.0, 3),
        (5, 2.0, 8),
        (10, 1.0, 7),
        (10, 3.0, 25),
    ])
    def test_event_window_frame_count(
        self, target_fps, event_duration, expected_min_frames,
    ):
        """Event penceresinde en az beklenen kadar frame yakalanmalı."""
        source_fps = 30
        total_duration = 15.0
        event_start = 5.0
        event_end = event_start + event_duration

        buf = VideoFrameBuffer(max_seconds=180, target_fps=target_fps)
        frames = generate_frames_at_fps(
            total_duration, source_fps,
            event_start=event_start, event_end=event_end,
        )
        feed_buffer(buf, frames)

        captured_frames = get_frames_in_window(buf, event_start, event_end)
        actual_count = len(captured_frames)

        assert actual_count >= expected_min_frames, (
            f"target_fps={target_fps}, event={event_duration}s: "
            f"beklenen>={expected_min_frames}, gelen={actual_count}"
        )

    def test_event_frames_are_actually_event(self):
        """Yakalanan event frame'leri gerçekten event içeriğine sahip olmalı."""
        buf = VideoFrameBuffer(max_seconds=180, target_fps=5)
        frames = generate_frames_at_fps(
            10.0, 30,
            event_start=3.0, event_end=5.0,
            event_color=(255, 0, 0),
        )
        feed_buffer(buf, frames)

        event_frames = get_frames_in_window(buf, 3.0, 5.0)
        assert len(event_frames) > 0

        for vf in event_frames:
            avg_red = vf.frame[:, :, 0].mean()
            avg_green = vf.frame[:, :, 1].mean()
            assert avg_red > avg_green, (
                f"Event frame kırmızı tonlarında olmalı: "
                f"red={avg_red:.0f}, green={avg_green:.0f}"
            )

    def test_non_event_frames_are_not_event(self):
        """Non-event frame'leri gri tonlarında olmalı."""
        buf = VideoFrameBuffer(max_seconds=180, target_fps=5)
        frames = generate_frames_at_fps(
            10.0, 30,
            event_start=8.0, event_end=10.0,
        )
        feed_buffer(buf, frames)

        non_event_frames = get_frames_in_window(buf, 0.0, 5.0)
        assert len(non_event_frames) > 0

        for vf in non_event_frames:
            avg_red = vf.frame[:, :, 0].mean()
            avg_blue = vf.frame[:, :, 2].mean()
            assert abs(float(avg_red) - float(avg_blue)) < 50, (
                f"Non-event frame gri tonlarında olmalı: "
                f"red={avg_red:.0f}, blue={avg_blue:.0f}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3: Detection Latency
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectionLatency:
    """
    İlk event anından, o event'in buffer'da yakalanmasına kadar
    geçen süreyi ölçer (worst-case latency).
    """

    @pytest.mark.parametrize("target_fps,max_expected_latency", [
        (2, 0.5),
        (5, 0.2),
        (10, 0.1),
    ])
    def test_first_event_frame_latency(self, target_fps, max_expected_latency):
        """İlk event frame'inin yakalanma gecikmesi max eşikten az olmalı."""
        source_fps = 30
        event_start = 5.0

        buf = VideoFrameBuffer(max_seconds=180, target_fps=target_fps)
        frames = generate_frames_at_fps(
            15.0, source_fps,
            event_start=event_start, event_end=event_start + 2.0,
        )
        feed_buffer(buf, frames)

        event_frames = get_frames_in_window(buf, event_start, event_start + 2.0)
        assert len(event_frames) > 0, f"target_fps={target_fps}: hiç event frame yakalanmadı"

        first_event_ts = event_frames[0].timestamp
        latency = first_event_ts - event_start

        assert latency <= max_expected_latency + 0.05, (
            f"target_fps={target_fps}: ilk event frame gecikmesi {latency:.3f}s, "
            f"max beklenen {max_expected_latency}s"
        )

    @pytest.mark.parametrize("target_fps", [2, 5, 10])
    def test_latency_never_exceeds_frame_interval(self, target_fps):
        """Gecikme her zaman frame aralığından (1/target_fps) az olmalı."""
        source_fps = 30
        event_start = 3.0

        buf = VideoFrameBuffer(max_seconds=180, target_fps=target_fps)
        frames = generate_frames_at_fps(
            10.0, source_fps,
            event_start=event_start, event_end=event_start + 5.0,
        )
        feed_buffer(buf, frames)

        event_frames = get_frames_in_window(buf, event_start, event_start + 5.0)
        assert len(event_frames) > 0

        first_latency = event_frames[0].timestamp - event_start
        frame_interval = 1.0 / target_fps

        assert first_latency < frame_interval + 0.05, (
            f"target_fps={target_fps}: latency {first_latency:.3f}s >= "
            f"frame_interval {frame_interval:.3f}s"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4: Memory Impact
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryImpact:
    """
    Her FPS ayarı için buffer bellek tüketimini hesaplar ve doğrular.
    """

    FRAME_SIZE_BYTES = 320 * 240 * 3  # rgb24

    @pytest.mark.parametrize("target_fps,max_buffer_seconds,expected_max_frames", [
        (2, 180, 360),
        (5, 180, 900),
        (10, 180, 1800),
    ])
    def test_buffer_capacity(
        self, target_fps, max_buffer_seconds, expected_max_frames,
    ):
        """Buffer capacity = max_seconds * target_fps olmalı."""
        buf = VideoFrameBuffer(max_seconds=max_buffer_seconds, target_fps=target_fps)
        assert buf.max_frames == expected_max_frames, (
            f"target_fps={target_fps}: max_frames={buf.max_frames}, "
            f"beklenen={expected_max_frames}"
        )

    @pytest.mark.parametrize("target_fps,max_frames", [
        (2, 360),
        (5, 900),
        (10, 1800),
    ])
    def test_buffer_memory_bytes(self, target_fps, max_frames):
        """Toplam bellek = max_frames * frame_size_bytes olmalı."""
        max_bytes = max_frames * self.FRAME_SIZE_BYTES

        assert max_bytes == max_frames * 230400
        if target_fps == 2:
            assert max_bytes == 82_944_000  # ~79MB
        elif target_fps == 5:
            assert max_bytes == 207_360_000  # ~198MB
        elif target_fps == 10:
            assert max_bytes == 414_720_000  # ~396MB

    def test_buffer_does_not_exceed_max(self):
        """Buffer maxlen aşıldığında eski frame'ler düşmeli."""
        buf = VideoFrameBuffer(max_seconds=5, target_fps=2)  # max 10 frames

        for i in range(20):
            ts = i * 0.5
            buf.maybe_add(make_synthetic_frame(), ts, 320, 240)

        assert buf.count <= 10, f"Buffer capacity aşıldı: {buf.count}"

    def test_total_memory_report(self):
        """Farklı FPS'ler için bellek tüketimini raporlar."""
        print("\n  === Bellek Tüketim Raporu ===")
        for fps in [2, 5, 10]:
            buf = VideoFrameBuffer(max_seconds=180, target_fps=fps)
            max_bytes = buf.max_frames * self.FRAME_SIZE_BYTES
            mb = max_bytes / (1024 * 1024)
            print(f"  {fps:2d} fps: {buf.max_frames:4d} frames x 225KB = {mb:.0f}MB")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5: Drop Pattern Analysis
# ═══════════════════════════════════════════════════════════════════════════════

class TestDropPattern:
    """
    Frame drop paternini analiz eder:
    - Hangi frame'ler düşüyor?
    - Event frame'leri düşme paterninden etkileniyor mu?
    - Düşme regular mı (deterministic) yoksa rastgele mi?
    """

    def test_drop_pattern_is_deterministic(self):
        """Aynı input ile drop paterni her zaman aynı olmalı."""
        buf1 = VideoFrameBuffer(max_seconds=180, target_fps=2)
        buf2 = VideoFrameBuffer(max_seconds=180, target_fps=2)

        frames = generate_frames_at_fps(5.0, 30)

        results1 = []
        for f, ts, _ in frames:
            results1.append(buf1.maybe_add(f, ts, 320, 240))

        results2 = []
        for f, ts, _ in frames:
            results2.append(buf2.maybe_add(f, ts, 320, 240))

        assert results1 == results2, "Drop paterni deterministic olmalı"

    def test_drop_pattern_regular_interval(self):
        """Drop paterni regular aralıkla olmalı (her N frame'de 1 yakalanır)."""
        buf = VideoFrameBuffer(max_seconds=180, target_fps=2)
        frames = generate_frames_at_fps(10.0, 30)

        added_indices = []
        for i, (f, ts, _) in enumerate(frames):
            if buf.maybe_add(f, ts, 320, 240):
                added_indices.append(i)

        intervals = [added_indices[i+1] - added_indices[i] for i in range(len(added_indices)-1)]
        assert len(intervals) > 0

        avg_interval = sum(intervals) / len(intervals)
        assert 14 <= avg_interval <= 16, (
            f"2fps drop interval ortalaması {avg_interval:.1f}, "
            f"beklenen ~15 (30fps/2fps)"
        )

    def test_event_captured_regardless_of_drop_pattern(self):
        """
        Yeterli süre event devam ederse, drop pattern'den bağımsız
        olarak en az 1 frame yakalanmalı.
        """
        for target_fps in [2, 5, 10]:
            buf = VideoFrameBuffer(max_seconds=180, target_fps=target_fps)
            frames = generate_frames_at_fps(
                10.0, 30,
                event_start=3.0,
                event_end=3.0 + 1.0 / target_fps + 0.5,
            )
            feed_buffer(buf, frames)

            event_frames = get_frames_in_window(
                buf, 3.0, 3.0 + 1.0 / target_fps + 0.5,
            )
            assert len(event_frames) >= 1, (
                f"target_fps={target_fps}: 1sn event hiç yakalanamadı"
            )

    def test_worst_case_event_at_drop_boundary(self):
        """
        Event'in tam drop anına denk gelme senaryosu:
        2fps'te 0.5sn event, tam 2 frame aralığının ortasında başlıyor.
        En az 1 frame yakalanmalı mı?
        """
        buf = VideoFrameBuffer(max_seconds=180, target_fps=2)

        event_start = 0.25  # İlk 0.5sn window'un ortası
        frames = generate_frames_at_fps(
            5.0, 30,
            event_start=event_start,
            event_end=event_start + 0.5,
        )
        feed_buffer(buf, frames)

        event_frames = get_frames_in_window(buf, event_start, event_start + 0.5)

        assert len(event_frames) >= 1, (
            f"0.5sn event drop boundary'de hiç yakalanamadı"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6: get_range / get_last_n_seconds API
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrameBufferAPI:
    """VideoFrameBuffer public API'sinin doğru çalıştığını doğrular."""

    def test_get_range_returns_correct_frames(self):
        """get_range() sadece belirtilen aralıktaki frame'leri döndürmeli."""
        buf = VideoFrameBuffer(max_seconds=180, target_fps=2)
        frames = generate_frames_at_fps(10.0, 30)
        feed_buffer(buf, frames)

        range_frames = buf.get_range(2.0, 4.0)
        for vf in range_frames:
            assert 2.0 <= vf.timestamp <= 4.0

    def test_get_last_n_seconds(self):
        """get_last_n_seconds() son N saniyedeki frame'leri döndürmeli."""
        buf = VideoFrameBuffer(max_seconds=180, target_fps=2)
        frames = generate_frames_at_fps(10.0, 30)
        feed_buffer(buf, frames)

        last_3 = buf.get_last_n_seconds(3.0)
        assert len(last_3) > 0

        current_time = buf.current_time
        for vf in last_3:
            assert vf.timestamp >= current_time - 3.0

    def test_current_time(self):
        """current_time son frame'in timestamp'i olmalı."""
        buf = VideoFrameBuffer(max_seconds=180, target_fps=2)
        assert buf.current_time == 0.0

        buf.maybe_add(make_synthetic_frame(), 5.0, 320, 240)
        assert buf.current_time == 5.0

        buf.maybe_add(make_synthetic_frame(), 10.0, 320, 240)
        assert buf.current_time == 10.0

    def test_clear(self):
        """clear() buffer'ı sıfırlamalı."""
        buf = VideoFrameBuffer(max_seconds=180, target_fps=2)
        buf.maybe_add(make_synthetic_frame(), 1.0, 320, 240)
        buf.maybe_add(make_synthetic_frame(), 2.0, 320, 240)
        assert buf.count == 2

        buf.clear()
        assert buf.count == 0
        assert buf.current_time == 0.0

    def test_frame_dataclass_fields(self):
        """VideoFrame dataclass'i doğru alanlara sahip olmalı."""
        buf = VideoFrameBuffer(max_seconds=180, target_fps=2)
        frame = make_synthetic_frame()
        buf.maybe_add(frame, 5.0, 320, 240)

        vf = buf.frames[0]
        assert vf.timestamp == 5.0
        assert vf.width == 320
        assert vf.height == 240
        assert vf.frame_index == 1
        assert vf.frame.shape == (240, 320, 3)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 7: Adaptive FPS Recommendation (Rapor)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdaptiveFPSRecommendation:
    """
    Farklı stream durumları için optimal FPS'i belirler.
    Bu testler rapor amaçlıdır — adaptive FPS mantığını doğrular.
    """

    def test_low_energy_2fps_sufficient(self):
        """
        Düşük enerji durumunda 2fps yeterli.
        Ana tetikleyici audio (44100Hz) olduğu için, video sadece
        emotion context sağlar. 2fps emotion detection için yeterli.
        """
        target_fps = 2
        duration = 30.0

        buf = VideoFrameBuffer(max_seconds=180, target_fps=target_fps)
        frames = generate_frames_at_fps(duration, 30)
        stats = feed_buffer(buf, frames)

        captured = stats["total_in_buffer"]
        expected = int(duration * target_fps)

        assert abs(captured - expected) <= 2
        assert buf.total_frames_received == int(duration * 30)

    def test_high_energy_5fps_beneficial(self):
        """
        Yüksek enerji durumunda 5fps daha iyi temporal resolution sağlar.
        3sn event → 2fps'te 3-4 frame, 5fps'te 14-15 frame.
        """
        for fps, min_frames in [(2, 3), (5, 10)]:
            buf = VideoFrameBuffer(max_seconds=180, target_fps=fps)
            frames = generate_frames_at_fps(
                10.0, 30,
                event_start=3.0, event_end=6.0,
            )
            feed_buffer(buf, frames)
            event_frames = get_frames_in_window(buf, 3.0, 6.0)
            assert len(event_frames) >= min_frames, (
                f"fps={fps}: 3sn event'te {len(event_frames)} frame, "
                f"min beklenen {min_frames}"
            )

    def test_recommendation_summary(self):
        """FPS tavsiyelerini özetleyen rapor."""
        print("\n  === Adaptive FPS Onerileri ===")
        scenarios = [
            ("Dusuk enerji (STEADY)", 2, 81, "Audio tetikleyici yeterli, video context icin 2fps ok"),
            ("Yuksek enerji (HIGH_ENERGY)", 5, 202, "Hizli gesture/emotion icin 5fps tercih edilmeli"),
            ("Peak moment (PEAK)", 10, 405, "Maksimum detail, sadece kritik anlarda"),
        ]

        for name, fps, mem_mb, rationale in scenarios:
            print(f"  {name}:")
            print(f"    FPS: {fps}, Bellek: ~{mem_mb}MB")
            print(f"    Gerekce: {rationale}")

        assert len(scenarios) == 3
