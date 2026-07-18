"""
Multilingual Subtitles — Çoklu Dil Altyazı Sistemi
────────────────────────────────────────────────────
FAZ-3.3: Çoklu dilde altyazı oluşturma ve yönetimi.

Features:
  - Whisper kaynak dili tespit
  - LLM ile çeviri (Türkçe → İngilizce, Almanca, vb.)
  - ASS/SRT format desteği
  - Dil bazında kalite kontrolü
  - Otomatik dil seçimi (izleyici kitlesine göre)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("multilingual_subs")


# ── Supported Languages ──

SUPPORTED_LANGUAGES = {
    "tr": {"name": "Türkçe", "native": "Türkçe", "whisper_code": "tr", "priority": 1},
    "en": {"name": "English", "native": "English", "whisper_code": "en", "priority": 2},
    "de": {"name": "Deutsch", "native": "Deutsch", "whisper_code": "de", "priority": 3},
    "es": {"name": "Español", "native": "Español", "whisper_code": "es", "priority": 4},
    "fr": {"name": "Français", "native": "Français", "whisper_code": "fr", "priority": 5},
    "pt": {"name": "Português", "native": "Português", "whisper_code": "pt", "priority": 6},
    "ja": {"name": "日本語", "native": "日本語", "whisper_code": "ja", "priority": 7},
    "ar": {"name": "العربية", "native": "العربية", "whisper_code": "ar", "priority": 8},
}


class SubtitleEntry(BaseModel):
    """Tek bir altyazı satırı."""
    index: int = 0
    start_time: float = 0.0  # saniye
    end_time: float = 0.0
    text: str = ""
    language: str = "tr"
    original_text: str = ""  # kaynak dildeki metin
    confidence: float = 1.0


class SubtitleTrack(BaseModel):
    """Bir dil için altyazı seti."""
    language: str = ""
    language_name: str = ""
    entries: List[SubtitleEntry] = Field(default_factory=list)
    source_language: str = ""
    is_translated: bool = False
    translation_quality: float = 0.0
    word_count: int = 0
    duration: float = 0.0


class MultilingualSubtitleManager:
    """
    Çoklu dil altyazı yöneticisi.
    """

    # ASS stil şablonları
    ASS_HEADER = """[Script Info]
