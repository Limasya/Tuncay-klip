"""
FAZE 2 Test Modülü
Tüm modüllerin entegrasyonunu test etmek için
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Modülleri import et
from src.pipeline import ClipsPipeline, PipelineState
from src.stream_monitor import StreamMonitor, StreamStatus, StreamInfo
from src.clipper import VideoClipper, DetectionMethod
from src.downloader import StreamDownloader


class TestStreamMonitor(unittest.TestCase):
    """Stream Monitor testleri"""
    
    def setUp(self):
        self.monitor = StreamMonitor()
    
    def test_add_stream(self):
        """Stream ekleme testi"""
        result = self.monitor.add_stream("test_channel", "https://twitch.tv/test")
        self.assertIsNotNone(result)
        self.assertEqual(result.channel, "test_channel")
    
    def test_remove_stream(self):
        """Stream kaldırma testi"""
        self.monitor.add_stream("test_channel", "https://twitch.tv/test")
        result = self.monitor.remove_stream("test_channel")
        self.assertTrue(result)
    
    def test_register_callback(self):
        """Callback kaydetme testi"""
        def dummy_callback(channel, info):
            pass
        
        self.monitor.register_callback("online", dummy_callback)
        self.assertIn(dummy_callback, self.monitor.callbacks["online"])
    
    def test_get_online_streams(self):
        """Yayında olan stream'leri alma testi"""
        self.monitor.add_stream("channel1", "https://twitch.tv/ch1")
        self.monitor.add_stream("channel2", "https://twitch.tv/ch2")
        
        online = self.monitor.get_online_streams()
        self.assertEqual(len(online), 0)  # Başlangıçta hiçbiri yayında değil


class TestVideoClipper(unittest.TestCase):
    """Video Clipper testleri"""
    
    def setUp(self):
        self.clipper = VideoClipper()
    
    def test_initialization(self):
        """İnisiyalizasyon testi"""
        self.assertTrue(self.clipper.output_dir.exists())
    
    def test_metadata_loading(self):
        """Metadata yükleme testi"""
        self.assertIsInstance(self.clipper.clips_metadata, list)
    
    def test_clip_segment_extraction(self):
        """Klip segment çıkarma testi"""
        # Mock video file
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            video_path = f.name
        
        try:
            # Mock çıktı dosyası
            output_path = str(self.clipper.output_dir / "test_clip.mp4")
            
            # Gerçek video olmadığından bu başarısız olacak (expected)
            result = self.clipper.extract_clip(video_path, output_path, 0, 10)
            # Error durumunda False dönmesi expected
            
        finally:
            Path(video_path).unlink(missing_ok=True)


class TestStreamDownloader(unittest.TestCase):
    """Stream Downloader testleri"""
    
    def setUp(self):
        self.downloader = StreamDownloader()
    
    def test_initialization(self):
        """İnisiyalizasyon testi"""
        self.assertTrue(self.downloader.output_dir.exists())
    
    def test_metadata_structure(self):
        """Metadata yapısı testi"""
        self.assertIsInstance(self.downloader.metadata, list)


class TestPipeline(unittest.TestCase):
    """Pipeline entegrasyon testleri"""
    
    def setUp(self):
        self.pipeline = ClipsPipeline()
    
    def test_pipeline_initialization(self):
        """Pipeline başlatma testi"""
        self.assertEqual(self.pipeline.state, PipelineState.IDLE)
        self.assertIsNotNone(self.pipeline.monitor)
        self.assertIsNotNone(self.pipeline.downloader)
        self.assertIsNotNone(self.pipeline.clipper)
    
    def test_add_channel(self):
        """Kanal ekleme testi"""
        self.pipeline.add_channel("test", "https://twitch.tv/test")
        self.assertIn("test", self.pipeline.monitor.streams)
    
    def test_get_status(self):
        """Status alma testi"""
        status = self.pipeline.get_status()
        self.assertIn("state", status)
        self.assertIn("timestamp", status)
        self.assertEqual(status["state"], "idle")
    
    def test_config_loading(self):
        """Config yükleme testi"""
        self.assertIn("clip_detection_methods", self.pipeline.config)
        self.assertIn("min_clip_duration", self.pipeline.config)
        self.assertIn("max_clip_duration", self.pipeline.config)


class TestIntegration(unittest.TestCase):
    """Entegrasyon testleri"""
    
    def test_pipeline_workflow(self):
        """Pipeline workflow testi"""
        pipeline = ClipsPipeline()
        
        # Kanal ekle
        pipeline.add_channel("twitch_channel", "https://twitch.tv/example")
        
        # Kanalın eklenmediğini doğrula
        channels = list(pipeline.monitor.streams.keys())
        self.assertIn("twitch_channel", channels)
        
        # Status kontrol et
        status = pipeline.get_status()
        self.assertEqual(status["state"], "idle")


def run_tests():
    """Tüm testleri çalıştır"""
    unittest.main(argv=[''], verbosity=2, exit=False)


if __name__ == "__main__":
    run_tests()
