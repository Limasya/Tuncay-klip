"""
Viral TikTok/Instagram Reels Editing Pattern Research — 2025-2026
Runs 3 LLM calls in parallel (Groq, Gemini, OpenRouter) and summarizes findings.

This is a standalone research script. It reads .env directly (dotenv injection)
and uses the provider implementations from services/llm_providers.py.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Fix Windows console encoding for Turkish + special characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure project root is on sys.path so we can import services
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Load .env into os.environ (manual dotenv, avoids extra dependency) ──────
_ENV_PATH = PROJECT_ROOT / ".env"
if _ENV_PATH.exists():
    with open(_ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value

from services.llm_providers import (
    GroqProvider, GeminiProvider, OpenRouterProvider,
)

# ── The research prompt (Turkish, as requested) ─────────────────────────────
RESEARCH_PROMPT = """Sen bir viral TikTok ve Instagram Reels edit uzmanısın. 2025-2026'da viral olan Türk gaming/yayıncı Reels ve TikTok videolarının ortak edit pattern'lerini analiz et. Özellikle şu konulara odaklan:

1. **Meme/Fotoğraf Overlay**: Viral videolarda meme ve fotoğraflar nasıl yerleştiriliyor? (boyut, pozisyon, zamanlama, animasyon). Tam ekran kaplamadan nasıl overlay yapılıyor?
2. **Ses Efektleri**: Hangi ses efektleri nerede kullanılıyor? (vine boom, click, bass drop, record scratch, vs). Hangi zamanlamalarda?
3. **Müzik**: Viral videolarda müzik kullanımı — orijinal ses mi, trending audio mu? Ses seviyesi nasıl ayarlanıyor?
4. **Text/Metin Overlay**: Başlık, alt yazı, hook text nasıl yerleştiriliyor? Hangi font, renk, animasyon?
5. **Geçiş Efektleri**: Hangi transition'lar viral oluyor? (jump cut, whip pan, zoom, glitch)
6. **Hız Değişimi**: Speed ramp, slow-mo, freeze frame nerede kullanılıyor?
7. **Renk/Filter**: Hangi renk grading, filter'lar popüler?
8. **Genel Yapı**: Viral videoların saniye saniye yapısı nasıl? (hook → buildup → payoff → send trigger)

