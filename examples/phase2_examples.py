"""
FAZE 2 Örnek Kullanım ve Demo
Pipeline'ın nasıl kullanılacağını gösteren örnek kod
"""

from src.pipeline import ClipsPipeline
from src.stream_monitor import StreamInfo, StreamStatus
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_1_basic_pipeline():
    """Örnek 1: Temel Pipeline Kullanımı"""
    print("\n" + "="*60)
    print("ÖRNEK 1: Temel Pipeline Kullanımı")
    print("="*60)
    
    # Pipeline'ı oluştur
    pipeline = ClipsPipeline()
    
    # Twitch kanallarını ekle
    pipeline.add_channel("tuncay", "https://twitch.tv/tuncay")
    pipeline.add_channel("example_channel", "https://twitch.tv/example_channel")
    
    # Status'u görüntüle
    status = pipeline.get_status()
    print(f"\nPipeline Durumu:")
    print(f"  State: {status['state']}")
    print(f"  Takip edilen kanal: {status['monitor']['total']}")
    print(f"  Yayında olan: {status['monitor']['online']}")
    
    # Konfigürasyonu görüntüle
    print(f"\nPipeline Konfigürasyonu:")
    for key, value in pipeline.config.items():
        print(f"  {key}: {value}")


def example_2_callback_setup():
    """Örnek 2: Callback Fonksiyonları"""
    print("\n" + "="*60)
    print("ÖRNEK 2: Callback Fonksiyonları Kurulumu")
    print("="*60)
    
    pipeline = ClipsPipeline()
    
    # Custom callback fonksiyonları
    def on_stream_online(channel: str, info: StreamInfo):
        """Yayın başladığında çalışacak fonksiyon"""
        print(f"\n🔴 CANLIYAYINDA: {channel}")
        print(f"   Başlangıç: {info.started_at}")
        if info.title:
            print(f"   Başlık: {info.title}")
        if info.viewers:
            print(f"   İzleyici: {info.viewers}")
    
    def on_stream_offline(channel: str, info: StreamInfo):
        """Yayın bittiğinde çalışacak fonksiyon"""
        print(f"\n✗ YAYINBITTI: {channel}")
    
    def on_stream_ended(channel: str, info: StreamInfo):
        """Yayın sonlandırıldığında çalışacak fonksiyon"""
        print(f"\n⊘ SONLANDI: {channel}")
    
    # Callback'leri kaydet
    pipeline.monitor.register_callback("online", on_stream_online)
    pipeline.monitor.register_callback("offline", on_stream_offline)
    pipeline.monitor.register_callback("ended", on_stream_ended)
    
    print("\nCallback'ler kaydedildi:")
    print(f"  Online callbacks: {len(pipeline.monitor.callbacks['online'])}")
    print(f"  Offline callbacks: {len(pipeline.monitor.callbacks['offline'])}")
    print(f"  Ended callbacks: {len(pipeline.monitor.callbacks['ended'])}")


def example_3_clipper_config():
    """Örnek 3: Klip Ayarlarını Özelleştirme"""
    print("\n" + "="*60)
    print("ÖRNEK 3: Klip Çıkarma Ayarları")
    print("="*60)
    
    pipeline = ClipsPipeline()
    
    # Klip ayarlarını özelleştir
    pipeline.config['min_clip_duration'] = 5.0  # Minimum 5 saniye
    pipeline.config['max_clip_duration'] = 120.0  # Maksimum 2 dakika
    pipeline.config['scene_change_threshold'] = 0.25  # Daha hassas
    pipeline.config['motion_threshold'] = 10.0  # Daha az hareket gerekli
    pipeline.config['clip_detection_methods'] = [
        "scene_change",
        "motion"
    ]
    
    pipeline.save_config()
    
    print("\nKlip Ayarları Güncellendi:")
    print(f"  Min Klip Süresi: {pipeline.config['min_clip_duration']}s")
    print(f"  Max Klip Süresi: {pipeline.config['max_clip_duration']}s")
    print(f"  Scene Change Eşiği: {pipeline.config['scene_change_threshold']}")
    print(f"  Motion Eşiği: {pipeline.config['motion_threshold']}")
    print(f"  Deteksyon Yöntemleri: {', '.join(pipeline.config['clip_detection_methods'])}")


