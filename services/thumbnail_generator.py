"""
Otomatik Thumbnail (Küçük Resim) Jeneratörü
───────────────────────────────────────────
Viral videolar için dikkat çekici (Clickbait) kapak fotoğrafları üretir.
Videonun içinden bir kare alır, arkaplanı bulanıklaştırır ve üzerine 
dev yazı ekler.
"""
import os
import asyncio
import logging
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger("thumbnail_generator")

class ThumbnailGenerator:
    def __init__(self):
        self.output_dir = Path("data/social_exports")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Arial fontu windows'ta bulunur, olmazsa default font
        self.font_path = "C:/Windows/Fonts/arialbd.ttf"
        
    async def extract_frame(self, video_path: str, time_sec: float) -> str:
        """FFmpeg ile videonun belirtilen saniyesinden bir ekran görüntüsü alır."""
        out_jpg = self.output_dir / f"{Path(video_path).stem}_raw_thumb.jpg"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(time_sec),
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(out_jpg)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return str(out_jpg)

    def draw_text_with_outline(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, 
                               pos: tuple, text_color: str, outline_color: str, outline_width: int):
        x, y = pos
        # Stroke (Kalın siyah dış çizgi)
        for dx in range(-outline_width, outline_width+1):
            for dy in range(-outline_width, outline_width+1):
                draw.text((x+dx, y+dy), text, font=font, fill=outline_color)
        # Ana metin
        draw.text((x, y), text, font=font, fill=text_color)

    async def generate_thumbnail(self, video_path: str, title: str, timestamp: float = 2.0) -> str:
        """
        Videodan kare alıp, üzerine "title" metnini viral formatta (sarı dev yazı) ekler.
        """
        logger.info(f"Generating viral thumbnail for {video_path}")
        
        # 1. FFmpeg ile kareyi al (Arka planda)
        raw_img_path = await self.extract_frame(video_path, timestamp)
        
        if not os.path.exists(raw_img_path):
            logger.error("Failed to extract frame for thumbnail.")
            return ""
            
        final_thumb_path = str(self.output_dir / f"{Path(video_path).stem}_THUMBNAIL.jpg")
        
        # 2. Resim isleme isini (CPU-bound) thread pool icinde yap
        def process_image():
            try:
                with Image.open(raw_img_path) as img:
                    # 9:16 formata uygun oldugundan emin ol
                    img = img.convert("RGB")
                    
                    # Hafif bir bulaniklik efekti (arka plani ayirmak icin)
                    # img = img.filter(ImageFilter.GaussianBlur(1.5))
                    
                    draw = ImageDraw.Draw(img)
                    
                    # Font ayari
                    font_size = 90
                    try:
                        font = ImageFont.truetype(self.font_path, font_size)
                    except IOError:
                        font = ImageFont.load_default()
                        
                    # Metni satirlara bol (max 15 karakter)
                    words = title.split()
                    lines = []
                    current_line = ""
                    for word in words:
                        if len(current_line) + len(word) <= 15:
                            current_line += word + " "
                        else:
                            lines.append(current_line.strip())
                            current_line = word + " "
                    if current_line:
                        lines.append(current_line.strip())
                        
                    # Y ekseninde tam ortaya hizala
                    img_w, img_h = img.size
                    y_offset = (img_h // 2) - ((len(lines) * font_size) // 2)
                    
                    for line in lines:
                        # Pillow 10+ icin getbbox kullanimi
                        bbox = font.getbbox(line)
                        text_w = bbox[2] - bbox[0]
                        
                        x_pos = (img_w - text_w) // 2
                        
                        self.draw_text_with_outline(
                            draw=draw,
                            text=line,
                            font=font,
                            pos=(x_pos, y_offset),
                            text_color="yellow",
                            outline_color="black",
                            outline_width=5
                        )
                        y_offset += int(font_size * 1.2)
                        
                    img.save(final_thumb_path, quality=95)
                    
                # Temp frame'i sil
                os.remove(raw_img_path)
            except Exception as e:
                logger.error(f"Image processing failed: {e}")

        await asyncio.to_thread(process_image)
        logger.info(f"Thumbnail saved: {final_thumb_path}")
        return final_thumb_path

# Singleton
thumbnail_generator = ThumbnailGenerator()
