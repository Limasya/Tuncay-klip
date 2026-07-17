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
                        except:
                            pass
        except Exception:
            pass
            
        return {"title": "Büyük An!", "description": "İyi seyirler.", "tags": "#oyun #viral"}

# Singleton
llm_reasoner = LLMReasoner()