def example_4_monitoring():
    """Örnek 4: Sürekli Monitoring"""
    print("\n" + "="*60)
    print("ÖRNEK 4: Sürekli Stream Monitoring")
    print("="*60)
    
    pipeline = ClipsPipeline()
    
    # Kanal ekle
    pipeline.add_channel("tuncay", "https://twitch.tv/tuncay")
    
    # Callback'leri ekle
    def on_online(channel, info):
        print(f"🔴 {channel} yayında! Otomatik indirme başlıyor...")
        # Pipeline otomatik olarak _process_stream'i çağıracak
    
    pipeline.monitor.register_callback("online", on_online)
    
    print("\nMonitoring başlatılıyor...")
    print("(Gerçek uygulamada bu sürekli çalışır)")
    
    # Monitoring'i başlat
    # pipeline.start()
    
    print("\nMonitoring komutları:")
    print("  pipeline.start()       - Monitoring başlat")
    print("  pipeline.stop()        - Monitoring durdur")
    print("  pipeline.get_status()  - Durumu kontrol et")


def example_5_full_workflow():
    """Örnek 5: Tam İşlem Akışı"""
    print("\n" + "="*60)
    print("ÖRNEK 5: Tam İşlem Akışı (Stream → İndir → Klip Çıkar)")
    print("="*60)
    
    pipeline = ClipsPipeline()
    
    print("\n1️⃣  Pipeline Konfigürasyonu")
    pipeline.config['auto_extract'] = True
    print("   ✓ Otomatik klip çıkarma: AÇIK")
    
    print("\n2️⃣  Kanalları Ekle")
    pipeline.add_channel("tuncay", "https://twitch.tv/tuncay")
    print("   ✓ Kanal eklendi: tuncay")
    
    print("\n3️⃣  Event Callback'lerini Kaydet")
    
    def handle_online(channel, info):
        print(f"\n   🔴 Yayın Başladı: {channel}")
        print(f"      Pipeline şu adımları yapacak:")
        print(f"      1. Video'yu indir → data/raw/")
        print(f"      2. Video'yu analiz et (scene_change, motion)")
        print(f"      3. Klip'leri çıkart → data/processed/")
        print(f"      4. Metadatasını kaydet → data/processed/clips.json")
    
    pipeline.monitor.register_callback("online", handle_online)
    print("   ✓ Callback'ler kaydedildi")
    
    print("\n4️⃣  Pipeline Başlatma")
    print("   Kod:")
    print("      pipeline.start()")
    print("   ")
    print("   Bu komutu çalıştırdığınızda:")
    print("   - Monitor her 5 dakikada bir kanalları kontrol eder")
    print("   - Yayın başladığında otomatik indirme ve klip çıkarma başlar")
    print("   - İşlemler arka planda devam eder")
    
    print("\n5️⃣  Status Monitoring")
    print("   Status almak için:")
    print("      status = pipeline.get_status()")
    print("      print(status)")


def example_6_advanced_config():
    """Örnek 6: İleri Seviye Konfigürasyon"""
    print("\n" + "="*60)
    print("ÖRNEK 6: İleri Seviye Konfigürasyon")
    print("="*60)
    
    pipeline = ClipsPipeline()
    
    # Gelişmiş ayarlar
    advanced_config = {
        "clip_detection_methods": ["scene_change", "motion"],
        "min_clip_duration": 3.0,
        "max_clip_duration": 60.0,
        "scene_change_threshold": 0.3,
        "motion_threshold": 15.0,
        "auto_extract": True,
        # İleri ayarlar
        "min_scenes_per_video": 5,  # Video'da min 5 sahne olması
        "quality_preference": "720p",  # Tercih edilen kalite
        "auto_upload_shorts": False,  # Otomatik Shorts'a yükle mi?
        "shorts_duration_max": 60,  # Shorts max süresi
    }
    
    pipeline.config.update(advanced_config)
    pipeline.save_config()
    
    print("\nİleri Seviye Ayarlar:")
    for key, value in advanced_config.items():
        print(f"  {key}: {value}")


def main():
    """Tüm örnekleri çalıştır"""
    print("\n" + "🎬 "*30)
    print("FAZE 2: TUNCAY-KLİP PIPELINE ÖRNEKLERI")
    print("🎬 "*30)
    
    try:
        example_1_basic_pipeline()
        example_2_callback_setup()
        example_3_clipper_config()
        example_4_monitoring()
        example_5_full_workflow()
        example_6_advanced_config()
        
        print("\n" + "="*60)
        print("✅ TÜM ÖRNEKLER TAMAMLANDI")
        print("="*60)
        print("\nSONRAKİ ADIMLAR:")
        print("1. FAZE 1 dosyalarını (requirements.txt, config.py vb) tamamla")
        print("2. Twitch/YouTube API key'lerini config.py'ye ekle")
        print("3. FFmpeg ve yt-dlp'yi kur")
        print("4. Pipeline'ı gerçek stream'le test et")
        print("5. FAZE 3'e geç (Otomatik yayınlama)")
        
    except Exception as e:
        print(f"\n❌ Hata: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
