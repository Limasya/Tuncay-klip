"""
Social Media Viral AI
─────────────────────
Bu servis, üretilen klipler için sosyal medya platformlarına 
(TikTok, Reels, Shorts) özel viral kanca (hook) başlıkları, 
açıklamalar ve trend hashtag'ler üretir.

Smart LLM Router altyapısını kullanarak ücretsiz/çok hızlı
API'lerle çalışır (Groq, Cerebras vb.)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from services.smart_llm_router import smart_router

logger = logging.getLogger("social_media_ai")


class SocialMediaAI:
    def __init__(self):
        self.system_prompt = (
            "Sen viral bir sosyal medya uzmanısın (TikTok, Instagram Reels, YouTube Shorts). "
            "Amacın, sana verilen oyun yayını kesiti (clip) bilgileri üzerinden "
            "izleyicinin kaydırmayı bırakmasını (scroll-stopping) sağlayacak 'kanca' (hook) "
            "başlıklar, kısa viral açıklamalar ve trend hashtag'ler üretmektir.\n"
            "Daima şu JSON formatında yanıt ver:\n"
            "{\n"
            '  "tiktok_hooks": ["Hook 1", "Hook 2", "Hook 3"],\n'
            '  "viral_description": "Açıklama metni",\n'
            '  "hashtags": ["#oyun", "#trend", "#komik"]\n'
            "}\n"
            "Yanıtın SADECE JSON olmalıdır, markdown (```json) veya ekstra metin İÇERMEMELİDİR."
        )

    async def generate_viral_package(
        self,
        transcript: str,
        metadata: dict[str, Any],
        strategy: str = "speed_first",
    ) -> dict[str, Any]:
        """
        Klip için viral sosyal medya paketi (başlıklar, açıklama, hashtagler) üretir.
        """
        # Verileri hazırla
        emotion = metadata.get("emotion", "Bilinmiyor")
        game = metadata.get("game", "Oyun")
        streamer = metadata.get("streamer", "Yayıncı")
        
        # Eğer transcript çok uzunsa, sadece ilk 500 ve son 500 karakteri (veya max 1000 karakter) alalım.
        # Bu LLM'in daha hızlı yanıt vermesini sağlar.
        if len(transcript) > 1500:
            short_transcript = transcript[:750] + "\n...[kesildi]...\n" + transcript[-750:]
        else:
            short_transcript = transcript or "[Konuşma yok]"

        prompt = (
            f"Oyun: {game}\n"
            f"Yayıncı: {streamer}\n"
            f"Klip Duygusu/Atmosferi: {emotion}\n"
            f"Klipteki Konuşmalar (Transkript):\n{short_transcript}\n\n"
            "Lütfen viral bir içerik paketi hazırla."
        )

        try:
            # Akıllı router üzerinden LLM çağrısı yap (JSON moduna uygun bir model seçecektir)
            result_text, provider_used = await smart_router.route(
                prompt=prompt,
                strategy=strategy,
                max_tokens=300,
                temperature=0.8,
                system_prompt=self.system_prompt,
            )

            # JSON temizleme
            result_text = result_text.strip()
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            result_text = result_text.strip()

            data = json.loads(result_text)
            
            logger.info("SocialMediaAI: Generated viral package using %s", provider_used)
            
            return {
                "success": True,
                "provider": provider_used,
                "hooks": data.get("tiktok_hooks", []),
                "description": data.get("viral_description", ""),
                "hashtags": data.get("hashtags", []),
            }

        except json.JSONDecodeError as e:
            logger.warning("SocialMediaAI: Failed to parse JSON response. Response: %s", result_text[:100])
            return {
                "success": False,
                "error": "JSON parse error",
                "raw_response": result_text[:200]
            }
        except Exception as e:
            logger.error("SocialMediaAI: Error generating viral package: %s", e)
            return {
                "success": False,
                "error": str(e)
            }


# Singleton
social_media_ai = SocialMediaAI()
