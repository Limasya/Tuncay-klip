"""
Açık Kaynak LLM Semantic Analiz Servisi
────────────────────────────────────────
Whisper'dan gelen tam transkripti analiz ederek, 
videodaki hikayesel, komik veya heyecanlı "Elmas" anların 
zaman damgalarını (timestamp) belirler.

LLM çağrıları artık `services.llm_client` facade'ı üzerinden geçer:
  - Feature flag `llm_litellm_router` açık ise LiteLLM SDK Router
  - Kapalı ise mevcut `llm_engine` (geri uyumlu)

Bu modül hâlâ aynı public API'yi sunar:
  - get_semantic_highlights
  - critique_video
  - get_media_kit
"""
import os
import json
import logging
from typing import Dict, Any, List

from services import llm_client

logger = logging.getLogger("llm_reasoner")


class LLMReasoner:
    def __init__(self):
        # Hizli sonuc icin Groq uzerindeki Llama-3-70b
        self.api_key = os.environ.get("GROQ_API_KEY", "")
        # Alternatif (Groq yoksa OpenRouter vs kullanilabilir)
        if not self.api_key:
            self.api_key = os.environ.get("OPENROUTER_API_KEY", "")

    async def get_semantic_highlights(self, transcript_text: str) -> List[Dict[str, float]]:
        """
        Tüm metni (Zaman damgalarıyla birlikte) LLM'e verir,
        en komik/aksiyonlu 3 klibin JSON seklinde (start, end)
        olarak donmesini saglar.
        """
        if not self.api_key:
            logger.warning(
                "LLM Reasoner needs GROQ_API_KEY or OPENROUTER_API_KEY to function."
            )
            return []

        logger.info("Sending transcript to LLM for Semantic Reasoning...")

        system_prompt = (
            "Sen odullu bir TikTok/Shorts kurgucususun. Görevin asagida verilen "
            "zaman damgali Twitch yayini metnini okumak ve icerisinden en "
            "viral olabilecek, en komik veya heyecanli maksimum 3 adet 60 saniyelik klibi cikartmak. "
            "Sadece JSON formatinde cevap ver, baska hicbir yazi yazma.\n"
            "Format: [{\"start\": 12.5, \"end\": 70.0, \"reason\": \"Cok komik bir saka yapiyor\"}]"
        )

        # Eger cok uzunsa LLM'in baglamina (8k-128k) sigdirmak gerek.
        # Basitlik icin son 50.000 karakteri aliyoruz (~10k token)
        safe_transcript = transcript_text[:50000]

        user_prompt = f"Transcript:\n{safe_transcript}"

        try:
            raw = await llm_client.generate(
                user_prompt,
                language="tr",
                max_tokens=2048,
                temperature=0.2,
                system_prompt=system_prompt,
            )
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and "clips" in parsed:
                    return parsed["clips"]
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    for v in parsed.values():
                        if isinstance(v, list):
                            return v
                    return [parsed]
            except json.JSONDecodeError:
                logger.error("LLM did not return valid JSON.")
                return []
        except Exception as e:
            logger.error("Error during LLM Semantic Reasoning: %s", e)
            return []

    async def critique_video(
        self, metrics: Dict[str, Any], transcript_snippet: str = ""
    ) -> Dict[str, Any]:
        """
        AI Critic — render edilmiş klibin objektif metriklerini (altyazı boyutu,
        ilk 3sn enerjisi, thumbnail kalitesi, zoom zamanlaması) alır ve
        0-10 arası bir puan + gerekçe listesi üretir.

        LLM çağrısı `services.llm_client` üzerinden geçer (flag açık ise LiteLLM
        Router, kapalı ise llm_engine). No-API-key durumunda boş dict döner.
        """
        if not self.api_key:
            return {}

        system_prompt = (
            "Sen deneyimli bir TikTok/Shorts kurgu editörü ve içerik eleştirmenisin. "
            "Sana bir dikey viral klip için ölçülmüş objektif metrikler (0-1 arası, "
            "1=mükemmel) verilecek. Bu metriklere ve klip metnine bakarak videoyu "
            "10 üzerinden puanla ve neden puan kırdığını kısa, somut maddelerle açıkla. "
            "Sadece JSON dön, başka yazı yazma.\n"
            "Format: {\"score\": 8.7, \"verdict\": \"tek cümle özet\", "
            "\"reasons\": [\"Altyazı küçük\", \"İlk 3 saniye sıkıcı\"]}"
        )

        user_content = (
            f"Metrikler (0-1):\n{json.dumps(metrics, ensure_ascii=False)}\n\n"
            f"Klip metni (ilk kısım):\n{transcript_snippet[:1500]}"
        )

        try:
            raw = await llm_client.generate(
                user_content,
                language="tr",
                max_tokens=1024,
                temperature=0.3,
                system_prompt=system_prompt,
            )
            if not raw:
                return {}
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return {}
            return {
                "score": float(parsed.get("score", 0)),
                "verdict": str(parsed.get("verdict", "")),
                "reasons": list(parsed.get("reasons", [])),
            }
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error("Critic LLM parse error: %s", e)
            return {}
        except Exception as e:
            logger.error("Critic LLM request error: %s", e)
            return {}

    async def get_media_kit(self, clip_transcript: str) -> Dict[str, str]:
        """
        Klibin transkriptine bakarak viral bir başlık (Hook),
        açıklama ve hashtag listesi üretir.

        LLM çağrısı `services.llm_client` üzerinden geçer.
        """
        if not self.api_key:
            return {"title": "Viral Klip", "description": "", "tags": "#viral"}

        system_prompt = (
            "Sen bir TikTok ve YouTube Shorts uzmanısın. Sana verilen kısa videonun metnini "
            "okuyarak bu video için maksimum 4 kelimelik clickbait bir Kapak Başlığı (title), "
            "1 cümlelik açıklama (description) ve 5 adet hashtag (tags) üret. "
            "Sadece JSON formatında dön. "
            "Format: {\"title\": \"Oha!\", \"description\": \"...\", \"tags\": \"#fyp #...\"}"
        )

        user_prompt = f"Metin:\n{clip_transcript[:5000]}"

        try:
            raw = await llm_client.generate(
                user_prompt,
                language="tr",
                max_tokens=600,
                temperature=0.5,
                system_prompt=system_prompt,
            )
            if not raw:
                return {"title": "Büyük An!", "description": "İyi seyirler.", "tags": "#oyun #viral"}
            try:
                parsed = json.loads(raw)
                return {
                    "title": parsed.get("title", "ŞOK OLACAKSINIZ!"),
                    "description": parsed.get("description", "Bu anları kaçırmayın!"),
                    "tags": parsed.get("tags", "#viral #kesfet"),
                }
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.debug("LLM yanıtı parse edilemedi, varsayılana düşülüyor: %s", e)
        except Exception as e:
            logger.warning("LLM reasoner isteği başarısız, varsayılana düşülüyor: %s", e)

        return {"title": "Büyük An!", "description": "İyi seyirler.", "tags": "#oyun #viral"}

# Singleton
llm_reasoner = LLMReasoner()
