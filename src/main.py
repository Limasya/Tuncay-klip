"""
src/main.py - CLI giris noktasi.
Komut satirindan klip indirme, cikarma ve yayinlama.
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Proje koku Python path'e ekle
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.downloader import stream_downloader
from src.clipper import clip_extractor
from src.uploader import auto_publisher
from src.ai_generator import ai_title_generator
from services.kick_archive import (
    TARGET_CHANNEL_URL,
    is_target_channel_url,
    is_target_vod_url,
    kick_archive,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def cmd_download(args):
    """Canli yayin veya VOD indir."""
    allowed = is_target_channel_url(args.url) if args.live else is_target_vod_url(args.url)
    if not allowed:
        print(
            "Bu kurulum yalnizca "
            f"{TARGET_CHANNEL_URL} kanalinin public yayinlarini isler."
        )
        return

    logger.info("Indirme baslatiliyor: %s", args.url)

    if args.live:
        path = await stream_downloader.download_live(
            args.url,
            duration=args.duration,
            quality=args.quality,
            format_ext=args.format,
        )
    else:
        path = await stream_downloader.download_vod(
            args.url,
            quality=args.quality,
            format_ext=args.format,
        )

    if path:
        print(f"Indirme tamamlandi: {path}")
    else:
        print("Indirme basarisiz!")


async def cmd_extract(args):
    """Video dosyasindan klip cikarir."""
    logger.info("Klip cikarma baslatiliyor: %s", args.video)

    if args.method == "energy":
        clips = await clip_extractor.extract_by_energy(
            args.video,
            min_clip_duration=args.min_duration,
            max_clip_duration=args.max_duration,
            top_n=args.top,
        )
    elif args.method == "scene":
        clips = await clip_extractor.extract_by_scene_change(
            args.video,
            min_clip_duration=args.min_duration,
        )
    elif args.method == "interval":
        clips = await clip_extractor.extract_by_intervals(
            args.video,
            interval_seconds=args.interval,
            clip_duration=args.clip_duration,
        )
    else:
        print(f"Bilinmeyen metot: {args.method}")
        return

    print(f"\n{len(clips)} klip cikarildi:")
    for i, clip in enumerate(clips, 1):
        print(f"  {i}. {clip['path']} ({clip['start']:.1f}s - {clip['end']:.1f}s)")


async def cmd_info(args):
    """Yayin/video bilgisi goster."""
    if not (is_target_channel_url(args.url) or is_target_vod_url(args.url)):
        print(f"Yalnizca {TARGET_CHANNEL_URL} kanali desteklenir.")
        return

    info = await asyncio.to_thread(stream_downloader.get_stream_info, args.url)
    if info:
        print(f"Baslik: {info['title']}")
        print(f"Yayinci: {info['uploader']}")
        print(f"Sure: {info['duration']}s")
        print(f"Canli: {info['is_live']}")
        print(f"Platform: {info['platform']}")
    else:
        print("Bilgi alinamadi!")


async def cmd_generate(args):
    """AI ile baslik/hashtag olustur."""
    metadata = ai_title_generator.generate_full_metadata(
        emotion=args.emotion,
        category=args.category,
        streamer_name=args.streamer,
        viewer_count=args.viewers,
        game_name=args.game,
        platform=args.platform,
    )

    print(f"Baslik: {metadata['title']}")
    print(f"\nAciklama:\n{metadata['description']}")
    print(f"\nHashtag'ler: {' '.join('#' + t for t in metadata['hashtags'])}")


async def cmd_publish(args):
    """Klip yayinla."""
    metadata = ai_title_generator.generate_full_metadata(
        category=args.category,
        streamer_name=args.streamer,
        platform=args.platform,
    )

    result = await auto_publisher.publish(
        video_path=args.video,
        title=metadata["title"],
        description=metadata["description"],
        tags=metadata["hashtags"],
        platform=args.platform,
        privacy=args.privacy,
    )

    if result:
        print(f"Yayinlandi: {result}")
    else:
        print("Yayinlama basarisiz (kimlik bilgileri gerekli)")


async def cmd_sync_kick_archive(args):
    """Yalnizca thetuncay kanalinin yeni acik VOD'larini analiz eder."""
    report = await kick_archive.sync_archive(
        vod_limit=args.vod_limit,
        max_clips_per_vod=args.max_clips_per_vod,
    )
    print(
        "Arsiv taramasi tamamlandi: "
        f"kesfedilen={report['discovered']}, "
        f"islenen={report['processed']}, "
        f"atlanan={report['skipped']}, "
        f"basarisiz={report['failed']}, "
        f"klip={report['clips_generated']}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Otomatik Klip Yakalama ve Duygu-Hareket Analizi Sistemi"
    )
    subparsers = parser.add_subparsers(dest="command", help="Komutlar")

    # Download
    dl = subparsers.add_parser("download", help="Canli yayin/VOD indir")
    dl.add_argument("url", help="Yayin URL'si")
    dl.add_argument("--live", action="store_true", help="Canli yayin modu")
    dl.add_argument("--duration", type=int, help="Kayit suresi (saniye)")
    dl.add_argument("--quality", default="best", choices=["best", "1080p", "720p", "480p", "worst"])
    dl.add_argument("--format", default="mp4", choices=["mp4", "mkv", "webm"])
    dl.set_defaults(func=cmd_download)

    # Extract
    ex = subparsers.add_parser("extract", help="Video'dan klip cikarir")
    ex.add_argument("video", help="Video dosyasi yolu")
    ex.add_argument("--method", default="energy", choices=["energy", "scene", "interval"])
    ex.add_argument("--top", type=int, default=10, help="En iyi N klip")
    ex.add_argument("--min-duration", type=float, default=10)
    ex.add_argument("--max-duration", type=float, default=60)
    ex.add_argument("--interval", type=float, default=30)
    ex.add_argument("--clip-duration", type=float, default=15)
    ex.set_defaults(func=cmd_extract)

    # Info
    info = subparsers.add_parser("info", help="Yayin bilgisi goster")
    info.add_argument("url", help="Yayin URL'si")
    info.set_defaults(func=cmd_info)

    # Generate
    gen = subparsers.add_parser("generate", help="AI baslik/hashtag olustur")
    gen.add_argument("--emotion", default="exciting")
    gen.add_argument("--category", default="exciting")
    gen.add_argument("--streamer", default="Yayinci")
    gen.add_argument("--viewers", type=int, default=0)
    gen.add_argument("--game", default="")
    gen.add_argument("--platform", default="youtube")
    gen.set_defaults(func=cmd_generate)

    # Publish
    pub = subparsers.add_parser("publish", help="Klip yayinla")
    pub.add_argument("video", help="Video dosyasi")
    pub.add_argument("--platform", default="youtube", choices=["youtube", "tiktok", "instagram", "twitter", "kick"])
    pub.add_argument("--category", default="exciting")
    pub.add_argument("--streamer", default="Yayinci")
    pub.add_argument("--privacy", default="private", choices=["private", "public", "unlisted"])
    pub.set_defaults(func=cmd_publish)

    archive = subparsers.add_parser(
        "sync-kick-archive",
        help="Sadece kick.com/thetuncay acik VOD arsivini analiz et",
    )
    archive.add_argument("--vod-limit", type=int, default=3, choices=range(1, 51))
    archive.add_argument("--max-clips-per-vod", type=int, default=5, choices=range(1, 11))
    archive.set_defaults(func=cmd_sync_kick_archive)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
