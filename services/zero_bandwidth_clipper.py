"""
Zero-Bandwidth Clip Engine
──────────────────────────
Kick VOD'lardan clip onerileri uretirken HICBIR video/ses indirmez.

Mimari:
  Kick API (sadece birkac KB JSON) -> LLM metadata analizi -> Clip onerileri
                                                                ↓
                                            Kullanici onaylarsa -> Sadece o 30sn segmenti indir -> Render

Bant genisligi kullanimi:
  Analiz: ~2-5 KB (API metadata JSON)
  Render: ~2-5 MB (sadece onaylanan clip segmenti, 30-60 sn)
  Toplam: 1 VOD analiz + 3 clip render = 10-15 MB (vs eski: 1-3 GB tam VOD indirme)

────────────────────────────────────────────────────────────────────────────────
TOPLULUK CLIP POLITIKASI (HAK/TIFLIF)
────────────────────────────────────────────────────────────────────────────────
Community clip'ler SADECE zaman/ilgi sinyali olarak kullanilir.

Nasil calisir:
  1. Kick API'den topluluk clip metadata'si cekilir (sadece JSON, video indirilmez)
  2. Bu clip'ler "bu VOD'un bu bolumu ilgi cekici" sinyali olarak LLM'e baglam verir
  3. LLM bu sinyalleri ve VOD metadata'sini analiz ederek clip onerileri uretir
  4. Nihai render her zaman ana VOD kaynagindan (HLS stream) kendi pipeline'imizla yapilir

Neden boyle:
  - Izleyicinin olusturdugu klip dosyasi (m3u8/mp4) dogrudan yayinlanmaz
  - Community clip'in icindeki video yayincinin yayini + izleyicinin editoryal secimi
  - Izin vermeden birinin clip dosyasini kullanmak telif/hak sorunu olabilir
  - Bu tasarim: izleyicinin clip'i sinyal olarak kullanilir, ancak kendi kaynagimizdan render ederiz

NOT: render_clip() fonksiyonu her zaman vod_url'den (ana VOD HLS kaynagindan) render eder,
     community clip URL'si asla dogrudan render kaynagi olarak kullanilmaz.

────────────────────────────────────────────────────────────────────────────────
BACKWARD-COMPATIBLE WRAPPER
────────────────────────────────────────────────────────────────────────────────
Bu dosya, eski import yollarini korumak icin ince bir wrapper'dir.
Tum is mantigi services/zero_bandwidth/ alt-paketinde bulunur.

Yeni kullanim:
    from services.zero_bandwidth import ZeroBandwidthClipper, ClipSuggestion, VODAnalysis

Eski kullanim (hala calisiyor):
    from services.zero_bandwidth_clipper import ZeroBandwidthClipper
"""
# Backward-compatible imports — eski import yollari hala calisiyor
from services.zero_bandwidth.models import ClipSuggestion, VODAnalysis
from services.zero_bandwidth.clipper import ZeroBandwidthClipper

__all__ = ["ZeroBandwidthClipper", "ClipSuggestion", "VODAnalysis"]

# Singleton — eski kodlar `from services.zero_bandwidth_clipper import zero_bandwidth_clipper` bekliyor
zero_bandwidth_clipper = ZeroBandwidthClipper()
