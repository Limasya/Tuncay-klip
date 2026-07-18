"""Quick integration test for Kick API — live status + VOD discovery."""
import asyncio
import sys

sys.path.insert(0, ".")


async def test():
    from services.kick_api import KickAPIService
    svc = KickAPIService()

    print("=== 1. CANLI YAYIN DURUMU ===")
    info = await svc.get_livestream_info()
    is_live = info.get("is_live", False)
    print(f"  is_live  : {is_live}")
    print(f"  title    : {info.get('title', '-')}")
    print(f"  viewers  : {info.get('viewer_count', 0)}")
    print(f"  hls_url  : {str(info.get('playback_url') or '')[:80]}")

    print()
    print("=== 2. SON VOD'LAR (limit=3) ===")
    vods = await svc.list_public_vods(limit=3)
    for v in vods:
        title = v.get("title", "?")
        dur   = v.get("duration", 0)
        url   = v.get("url", "?")
        print(f"  - {title} | {dur}s | {url}")

    await svc.close()

    print()
    live_label = "CANLI" if is_live else "Yayin yok"
    print(f"=== SONUC: {live_label}, {len(vods)} VOD bulundu ===")


asyncio.run(test())