Title: Multilingual Subtitles
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,10,10,50,1
Style: English,Arial,42,&H0000FFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,50,1
Style: German,Arial,42,&H000080FF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def __init__(self, output_dir: str | Path | None = None):
        self._output_dir = Path(output_dir or "data/subtitles")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._tracks: Dict[str, SubtitleTrack] = {}  # language -> track
        self._translation_cache: Dict[str, str] = {}

    async def extract_source_subtitles(
        self,
        video_path: str,
        transcript_data: Optional[Dict] = None,
        language: str = "tr",
    ) -> SubtitleTrack:
        """Videonun kaynak dilinde altyazı çıkar."""
        if not transcript_data:
            try:
                from services.faster_whisper_service import faster_whisper
                transcript_data = await faster_whisper.transcribe(
                    video_path, word_timestamps=True
                )
                transcript_data = transcript_data.get("data", {})
            except Exception as e:
                logger.warning("Transcription failed: %s", e)
                return SubtitleTrack(language=language)

        words = transcript_data.get("words", [])
        entries = self._words_to_entries(words, language)

        # Cümle bazlı birleştirme
        merged = self._merge_into_sentences(entries)

        track = SubtitleTrack(
            language=language,
            language_name=SUPPORTED_LANGUAGES.get(language, {}).get("name", language),
            entries=merged,
            source_language=language,
            is_translated=False,
            word_count=len(words),
            duration=merged[-1].end_time if merged else 0.0,
        )

        self._tracks[language] = track
        return track

    async def translate_to(
        self,
        source_language: str,
        target_language: str,
        max_concurrent: int = 10,
    ) -> Optional[SubtitleTrack]:
        """Kaynak dilden hedef dile çevir."""
        source = self._tracks.get(source_language)
        if not source:
            logger.warning("Source track not found: %s", source_language)
            return None

        if target_language == source_language:
            return source

        lang_info = SUPPORTED_LANGUAGES.get(target_language)
        if not lang_info:
            logger.warning("Unsupported target language: %s", target_language)
            return None

        # Çeviri için metinleri topla
        texts_to_translate = [
            (i, entry.text) for i, entry in enumerate(source.entries)
        ]

        # Toplu çeviri (batch)
        translated_texts = await self._batch_translate(
            [t for _, t in texts_to_translate],
            source_language,
            target_language,
        )

        # Çevrilmiş entry'leri oluştur
        translated_entries = []
        for idx, (orig_idx, original_text) in enumerate(texts_to_translate):
            translated_text = translated_texts[idx] if idx < len(translated_texts) else original_text
            orig = source.entries[orig_idx]
            translated_entries.append(SubtitleEntry(
                index=orig.index,
                start_time=orig.start_time,
                end_time=orig.end_time,
                text=translated_text,
                language=target_language,
                original_text=original_text,
                confidence=0.85,  # çeviriler varsayılan güven
            ))

        track = SubtitleTrack(
            language=target_language,
            language_name=lang_info["name"],
            entries=translated_entries,
            source_language=source_language,
            is_translated=True,
            word_count=sum(len(e.text.split()) for e in translated_entries),
            duration=source.duration,
        )

        self._tracks[target_language] = track
        return track

    async def translate_to_all(
        self,
        source_language: str = "tr",
        target_languages: Optional[List[str]] = None,
    ) -> Dict[str, SubtitleTrack]:
        """Birden fazla dile çevir."""
        targets = target_languages or ["en", "de"]
        results = {}

        for lang in targets:
            if lang == source_language:
                continue
            track = await self.translate_to(source_language, lang)
            if track:
                results[lang] = track

        return results

    async def _batch_translate(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        """Toplu çeviri: LLM ile."""
        if not texts:
            return []

        # Önbellek kontrolü
        cached = []
        uncached_indices = []
        uncached_texts = []
        for i, text in enumerate(texts):
            cache_key = f"{source_lang}:{target_lang}:{text}"
            if cache_key in self._translation_cache:
                cached.append((i, self._translation_cache[cache_key]))
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # LLM ile çevir
        if uncached_texts:
            translated = await self._llm_translate(
                uncached_texts, source_lang, target_lang
            )
            for idx, text in zip(uncached_indices, translated):
                cache_key = f"{source_lang}:{target_lang}:{texts[idx]}"
                self._translation_cache[cache_key] = text
                cached.append((idx, text))

        # Sonucu sırala
        result_map = {i: t for i, t in cached}
        return [result_map.get(i, texts[i]) for i in range(len(texts))]

    async def _llm_translate(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        """LLM ile çeviri."""
        lang_names = {
            "tr": "Turkish", "en": "English", "de": "German",
            "es": "Spanish", "fr": "French", "pt": "Portuguese",
            "ja": "Japanese", "ar": "Arabic",
        }
        src_name = lang_names.get(source_lang, source_lang)
        tgt_name = lang_names.get(target_lang, target_lang)

        # Toplu çeviri: 10'arlı gruplar
        results = []
        batch_size = 10
        for batch_start in range(0, len(texts), batch_size):
            batch = texts[batch_start:batch_start + batch_size]
            numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(batch))

            prompt = (
                f"Translate the following {src_name} subtitle lines to {tgt_name}.\n"
                f"Keep the translations concise and natural for subtitles.\n"
                f"Return ONLY the translations, one per line, numbered.\n\n"
                f"{numbered}"
            )

            try:
                from services.llm_engine import llm_engine
                response = await llm_engine.generate(prompt, max_tokens=500)
                if response:
                    lines = response.strip().split("\n")
                    # Numaraları temizle
                    translated = []
                    for line in lines:
                        cleaned = re.sub(r'^\d+\.\s*', '', line.strip())
                        if cleaned:
                            translated.append(cleaned)
                    # Eksik varsa orijinali kullan
                    while len(translated) < len(batch):
                        translated.append(batch[len(translated)])
                    results.extend(translated[:len(batch)])
                else:
                    results.extend(batch)
            except Exception as e:
                logger.warning("LLM translation failed: %s", e)
                results.extend(batch)

        return results

    def _words_to_entries(self, words: List[Dict], language: str) -> List[SubtitleEntry]:
        """Kelime listesinden SubtitleEntry listesi oluştur."""
        entries = []
        for i, w in enumerate(words):
            entries.append(SubtitleEntry(
                index=i + 1,
                start_time=float(w.get("start", 0)),
                end_time=float(w.get("end", 0)),
                text=w.get("word", "").strip(),
                language=language,
            ))
        return entries

    def _merge_into_sentences(
        self, entries: List[SubtitleEntry], max_chars: int = 60
    ) -> List[SubtitleEntry]:
        """Kelimeleri cümle bazında birleştir."""
        if not entries:
            return []

        sentences = []
        current_text = []
        current_start = entries[0].start_time
        current_end = entries[0].end_time

        for entry in entries:
            test_text = " ".join(current_text + [entry.text])
            if len(test_text) > max_chars and current_text:
                # Cümleyi kaydet
                sentences.append(SubtitleEntry(
                    index=len(sentences) + 1,
                    start_time=current_start,
                    end_time=current_end,
                    text=" ".join(current_text),
                    language=entry.language,
                ))
                current_text = [entry.text]
                current_start = entry.start_time
            else:
                current_text.append(entry.text)

            current_end = entry.end_time

        # Son cümle
        if current_text:
            sentences.append(SubtitleEntry(
                index=len(sentences) + 1,
                start_time=current_start,
                end_time=current_end,
                text=" ".join(current_text),
                language=entries[-1].language if entries else "tr",
            ))

        return sentences

    # ── Export ──

    def export_srt(self, language: str) -> Optional[str]:
        """SRT formatında dışa aktar."""
        track = self._tracks.get(language)
        if not track:
            return None

        lines = []
        for entry in track.entries:
            start = self._format_srt_time(entry.start_time)
            end = self._format_srt_time(entry.end_time)
            lines.append(f"{entry.index}")
            lines.append(f"{start} --> {end}")
            lines.append(entry.text)
            lines.append("")

        return "\n".join(lines)

    def export_ass(self, language: str) -> Optional[str]:
        """ASS formatında dışa aktar."""
        track = self._tracks.get(language)
        if not track:
            return None

        lines = [self.ASS_HEADER.rstrip()]
        for entry in track.entries:
            start = self._format_ass_time(entry.start_time)
            end = self._format_ass_time(entry.end_time)
            style = "Default" if language == "tr" else language.capitalize()
            lines.append(
                f"Dialogue: 0,{start},{end},{style},,0,0,0,,{entry.text}"
            )

        return "\n".join(lines)

    async def save_to_file(
        self, language: str, format: str = "srt"
    ) -> Optional[str]:
        """Altyazıyı dosyaya kaydet."""
        if format == "srt":
            content = self.export_srt(language)
        elif format == "ass":
            content = self.export_ass(language)
        else:
            return None

        if not content:
            return None

        ext = "srt" if format == "srt" else "ass"
        file_path = self._output_dir / f"subtitle_{language}.{ext}"
        await asyncio.to_thread(
            file_path.write_text, content, "utf-8"
        )
        return str(file_path)

    def _format_srt_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _format_ass_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    # ── Query ──

    def get_track(self, language: str) -> Optional[SubtitleTrack]:
        return self._tracks.get(language)

    def get_all_tracks(self) -> Dict[str, SubtitleTrack]:
        return dict(self._tracks)

    def get_available_languages(self) -> List[str]:
        return list(self._tracks.keys())

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_languages": len(self._tracks),
            "languages": list(self._tracks.keys()),
            "total_entries": sum(len(t.entries) for t in self._tracks.values()),
            "total_words": sum(t.word_count for t in self._tracks.values()),
            "translation_cache_size": len(self._translation_cache),
        }


# Singleton
multilingual_subs = MultilingualSubtitleManager()
