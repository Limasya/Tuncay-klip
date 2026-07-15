"""
AI destekli baslik ve hashtag olusturucu.
Klip icerigini analiz ederek otomatik baslik, aciklama ve hashtag uretir.
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# Platform bazli hashtag limitleri ve kurallar
PLATFORM_RULES = {
    "youtube": {"max_title": 100, "max_tags": 30, "max_desc": 5000},
    "tiktok": {"max_title": 150, "max_tags": 5, "max_desc": 2200},
    "instagram": {"max_title": 150, "max_tags": 30, "max_desc": 2200},
    "twitter": {"max_title": 280, "max_tags": 5, "max_desc": 280},
    "kick": {"max_title": 100, "max_tags": 10, "max_desc": 500},
}

# Turkce/Ingilizce populer gaming/streaming hashtag'leri
BASE_HASHTAGS = {
    "gaming": [
        "gaming", "gamer", "livestream", "twitch", "kick",
        "oyun", "yayin", "canliayin", "streamer",
    ],
    "funny": [
        "funny", "lol", "komik", "komikanlar", "eglence",
        "epic", "fail", "lmao", "haha",
    ],
    "exciting": [
        "epic", "clutch", "insane", "amazing", "efsane",
        "muhtesem", "incredible", "pogchamp", "hype",
    ],
    "rage": [
        "rage", "tilt", "sinirli", "kizgin", "ragequit",
        "frustrating", "mad", "angry",
    ],
    "victory": [
        "victory", "win", "galibiyet", "kazandik", "gg",
        "champion", "birinci", "winner",
    ],
    "skill": [
        "skill", "yetenek", "pro", "godlike", "profesyonel",
        "headshot", "clutch", "ace",
    ],
}

# Baslik semlonlari
TITLE_TEMPLATES = {
    "funny": [
        "Bu An Herkesi Guldurdu! {emotion}",
        "Kahkaha Garantili An - {streamer}",
        "En Komik {emotion} An!",
        "{streamer} Tarafindan En Eglenceli An",
        "Bu {emotion} Ani Viral Olmali!",
    ],
    "exciting": [
        "Inanilmaz {emotion} An! {viewer} Izleyici",
        "Bu Ani Gormelisin! - {streamer}",
        "En Heyecanli {emotion} An",
        "{streamer} Cildirdi! {emotion}",
        "EPIC {emotion} Moment!",
    ],
    "rage": [
        "{streamer} Tam Anlamyla Cildirdi!",
        "En Büyük {emotion} An",
        "Bu Rage An Efsane!",
        "Kontrol Kaybedildi - {emotion}",
        "{streamer} Rage Quit'e Yaklasti!",
    ],
    "victory": [
        "MUHTEŞEM {emotion} Galibiyet!",
        "{streamer} Kazandi! Iste O An",
        "Bu Zafer Anini Kacirmayin!",
        "Son Saniye {emotion} Galibiyet!",
        "Tarih Yazildi - {emotion}",
    ],
    "skill": [
        "Insanustu {emotion} Hareket!",
        "Bu Hareket Mumkun Degil! {emotion}",
        "PRO {emotion} Gameplay",
        "{streamer} God Mode'da!",
        "En Yetenekli {emotion} An",
    ],
}


class AITitleGenerator:
    """
    AI destekli baslik, aciklama ve hashtag olusturucu.
    """

    def __init__(self):
        self._model = None

    def _load_model(self):
        """HuggingFace text generation model yukle."""
        try:
            from transformers import pipeline
            self._model = pipeline(
                "text-generation",
                model="gpt2",
                max_length=100,
                temperature=0.8,
                device=-1,
            )
            logger.info("AI baslik modeli yuklendi (GPT-2).")
        except Exception as e:
            logger.warning("AI model yuklenemedi, semlon bazli uretim: %s", e)

    def generate_title(
        self,
        emotion: str = "exciting",
        streamer_name: str = "Yayinci",
        viewer_count: int = 0,
        category: str = "exciting",
        language: str = "tr",
    ) -> str:
        """
        Klip icin cekici bir baslik olusturur.

        Args:
            emotion: Baskin duygu
            streamer_name: Yayinci adi
            viewer_count: Izleyici sayisi
            category: Klip kategorisi
            language: Dil (tr/en)

        Returns:
            Olusturulan baslik
        """
        import random

        templates = TITLE_TEMPLATES.get(
            category, TITLE_TEMPLATES["exciting"]
        )
        template = random.choice(templates)

        title = template.format(
            emotion=emotion.capitalize(),
            streamer=streamer_name,
            viewer=f"{viewer_count:,}" if viewer_count else "",
        )

        return title

    def generate_description(
        self,
        title: str,
        streamer_name: str = "",
        stream_title: str = "",
        category: str = "",
        emotion: str = "",
        extra_info: str = "",
    ) -> str:
        """Klip icin aciklama metni olusturur."""
        parts = [title, ""]

        if streamer_name:
            parts.append(f"Yayinci: {streamer_name}")
        if stream_title:
            parts.append(f"Yayin Basligi: {stream_title}")
        if category:
            parts.append(f"Kategori: {category.capitalize()}")
        if emotion:
            parts.append(f"Duygu: {emotion.capitalize()}")
        if extra_info:
            parts.append(extra_info)

        parts.append("")
        parts.append("Otomatik klip yakalama sistemi ile olusturuldu.")

        return "\n".join(parts)

    def generate_hashtags(
        self,
        category: str = "exciting",
        platform: str = "youtube",
        custom_tags: List[str] = None,
        game_name: str = "",
        streamer_name: str = "",
    ) -> List[str]:
        """
        Platform ve kategoriye uygun hashtag listesi olusturur.

        Args:
            category: Klip kategorisi
            platform: Hedef platform
            custom_tags: Ek ozel etiketler
            game_name: Oyun adi
            streamer_name: Yayinci adi

        Returns:
            Hashtag listesi
        """
        rules = PLATFORM_RULES.get(platform, PLATFORM_RULES["youtube"])
        max_tags = rules["max_tags"]

        tags = []

        # Baz hashtag'ler
        base = BASE_HASHTAGS.get(category, BASE_HASHTAGS["gaming"])
        tags.extend(base[:max_tags // 2])

        # Oyun adi
        if game_name:
            tags.append(game_name.replace(" ", "").lower())
            tags.append(f"{game_name}clips".replace(" ", "").lower())

        # Yayinci adi
        if streamer_name:
            tags.append(streamer_name.replace(" ", "").lower())

        # Platform etiketi
        tags.append(platform)
        tags.append(f"{platform}clips")

        # Ozel etiketler
        if custom_tags:
            tags.extend(custom_tags)

        # Temizle ve sinirla
        tags = list(dict.fromkeys(tags))  # Duplicate kaldir, sira koru
        tags = [t for t in tags if len(t) <= 30][:max_tags]

        return tags

    def generate_full_metadata(
        self,
        emotion: str = "exciting",
        category: str = "exciting",
        streamer_name: str = "Yayinci",
        viewer_count: int = 0,
        stream_title: str = "",
        game_name: str = "",
        platform: str = "youtube",
        custom_tags: List[str] = None,
    ) -> Dict:
        """
        Tam metadata paketi olusturur: baslik + aciklama + hashtag.

        Returns:
            {"title": str, "description": str, "hashtags": list}
        """
        title = self.generate_title(
            emotion=emotion,
            streamer_name=streamer_name,
            viewer_count=viewer_count,
            category=category,
        )

        description = self.generate_description(
            title=title,
            streamer_name=streamer_name,
            stream_title=stream_title,
            category=category,
            emotion=emotion,
        )

        hashtags = self.generate_hashtags(
            category=category,
            platform=platform,
            custom_tags=custom_tags,
            game_name=game_name,
            streamer_name=streamer_name,
        )

        # Hashtag'leri aciklamaya ekle
        hashtag_str = " ".join(f"#{tag}" for tag in hashtags)
        full_description = f"{description}\n\n{hashtag_str}"

        return {
            "title": title,
            "description": full_description,
            "hashtags": hashtags,
            "raw_title": title,
        }


# Singleton
ai_title_generator = AITitleGenerator()
