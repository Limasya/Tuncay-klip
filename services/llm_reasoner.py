"""
Açık Kaynak LLM Semantic Analiz Servisi
────────────────────────────────────────
Whisper'dan gelen tam transkripti analiz ederek, 
videodaki hikayesel, komik veya heyecanlı "Elmas" anların 
zaman damgalarını (timestamp) belirler. 
Llama-3 modelini kullanmak için Groq veya Together API kullanır.
"""
import os
import json
import logging
import aiohttp
from typing import Dict, Any, List

logger = logging.getLogger("llm_reasoner")

class LLMReasoner:
    def __init__(self):
        # Hizli sonuc icin Groq uzerindeki Llama-3-70b
        self.api_key = os.environ.get("GROQ_API_KEY", "")
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = "llama3-70b-8192"
        
        # Alternatif (Groq yoksa OpenRouter vs kullanilabilir)
        if not self.api_key:
            self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
            self.api_url = "https://openrouter.ai/api/v1/chat/completions"
            self.model = "meta-llama/llama-3-70b-instruct"

    async def get_semantic_highlights(self, transcript_text: str) -> List[Dict[str, float]]:
        """
        Tüm metni (Zaman damgalarıyla birlikte) LLM'e verir,
        en komik/aksiyonlu 3 klibin JSON seklinde (start, end)
        olarak donmesini saglar.
        """
        if not self.api_key:
            logger.warning("LLM Reasoner needs GROQ_API_KEY or OPENROUTER_API_KEY to function.")
            return []
            
        logger.info(f"Sending transcript to {self.model} for Semantic Reasoning...")

        # Sistemi promptu: TikTok kurgucusu rolu
        system_prompt = (
            "Sen odullu bir TikTok/Shorts kurgucususun. Görevin asagida verilen "
            "zaman damgali Twitch yayini metnini okumak ve icerisinden en "
            "viral olabilecek, en komik veya heyecanli maksimum 3 adet 60 saniyelik klibi cikartmak. "
            "Sadece JSON formatinda cevap ver, baska hicbir yazi yazma.\n"
            "Format: [{\"start\": 12.5, \"end\": 70.0, \"reason\": \"Cok komik bir saka yapiyor\"}]"
        )
        
        # Eger cok uzunsa LLM'in baglamina (8k-128k) sigdirmak gerek.
        # Basitlik icin son 50.000 karakteri aliyoruz (~10k token)
        safe_transcript = transcript_text[:50000]
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Transcript:\n{safe_transcript}"}
            ],
            "response_format": {"type": "json_object"} if "groq" in self.api_url else None,
            "temperature": 0.2
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data["choices"][0]["message"]["content"]
                        
                        try:
                            # Groq bazen json_object'i bir ust key icine koyar
                            parsed = json.loads(content)
                            if isinstance(parsed, dict) and "clips" in parsed:
                                return parsed["clips"]
                            elif isinstance(parsed, list):
                                return parsed
                            elif isinstance(parsed, dict):
                                # Eger dogrudan obje dondurmusse (ornek [..] degilse)
                                # anahtarlari kontrol et
                                for k, v in parsed.items():
                                    if isinstance(v, list):
                                        return v
                                return [parsed]
                        except json.JSONDecodeError:
                            logger.error("LLM did not return valid JSON.")
                            return []
                    else:
                        logger.error(f"LLM API Error: {resp.status} - {await resp.text()}")
                        return []
        except Exception as e:
            logger.error(f"Error during LLM Semantic Reasoning: {str(e)}")
            return []

    async def critique_video(
        self, metrics: Dict[str, Any], transcript_snippet: str = ""
    ) -> Dict[str, Any]:
        """
        AI Critic — render edilmiş klibin objektif metriklerini (altyazı boyutu,
        ilk 3sn enerjisi, thumbnail kalitesi, zoom zamanlaması) alır ve
        0-10 arası bir puan + gerekçe listesi üretir.

        metrics örneği:
          {"subtitle": 0.4, "opening": 0.3, "thumbnail": 0.6, "zoom": 0.5,
           "zoom_first_peak_s": 6.2, "subtitle_ratio": 0.012}

        Dönüş:
          {"score": 8.7, "verdict": "...", "reasons": ["Altyazı küçük", ...]}
        Boş dict dönerse çağıran taraf heuristik fallback kullanmalı.
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

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"} if "groq" in self.api_url else None,
            "temperature": 0.3,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        logger.error("Critic LLM API Error: %s", resp.status)
                        return {}
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
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
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Metin:\n{clip_transcript[:5000]}"}
            ],
            "response_format": {"type": "json_object"} if "groq" in self.api_url else None,
            "temperature": 0.5
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data["choices"][0]["message"]["content"]
                        try:
                            parsed = json.loads(content)
                            return {
                                "title": parsed.get("title", "ŞOK OLACAKSINIZ!"),
                                "description": parsed.get("description", "Bu anları kaçırmayın!"),
                                "tags": parsed.get("tags", "#viral #kesfet")
                            }
                        except (json.JSONDecodeError, KeyError, TypeError) as e:
                            logger.debug("LLM yanıtı parse edilemedi, varsayılana düşülüyor: %s", e)
        except Exception as e:
            logger.warning("LLM reasoner isteği başarısız, varsayılana düşülüyor: %s", e)
            
        return {"title": "Büyük An!", "description": "İyi seyirler.", "tags": "#oyun #viral"}

# Singleton
llm_reasoner = LLMReasoner()
