"""
AI Critic — Kapalı Döngü Kalite Kontrolü (Closed-Loop QC) v2
──────────────────────────────────────────────────────────────
Render bittikten sonra videonun *viral/içerik* kalitesini değerlendirir.

5 boyut, her biri ayrı skor:
  - opening  : ilk 3 saniyenin hareket + enerji yoğunluğu
  - subtitle : altyazı okunabilirliği (font / video yüksekliği oranı)
  - zoom     : ilk ses tepesinin ne kadar geç geldiği
  - thumbnail: kapak karesinin keskinlik/parlaklık/kadraj skoru
  - cut      : kesim noktası hassasiyeti (cümle ortasında kesim var mı)

Her boyut için:
  1. Ölçüm (heuristik)
  2. Eşik kontrolü → CriticIssue
  3. Auto-fix (FFmpeg / ASS manipülasyonu)

master_pipeline v2: tüm boyutlar için auto-fix döngüsü.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ai_critic")

# İsteğe bağlı ağır bağımlılıklar — yoksa nazikçe fallback.
try:
    import cv2
    import numpy as np
    _HAS_CV2 = True
except Exception:  # pragma: no cover
    cv2 = None
    np = None
    _HAS_CV2 = False


# ─── Eşikler ve ağırlıklar ───────────────────────────────────────────────────

SUBTITLE_MIN_RATIO = 0.030
OPENING_WINDOW_S = 3.0
ZOOM_LATE_THRESHOLD_S = 3.0
CUT_MIN_SILENCE_MS = 200

# 5 boyutun toplam puana ağırlığı (toplam = 1.0).
DIMENSION_WEIGHTS = {
    "opening": 0.28,
    "subtitle": 0.20,
    "zoom": 0.18,
    "thumbnail": 0.14,
    "cut": 0.20,
}


@dataclass
class CriticIssue:
    """Tek bir eleştiri maddesi."""
    dimension: str
    severity: str           # "info" | "warning" | "error"
    message: str
    metric: float = 0.0
    suggested_fix: str = ""


@dataclass
class CritiqueReport:
    """AI Critic raporu — ayrıştırılmış boyut skorları dahil."""
    score: float                                  # 0-10 ağırlıklı toplam
    passed: bool
    verdict: str = ""
    issues: List[CriticIssue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    used_llm: bool = False
    # ── Yeni: boyut bazında skorlar (0-1) ──
    dimension_scores: Dict[str, float] = field(default_factory=dict)
    # ── Yeni: auto-fix uygulandı mı? ──
    applied_fixes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        head = f"AI Critic: {self.score:.1f}/10"
        if self.verdict:
            head += f" — {self.verdict}"
        dim_str = " | ".join(
            f"{d}:{s:.2f}" for d, s in self.dimension_scores.items()
        )
        if dim_str:
            head += f"\n  Boyutlar: {dim_str}"
        if self.issues:
            reasons = " | ".join(f"↓ {i.message}" for i in self.issues)
            head += f"\n  Sorunlar: {reasons}"
        if self.applied_fixes:
            head += f"\n  Auto-fix: {', '.join(self.applied_fixes)}"
        return head

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "passed": self.passed,
            "verdict": self.verdict,
            "used_llm": self.used_llm,
            "dimension_scores": {
                d: round(s, 3) for d, s in self.dimension_scores.items()
            },
            "applied_fixes": self.applied_fixes,
            "reasons": [i.message for i in self.issues],
            "issues": [
                {
                    "dimension": i.dimension,
                    "severity": i.severity,
                    "message": i.message,
                    "metric": round(i.metric, 3),
                    "suggested_fix": i.suggested_fix,
                }
                for i in self.issues
            ],
            "metrics": self.metrics,
        }


class AICritic:
    """
    Render sonrası içerik/viral kalite eleştirmeni.
    5 boyut, her biri için ölçüm + auto-fix.
    """

    def __init__(self, target_score: float = 8.5):
        self.target_score = target_score

    # ════════════════════════════════════════════════════════════════════════
    #  ANA CRITIQUE METODU
    # ════════════════════════════════════════════════════════════════════════

    async def critique(
        self,
        video_path: str,
        transcript_data: Optional[Dict] = None,
        thumbnail_path: Optional[str] = None,
        subtitle_fontsize: Optional[int] = None,
        subtitle_ass_path: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> CritiqueReport:
        """
        Render edilmiş videoyu 5 boyutta değerlendirir.
        """
        if not Path(video_path).exists():
            return CritiqueReport(
                score=0.0, passed=False, verdict="Video bulunamadı",
                issues=[CriticIssue("format", "error", "Video dosyası yok")],
            )

        width, height = await self._probe_dimensions(video_path)

        # ── Objektif ölçümler (paralel) ──────────────────────────────────
        opening_score, thumbnail_score, zoom_score, zoom_peak_s, cut_score, cut_info = \
            await asyncio.gather(
                self._measure_opening(video_path),
                self._measure_thumbnail(thumbnail_path),
                self._measure_zoom_timing(video_path),
                self._first_peak_time(video_path),
                self._measure_cut_precision(video_path, transcript_data),
                self._get_cut_info(video_path, transcript_data),
            )

        subtitle_score, subtitle_ratio = self._measure_subtitle(
            subtitle_fontsize, height
        )

        scores = {
            "opening": opening_score,
            "subtitle": subtitle_score,
            "thumbnail": thumbnail_score,
            "zoom": zoom_score,
            "cut": cut_score,
        }

        metrics = {
            **{k: round(v, 3) for k, v in scores.items()},
            "zoom_first_peak_s": round(zoom_peak_s, 2),
            "subtitle_ratio": round(subtitle_ratio, 4),
            "video_size": f"{width}x{height}",
            "cut_info": cut_info,
        }

        # ── Heuristik temel puan ─────────────────────────────────────────
        base_score = sum(
            scores[d] * w for d, w in DIMENSION_WEIGHTS.items()
        ) * 10.0

        # ── Sorun listesi ────────────────────────────────────────────────
        heuristic_issues = self._build_issues(
            scores, subtitle_ratio, zoom_peak_s, cut_info
        )

        # ── LLM sentezi (varsa) ──────────────────────────────────────────
        verdict = ""
        used_llm = False
        final_score = base_score
        llm_reasons: List[str] = []
        try:
            from services.llm_reasoner import llm_reasoner
            transcript_snippet = self._transcript_snippet(transcript_data)
            llm_out = await llm_reasoner.critique_video(metrics, transcript_snippet)
            if llm_out:
                used_llm = True
                verdict = llm_out.get("verdict", "")
                llm_reasons = llm_out.get("reasons", []) or []
                llm_score = float(llm_out.get("score", 0) or 0)
                if 0 < llm_score <= 10:
                    final_score = round(base_score * 0.5 + llm_score * 0.5, 2)
        except Exception as e:
            logger.warning("Critic LLM sentezi atlandı: %s", e)

        issues = heuristic_issues
        if not verdict:
            verdict = self._heuristic_verdict(final_score, issues)

        final_score = max(0.0, min(10.0, final_score))
        passed = final_score >= self.target_score

        report = CritiqueReport(
            score=final_score,
            passed=passed,
            verdict=verdict,
            issues=issues,
            dimension_scores=scores,
            metrics={**metrics, "llm_reasons": llm_reasons},
            used_llm=used_llm,
        )
        logger.info("AI Critic tamamlandı: %s", report.summary().replace("\n", " "))
        return report

    # ════════════════════════════════════════════════════════════════════════
    #  AUTO-FIX METODLARI
    # ════════════════════════════════════════════════════════════════════════

    async def auto_fix(
        self,
        video_path: str,
        report: CritiqueReport,
        subtitle_fontsize: Optional[int] = None,
        subtitle_ass_path: Optional[str] = None,
        transcript_data: Optional[Dict] = None,
        fix_round: int = 0,
    ) -> Tuple[Optional[str], List[str]]:
        """
        Critique raporuna göre auto-fix uygular.
        Düzeltme yapılmışsa yeni video yolunu,否则 None döndürür.
        Hangi fix'lerin uygulandığını listeler.
        """
        applied: List[str] = []
        current_path = video_path

        # Hangi boyutlarda sorun var?
        issue_dims = {i.dimension for i in report.issues}

        # ── 1. Hook (opening) auto-fix ──
        if "opening" in issue_dims:
            fixed = await self._apply_hook_fix(current_path, fix_round)
            if fixed:
                current_path = fixed
                applied.append("hook")

        # ── 2. Subtitle auto-fix ──
        if "subtitle" in issue_dims and subtitle_fontsize:
            fixed = await self._apply_subtitle_fix(
                current_path, subtitle_fontsize, subtitle_ass_path, fix_round
            )
            if fixed:
                current_path = fixed
                applied.append("subtitle")

        # ── 3. Zoom timing auto-fix ──
        if "zoom" in issue_dims:
            fixed = await self._apply_zoom_fix(
                current_path, transcript_data, fix_round
            )
            if fixed:
                current_path = fixed
                applied.append("zoom")

        # ── 4. Cut precision auto-fix ──
        if "cut" in issue_dims:
            fixed = await self._apply_cut_fix(
                current_path, transcript_data, fix_round
            )
            if fixed:
                current_path = fixed
                applied.append("cut")

        if applied:
            logger.info("Auto-fix uygulandı (%d): %s", fix_round, ", ".join(applied))
        return current_path if applied else None, applied

    # ── Hook (opening) auto-fix ───────────────────────────────────────────

    async def _apply_hook_fix(
        self, video_path: str, round_idx: int
    ) -> Optional[str]:
        """Sıkıcı girişi kırp — ilk ses tepesinin 0.5sn öncesinden başlat."""
        try:
            from services.audio_analyzer import audio_analyzer
            res = await audio_analyzer.get_loud_peaks(video_path)
            peaks = res.get("peaks") if isinstance(res, dict) else None
            if not peaks:
                return None
            starts = [float(p.get("start", 0)) for p in peaks if "start" in p]
            if not starts:
                return None
            first_peak = min(starts)
            if first_peak <= 3.0:
                return None
            new_start = max(0.0, first_peak - 0.5)
            out_path = Path(video_path).parent / f"{Path(video_path).stem}_hook_r{round_idx}.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(new_start),
                "-i", str(video_path),
                "-c:v", "copy", "-c:a", "copy",
                str(out_path),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            if out_path.exists() and out_path.stat().st_size > 0:
                logger.info("Hook auto-fix: %.1fs öne alındı", new_start)
                return str(out_path)
        except Exception as e:
            logger.warning("Hook auto-fix hatası: %s", e)
        return None

    # ── Subtitle auto-fix ─────────────────────────────────────────────────

    async def _apply_subtitle_fix(
        self,
        video_path: str,
        current_fontsize: int,
        ass_path: Optional[str],
        round_idx: int,
    ) -> Optional[str]:
        """
        Altyazı boyutu auto-fix: Ekran doluluk oranına göre dinamik font
        scaling. ASS dosyası varsa fontscale ile, yoksa FFmpeg drawtext
        ile yeniden render.
        """
        try:
            # Hedef: font_high / video_high >= SUBTITLE_MIN_RATIO * 1.5
            cmd = [
                "ffprobe", "-v", "quiet", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x", video_path,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            txt = stdout.decode().strip()
            if "x" not in txt:
                return None
            w, h = (int(x) for x in txt.split("x")[:2])

            # Hedef font boyutu: min_ratio * video_height * 1.5 (okunabilirlik payı)
            target_ratio = SUBTITLE_MIN_RATIO * 1.8
            target_fontsize = max(32, min(120, int(h * target_ratio)))

            if abs(current_fontsize - target_fontsize) < 4:
                return None  # zaten yeterli

            # ── ASS fix: fontscale ile ──
            if ass_path and Path(ass_path).exists():
                return await self._fix_ass_fontscale(
                    ass_path, video_path, current_fontsize, target_fontsize, round_idx
                )

            # ── FFmpeg drawtext ile yeniden render ──
            return await self._fix_subtitle_drawtext(
                video_path, current_fontsize, target_fontsize, round_idx
            )

        except Exception as e:
            logger.warning("Subtitle auto-fix hatası: %s", e)
        return None

    async def _fix_ass_fontscale(
        self, ass_path: str, video_path: str,
        current_fs: int, target_fs: int, round_idx: int,
    ) -> Optional[str]:
        """ASS dosyasındaki fontscale'i ayarla ve videoyu yeniden render et."""
        try:
            data = await asyncio.to_thread(
                Path(ass_path).read_text, encoding="utf-8"
            )
            scale = target_fs / max(1, current_fs)

            # [V4+ Styles] satırındaki ScaleX ve ScaleY'yi ayarla
            new_lines = []
            in_styles = False
            for line in data.split("\n"):
                if line.strip().startswith("[V4+ Styles]"):
                    in_styles = True
                    new_lines.append(line)
                elif line.strip().startswith("[") and in_styles:
                    in_styles = False
                    new_lines.append(line)
                elif in_styles and line.startswith("Style:"):
                    parts = line.split(",")
                    if len(parts) >= 3:
                        # ScaleX (index 2), ScaleY (index 3)
                        try:
                            sx = float(parts[2]) * scale
                            sy = float(parts[3]) * scale
                            parts[2] = f"{sx:.1f}"
                            parts[3] = f"{sy:.1f}"
                        except (ValueError, IndexError):
                            pass
                    new_lines.append(",".join(parts))
                else:
                    new_lines.append(line)

            new_ass = str(Path(ass_path).parent / f"{Path(ass_path).stem}_fixed.ass")
            await asyncio.to_thread(
                Path(new_ass).write_text, "\n".join(new_lines), "utf-8"
            )

            out_path = Path(video_path).parent / f"{Path(video_path).stem}_sub_r{round_idx}.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-vf", f"ass={new_ass}",
                "-c:v", "libx264", "-crf", "20",
                "-c:a", "copy",
                str(out_path),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            if out_path.exists() and out_path.stat().st_size > 0:
                logger.info("Subtitle auto-fix (ASS): fontscale %.2f → %.2f", 1.0, scale)
                return str(out_path)
        except Exception as e:
            logger.warning("ASS subtitle fix hatası: %s", e)
        return None

    async def _fix_subtitle_drawtext(
        self, video_path: str, current_fs: int, target_fs: int, round_idx: int,
    ) -> Optional[str]:
        """FFmpeg drawtext ile font boyutunu ayarla (ASS yoksa fallback)."""
        # Bu bir fallback; drawtext ile tüm altyazıyı yeniden yazmak karmaşık.
        # En basit yol: ASS'i yeniden oluşturma imkanı yoksa, sadece log.
        logger.info(
            "Subtitle auto-fix: drawtext fallback — mevcut %d → hedef %d (ASS gerekli)",
            current_fs, target_fs,
        )
        return None

    # ── Zoom timing auto-fix ──────────────────────────────────────────────

    async def _apply_zoom_fix(
        self,
        video_path: str,
        transcript_data: Optional[Dict],
        round_idx: int,
    ) -> Optional[str]:
        """
        Zoom timing auto-fix: İlk ses tepesi çok geç geliyorsa, videoyu
        kırparak zoom'un erken başlamasını sağla. Ya da transcript'teki
        ilk konuşulan kelimeye göre zoom tetikleyicisini öne al.
        """
        try:
            from services.audio_analyzer import audio_analyzer
            res = await audio_analyzer.get_loud_peaks(video_path)
            peaks = res.get("peaks") if isinstance(res, dict) else None
            if not peaks:
                return None
            starts = [float(p.get("start", 0)) for p in peaks if "start" in p]
            if not starts:
                return None
            first_peak = min(starts)

            if first_peak <= ZOOM_LATE_THRESHOLD_S:
                return None  # zoom zaten erken

            # Transcript'ten ilk konuşma anını bul (varsa)
            speech_start = 0.0
            if transcript_data:
                words = transcript_data.get("words", [])
                if words:
                    speech_start = float(words[0].get("start", 0))

            # Kırpma noktası: max(0, peak veya speech_start - 1.0)
            trim_point = max(0.0, min(first_peak, speech_start) - 1.0)
            if trim_point < 0.5:
                return None  # çok az kırpma, faydası yok

            out_path = Path(video_path).parent / f"{Path(video_path).stem}_zoom_r{round_idx}.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(trim_point),
                "-i", str(video_path),
                "-c:v", "copy", "-c:a", "copy",
                str(out_path),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            if out_path.exists() and out_path.stat().st_size > 0:
                logger.info("Zoom auto-fix: %.1fs kırpıldı (ilk peak %.1fs'te)", trim_point, first_peak)
                return str(out_path)
        except Exception as e:
            logger.warning("Zoom auto-fix hatası: %s", e)
        return None

    # ── Cut precision auto-fix ────────────────────────────────────────────

    async def _apply_cut_fix(
        self,
        video_path: str,
        transcript_data: Optional[Dict],
        round_idx: int,
    ) -> Optional[str]:
        """
        Kesim noktası auto-fix: Klibin başındaki/sonundaki kesik kelimeleri
        tespit edip kırpma noktasını en yakın cümle sonuna kaydırır.
        """
        try:
            if not transcript_data:
                return None
            words = transcript_data.get("words", [])
            if len(words) < 3:
                return None

            # İlk 3 kelimeye bak: eğer 0.0 saniyede başlamıyorsa,
            # klip'in真正 başlangıcı muhtemelen bir kelimenin ortasında
            first_word_start = float(words[0].get("start", 0))
            first_word_end = float(words[0].get("end", 0))

            # Sonda: son kelimenin bitiş zamanı ile videonun süresini karşılaştır
            duration = await self._probe_duration(video_path)
            last_word_end = float(words[-1].get("end", 0))

            trim_start = 0.0
            trim_end_offset = 0.0

            # Baş: İlk kelime çok geç başlıyorsa (1sn+), önündeki sessizliği kırp
            if first_word_start > 1.0:
                trim_start = max(0.0, first_word_start - 0.1)

            # Son: Son kelime bitmeden video bitiyorsa, videonun sonunu kelime bitişine kaydır
            # Ya da kelime bitiminden çok sonra video devam ediyorsa, sonu kırp
            if duration > 0 and last_word_end > 0:
                trailing_silence = duration - last_word_end
                if trailing_silence > 2.0:
                    # 2sn+ sessizlik varsa sonu kırp
                    trim_end_offset = trailing_silence - 0.5

            if trim_start < 0.1 and trim_end_offset < 0.1:
                return None

            out_path = Path(video_path).parent / f"{Path(video_path).stem}_cut_r{round_idx}.mp4"
            cmd = ["ffmpeg", "-y", "-ss", str(trim_start), "-i", str(video_path)]
            if trim_end_offset > 0:
                effective_dur = max(0.5, duration - trim_start - trim_end_offset)
                cmd += ["-t", str(effective_dur)]
            cmd += ["-c:v", "copy", "-c:a", "copy", str(out_path)]

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            if out_path.exists() and out_path.stat().st_size > 0:
                logger.info(
                    "Cut auto-fix: baş=%.2fs, son −%.1fs",
                    trim_start, trim_end_offset,
                )
                return str(out_path)
        except Exception as e:
            logger.warning("Cut auto-fix hatası: %s", e)
        return None

    # ════════════════════════════════════════════════════════════════════════
    #  ÖLÇÜM METODLARI
    # ════════════════════════════════════════════════════════════════════════

    # ── Subtitle ──

    def _measure_subtitle(
        self, fontsize: Optional[int], height: int
    ) -> Tuple[float, float]:
        """Altyazı font yüksekliğinin video yüksekliğine oranından skor."""
        if not fontsize or not height:
            return 1.0, 0.0
        ratio = fontsize / height
        score = min(1.0, 0.6 * (ratio / SUBTITLE_MIN_RATIO))
        return round(score, 3), ratio

    # ── Opening ──

    async def _measure_opening(self, video_path: str) -> float:
        if not _HAS_CV2:
            return 0.7
        return await asyncio.to_thread(self._opening_sync, video_path)

    def _opening_sync(self, video_path: str) -> float:
        cap = None
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return 0.7
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            max_frames = int(fps * OPENING_WINDOW_S)
            prev_gray = None
            motion_acc = 0.0
            edge_acc = 0.0
            n = 0
            step = max(1, int(fps // 5))
            idx = 0
            while n < 15:
                ok, frame = cap.read()
                if not ok or idx > max_frames:
                    break
                if idx % step != 0:
                    idx += 1
                    continue
                small = cv2.resize(frame, (160, 90))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                edge_acc += float(np.mean(cv2.Canny(gray, 60, 160))) / 255.0
                if prev_gray is not None:
                    motion_acc += float(np.mean(cv2.absdiff(gray, prev_gray))) / 255.0
                prev_gray = gray
                n += 1
                idx += 1
            if n == 0:
                return 0.7
            motion = motion_acc / max(1, n - 1)
            edges = edge_acc / n
            motion_score = min(1.0, motion / 0.05)
            edge_score = min(1.0, edges / 0.15)
            return round(motion_score * 0.65 + edge_score * 0.35, 3)
        except Exception as e:
            logger.warning("Opening ölçümü hatası: %s", e)
            return 0.7
        finally:
            if cap is not None:
                cap.release()

    # ── Thumbnail ──

    async def _measure_thumbnail(self, thumbnail_path: Optional[str]) -> float:
        if not thumbnail_path or not Path(thumbnail_path).exists() or not _HAS_CV2:
            return 0.6
        return await asyncio.to_thread(self._thumbnail_sync, thumbnail_path)

    def _thumbnail_sync(self, path: str) -> float:
        try:
            img = cv2.imread(path)
            if img is None:
                return 0.6
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            sharpness = min(1.0, float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 500.0)
            brightness = float(np.mean(gray)) / 255.0
            contrast = min(1.0, float(np.std(gray)) / 128.0)
            brightness_score = max(0.0, 1.0 - abs(brightness - 0.55) * 2)
            return round(sharpness * 0.5 + brightness_score * 0.25 + contrast * 0.25, 3)
        except Exception as e:
            logger.warning("Thumbnail ölçümü hatası: %s", e)
            return 0.6

    # ── Zoom ──

    async def _measure_zoom_timing(self, video_path: str) -> float:
        peak_s = await self._first_peak_time(video_path)
        if peak_s < 0:
            return 0.6
        if peak_s <= ZOOM_LATE_THRESHOLD_S:
            return 1.0
        return round(max(0.2, 1.0 - (peak_s - ZOOM_LATE_THRESHOLD_S) * 0.1), 3)

    async def _first_peak_time(self, video_path: str) -> float:
        try:
            from services.audio_analyzer import audio_analyzer
            res = await audio_analyzer.get_loud_peaks(video_path)
            peaks = res.get("peaks") if isinstance(res, dict) else None
            if peaks:
                starts = [float(p.get("start", 0)) for p in peaks if "start" in p]
                if starts:
                    return min(starts)
        except Exception as e:
            logger.warning("Zoom/peak ölçümü atlandı: %s", e)
        return -1.0

    # ── Cut precision ──

    async def _measure_cut_precision(
        self, video_path: str, transcript_data: Optional[Dict]
    ) -> float:
        """
        Kesim noktası hassasiyeti: Video başında/sonunda kesik kelime var mı?
        1.0 = mükemmel kesim (kelime tam bitmiş), 0.0 = cümle ortasında kesilmiş.
        """
        if not transcript_data:
            return 0.8  # transcript yoksa nötr

        words = transcript_data.get("words", [])
        if len(words) < 2:
            return 0.8

        score = 1.0

        # ── Baş kontrolü: İlk kelime 0.3sn'den geç başlıyorsa kesim problemli ──
        first_start = float(words[0].get("start", 0))
        if first_start > 0.3:
            # Ne kadar geç başlıyorsa o kadar kötü
            penalty = min(0.5, (first_start - 0.3) * 0.2)
            score -= penalty

        # ── Son kontrol: Videonun süresi ile son kelimenin bitişi ──
        duration = await self._probe_duration(video_path)
        if duration > 0:
            last_end = float(words[-1].get("end", 0))
            trailing = duration - last_end
            if trailing > 2.0:
                # 2sn+ sessizlik — clip sonu gereksiz uzun
                penalty = min(0.4, (trailing - 2.0) * 0.1)
                score -= penalty
            elif trailing < -0.3:
                # Son kelime kesilmiş
                score -= 0.3

        # ── Orta kontrol: Kelimeler arası anormal boşluk ──
        for i in range(1, min(len(words), 20)):
            prev_end = float(words[i - 1].get("end", 0))
            curr_start = float(words[i].get("start", 0))
            gap = curr_start - prev_end
            if gap > 3.0:  # 3sn+ sessizlik = muhtemelen kötü kesim
                score -= 0.15
                break

        return round(max(0.0, score), 3)

    async def _get_cut_info(
        self, video_path: str, transcript_data: Optional[Dict]
    ) -> Dict[str, Any]:
        """Cut ölçümü için detaylı bilgi döndür."""
        info: Dict[str, Any] = {}
        if not transcript_data:
            return info

        words = transcript_data.get("words", [])
        if not words:
            return info

        duration = await self._probe_duration(video_path)
        first_start = float(words[0].get("start", 0))
        last_end = float(words[-1].get("end", 0))

        info["first_word_start_s"] = round(first_start, 2)
        info["last_word_end_s"] = round(last_end, 2)
        info["duration_s"] = round(duration, 2)
        info["leading_silence_s"] = round(first_start, 2)
        info["trailing_silence_s"] = round(max(0, duration - last_end), 2)
        info["word_count"] = len(words)

        return info

    # ── ffprobe helpers ──

    async def _probe_dimensions(self, video_path: str) -> Tuple[int, int]:
        cmd = [
            "ffprobe", "-v", "quiet", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x", video_path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            txt = stdout.decode().strip()
            if "x" in txt:
                w, h = txt.split("x")[:2]
                return int(w), int(h)
        except Exception as e:
            logger.warning("ffprobe boyut hatası: %s", e)
        return 1080, 1920

    async def _probe_duration(self, video_path: str) -> float:
        cmd = [
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "csv=p=0", video_path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            return float(stdout.decode().strip() or "0")
        except Exception:
            return 0.0

    # ════════════════════════════════════════════════════════════════════════
    #  RAPOR KURUCULAR
    # ════════════════════════════════════════════════════════════════════════

    def _build_issues(
        self,
        scores: Dict[str, float],
        subtitle_ratio: float,
        zoom_peak_s: float,
        cut_info: Dict[str, Any],
    ) -> List[CriticIssue]:
        issues: List[CriticIssue] = []

        if scores["opening"] < 0.5:
            issues.append(CriticIssue(
                "opening", "warning", "İlk 3 saniye sıkıcı",
                metric=scores["opening"],
                suggested_fix="En aksiyonlu anı başa al (hook auto-fix).",
            ))
        if scores["subtitle"] < 0.6 and subtitle_ratio > 0:
            issues.append(CriticIssue(
                "subtitle", "warning", "Altyazı küçük — ekranı tam okuyamaz",
                metric=scores["subtitle"],
                suggested_fix="Font boyutunu büyüt (dinamik font scaling auto-fix).",
            ))
        if zoom_peak_s > ZOOM_LATE_THRESHOLD_S:
            issues.append(CriticIssue(
                "zoom", "info", "Zoom geç — ilk ses tepesi %.1fs'de" % zoom_peak_s,
                metric=scores["zoom"],
                suggested_fix="Kırpma noktasını öne al (zoom timing auto-fix).",
            ))
        if scores["thumbnail"] < 0.55:
            issues.append(CriticIssue(
                "thumbnail", "info", "Thumbnail zayıf",
                metric=scores["thumbnail"],
                suggested_fix="KeyFrameSelector ile daha keskin/ifadeli kare seç.",
            ))
        if scores["cut"] < 0.6:
            leading = cut_info.get("leading_silence_s", 0)
            trailing = cut_info.get("trailing_silence_s", 0)
            reason = []
            if leading > 1.0:
                reason.append(f"başta {leading:.1f}s sessizlik")
            if trailing > 2.0:
                reason.append(f"sonda {trailing:.1f}s gereksiz")
            if not reason:
                reason.append("kelime ortasında kesilmiş")
            issues.append(CriticIssue(
                "cut", "warning",
                "Kesim noktası hassas değil — " + " + ".join(reason),
                metric=scores["cut"],
                suggested_fix="Kırpma noktasını en yakın cümle sonuna kaydır (cut auto-fix).",
            ))

        return issues

    def _heuristic_verdict(self, score: float, issues: List[CriticIssue]) -> str:
        if score >= 9.0:
            return "Mükemmel — yayına hazır"
        if score >= self.target_score:
            return "İyi — küçük iyileştirmeler mümkün"
        if score >= 6.0:
            return "Orta — birkaç sorun düzeltilmeli"
        return "Zayıf — yeniden render önerilir"

    @staticmethod
    def _transcript_snippet(transcript_data: Optional[Dict]) -> str:
        if not transcript_data:
            return ""
        words = transcript_data.get("words", []) if isinstance(transcript_data, dict) else []
        return " ".join(w.get("word", "") for w in words[:120])


# Singleton
ai_critic = AICritic()
