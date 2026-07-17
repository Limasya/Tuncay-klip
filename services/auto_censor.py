"""
Otomatik Sansür (Auto-Censor) Servisi
─────────────────────────────────────
Whisper transkriptindeki küfür ve argo kelimeleri tespit eder.
Bu kelimelerin geçtiği saniyelere FFmpeg üzerinden "BİİİP" 
(sine wave) sesi eklemek için filtre oluşturur.
Monetizasyon (reklam geliri) dostu videolar üretilmesini sağlar.
"""
import logging
from typing import Dict, List, Any

logger = logging.getLogger("auto_censor")

# Basit bir örnek küfür/argo listesi (Kendi ihtiyaçlarınıza göre genişletebilirsiniz)
PROFANITY_LIST = [
    "amk", "aq", "siktir", "sik", "piç", "oç", "orospu", "yarak", "yarak kafalı",
    "fuck", "shit", "bitch", "asshole", "cunt", "motherfucker"
]

class AutoCensor:
    def __init__(self, bad_words: List[str] = None):
        self.bad_words = [w.lower() for w in (bad_words or PROFANITY_LIST)]

    def detect_profanity(self, transcript_data: Dict[str, Any]) -> List[Dict[str, float]]:
        """
        Whisper'dan gelen word-level veriyi tarar.
        Küfür bulduğu anların start-end sürelerini döndürür.
        """
        bleeps = []
        words = transcript_data.get("words", [])
        
        for w_info in words:
            word = w_info.get("word", "").lower().strip()
            # Kelimedeki noktalama işaretlerini temizle
            clean_word = ''.join(c for c in word if c.isalnum())
            
            if clean_word in self.bad_words:
                start = w_info.get("start", 0.0)
                end = w_info.get("end", 0.0)
                
                # Eğer çok kısa bir kelimeyse bleep süresini minimum 0.2sn yapalim ki duyulsun
                if end - start < 0.2:
                    end = start + 0.2
                    
                bleeps.append({
                    "start": start,
                    "end": end,
                    "word": word # İstenirse altyazı tarafında *** ile sansürlemek için
                })
                
        return bleeps

    def generate_bleep_filter(self, bleeps: List[Dict[str, float]], input_audio_label: str = "0:a") -> str:
        """
        Süre listesi alarak FFmpeg volume ve sine (beep) filtrelerini üretir.
        Geriye (audio_filter_string, output_label) döndürür.
        """
        if not bleeps:
            return "", input_audio_label

        filter_parts = []
        
        # 1. Ana sesi küfür anlarında kıs (mute)
        volume_exprs = []
        for b in bleeps:
            st = b["start"]
            en = b["end"]
            volume_exprs.append(f"between(t,{st},{en})")
            
        vol_cond = "+".join(volume_exprs)
        # Eğer cond 1 ise ses 0, değilse 1
        filter_parts.append(f"[{input_audio_label.strip('[]')}]volume='if({vol_cond},0,1)':eval=frame[muted_a];")
        
        # 2. Bleep (sine wave 1000Hz) sesleri üret ve ilgili saniyelere koy
        # Toplam klibin sonunu bilmiyoruz ama her bleep için bir sine uretelim
        bleep_mix_inputs = "[muted_a]"
        mix_count = 1
        
        for i, b in enumerate(bleeps):
            st = b["start"]
            dur = b["end"] - b["start"]
            # Her bleep icin 1000Hz sinyal uret, delay ile baslat, trim ile bitir
            filter_parts.append(
                f"sine=f=1000:d={dur}[beep{i}_raw];"
                f"[beep{i}_raw]adelay={int(st*1000)}|{int(st*1000)}[beep{i}];"
            )
            bleep_mix_inputs += f"[beep{i}]"
            mix_count += 1
            
        # 3. Mute edilmis ana ses ile bleep'leri birlestir
        filter_parts.append(f"{bleep_mix_inputs}amix=inputs={mix_count}:duration=first:dropout_transition=0[censored_a]")
        
        return "".join(filter_parts), "[censored_a]"

# Singleton
auto_censor = AutoCensor()