Her bir teknik için şu formatta cevap ver:
- Teknik adı
- Viral etki skoru (1-100)
- Kullanım zamanlaması (video'nun hangi saniyesinde)
- FFmpeg ile nasıl implemente edilir (teknik detay)
- Örnek açıklama

JSON formatında cevap ver, analizlerini detaylandır. Her teknik için array içinde object döndür."""


SYSTEM_PROMPT = (
    "Sen bir viral video edit uzmanısın. TikTok, Instagram Reels ve YouTube Shorts için "
    "içerik üretiyorsun. FFmpeg, After Effects ve CapCut biliyorsun. "
    "Her zaman JSON formatında, temiz ve parse edilebilir cevap ver. "
    "Türkçe konuş, Türk gaming/yayıncı kitlesine hitap ediyorsun."
)


# ── Provider setup ──────────────────────────────────────────────────────────
def _make_groq() -> GroqProvider:
    key = os.environ.get("GROQ_API_KEY", "")
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    if not key:
        raise RuntimeError("GROQ_API_KEY not found in .env")
    return GroqProvider(api_key=key, model=model)


def _make_gemini() -> GeminiProvider:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not found in .env")
    from services.llm_model_defaults import resolve_gemini_model
    model = resolve_gemini_model()
    return GeminiProvider(api_key=key, model=model)


def _make_openrouter() -> OpenRouterProvider:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not found in .env")
    # The LLM API suggested this slug. Free tier models rotate frequently.
    # Using the paid slug for one call (minimal cost ~$0.0001).
    model = os.environ.get(
        "OPENROUTER_MODEL",
        "qwen/qwen-2.5-7b-instruct",
    )
    return OpenRouterProvider(api_key=key, model=model)


# ── Parallel call ───────────────────────────────────────────────────────────
async def call_provider(
    name: str,
    provider_obj,
    prompt: str,
    system_prompt: str = SYSTEM_PROMPT,
) -> dict[str, Any]:
    start = time.time()
    try:
        raw = await provider_obj(
            prompt=prompt,
            max_tokens=8192,
            temperature=0.6,
            system_prompt=system_prompt,
        )
        elapsed = time.time() - start
        print(f"[{name}] OK in {elapsed:.1f}s ({len(raw)} chars)")
        return {
            "provider": name,
            "success": True,
            "raw": raw,
            "elapsed_s": round(elapsed, 1),
            "error": None,
        }
    except Exception as e:
        elapsed = time.time() - start
        print(f"[{name}] FAILED in {elapsed:.1f}s: {e}")
        return {
            "provider": name,
            "success": False,
            "raw": "",
            "elapsed_s": round(elapsed, 1),
            "error": str(e),
        }


# ── JSON extraction (same logic as llm_engine._extract_json) ────────────────
def extract_json(raw: str) -> dict | list | None:
    raw = raw.strip()
    if not raw:
        return None

    # Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Markdown code fences
    import re
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Balanced brackets/braces
    for open_c, close_c in [('[', ']'), ('{', '}')]:
        depth = 0
        start = -1
        for i, ch in enumerate(raw):
            if ch == open_c:
                if depth == 0:
                    start = i
                depth += 1
            elif ch == close_c:
                depth -= 1
                if depth == 0 and start >= 0:
                    candidate = raw[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        start = -1

    # Fix single quotes, trailing commas
    cleaned = raw.replace("'", '"')
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Truncated JSON fix: try to auto-close unclosed braces/brackets
    for open_c, close_c in [('[', ']'), ('{', '}')]:
        depth = 0
        start = -1
        last_closed = -1
        for i, ch in enumerate(raw):
            if ch == open_c:
                if depth == 0:
                    start = i
                depth += 1
            elif ch == close_c:
                depth -= 1
                if depth == 0:
                    last_closed = i
        if start >= 0 and last_closed < start:
            # Found an unclosed structure — try closing it
            missing = depth
            candidate = raw[start:] + (close_c * missing)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    return None


# ── Summarize across providers ──────────────────────────────────────────────
def _flatten_techniques(parsed) -> list[dict]:
    """Accept list or dict and return a flat list of technique dicts."""
    if isinstance(parsed, list):
        return [t for t in parsed if isinstance(t, dict)]
    if isinstance(parsed, dict):
        for v in parsed.values():
            if isinstance(v, list):
                return _flatten_techniques(v)
        # keys = technique names, values = details
        flat = []
        for k, v in parsed.items():
            if isinstance(v, dict):
                if "teknik" not in v and "viral_etki_skoru" not in v:
                    v["teknik_adi"] = k
                flat.append(v)
        return flat
    return []


def _score_from(item: dict) -> float:
    """Extract viral impact score from a technique dict, trying multiple key names."""
    for key in ("viral_etki_skoru", "viral_etki_skor", "viral_impact_score",
                "virality_score", "skor", "score", "viral skoru", "etki skoru"):
        val = item.get(key)
        if val is not None:
            try:
                s = float(val)
                # LLMs sometimes output 1-100, sometimes 1-10 — normalize to 0-100
                if s <= 10 and key != "score":
                    s *= 10
                return min(max(s, 0), 100)
            except (ValueError, TypeError):
                pass
    # Try to find any numeric field containing "score" or "skor"
    for k, v in item.items():
        if ("skor" in k.lower() or "score" in k.lower()) and v is not None:
            try:
                s = float(v)
                if s <= 10:
                    s *= 10
                return min(max(s, 0), 100)
            except (ValueError, TypeError):
                pass
    return 50.0  # default


def _name_from(item: dict) -> str:
    """Extract technique name."""
    for key in ("teknik_adi", "teknik adı", "teknik", "teknik_name",
                "technique", "name", "isim", "ad"):
        val = item.get(key)
        if val and isinstance(val, str):
            return val.strip()
    return "Bilinmeyen Teknik"


def _ffmpeg_from(item: dict) -> str:
    """Extract FFmpeg implementation."""
    for key in ("ffmpeg_implementasyon", "ffmpeg", "ffmpeg_implementation",
                "implementasyon", "implementation", "ffmpeg_komutu"):
        val = item.get(key)
        if val and isinstance(val, str):
            return val.strip()
    return ""


def _description_from(item: dict) -> str:
    for key in ("ornek_aciklama", "örnek_açıklama", "aciklama", "açıklama",
                "description", "ornek", "örnek", "detay"):
        val = item.get(key)
        if val and isinstance(val, str):
            return val.strip()
    return ""


def merge_and_rank(results: list[dict]) -> dict[str, Any]:
    """Merge all parsed techniques from multiple providers, deduplicate, rank."""
    all_techniques: list[dict] = []

    for r in results:
        if not r.get("parsed"):
            continue
        techniques = _flatten_techniques(r["parsed"])
        for t in techniques:
            t["_source_provider"] = r["provider"]
            all_techniques.append(t)

    # Deduplicate by normalized name
    deduped: dict[str, dict] = {}
    for t in all_techniques:
        name = _name_from(t).lower().strip()
        if name not in deduped:
            deduped[name] = t
        else:
            # Keep the one with higher score
            if _score_from(t) > _score_from(deduped[name]):
                deduped[name] = t

    # Rank by viral impact score
    ranked = sorted(deduped.values(), key=_score_from, reverse=True)

    # Build clean top-level summary
    top_techniques = []
    for t in ranked:
        score = _score_from(t)
        name = _name_from(t)
        ffmpeg = _ffmpeg_from(t)
        desc = _description_from(t)
        source = t.get("_source_provider", "unknown")
        timing = t.get("kullanim_zamanlamasi") or t.get("zamanlama") or t.get("timing", "")

        top_techniques.append({
            "teknik_adi": name,
            "viral_etki_skoru": score,
            "zamanlama": str(timing),
            "ffmpeg_implementasyon": ffmpeg,
            "aciklama": desc,
            "kaynak_provider": source,
        })

    # FFmpeg command summary
    ffmpeg_commands = []
    for t in top_techniques:
        ffmpeg = _ffmpeg_from(t)
        if ffmpeg:
            ffmpeg_commands.append({
                "teknik": _name_from(t),
                "skor": _score_from(t),
                "ffmpeg": ffmpeg,
            })

    return {
        "toplam_teknik_sayisi": len(ranked),
        "top_10_teknik": top_techniques[:10],
        "tum_teknikler": top_techniques,
        "provider_katkilari": _provider_contributions(results),
        "ffmpeg_komut_ozeti": ffmpeg_commands[:10],
    }


def _provider_contributions(results: list[dict]) -> dict:
    contrib = {}
    for r in results:
        name = r["provider"]
        count = 0
        if r.get("parsed"):
            count = len(_flatten_techniques(r["parsed"]))
        contrib[name] = {
            "success": r["success"],
            "teknik_sayisi": count,
            "sure_s": r.get("elapsed_s", 0),
            "hata": r.get("error"),
        }
    return contrib


# ── Main ────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 70)
    print("Viral Reels/TikTok Edit Pattern Research — 2025-2026")
    print("Running 3 parallel LLM calls: Groq (llama-3.3-70b), Gemini, OpenRouter")
    print("=" * 70)

    # Resolve what's available
    providers_to_run: list[tuple[str, Any]] = []

    try:
        providers_to_run.append(("groq", _make_groq()))
        print("[setup] Groq      — OK")
    except Exception as e:
        print(f"[setup] Groq      — SKIP: {e}")

    try:
        providers_to_run.append(("gemini", _make_gemini()))
        print("[setup] Gemini    — OK")
    except Exception as e:
        print(f"[setup] Gemini    — SKIP: {e}")

    try:
        providers_to_run.append(("openrouter", _make_openrouter()))
        print("[setup] OpenRouter — OK")
    except Exception as e:
        print(f"[setup] OpenRouter — SKIP: {e}")

    if not providers_to_run:
        print("[FATAL] No providers available. Exiting.")
        return

    # Run all in parallel
    print(f"\nRunning {len(providers_to_run)} providers in parallel...\n")
    start_all = time.time()
    tasks = [
        call_provider(name, obj, RESEARCH_PROMPT, SYSTEM_PROMPT)
        for name, obj in providers_to_run
    ]
    raw_results = await asyncio.gather(*tasks)
    total_elapsed = time.time() - start_all

    # Parse each result
    for r in raw_results:
        if r["success"] and r["raw"]:
            parsed = extract_json(r["raw"])
            if parsed is not None:
                r["parsed"] = parsed
                print(f"[{r['provider']}] JSON parsed successfully")
            else:
                print(f"[{r['provider']}] JSON parse failed — storing raw text")
                r["parsed"] = None

    # Merge and rank
    summary = merge_and_rank(raw_results)

    print(f"\n{'=' * 70}")
    print(f"RESEARCH COMPLETE — Total time: {total_elapsed:.1f}s")
    print(f"Techniques collected: {summary['toplam_teknik_sayisi']}")
    print(f"Providers contributed: {list(summary['provider_katkilari'].keys())}")
    print(f"{'=' * 70}\n")

    # ── Output ──

    # 1. Print full results to console
    print("\n" + "#" * 70)
    print("# FULL PROVIDER RAW RESPONSES")
    print("#" * 70)
    for r in raw_results:
        print(f"\n--- {r['provider'].upper()} (success={r['success']}, {r['elapsed_s']}s) ---")
        if r["success"]:
            print(r["raw"][:3000])
            if len(r["raw"]) > 3000:
                print(f"... (truncated, total {len(r['raw'])} chars)")
        else:
            print(f"ERROR: {r['error']}")

    # 2. Print top 10 summary
    print("\n" + "#" * 70)
    print("# TOP 10 MOST IMPACTFUL EDITING TECHNIQUES")
    print("#" * 70)
    for i, t in enumerate(summary["top_10_teknik"], 1):
        print(f"\n{i:2d}. {t['teknik_adi']}")
        print(f"    Viral Etki Skoru: {t['viral_etki_skoru']:.0f}/100")
        print(f"    Zamanlama: {t['zamanlama']}")
        print(f"    Kaynak: {t['kaynak_provider']}")
        if t['aciklama']:
            desc = t['aciklama'][:200]
            print(f"    Açıklama: {desc}")
        if t['ffmpeg_implementasyon']:
            ff = t['ffmpeg_implementasyon'][:300]
            print(f"    FFmpeg: {ff}")

    # 3. Print FFmpeg commands
    print("\n" + "#" * 70)
    print("# FFMPEG COMMANDS NEEDED PER TECHNIQUE")
    print("#" * 70)
    for i, cmd in enumerate(summary["ffmpeg_komut_ozeti"], 1):
        print(f"\n{i:2d}. [{cmd['teknik']}] (Skor: {cmd['skor']:.0f})")
        print(f"    {cmd['ffmpeg'][:500]}")

    # ── Save to JSON file ──
    output_dir = PROJECT_ROOT / "tools"
    output_path = output_dir / "viral_reels_research_results.json"

    full_output = {
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_elapsed_s": round(total_elapsed, 1),
            "providers_called": [r["provider"] for r in raw_results],
            "prompt": RESEARCH_PROMPT[:500],
        },
        "raw_responses": [
            {
                "provider": r["provider"],
                "success": r["success"],
                "elapsed_s": r["elapsed_s"],
                "raw_text": r["raw"],
                "error": r["error"],
            }
            for r in raw_results
        ],
        "summary": summary,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(full_output, f, ensure_ascii=False, indent=2)

    print(f"\n[SAVED] Full results written to: {output_path}")
    print("[DONE]")


if __name__ == "__main__":
    asyncio.run(main())