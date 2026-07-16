# 05 — Ses Motoru (Audio Engine)

## Ses Karıştırma, Loudness İşleme ve Müzik Ducking Sistem Tasarım Dokümanı

**Sürüm:** 1.0.0  
**Durum:** Taslak  
**Son Güncelleme:** 2026-07-16  
**Kapsam:** Kick/Twitch yayınlarından gelen konuşma, oyun sesi, müzik ve ses efekti kaynaklarının profesyonel düzeyde karıştırılması, loudness standardizasyonu ve otomatik müzik ducking mekanizması.

---

## İçindekiler

1. [Genel Bakış ve Mimari](#1-genel-bakış-ve-mimari)
2. [Profesyonel Ses Karıştırıcı](#2-profesyonel-ses-karıştırıcı)
3. [Loudness İşleme](#3-loudness-işleme)
4. [Müzik Ducking Motoru](#4-müzik-ducing-motoru)
5. [Ses Efektleri Zinciri](#5-ses-efektleri-zinciri)
6. [Ses-Video Senkronizasyonu](#6-ses-video-senkronizasyonu)
7. [Performans ve Darboğaz Analizi](#7-performans-ve-darboğaz-analizi)
8. [Ekler](#8-ekler)

---

## 1. Genel Bakış ve Mimari

### 1.1 Sistem Kapsamı

Ses motoru, yayın (Kick/Twitch) kaynaklarından gelen çoklu ses akışlarını real-time veya offline olarak işleyen, profesyonel broadcast standartlarına uygun bir karıştırma ve işleme pipeline'ıdır. Sistem aşağıdaki temel bileşenlerden oluşur:

```
+---------------------------------------------------------------------+
|                        SES MOTORU (AudioEngine)                      |
|                                                                      |
|  +---------------+  +---------------+  +-------------------------+  |
|  | Ses Karistirici|  |  Loudness     |  |  Muzik Ducking Motoru   |  |
|  |  (AudioMixer)   |  |  Isleme       |  |  (DuckingEngine)        |  |
|  |                  |  |  (Loudness    |  |                         |  |
|  |  - Coklu iz      |  |  Processor)  |  |  - Sidechain tabanli    |  |
|  |  - Otomasyon    |  |              |  |  - Spektral ducking      |  |
|  |  - Bus yonlendir |  |  - BS.1770   |  |  - Coklu kaynak         |  |
|  |  - Crossfade    |  |  - EBU R128   |  |  - Otomatik mixes       |  |
|  +----------------+  |  - ATSC A/85  |  +-------------------------+  |
|                       +---------------+                                |
|  +--------------------------------------------------------------+    |
|  |  Ses Efektleri Zinciri (AudioEffectChain)                    |    |
|  |  - EQ - Kompresor - Gurultu Kapisi - De-esser - Reverb      |    |
|  |  - Zaman uzatma - Perde kaydirma                             |    |
|  +--------------------------------------------------------------+    |
|  +--------------------------------------------------------------+    |
|  |  Ses-Video Senkronizasyonu (SyncEngine)                      |    |
|  |  - Lip sync algilama - A/V offset duzeltme - Frame hassas   |    |
|  +--------------------------------------------------------------+    |
+---------------------------------------------------------------------+
```

### 1.2 Veri Akis Semaasi

```
Kaynak Akislari (PCM/AAC/MP3/Opus)
    |
    v
+---------------------+
|  Format cozumleme    |  <- ffmpeg/libav
|  ve normalizasyon    |
|  (PCM 32-bit float) |
+---------+-----------+
          |
          v
+---------------------+
|  Ornekleme hizi      |  <- SoXR
|  donusturme          |
|  (48kHz hedef)       |
+---------+-----------+
          |
          v
+---------------------+
|  Kanal duzeni        |
|  yonetimi            |
|  (stereo hedef)      |
+---------+-----------+
          |
          v
+---------------------+     +------------------+
|  Ses Efektleri       |<----|  Ducking Motoru   |
|  Zinciri             |     |  (sidechain sinyal)|
+---------+-----------+     +------------------+
          |
          v
+---------------------+
|  Karistirici        |
|  (AudioMixer)        |
|  - Vol otomasyon     |
|  - Pan kontrol       |
|  - Bus yonlendirme   |
|  - Crossfade         |
+---------+-----------+
          |
          v
+---------------------+
|  Loudness Isleme     |
|  - Olcum (BS.1770)  |
|  - Normalizasyon     |
|  - Limiting          |
+---------+-----------+
          |
          v
+---------------------+
|  Cikis Kodlama       |
|  (AAC/Opus/FLAC)    |
+---------------------+
```

### 1.3 Temel Tasarim İlkeleri

| Ilke | Aciklama |
|------|----------|
| **Ornekleme Hassasiyeti** | Tum karistirma ve efekt islemleri sample-hassas olmalidir. |
| **Kayipsiz Zincir** | Ic pipeline her zaman 32-bit float PCM kullanir. |
| **Yalitilmis Izlar** | Her iz bagimsiz olarak islenir; efektler iz-seviyesinde uygulanir. |
| **Gercek-Zamanli Uyumluluk** | Real-time senaryolarda 20ms'den az buffer gecikmesi hedeflenir. |
| **Yayin Standardi Uyumu** | Cikis her zaman EBU R128 / ATSC A/85 uyumlu olmalidir. |

---

## 2. Profesyonel Ses Karistirici

### 2.1 Amaç

AudioMixer, coklu ses izlerinin (track) bagimsiz olarak kontrol edildigi, otomasyon ile donatilmis, bus yonlendirmesine sahip, sample-hassas calisan bir dijital ses karistiricisidir. Kick/Twitch yayinlarindan gelen farkli ses kaynaklarini (konusma, oyun sesi, muzik, ses efekti) tek bir tutarli cikis sinyaline donusturur.

### 2.2 Mimari

```
AudioMixer
|
+-- AudioTrack[]           <- Iz koleksiyonu
|   +-- AudioClip[]        <- Iz uzerindeki ses klipleri
|   +-- VolumeKeyframe[]   <- Ses seviyesi otomasyonu
|   +-- PanKeyframe[]      <- Pan otomasyonu
|   +-- AudioEffectChain   <- Iz-seviyesi efektler
|   +-- TrackState         <- Mute/Solo/RecordArm
|
+-- AudioBus[]             <- Alt karistirma otobusleri
|   +-- AudioTrack[] (giris)
|   +-- AudioEffectChain   <- Bus-seviyesi efektler
|   +-- VolumeKeyframe[]   <- Bus otomasyonu
|
+-- MasterBus              <- Ana cikis otobusu
|   +-- AudioBus[] (giris)
|   +-- LoudnessProcessor  <- Loudness isleme
|   +-- SampleRateConverter <- SoXR tabanli
|
+-- MixingEngine           <- Karistirma hesaplama motoru
    +-- ThreadPool         <- Paralel iz isleme
    +-- RingBuffer[]       <- Her iz icin giris tamponu
    +-- OutputBuffer       <- Cikis tamponu (mix-down)
```

### 2.3 Veri Yapisi Tanimlari

```python
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple
import numpy as np


class TrackType(Enum):
    """Iz tipi tanimlari - DMEC siniflandirmasi."""
    DIALOGUE = auto()    # Konusma / VoIP / Streamer sesi
    MUSIC = auto()       # Muzik parcalari / BGM
    EFFECTS = auto()     # Ses efektleri / SFX
    AMBIENCE = auto()    # Ortam sesi / Atmosfer


class ChannelLayout(Enum):
    """Kanallarin uzamsal duzeni."""
    MONO = 1
    STEREO = 2
    SURROUND_5_1 = 6
    SURROUND_7_1 = 8
    ATMOS = 128          # Nesne tabanli; max 128 nesne


class BusType(Enum):
    """Bus (otobus) tipi tanimlari."""
    STANDARD = auto()
    SUBMIX = auto()
    MASTER = auto()


class TrackState:
    """Izin anlik durum bayraklari."""
    def __init__(self):
        self.muted: bool = False
        self.solo: bool = False
        self.record_arm: bool = False
        self.volume_db: float = 0.0
        self.pan: float = 0.0          # -1.0 (sol) ... +1.0 (sag)
        self.height_pan: float = 0.0   # Atmos yukseklik pan
        self.depth_pan: float = 0.0    # Atmos derinlik pan

    def is_audible(self, any_solo_active: bool) -> bool:
        """Bu izin duyulabilir olup olmadigini hesaplar."""
        if self.muted:
            return False
        if any_solo_active and not self.solo:
            return False
        return True


@dataclass
class VolumeKeyframe:
    """Ses seviyesi anahtar karesi (keyframe)."""
    time_seconds: float       # Zaman damgasi (saniye)
    volume_db: float          # Desibel cinsinden ses seviyesi
    curve_type: str = "linear"  # linear | exponential | logarithmic | s_curve
    bezier_cp1: float = 0.0
    bezier_cp2: float = 0.0


@dataclass
class PanKeyframe:
    """Pan otomasyonu anahtar karesi."""
    time_seconds: float
    pan_l_r: float = 0.0      # Sol-Sag (-1.0 ... +1.0)
    pan_u_d: float = 0.0      # Ust-Alt (atmos)
    pan_f_b: float = 0.0      # On-Arka (atmos)


@dataclass
class AudioClip:
    """Tek bir ses klibini temsil eder."""
    clip_id: str
    source_path: str
    start_time_seconds: float       # Timeline uzerindeki baslangic
    in_point_seconds: float         # Kaynak dosyadaki icerik baslangici
    out_point_seconds: float        # Kaynak dosyadaki bitis noktasi
    playback_rate: float = 1.0      # Hiz carpani (0.5x - 2.0x)
    gain_db: float = 0.0            # Klibe ozgu kazanc
    fade_in_samples: int = 0        # Fade-in uzunlugu
    fade_out_samples: int = 0       # Fade-out uzunlugu
    crossfade_type: str = "equal_power"
    _cached_pcm: Optional[np.ndarray] = field(default=None, repr=False)
    _sample_rate: int = 48000
    _channels: int = 2

    @property
    def duration_seconds(self) -> float:
        return self.out_point_seconds - self.in_point_seconds

    @property
    def total_samples(self) -> int:
        return int(self.duration_seconds * self._sample_rate)

    def get_samples_at(self, timeline_time: float) -> Optional[Tuple[np.ndarray, int]]:
        """Timeline zamanina karsilik gelen ornekleri dondurur."""
        local_time = timeline_time - self.start_time_seconds + self.in_point_seconds
        if local_time < self.in_point_seconds or local_time >= self.out_point_seconds:
            return None
        sample_offset = int((local_time - self.in_point_seconds) * self._sample_rate)
        return (self._cached_pcm, sample_offset)


@dataclass
class AudioTrack:
    """Tek bir ses izini temsil eder."""
    track_id: str
    name: str
    track_type: TrackType
    channel_layout: ChannelLayout = ChannelLayout.STEREO
    clips: List[AudioClip] = field(default_factory=list)
    volume_keyframes: List[VolumeKeyframe] = field(default_factory=list)
    pan_keyframes: List[PanKeyframe] = field(default_factory=list)
    state: TrackState = field(default_factory=TrackState)
    bus_id: Optional[str] = None
    effect_chain: Optional['AudioEffectChain'] = None
    peak_meter_l: float = -96.0
    peak_meter_r: float = -96.0

    def get_active_clips_at(self, time_s: float) -> List[AudioClip]:
        """Belirli bir zamanda aktif olan klipleri dondurur."""
        return [c for c in self.clips
                if c.start_time_seconds <= time_s
                < c.start_time_seconds + c.duration_seconds]

    def evaluate_volume_at(self, time_s: float) -> float:
        """Volume otomasyonunu degerlendirerek belirli zamandaki ses seviyesini hesaplar."""
        if not self.volume_keyframes:
            return self.state.volume_db
        sorted_kf = sorted(self.volume_keyframes, key=lambda k: k.time_seconds)
        if time_s <= sorted_kf[0].time_seconds:
            return sorted_kf[0].volume_db
        if time_s >= sorted_kf[-1].time_seconds:
            return sorted_kf[-1].volume_db
        for i in range(len(sorted_kf) - 1):
            kf_a = sorted_kf[i]
            kf_b = sorted_kf[i + 1]
            if kf_a.time_seconds <= time_s < kf_b.time_seconds:
                t = ((time_s - kf_a.time_seconds)
                     / (kf_b.time_seconds - kf_a.time_seconds))
                return _interpolate_volume(kf_a, kf_b, t)
        return self.state.volume_db


@dataclass
class AudioBus:
    """Alt karistirma otobusu (submix bus)."""
    bus_id: str
    name: str
    bus_type: BusType = BusType.SUBMIX
    input_track_ids: List[str] = field(default_factory=list)
    volume_keyframes: List[VolumeKeyframe] = field(default_factory=list)
    pan_keyframes: List[PanKeyframe] = field(default_factory=list)
    effect_chain: Optional['AudioEffectChain'] = None
    output_bus_id: Optional[str] = None
    state: TrackState = field(default_factory=TrackState)


class AudioMixer:
    """Ana ses karistiricisi. Tum izleri ve bus'lari yonetir, sample-hassas karistirma islemini yurutur."""

    def __init__(self, sample_rate: int = 48000, channels: int = 2, bit_depth: int = 32):
        self.sample_rate = sample_rate
        self.channels = channels
        self.bit_depth = bit_depth
        self.tracks: dict[str, AudioTrack] = {}
        self.buses: dict[str, AudioBus] = {}
        self.master_bus: AudioBus = AudioBus(bus_id="master", name="Master Bus", bus_type=BusType.MASTER)
        self.timeline_position: float = 0.0
        self._thread_pool_size: int = 8

    def add_track(self, track: AudioTrack) -> None:
        """Yeni bir iz ekler."""
        self.tracks[track.track_id] = track

    def remove_track(self, track_id: str) -> None:
        """Izi kaldirir."""
        if track_id in self.tracks:
            del self.tracks[track_id]

    def add_bus(self, bus: AudioBus) -> None:
        """Yeni bir bus ekler."""
        self.buses[bus.bus_id] = bus

    def route_track_to_bus(self, track_id: str, bus_id: str) -> None:
        """Izi bir bus'a yonlendirir."""
        if track_id in self.tracks and bus_id in self.buses:
            self.tracks[track_id].bus_id = bus_id
            if bus_id not in self.buses[bus_id].input_track_ids:
                self.buses[bus_id].input_track_ids.append(track_id)

    def get_solo_active(self) -> bool:
        """Herhangi bir izin solo modda olup olmadigini kontrol eder."""
        return any(t.state.solo for t in self.tracks.values())

    def mix_block(self, frame_count: int) -> np.ndarray:
        """
        Belirtilen sayida ornek (frame) icin tum izleri karistirir.

        Algoritma:
        1. Her iz icin ilgili kliplerden PCM verisi okunur
        2. Volume ve pan otomasyonu degerlendirilir
        3. Efektler uygulanir (varsa)
        4. Bus seviyesinde toplama yapilir
        5. Master bus'ta nihai mix-down gerceklestirilir

        Return: Shape (frame_count, channels) numpy array -- float32
        """
        any_solo = self.get_solo_active()
        bus_buffers: dict[str, np.ndarray] = {}
        for bus_id in self.buses:
            bus_buffers[bus_id] = np.zeros((frame_count, self.channels), dtype=np.float32)
        master_buffer = np.zeros((frame_count, self.channels), dtype=np.float32)

        for track_id, track in self.tracks.items():
            if not track.state.is_audible(any_solo):
                continue
            track_buffer = np.zeros((frame_count, self.channels), dtype=np.float32)

            for clip in track.get_active_clips_at(self.timeline_position):
                result = clip.get_samples_at(self.timeline_position)
                if result is None:
                    continue
                pcm_data, offset = result
                end_offset = min(offset + frame_count, len(pcm_data))
                available = end_offset - offset
                if available <= 0:
                    continue
                block = pcm_data[offset:offset + available].copy()
                gain_linear = 10 ** (clip.gain_db / 20.0)
                block *= gain_linear
                block = _apply_fades(block, clip, offset, self.sample_rate)
                if block.ndim == 1:
                    block = np.column_stack([block, block])
                track_buffer[:available] += block[:available]

            for i in range(frame_count):
                sample_time = self.timeline_position + i / self.sample_rate
                vol_db = track.evaluate_volume_at(sample_time)
                vol_linear = 10 ** (vol_db / 20.0)
                track_buffer[i] *= vol_linear

            pan_kf = track.pan_keyframes
            if pan_kf:
                sorted_pan = sorted(pan_kf, key=lambda k: k.time_seconds)
                for i in range(frame_count):
                    sample_time = self.timeline_position + i / self.sample_rate
                    pan_val = _interpolate_pan_at(sorted_pan, sample_time)
                    track_buffer[i] = _apply_stereo_pan(track_buffer[i], pan_val)
            elif track.state.pan != 0.0:
                pan_val = track.state.pan
                for i in range(frame_count):
                    track_buffer[i] = _apply_stereo_pan(track_buffer[i], pan_val)

            if track.effect_chain:
                track_buffer = track.effect_chain.process(track_buffer, self.sample_rate)

            target_bus = track.bus_id or "master"
            if target_bus in bus_buffers:
                bus_buffers[target_bus] += track_buffer
            else:
                master_buffer += track_buffer

        for bus_id, bus in self.buses.items():
            if bus_id not in bus_buffers:
                continue
            buf = bus_buffers[bus_id]
            for i in range(frame_count):
                sample_time = self.timeline_position + i / self.sample_rate
                if bus.volume_keyframes:
                    sorted_kf = sorted(bus.volume_keyframes, key=lambda k: k.time_seconds)
                    vol_db = _interpolate_volume_at_list(sorted_kf, sample_time)
                else:
                    vol_db = bus.state.volume_db
                vol_linear = 10 ** (vol_db / 20.0)
                buf[i] *= vol_linear
            if bus.effect_chain:
                buf = bus.effect_chain.process(buf, self.sample_rate)
            master_buffer += buf

        master_buffer = np.clip(master_buffer, -1.0, 1.0)
        return master_buffer

    def seek(self, time_seconds: float) -> None:
        """Timeline konumunu ayarlar."""
        self.timeline_position = max(0.0, time_seconds)

    def render_range(self, start_time: float, end_time: float, block_size: int = 4096) -> np.ndarray:
        """Belirtilen zaman araligini tam olarak render eder."""
        self.seek(start_time)
        total_duration = end_time - start_time
        total_samples = int(total_duration * self.sample_rate)
        output = np.zeros((total_samples, self.channels), dtype=np.float32)
        written = 0
        while written < total_samples:
            remaining = total_samples - written
            current_block = min(block_size, remaining)
            block = self.mix_block(current_block)
            output[written:written + current_block] = block
            written += current_block
            self.timeline_position += current_block / self.sample_rate
        return output


def db_to_linear(db: float) -> float:
    """Degeri lineer kazanc carpanina donusturur."""
    return 10.0 ** (db / 20.0)


def linear_to_db(linear: float) -> float:
    """Lineer kazanc carpanini desibele donusturur."""
    if linear <= 0:
        return -96.0
    return 20.0 * np.log10(linear)


def _interpolate_volume(kf_a: VolumeKeyframe, kf_b: VolumeKeyframe, t: float) -> float:
    """Iki volume keyframe arasinda interpolasyon yapar."""
    if kf_a.curve_type == "linear":
        return kf_a.volume_db + (kf_b.volume_db - kf_a.volume_db) * t
    elif kf_a.curve_type == "exponential":
        return kf_a.volume_db + (kf_b.volume_db - kf_a.volume_db) * (t ** 2)
    elif kf_a.curve_type == "logarithmic":
        return kf_a.volume_db + (kf_b.volume_db - kf_a.volume_db) * np.log(1 + t * (np.e - 1))
    elif kf_a.curve_type == "s_curve":
        s = 3 * t ** 2 - 2 * t ** 3
        return kf_a.volume_db + (kf_b.volume_db - kf_a.volume_db) * s
    else:
        return kf_a.volume_db + (kf_b.volume_db - kf_a.volume_db) * t


def _interpolate_volume_at_list(sorted_kf: List[VolumeKeyframe], time_s: float) -> float:
    """Sirali keyframe listesinde belirli zamandaki volume degerini hesaplar."""
    if not sorted_kf:
        return 0.0
    if time_s <= sorted_kf[0].time_seconds:
        return sorted_kf[0].volume_db
    if time_s >= sorted_kf[-1].time_seconds:
        return sorted_kf[-1].volume_db
    for i in range(len(sorted_kf) - 1):
        if sorted_kf[i].time_seconds <= time_s < sorted_kf[i + 1].time_seconds:
            t = ((time_s - sorted_kf[i].time_seconds) / (sorted_kf[i + 1].time_seconds - sorted_kf[i].time_seconds))
            return _interpolate_volume(sorted_kf[i], sorted_kf[i + 1], t)
    return sorted_kf[-1].volume_db


def _interpolate_pan_at(sorted_pan: List[PanKeyframe], time_s: float) -> float:
    """Belirli zamandaki pan degerini hesaplar."""
    if not sorted_pan:
        return 0.0
    if time_s <= sorted_pan[0].time_seconds:
        return sorted_pan[0].pan_l_r
    if time_s >= sorted_pan[-1].time_seconds:
        return sorted_pan[-1].pan_l_r
    for i in range(len(sorted_pan) - 1):
        if sorted_pan[i].time_seconds <= time_s < sorted_pan[i + 1].time_seconds:
            t = ((time_s - sorted_pan[i].time_seconds) / (sorted_pan[i + 1].time_seconds - sorted_pan[i].time_seconds))
            return sorted_pan[i].pan_l_r + (sorted_pan[i + 1].pan_l_r - sorted_pan[i].pan_l_r) * t
    return sorted_pan[-1].pan_l_r


def _apply_stereo_pan(sample: np.ndarray, pan: float) -> np.ndarray:
    """Stereo pan Law uygulanir. -3dB pan law: Sol = sqrt((1 - pan) / 2), Sag = sqrt((1 + pan) / 2)"""
    if len(sample) < 2:
        return sample
    left_gain = np.sqrt((1.0 - pan) / 2.0)
    right_gain = np.sqrt((1.0 + pan) / 2.0)
    return np.array([sample[0] * left_gain, sample[1] * right_gain], dtype=np.float32)


def _apply_fades(block: np.ndarray, clip: AudioClip, sample_offset: int, sample_rate: int) -> np.ndarray:
    """Klibe fade-in ve fade-out uygular."""
    result = block.copy()
    total_samples = clip.total_samples
    if clip.fade_in_samples > 0 and sample_offset < clip.fade_in_samples:
        fade_end = min(clip.fade_in_samples - sample_offset, len(result))
        fade_curve = np.linspace(0.0, 1.0, fade_end, dtype=np.float32)
        if result.ndim > 1:
            result[:fade_end] *= fade_curve[:, np.newaxis]
        else:
            result[:fade_end] *= fade_curve
    if clip.fade_out_samples > 0:
        fade_start_sample = total_samples - clip.fade_out_samples
        local_start = fade_start_sample - sample_offset
        if local_start < len(result) and local_start >= 0:
            fade_len = min(len(result) - local_start, clip.fade_out_samples)
            fade_curve = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
            end_idx = local_start + fade_len
            if result.ndim > 1:
                result[local_start:end_idx] *= fade_curve[:, np.newaxis]
            else:
                result[local_start:end_idx] *= fade_curve
    return result
```

### 2.4 Ses Crossfade Algoritmalari

Crossfade, iki ses klibi arasindaki gecis sirasinda her ikisini de ayni anda calarak yumusak bir gecis saglar. Uc ana algoritma desteklenir:

```
Equal Power Crossfade:
  -- A'nin gucu azalirken B'nin gucu artar
  -- Toplam guc her zaman sabittir (enerji korunumu)
  -- Gecis bolgesinde volume dususu olmaz

  gain_A(t) = cos(t x pi/2)
  gain_B(t) = sin(t x pi/2)
  t: 0.0 (gecis baslangici) -> 1.0 (gecis bitisi)

Linear Crossfade:
  -- Dogrusal rampa
  -- Gecis bolgesinde ~-6dB dusus (volume cukuru)
  -- Basit ama profesyonel olmayan

  gain_A(t) = 1.0 - t
  gain_B(t) = t

Exponential Crossfade:
  -- Ustel egrI
  -- Daha agresif gecis
  -- Bazi senaryolarda tercih edilir

  gain_A(t) = (1 - t)^2
  gain_B(t) = 1 - (1 - t)^2
```

```python
def crossfade_equal_power(block_a: np.ndarray, block_b: np.ndarray,
                          overlap_samples: int) -> np.ndarray:
    """
    Equal-power crossfade iki blok arasinda uygulanir.
    block_a ve block_b ayni boyutta olmalidir.
    overlap_samples: caprazlama yapilacak ornek sayisi.
    """
    assert len(block_a) == len(block_b), "Bloklar ayni boyutta olmali"
    n = len(block_a)
    result = np.zeros_like(block_a, dtype=np.float64)
    fade_region = min(overlap_samples, n)
    for i in range(n):
        if i < n - fade_region:
            result[i] = block_a[i]
        elif i < n:
            t = (i - (n - fade_region)) / fade_region
            gain_a = np.cos(t * np.pi / 2)
            gain_b = np.sin(t * np.pi / 2)
            result[i] = block_a[i] * gain_a + block_b[i] * gain_b
        else:
            result[i] = block_b[i]
    return result.astype(np.float32)


def crossfade_linear(block_a: np.ndarray, block_b: np.ndarray,
                     overlap_samples: int) -> np.ndarray:
    """Dogrusal crossfade."""
    n = len(block_a)
    result = np.zeros_like(block_a, dtype=np.float64)
    fade_region = min(overlap_samples, n)
    for i in range(n):
        if i < n - fade_region:
            result[i] = block_a[i]
        elif i < n:
            t = (i - (n - fade_region)) / fade_region
            result[i] = block_a[i] * (1.0 - t) + block_b[i] * t
        else:
            result[i] = block_b[i]
    return result.astype(np.float32)


def crossfade_exponential(block_a: np.ndarray, block_b: np.ndarray,
                          overlap_samples: int) -> np.ndarray:
    """Ustel crossfade."""
    n = len(block_a)
    result = np.zeros_like(block_a, dtype=np.float64)
    fade_region = min(overlap_samples, n)
    for i in range(n):
        if i < n - fade_region:
            result[i] = block_a[i]
        elif i < n:
            t = (i - (n - fade_region)) / fade_region
            gain_a = (1.0 - t) ** 2
            gain_b = 1.0 - (1.0 - t) ** 2
            result[i] = block_a[i] * gain_a + block_b[i] * gain_b
        else:
            result[i] = block_b[i]
    return result.astype(np.float32)
```

### 2.5 Biçim Yonetimi (Format Handling)

#### 2.5.1 Desteklenen Ses Biçimleri

| Biçim | Codec | Bit Derinligi | Ornekleme Hizi | Kullanim Alani |
|-------|-------|---------------|-----------------|----------------|
| PCM (WAV/AVI) | LPCM | 16/24/32-bit int, 32/64-bit float | 8kHz - 192kHz | Ham ses, intermediate processing |
| AAC | AAC-LC / HE-AAC | 16-bit | 44.1kHz / 48kHz | Twitch/Kick cikisi, broadcast |
| MP3 | MPEG-1/2 Layer III | 16-bit | 44.1kHz / 48kHz | Geriye uyumluluk |
| FLAC | FLAC | 16/24/32-bit | 1kHz - 655kHz | Kayipsiz arsiv, ses efekti kutuphanesi |
| Opus | Opus | 16-bit | 8kHz - 48kHz | Dusuk gecikme, live streaming |

#### 2.5.2 Cozumleme Pipeline'i

```
Girdi Biçimi -> ffmpeg/libav decode -> Ham PCM (32-bit float, 48kHz)
    -> SoXR yeniden ornekleme (gerekirse)
    -> Kanal donusumu (gerekirse)
    -> Mix motoru
```

#### 2.5.3 Yeniden Ornekleme (SoXR Entegrasyonu)

```python
class SampleRateConverter:
    """SoXR tabanli yeniden ornekleme."""

    QUALITY_LOW = 0       # Hiz oncelikli (real-time icin)
    QUALITY_MEDIUM = 1    # Dengeli
    QUALITY_HIGH = 2      # Kalite oncelikli (offline rendering)
    QUALITY_VERY_HIGH = 3 # En yuksek kalite (mastering)

    def __init__(self, quality: int = 2):
        self.quality = quality

    def convert(self, input_pcm: np.ndarray, input_rate: int,
                output_rate: int, channels: int) -> np.ndarray:
        if input_rate == output_rate:
            return input_pcm
        ratio = output_rate / input_rate
        new_length = int(len(input_pcm) * ratio)
        indices = np.linspace(0, len(input_pcm) - 1, new_length)
        output = np.zeros((new_length, channels), dtype=np.float32)
        for ch in range(channels):
            output[:, ch] = np.interp(indices, np.arange(len(input_pcm)), input_pcm[:, ch])
        return output
```

#### 2.5.4 Kanal Duzeni Yonetimi

```python
class ChannelManager:
    """Kanal donusumlerini yonetir."""

    @staticmethod
    def mono_to_stereo(mono: np.ndarray) -> np.ndarray:
        if mono.ndim == 1:
            return np.column_stack([mono, mono])
        return mono

    @staticmethod
    def stereo_to_mono(stereo: np.ndarray) -> np.ndarray:
        if stereo.ndim == 2 and stereo.shape[1] >= 2:
            return (stereo[:, 0] + stereo[:, 1]) / 2.0
        return stereo

    @staticmethod
    def stereo_to_5_1(stereo: np.ndarray) -> np.ndarray:
        """Stereo -> 5.1 surround donusumu (ITU-R BS.775)."""
        n = len(stereo)
        output = np.zeros((n, 6), dtype=np.float32)
        l = stereo[:, 0]
        r = stereo[:, 1] if stereo.shape[1] > 1 else stereo[:, 0]
        output[:, 0] = l * 0.7071
        output[:, 1] = r * 0.7071
        output[:, 2] = (l + r) * 0.5
        output[:, 3] = (l + r) * 0.5
        output[:, 4] = l * 0.7071
        output[:, 5] = r * 0.7071
        return output

    @staticmethod
    def downmix_5_1_to_stereo(surround: np.ndarray) -> np.ndarray:
        """5.1 -> Stereo downmix."""
        if surround.shape[1] < 6:
            raise ValueError("Girdi en az 6 kanalli olmalidir")
        n = len(surround)
        output = np.zeros((n, 2), dtype=np.float32)
        output[:, 0] = surround[:, 0] + surround[:, 2] * 0.7071 + surround[:, 4] * 0.7071
        output[:, 1] = surround[:, 1] + surround[:, 2] * 0.7071 + surround[:, 5] * 0.7071
        return output
```

### 2.6 API Sozlesmeleri

```python
class AudioMixerAPI:
    """Ses karistiricisi icin ust duzey API."""

    def create_track(self, name, track_type, channel_layout=ChannelLayout.STEREO) -> AudioTrack: ...
    def import_clip(self, track_id, file_path, start_time=0.0) -> AudioClip: ...
    def set_volume_keyframe(self, track_id, time_s, volume_db, curve="linear") -> None: ...
    def set_pan_keyframe(self, track_id, time_s, pan_lr) -> None: ...
    def mute_track(self, track_id, muted=True) -> None: ...
    def solo_track(self, track_id, solo=True) -> None: ...
    def create_bus(self, name, bus_type=BusType.SUBMIX) -> AudioBus: ...
    def route_track(self, track_id, bus_id) -> None: ...
    def render(self, start, end, output_path, format="wav") -> None: ...
```

### 2.7 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|----------|------|-------|
| **Buyuk dosya okuma** | 4GB+ WAV icin bellek baskisi | Memory-mapped dosya I/O; chunk bazli okuma |
| **Coklu iz karistirma** | 50+ iz ile performans dususu | SIMD vektor islemler; paralel iz isleme |
| **Yuksek ornekleme hizi** | 96kHz/192kHz CPU yogunlugu | Isleme 48kHz'de; cikista yeniden ornekleme |
| **Efekt zinciri gecikmesi** | Latency artisi | Block-based processing; lookahead buffer |
| **Format cozumleme** | CPU darboğazi | Hardware-accelerated decode; parallel threads |

---

## 3. Loudness Isleme

### 3.1 Amaç

Loudness isleme modulu, cikis sesinin uluslararasi yayin standartlarina (ITU-R BS.1770, EBU R128, ATSC A/85) uygunlugunu saglar. Sosyal medya platformlari icin -14 LUFS hedef loudness ile loudness normalizasyonu ve true peak sinirlama yapar.

### 3.2 Mimari

```
LoudnessProcessor
|
+-- MeasurementEngine
|   +-- MomentaryMeter      <- 400ms pencere
|   +-- ShortTermMeter      <- 3s pencere
|   +-- IntegratedMeter     <- Tam program olcumu
|   +-- TruePeakMeter       <- True peak (4x OS)
|   +-- LRAMeter            <- Loudness range hesabi
|
+-- NormalizationEngine
|   +-- LoudnessNormalizer   <- Hedef loudness'a normalizasyon
|   +-- GainComputer         <- Kazanc hesaplama (dB)
|   +-- DitherEngine         <- Dithering
|
+-- LimiterEngine
|   +-- TruePeakLimiter      <- True peak sinirlama
|   +-- LoudnessLimiter      <- Loudness tabanli sinirlama
|   +-- ReleaseComputer      <- Release zamani hesaplama
|
+-- ComplianceChecker
    +-- EBU_R128_Checker      <- EBU R128 uyum kontrolu
    +-- ATSC_A85_Checker      <- ATSC A/85 uyum kontrolu
    +-- PlatformChecker       <- Platform-spesifik kontrol
```

### 3.3 Veri Yapisi Tanimlari

```python
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple
import numpy as np


class LoudnessStandard(Enum):
    ITU_BS1770_4 = auto()
    EBU_R128 = auto()
    ATSC_A85 = auto()
    OPUS = auto()
    PLATFORM_SOCIAL = auto()


@dataclass
class LoudnessMeasurement:
    """Loudness olcum sonuclarini tutar. Tum degerler LUFS cinsindendir."""
    integrated_lufs: float = -70.0
    momentary_lufs: float = -70.0
    short_term_lufs: float = -70.0
    loudness_range_lu: float = 0.0
    true_peak_dbtp: float = -96.0
    true_peak_sample: float = 0.0
    lra_low_lu: float = -70.0
    lra_high_lu: float = -70.0
    measurement_duration: float = 0.0
    sample_rate: int = 48000
    channels: int = 2
    momentary_history: List[float] = field(default_factory=list)
    short_term_history: List[float] = field(default_factory=list)
    true_peak_history: List[float] = field(default_factory=list)


@dataclass
class LoudnessTarget:
    """Hedef loudness parametreleri."""
    target_lufs: float = -14.0
    tolerance_lu: float = 1.0
    max_true_peak_dbtp: float = -1.0
    max_lra_lu: float = 20.0
    min_lra_lu: float = 5.0
    standard: LoudnessStandard = LoudnessStandard.PLATFORM_SOCIAL

    @classmethod
    def youtube(cls): return cls(target_lufs=-14.0, max_true_peak_dbtp=-1.0, standard=LoudnessStandard.PLATFORM_SOCIAL)
    @classmethod
    def spotify(cls): return cls(target_lufs=-14.0, max_true_peak_dbtp=-1.0, standard=LoudnessStandard.PLATFORM_SOCIAL)
    @classmethod
    def broadcast_ebu(cls): return cls(target_lufs=-23.0, max_true_peak_dbtp=-1.0, tolerance_lu=0.5, standard=LoudnessStandard.EBU_R128)
    @classmethod
    def broadcast_atsc(cls): return cls(target_lufs=-24.0, max_true_peak_dbtp=-2.0, tolerance_lu=2.0, standard=LoudnessStandard.ATSC_A85)
    @classmethod
    def twitch(cls): return cls(target_lufs=-14.0, max_true_peak_dbtp=-1.0, standard=LoudnessStandard.PLATFORM_SOCIAL)


@dataclass
class LoudnessCompliance:
    """Loudness uygunluk sonuc raporu."""
    is_compliant: bool = False
    standard: LoudnessStandard = LoudnessStandard.PLATFORM_SOCIAL
    measurement: Optional[LoudnessMeasurement] = None
    target: Optional[LoudnessTarget] = None
    integrated_deviation_lu: float = 0.0
    true_peak_exceeded: bool = False
    lra_exceeded: bool = False
    recommended_gain_db: float = 0.0
    issues: List[str] = field(default_factory=list)
```

### 3.4 Ana Loudness Islemci

```python
class LoudnessProcessor:
    """
    ITU-R BS.1770 tabanli loudness olcum ve isleme motoru.
    BS.1770 Algoritmasi:
    1. Girdi sinyali K-weighting ile filtrelenir
    2. Kanallar MSFC hesaplanir
    3. Kanal agirliklari uygulanir
    4. Momentary, short-term, integrated loudness hesaplanir
    5. True peak 4x oversampling ile olculur
    """

    def __init__(self, sample_rate: int = 48000, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self.target = LoudnessTarget.youtube()
        self._k_weighting_filter = KWeightingFilter(sample_rate)
        self._true_peak_detector = TruePeakDetector(4)

    def measure(self, audio: np.ndarray) -> LoudnessMeasurement:
        measurement = LoudnessMeasurement(
            sample_rate=self.sample_rate, channels=self.channels,
            measurement_duration=len(audio) / self.sample_rate)
        weighted = self._k_weighting_filter.process(audio)

        # Momentary loudness (400ms)
        window_samples = int(0.4 * self.sample_rate)
        hop_samples = int(0.1 * self.sample_rate)
        momentary_values = []
        for start in range(0, len(weighted) - window_samples, hop_samples):
            block = weighted[start:start + window_samples]
            momentary_values.append(self._calculate_block_loudness(block))
        measurement.momentary_history = momentary_values
        if momentary_values:
            measurement.momentary_lufs = max(momentary_values)

        # Short-term loudness (3s)
        st_window = int(3.0 * self.sample_rate)
        st_hop = int(1.0 * self.sample_rate)
        st_values = []
        for start in range(0, len(weighted) - st_window, st_hop):
            block = weighted[start:start + st_window]
            st_values.append(self._calculate_block_loudness(block))
        measurement.short_term_history = st_values
        if st_values:
            measurement.short_term_lufs = max(st_values)

        # Integrated loudness
        measurement.integrated_lufs = self._calculate_block_loudness(weighted)

        # True peak
        tp_val, tp_sample = self._true_peak_detector.find_peak(audio)
        measurement.true_peak_dbtp = tp_val
        measurement.true_peak_sample = tp_sample

        # Loudness Range (LRA)
        if st_values:
            sorted_st = sorted(st_values)
            n = len(sorted_st)
            low_idx = max(0, int(n * 0.10))
            high_idx = min(n - 1, int(n * 0.95))
            measurement.lra_low_lu = sorted_st[low_idx]
            measurement.lra_high_lu = sorted_st[high_idx]
            measurement.loudness_range_lu = sorted_st[high_idx] - sorted_st[low_idx]
        return measurement

    def normalize(self, audio: np.ndarray, target=None):
        target = target or self.target
        measurement = self.measure(audio)
        gain_db = target.target_lufs - measurement.integrated_lufs
        gain_linear = 10 ** (gain_db / 20.0)
        normalized = audio * gain_linear

        tp_val, _ = self._true_peak_detector.find_peak(normalized)
        if tp_val > target.max_true_peak_dbtp:
            limiting_gain_db = target.max_true_peak_dbtp - tp_val
            normalized *= 10 ** (limiting_gain_db / 20.0)

        final_measurement = self.measure(normalized)
        compliance = LoudnessCompliance(
            standard=target.standard, measurement=final_measurement, target=target,
            integrated_deviation_lu=abs(final_measurement.integrated_lufs - target.target_lufs),
            true_peak_exceeded=final_measurement.true_peak_dbtp > target.max_true_peak_dbtp,
            lra_exceeded=final_measurement.loudness_range_lu > target.max_lra_lu,
            recommended_gain_db=gain_db)
        compliance.is_compliant = (compliance.integrated_deviation_lu <= target.tolerance_lu
                                   and not compliance.true_peak_exceeded and not compliance.lra_exceeded)
        return normalized, compliance

    def _calculate_block_loudness(self, block: np.ndarray) -> float:
        """BS.1770 blok loudness hesabi. L = -0.691 + 10 x log10(Sigma Gi x M_i)"""
        if block.ndim == 1:
            block = block.reshape(-1, 1)
        channels = block.shape[1]
        weights = [1.0, 1.0]
        if channels > 2:
            weights = [1.0, 1.0, 1.0, 0.0, 1.41, 1.41]
        j = 0.0
        for ch in range(min(channels, len(weights))):
            j += weights[ch] * np.mean(block[:, ch] ** 2)
        if j <= 0:
            return -70.0
        return round(-0.691 + 10.0 * np.log10(j), 1)


class KWeightingFilter:
    """
    BS.1770-4 K-weighting filtresi.
    Iki asamali: High-shelf (+4dB @ ~1.5kHz) ve High-pass (RLB).
    IIR filtre katsayilari (48kHz icin).
    """

    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        if sample_rate == 48000:
            self._pre_b = [1.53512485958697, -2.69169618940638, 1.19839281085285]
            self._pre_a = [1.0, -1.69065929318241, 0.73248077421585]
            self._rlb_b = [1.0, -2.0, 1.0]
            self._rlb_a = [1.0, -1.99004745483398, 0.99007225036621]
        else:
            raise ValueError(f"Desteklenmeyen ornekleme hizi: {sample_rate}")

    def process(self, audio: np.ndarray) -> np.ndarray:
        from scipy.signal import lfilter
        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)
        result = np.zeros_like(audio, dtype=np.float64)
        for ch in range(audio.shape[1]):
            stage1 = lfilter(self._pre_b, self._pre_a, audio[:, ch].astype(np.float64))
            stage2 = lfilter(self._rlb_b, self._rlb_a, stage1)
            result[:, ch] = stage2
        return result.astype(np.float32)


class TruePeakDetector:
    """True peak olcumcusu (4x oversampling ile)."""

    def __init__(self, oversample_factor: int = 4):
        self.oversample_factor = oversample_factor

    def find_peak(self, audio: np.ndarray) -> Tuple[float, float]:
        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)
        max_peak = -96.0
        max_sample = 0.0
        for ch in range(audio.shape[1]):
            oversampled = np.interp(
                np.arange(len(audio[:, ch]) * self.oversample_factor) / self.oversample_factor,
                np.arange(len(audio[:, ch])), audio[:, ch].astype(np.float64))
            abs_max = np.max(np.abs(oversampled))
            if abs_max > 0:
                peak_db = 20 * np.log10(abs_max)
                if peak_db > max_peak:
                    max_peak = peak_db
                    max_sample = abs_max
        return (max_peak, max_sample)
```

### 3.5 Tam BS.1770 Olcum Implementasyonu

```python
import numpy as np
from scipy.io import wavfile
from scipy.signal import lfilter


def measure_loudness_bs1770(file_path: str) -> dict:
    """
    Bir WAV dosyasinin BS.1770-4 uyumlu loudness olcumunu yapar.
    Returns: integrated_lufs, momentary_lufs, short_term_lufs, true_peak_dbtp, loudness_range_lu
    """
    sr, data = wavfile.read(file_path)
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        data = data.astype(np.float32) / 2147483648.0
    elif data.dtype == np.float64:
        data = data.astype(np.float32)
    if data.ndim > 1:
        data = (data[:, 0] + data[:, 1]) / 2.0

    if sr != 48000:
        raise ValueError(f"Bu implementasyon sadece 48kHz destekler. Girdi: {sr}Hz")

    pre_b = [1.53512485958697, -2.69169618940638, 1.19839281085285]
    pre_a = [1.0, -1.69065929318241, 0.73248077421585]
    rlb_b = [1.0, -2.0, 1.0]
    rlb_a = [1.0, -1.99004745483398, 0.99007225036621]

    weighted = lfilter(pre_b, pre_a, data.astype(np.float64))
    weighted = lfilter(rlb_b, rlb_a, weighted)

    j = np.mean(weighted ** 2)
    integrated_lufs = -0.691 + 10.0 * np.log10(max(j, 1e-20))

    block_size = int(0.4 * sr)
    hop_size = int(0.1 * sr)
    momentary_values = []
    for start in range(0, len(weighted) - block_size, hop_size):
        block = weighted[start:start + block_size]
        momentary_values.append(-0.691 + 10.0 * np.log10(max(np.mean(block ** 2), 1e-20)))
    momentary_lufs = max(momentary_values) if momentary_values else -70.0

    st_block = int(3.0 * sr)
    st_hop = int(1.0 * sr)
    st_values = []
    for start in range(0, len(weighted) - st_block, st_hop):
        block = weighted[start:start + st_block]
        st_values.append(-0.691 + 10.0 * np.log10(max(np.mean(block ** 2), 1e-20)))
    short_term_lufs = max(st_values) if st_values else -70.0

    if st_values:
        sorted_st = sorted(st_values)
        n = len(sorted_st)
        lra = sorted_st[min(n - 1, int(n * 0.95))] - sorted_st[max(0, int(n * 0.10))]
    else:
        lra = 0.0

    os_factor = 4
    oversampled = np.interp(np.arange(len(data) * os_factor) / os_factor, np.arange(len(data)), data.astype(np.float64))
    true_peak_dbtp = 20.0 * np.log10(max(np.max(np.abs(oversampled)), 1e-20))

    return {
        "integrated_lufs": round(integrated_lufs, 1),
        "momentary_lufs": round(momentary_lufs, 1),
        "short_term_lufs": round(short_term_lufs, 1),
        "true_peak_dbtp": round(true_peak_dbtp, 2),
        "loudness_range_lu": round(lra, 1),
        "duration_seconds": round(len(data) / sr, 2),
        "sample_rate": sr
    }
```

### 3.6 Loudness Normalization Pipeline

```
Girdi Sinyali
    |
    v
+------------------------+
| 1. BS.1770 Olcum       |  <- Tam program olcumu
|    (K-weighting uygula)|
+---------+--------------+
          |
          v
+------------------------+
| 2. Kazanc Hesaplama    |  gain_db = target_lufs - measured_lufs
+---------+--------------+
          |
          v
+------------------------+
| 3. Kazanc Uygulama     |  sinyal x 10^(gain_db/20)
+---------+--------------+
          |
          v
+------------------------+
| 4. True Peak Kontrolu  |  Sinyal true peak > max_true_peak?
|    +- Evet -> Limiter  |
+---------+--------------+
          |
          v
+------------------------+
| 5. Nihai Olcum         |  Uyumluluk kontrolu
|    +- Compliance raporu|
+---------+--------------+
          |
          v
    Normalized Sinyal + Compliance Raporu
```

### 3.7 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|----------|------|-------|
| **K-weighting filtre gecikmesi** | Baslangic gecikmesi | Causal filtre; filter state management |
| **4x oversampling true peak** | CPU yogunlugu | SIMD upsampling |
| **Large file measurement** | Bellek tuketimi | Streaming measurement |
| **Birden fazla gecis** | Iki gecis gecikmesi | Tek geciste kombine gain + limiter |

---

## 4. Muzik Ducking Motoru

### 4.1 Amaç

Ducking motoru, konusmacinin (streamer) ses duyulabilirligini saglamak icin arka plan muzigini ve/veya oyun seslerini otomatik olarak alcalatirir.

### 4.2 Mimari

```
DuckingEngine
|
+-- SidechainAnalyzer
|   +-- SpeechDetector         <- Konusma algilama (VAD)
|   +-- SpectralAnalyzer       <- Spektral analiz
|   +-- LevelDetector          <- Seviye algilama
|
+-- DuckingProcessor
|   +-- GainComputer           <- Ducking kazanc hesaplama
|   +-- EnvelopeFollower       <- Zarf izleme (attack/release)
|   +-- SpectralDucker         <- Spektral band ducking
|   +-- MultiSourceManager     <- Coklu kaynak ducking
|
+-- AutomationEngine
|   +-- AutoMixController      <- Otomatik karistirma
|   +-- PriorityManager        <- Oncelik yonetimi
|
+-- Profiles
    +-- DuckingProfile[]       <- Hazir ducking profilleri
    +-- DuckingRule[]          <- Kural tabanli ducking
```

### 4.3 Veri Yapisi Tanimlari

```python
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional
import numpy as np


class DuckingMode(Enum):
    SIDECHAIN = auto()
    SPECTRAL = auto()
    THRESHOLD = auto()
    MANUAL = auto()
    AUTOMIX = auto()


class DuckingCurve(Enum):
    LINEAR = auto()
    EXPONENTIAL = auto()
    LOGARITHMIC = auto()
    S_CURVE = auto()


@dataclass
class SidechainConfig:
    source_track_ids: List[str] = field(default_factory=list)
    speech_detection_enabled: bool = True
    vad_threshold: float = 0.5
    analysis_window_ms: float = 20.0
    crossover_freq_hz: float = 3000.0


@dataclass
class DuckingProfile:
    """Ducking profili - belirli bir senaryo icin ayarlar."""
    profile_id: str
    name: str
    mode: DuckingMode = DuckingMode.SIDECHAIN
    threshold_db: float = -30.0
    range_db: float = -12.0
    knee_db: float = 6.0
    attack_ms: float = 50.0
    hold_ms: float = 200.0
    release_ms: float = 500.0
    spectral_enabled: bool = False
    target_bands_hz: List[float] = field(default_factory=lambda: [250, 500, 1000, 2000, 4000])
    band_range_db: List[float] = field(default_factory=lambda: [-12, -12, -15, -12, -10])
    curve: DuckingCurve = DuckingCurve.EXPONENTIAL


@dataclass
class DuckingRule:
    rule_id: str
    source_track_id: str
    trigger_track_ids: List[str]
    profile: DuckingProfile = field(default_factory=lambda: DuckingProfile(profile_id="default", name="Varsayilan"))
    priority: int = 0
    enabled: bool = True


@dataclass
class DuckingState:
    current_gain_reduction_db: float = 0.0
    is_ducking: bool = False
    ducking_start_time: float = 0.0
    envelope_value: float = 0.0
    spectral_gains: List[float] = field(default_factory=list)
    hold_counter: int = 0
    previous_target_db: Optional[float] = None
```

### 4.4 Ana Ducking Motoru

```python
class DuckingEngine:
    """Muzik ducking motoru. Konusma algilayarak arka plan sesini otomatik olarak alcalatirir."""

    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self.profiles: dict[str, DuckingProfile] = {}
        self.rules: dict[str, DuckingRule] = {}
        self.states: dict[str, DuckingState] = {}
        self._speech_detector = SpeechDetector(sample_rate)
        self._register_defaults()

    def _register_defaults(self):
        self.profiles["gentle"] = DuckingProfile(profile_id="gentle", name="Yumusak", range_db=-6.0, attack_ms=100, release_ms=1000, knee_db=12.0)
        self.profiles["standard"] = DuckingProfile(profile_id="standard", name="Standart", range_db=-12.0, attack_ms=50, release_ms=500)
        self.profiles["aggressive"] = DuckingProfile(profile_id="aggressive", name="Agresif", range_db=-18.0, attack_ms=20, release_ms=300, knee_db=3.0)
        self.profiles["broadcast"] = DuckingProfile(profile_id="broadcast", name="Yayin", range_db=-10.0, attack_ms=30, release_ms=700, knee_db=6.0, spectral_enabled=True)

    def add_rule(self, rule: DuckingRule):
        self.rules[rule.rule_id] = rule
        self.states[rule.source_track_id] = DuckingState()

    def process_block(self, source_track, target_track, trigger_tracks, rule, frame_count):
        profile = rule.profile
        state = self.states.get(rule.source_track_id, DuckingState())

        trigger_combined = np.zeros(frame_count, dtype=np.float64)
        for trigger in trigger_tracks:
            trigger_mono = np.mean(trigger[:frame_count], axis=1) if trigger.ndim > 1 else trigger[:frame_count]
            trigger_combined = np.maximum(trigger_combined, np.abs(trigger_mono))

        trigger_level_db = self._measure_level_db(trigger_combined)

        if profile.mode == DuckingMode.SPECTRAL:
            return self._process_spectral_ducking(source_track, trigger_combined, profile, frame_count)

        gain_db = self._calculate_ducking_gain(trigger_level_db, profile, state)
        gain_envelope = self._compute_gain_envelope(gain_db, state, frame_count, profile)

        result = source_track[:frame_count].copy()
        gain_linear = 10 ** (gain_envelope / 20.0)
        if result.ndim > 1:
            result[:, 0] *= gain_linear
            result[:, 1] *= gain_linear
        else:
            result *= gain_linear
        return result

    def _calculate_ducking_gain(self, trigger_level_db, profile, state):
        """Soft-knee yaklasimi: threshold-knee altinda 0, ustunde range_db, arada interpolasyon."""
        threshold = profile.threshold_db
        range_db = profile.range_db
        knee = profile.knee_db
        if trigger_level_db < threshold - knee:
            return 0.0
        if trigger_level_db > threshold + knee:
            return range_db
        t = (trigger_level_db - (threshold - knee)) / (2.0 * knee)
        if profile.curve == DuckingCurve.EXPONENTIAL:
            t = t ** 2
        return range_db * t

    def _compute_gain_envelope(self, target_gain_db, state, frame_count, profile):
        """Attack/Hold/Release zarf hesaplamasi."""
        attack_samples = int(profile.attack_ms * self.sample_rate / 1000)
        hold_samples = int(profile.hold_ms * self.sample_rate / 1000)
        release_samples = int(profile.release_ms * self.sample_rate / 1000)
        envelope = np.zeros(frame_count, dtype=np.float64)
        current = state.envelope_value
        target_linear = abs(target_gain_db)
        is_active = target_gain_db < 0.0

        for i in range(frame_count):
            if is_active:
                if current < target_linear:
                    step = target_linear / max(attack_samples, 1)
                    current = min(current + step, target_linear)
                    state.hold_counter = hold_samples
                elif state.hold_counter > 0:
                    state.hold_counter -= 1
                else:
                    step = target_linear / max(release_samples, 1)
                    current = max(current - step, 0.0)
            else:
                if current > 0:
                    prev = abs(state.previous_target_db or -12.0)
                    step = prev / max(release_samples, 1)
                    current = max(current - step, 0.0)
            envelope[i] = -current

        state.envelope_value = current
        state.current_gain_reduction_db = envelope[-1] if len(envelope) > 0 else 0.0
        state.is_ducking = current > 0.1
        state.previous_target_db = target_gain_db
        return envelope

    def _measure_level_db(self, signal):
        if len(signal) == 0:
            return -96.0
        rms = np.sqrt(np.mean(signal ** 2))
        if rms <= 0:
            return -96.0
        return 20.0 * np.log10(rms)

    def _process_spectral_ducking(self, source, trigger, profile, frame_count):
        """Spektral ducking - sadece caprazlama yapan frekans bantlarini duck eder."""
        from scipy.signal import butter, sosfilt
        result = source[:frame_count].copy().astype(np.float64)
        bands = profile.target_bands_hz
        for i in range(len(bands) - 1):
            low, high = bands[i], bands[i + 1] if i + 1 < len(bands) else 8000
            try:
                sos = butter(4, [low, high], btype='band', fs=self.sample_rate, output='sos')
                trigger_filtered = sosfilt(sos, trigger[:frame_count])
                if np.sqrt(np.mean(trigger_filtered ** 2)) > 0.01:
                    band_gain_db = profile.band_range_db[i] if i < len(profile.band_range_db) else -12.0
                    band_result = sosfilt(sos, result)
                    result = result - band_result + band_result * (10 ** (band_gain_db / 20.0))
            except Exception:
                continue
        return result.astype(np.float32)


class SpeechDetector:
    """Konusma algilama (VAD). Enerji tabanli basit VAD."""

    def __init__(self, sample_rate=48000, frame_duration_ms=30.0, energy_threshold=0.01):
        self.sample_rate = sample_rate
        self.frame_samples = int(sample_rate * frame_duration_ms / 1000)
        self.energy_threshold = energy_threshold
        self._hangover_count = 0
        self._hangover_frames = 5

    def detect(self, audio_block) -> bool:
        audio_mono = np.mean(audio_block, axis=1) if audio_block.ndim > 1 else audio_block
        energy = np.sqrt(np.mean(audio_mono ** 2))
        is_speech = energy > self.energy_threshold
        if is_speech:
            self._hangover_count = self._hangover_frames
        elif self._hangover_count > 0:
            self._hangover_count -= 1
            is_speech = True
        return is_speech
```

### 4.5 Ducking Zamanlama Diyagrami

```
Konusma Sinyali:  ----------||    ||==========||         ||==========
                             ||    ||          ||         ||

Muzik (Orijinal): ============================

Ducking Kazanci:  0dB ------------\         /--------------------
                                   |         |
                           attack-> |  hold   |  release->
                                   |         |
                          range_db |         |
                                   ''-------''

Muzik (Ducked):   ============\    \==========\         /==========
```

### 4.6 Coklu Kaynak Ducking

```python
class MultiSourceDuckingManager:
    """Coklu kaynak icin kademeli ducking yonetimi. Oncelik: Konusma > Oyun > Muzik > Ambiyans."""

    def __init__(self, engine: DuckingEngine):
        self.engine = engine
        self.priority_map = {
            TrackType.DIALOGUE: 100, TrackType.EFFECTS: 50,
            TrackType.MUSIC: 30, TrackType.AMBIENCE: 10}

    def process_all_sources(self, tracks, rules, frame_count):
        results = {}
        dialogue_tracks = {k: v for k, v in tracks.items() if "dialogue" in k.lower() or "speech" in k.lower()}
        any_speech = any(self.engine._speech_detector.detect(v[:frame_count]) for v in dialogue_tracks.values())

        for track_id, audio in tracks.items():
            if track_id in dialogue_tracks:
                results[track_id] = audio
                continue
            if any_speech:
                applicable_rule = next((r for r in rules.values() if r.source_track_id == track_id and r.enabled), None)
                if applicable_rule:
                    trigger_audio = list(dialogue_tracks.values())[0]
                    results[track_id] = self.engine.process_block(audio, audio, [trigger_audio], applicable_rule, frame_count)
                else:
                    results[track_id] = audio
            else:
                results[track_id] = audio
        return results
```

### 4.7 API Sozlesmeleri

```python
class DuckingAPI:
    def create_profile(self, name, **kwargs) -> DuckingProfile: ...
    def create_rule(self, source_track_id, trigger_track_ids, profile_id="standard", priority=0) -> DuckingRule: ...
    def enable_rule(self, rule_id) -> None: ...
    def disable_rule(self, rule_id) -> None: ...
    def get_ducking_state(self, track_id) -> DuckingState: ...
    def process(self, frame_count) -> dict: ...
```

### 4.8 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|----------|------|-------|
| **Speech detection gecikmesi** | Yanlis negatif | WebRTC VAD; lookahead buffer |
| **Spektral ducking FFT** | CPU yogunlugu | Onceden hesaplanmis SOS; FFT overlap-add |
| **Coklu kural cakismasi** | Ayni anda birden fazla tetikleyici | Oncelik siralamasi; max kazanc secimi |
| **Zarf gecikmesi** | Ducking erken/gec baslar | Parametrik attack/release; lookahead |

---

## 5. Ses Efektleri Zinciri

### 5.1 Amaç

AudioEffectChain, bir iz veya bus uzerinde sirali olarak uygulanan ses efektleri zincirini temsil eder. Her efekt bagimsiz olarak yapilandirilabilir ve zincir siraasi onemlidir.

### 5.2 Veri Yapisi Tanimlari

```python
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional
import numpy as np
from abc import ABC, abstractmethod


class EffectType(Enum):
    EQ_PARAMETRIC = auto()
    EQ_GRAPHIC = auto()
    COMPRESSOR = auto()
    LIMITER = auto()
    NOISE_GATE = auto()
    DEESSER = auto()
    REVERB_CONVOLUTION = auto()
    REVERB_ALGORITHMIC = auto()
    TIME_STRETCH = auto()
    PITCH_SHIFT = auto()
    CHORUS = auto()
    DELAY = auto()
    SATURATION = auto()


@dataclass
class EQBand:
    frequency_hz: float = 1000.0
    gain_db: float = 0.0
    q_factor: float = 1.0
    filter_type: str = "peaking"  # peaking | lowshelf | highshelf | notch


@dataclass
class CompressorParams:
    threshold_db: float = -20.0
    ratio: float = 4.0
    attack_ms: float = 10.0
    release_ms: float = 100.0
    knee_db: float = 6.0
    makeup_gain_db: float = 0.0
    mix: float = 1.0
    mode: str = "downward"


@dataclass
class NoiseGateParams:
    threshold_db: float = -40.0
    attack_ms: float = 1.0
    hold_ms: float = 50.0
    release_ms: float = 100.0
    range_db: float = -80.0
    hysteresis_db: float = 2.0


@dataclass
class DeesserParams:
    frequency_hz: float = 6000.0
    threshold_db: float = -20.0
    reduction_db: float = -12.0
    detection_mode: str = "split"


@dataclass
class ReverbParams:
    room_size: float = 0.5
    damping: float = 0.5
    wet_gain_db: float = -6.0
    dry_gain_db: float = 0.0
    pre_delay_ms: float = 20.0
    diffusion: float = 0.8
    density: float = 0.8
    ir_path: Optional[str] = None
    ir_data: Optional[np.ndarray] = None


@dataclass
class TimeStretchParams:
    rate: float = 1.0
    algorithm: str = "wsola"
    pitch_preserve: bool = True


@dataclass
class PitchShiftParams:
    semitones: float = 0.0
    cents: float = 0.0
    algorithm: str = "phase_vocoder"
    formant_preserve: bool = True


class AudioEffect(ABC):
    def __init__(self, effect_type: EffectType, enabled: bool = True):
        self.effect_type = effect_type
        self.enabled = enabled
        self.bypassed = False

    @abstractmethod
    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def get_latency_samples(self) -> int: ...

    def _passthrough(self, audio):
        if not self.enabled or self.bypassed:
            return audio
        return audio
```

### 5.3 Parametrik EQ

```python
class ParametricEQ(AudioEffect):
    """
    Parametrik EQ - bant basina frequency, gain, Q kontrolu.
    Her bant icin biquad IIR filtresi (Audio EQ Cookbook).
    """

    def __init__(self, bands: Optional[List[EQBand]] = None):
        super().__init__(EffectType.EQ_PARAMETRIC)
        self.bands = bands or [EQBand()]

    def process(self, audio, sample_rate):
        from scipy.signal import lfilter
        result = audio.astype(np.float64)
        for band in self.bands:
            if abs(band.gain_db) < 0.1:
                continue
            b, a = self._compute_biquad(band, sample_rate)
            channels = result.shape[1] if result.ndim > 1 else 1
            for ch in range(channels):
                data = result[:, ch] if result.ndim > 1 else result
                result_ch = lfilter(b, a, data)
                if result.ndim > 1:
                    result[:, ch] = result_ch
                else:
                    result = result_ch
        return result.astype(np.float32)

    def _compute_biquad(self, band, sample_rate):
        f0, Q, gain = band.frequency_hz, band.q_factor, band.gain_db
        w0 = 2.0 * np.pi * f0 / sample_rate
        A = 10 ** (gain / 40.0)
        alpha = np.sin(w0) / (2.0 * Q)
        if band.filter_type == "peaking":
            b0 = 1 + alpha * A; b1 = -2 * np.cos(w0); b2 = 1 - alpha * A
            a0 = 1 + alpha / A; a1 = -2 * np.cos(w0); a2 = 1 - alpha / A
        elif band.filter_type == "lowshelf":
            SQRT2A = np.sqrt(2 * A)
            b0 = A * ((A + 1) - (A - 1) * np.cos(w0) + SQRT2A * alpha)
            b1 = 2 * A * ((A - 1) - (A + 1) * np.cos(w0))
            b2 = A * ((A + 1) - (A - 1) * np.cos(w0) - SQRT2A * alpha)
            a0 = (A + 1) + (A - 1) * np.cos(w0) + SQRT2A * alpha
            a1 = -2 * ((A - 1) + (A + 1) * np.cos(w0))
            a2 = (A + 1) + (A - 1) * np.cos(w0) - SQRT2A * alpha
        elif band.filter_type == "highshelf":
            SQRT2A = np.sqrt(2 * A)
            b0 = A * ((A + 1) + (A - 1) * np.cos(w0) + SQRT2A * alpha)
            b1 = -2 * A * ((A - 1) + (A + 1) * np.cos(w0))
            b2 = A * ((A + 1) + (A - 1) * np.cos(w0) - SQRT2A * alpha)
            a0 = (A + 1) - (A - 1) * np.cos(w0) + SQRT2A * alpha
            a1 = 2 * ((A - 1) - (A + 1) * np.cos(w0))
            a2 = (A + 1) - (A - 1) * np.cos(w0) - SQRT2A * alpha
        else:
            b0 = 1 + alpha * A; b1 = -2 * np.cos(w0); b2 = 1 - alpha * A
            a0 = 1 + alpha / A; a1 = -2 * np.cos(w0); a2 = 1 - alpha / A
        return ([b0 / a0, b1 / a0, b2 / a0], [1.0, a1 / a0, a2 / a0])

    def reset(self): pass
    def get_latency_samples(self): return 0
```

### 5.4 Kompresor

```python
class Compressor(AudioEffect):
    """Downward kompresor. Attack/release zarf izleme ile."""

    def __init__(self, params: Optional[CompressorParams] = None):
        super().__init__(EffectType.COMPRESSOR)
        self.params = params or CompressorParams()
        self._envelope = 0.0

    def process(self, audio, sample_rate):
        result = self._passthrough(audio)
        if result is audio: return result
        result = result.astype(np.float64)
        p = self.params
        attack_coeff = np.exp(-1.0 / (p.attack_ms * sample_rate / 1000.0))
        release_coeff = np.exp(-1.0 / (p.release_ms * sample_rate / 1000.0))
        if result.ndim == 1: result = result.reshape(-1, 1)
        output = np.zeros_like(result)

        for ch in range(result.shape[1]):
            for i in range(len(result)):
                level_db = 20.0 * np.log10(max(abs(result[i, ch]), 1e-20))
                gain_reduction = 0.0
                if level_db > p.threshold_db:
                    over = level_db - p.threshold_db
                    gain_reduction = min(over - over / p.ratio, 60.0)
                coeff = attack_coeff if gain_reduction > self._envelope else release_coeff
                self._envelope = coeff * self._envelope + (1 - coeff) * gain_reduction
                output[i, ch] = result[i, ch] * 10 ** (-self._envelope / 20.0) * 10 ** (p.makeup_gain_db / 20.0)

        if p.mix < 1.0:
            output = audio.astype(np.float64) * (1 - p.mix) + output * p.mix
        return output.astype(np.float32)

    def reset(self): self._envelope = 0.0
    def get_latency_samples(self): return int(self.params.attack_ms * 48000 / 1000.0)
```

### 5.5 True Peak Limiter

```python
class TruePeakLimiter(AudioEffect):
    """True peak limiter - absolute ceiling korumasi."""

    def __init__(self, ceiling_dbtp: float = -1.0, release_ms: float = 50.0):
        super().__init__(EffectType.LIMITER)
        self.ceiling_dbtp = ceiling_dbtp
        self.release_ms = release_ms
        self._envelope = 1.0

    def process(self, audio, sample_rate):
        result = self._passthrough(audio)
        if result is audio: return result
        ceiling = 10 ** (self.ceiling_dbtp / 20.0)
        release_coeff = np.exp(-1.0 / (self.release_ms * sample_rate / 1000.0))
        result = result.astype(np.float64)
        if result.ndim == 1: result = result.reshape(-1, 1)
        output = np.zeros_like(result)
        for ch in range(result.shape[1]):
            for i in range(len(result)):
                val = abs(result[i, ch])
                gain = ceiling / val if val > ceiling else 1.0
                self._envelope = gain if gain < self._envelope else release_coeff * self._envelope + (1 - release_coeff) * gain
                output[i, ch] = result[i, ch] * self._envelope
        return output.astype(np.float32)

    def reset(self): self._envelope = 1.0
    def get_latency_samples(self): return 0
```

### 5.6 Gürültü Kapısı (Noise Gate)

```python
class NoiseGate(AudioEffect):
    """Gurultu kapisi - histerezis ile false-trigger engeli."""

    def __init__(self, params: Optional[NoiseGateParams] = None):
        super().__init__(EffectType.NOISE_GATE)
        self.params = params or NoiseGateParams()
        self._is_open = False
        self._hold_counter = 0

    def process(self, audio, sample_rate):
        result = self._passthrough(audio)
        if result is audio: return result
        p = self.params
        result = result.astype(np.float64)
        if result.ndim == 1: result = result.reshape(-1, 1)
        output = np.zeros_like(result)
        range_linear = 10 ** (p.range_db / 20.0)

        for ch in range(result.shape[1]):
            for i in range(len(result)):
                level_db = 20 * np.log10(max(abs(result[i, ch]), 1e-20))
                if not self._is_open:
                    if level_db > p.threshold_db:
                        self._is_open = True
                        self._hold_counter = int(p.hold_ms * sample_rate / 1000)
                elif self._hold_counter > 0:
                    self._hold_counter -= 1
                elif level_db < p.threshold_db - p.hysteresis_db:
                    self._is_open = False
                output[i, ch] = result[i, ch] if self._is_open else result[i, ch] * range_linear
        return output.astype(np.float32)

    def reset(self): self._is_open = False; self._hold_counter = 0
    def get_latency_samples(self): return 0
```

### 5.7 De-esser

```python
class Deesser(AudioEffect):
    """De-esser - tiz frekanslari azaltir."""

    def __init__(self, params: Optional[DeesserParams] = None):
        super().__init__(EffectType.DEESSER)
        self.params = params or DeesserParams()

    def process(self, audio, sample_rate):
        result = self._passthrough(audio)
        if result is audio: return result
        from scipy.signal import butter, sosfilt
        p = self.params
        sos = butter(4, [p.frequency_hz * 0.7, p.frequency_hz * 1.4], btype='band', fs=sample_rate, output='sos')
        audio_2d = audio.reshape(-1, 1) if audio.ndim == 1 else audio
        output = audio_2d.astype(np.float64).copy()
        for ch in range(audio_2d.shape[1]):
            band_signal = sosfilt(sos, audio_2d[:, ch])
            band_level_db = 20 * np.log10(max(np.sqrt(np.mean(band_signal ** 2)), 1e-20))
            if band_level_db > p.threshold_db:
                gain = 10 ** (p.reduction_db / 20.0)
                output[:, ch] = audio_2d[:, ch] - band_signal + band_signal * gain
        return output.astype(np.float32)

    def reset(self): pass
    def get_latency_samples(self): return 0
```

### 5.8 Zaman Uzatma ve Perde Kaydirma

```python
class TimeStretcher(AudioEffect):
    """Zaman uzatma - WSOLA ve Phase Vocoder."""

    def __init__(self, params=None):
        super().__init__(EffectType.TIME_STRETCH)
        self.params = params or TimeStretchParams()

    def process(self, audio, sample_rate):
        result = self._passthrough(audio)
        if result is audio: return result
        if self.params.rate == 1.0: return audio
        if self.params.algorithm == "wsola":
            return self._wsola(audio, sample_rate)
        return self._phase_vocoder(audio, sample_rate)

    def _wsola(self, audio, sample_rate):
        hop_size, window_size = int(0.01 * sample_rate), int(0.04 * sample_rate)
        rate = self.params.rate
        output_length = int(len(audio) / rate)
        output = np.zeros((output_length, audio.shape[1]) if audio.ndim > 1 else output_length, dtype=np.float64)
        read_pos, write_pos = 0.0, 0
        window = np.hanning(window_size)
        while int(read_pos) + window_size < len(audio) and write_pos + window_size < len(output):
            frame = audio[int(read_pos):int(read_pos) + window_size].copy()
            frame = frame * (window[:, np.newaxis] if frame.ndim > 1 else window)
            end = min(write_pos + window_size, len(output))
            actual = end - write_pos
            if output.ndim > 1: output[write_pos:end] += frame[:actual]
            else: output[write_pos:end] += frame[:actual]
            read_pos += hop_size * rate
            write_pos += hop_size
        return output.astype(np.float32)

    def _phase_vocoder(self, audio, sample_rate):
        fft_size, hop_size = 2048, 512
        rate = self.params.rate
        audio_mono = np.mean(audio, axis=1) if audio.ndim > 1 else audio
        output_length = int(len(audio_mono) / rate)
        padded = np.zeros(max(output_length, len(audio_mono)) + fft_size)
        padded[:len(audio_mono)] = audio_mono
        output = np.zeros(output_length + fft_size, dtype=np.float64)
        output_window = np.zeros_like(output)
        read_pos, write_pos = 0.0, 0
        window = np.hanning(fft_size)
        while int(read_pos) + fft_size <= len(padded) and write_pos + fft_size <= len(output):
            frame = padded[int(read_pos):int(read_pos) + fft_size] * window
            spectrum = np.fft.rfft(frame)
            output[write_pos:write_pos + fft_size] += np.fft.irfft(spectrum) * window
            output_window[write_pos:write_pos + fft_size] += window ** 2
            read_pos += hop_size * rate
            write_pos += hop_size
        mask = output_window > 1e-10
        output[mask] /= output_window[mask]
        return output[:output_length].astype(np.float32)

    def reset(self): pass
    def get_latency_samples(self): return 2048


class PitchShifter(AudioEffect):
    """Perde kaydirma - Phase Vocoder tabanli."""

    def __init__(self, params=None):
        super().__init__(EffectType.PITCH_SHIFT)
        self.params = params or PitchShiftParams()

    def process(self, audio, sample_rate):
        result = self._passthrough(audio)
        if result is audio: return result
        semitones = self.params.semitones + self.params.cents / 100.0
        if semitones == 0.0: return audio
        freq_ratio = 2 ** (semitones / 12.0)
        fft_size, hop_size = 4096, 1024
        window = np.hanning(fft_size)
        audio_mono = np.mean(audio, axis=1) if audio.ndim > 1 else audio
        padded = np.zeros(len(audio_mono) + fft_size * 2)
        padded[:len(audio_mono)] = audio_mono
        output = np.zeros(len(padded), dtype=np.float64)
        output_win = np.zeros(len(padded), dtype=np.float64)
        for pos in range(0, len(padded) - fft_size, hop_size):
            frame = padded[pos:pos + fft_size] * window
            spectrum = np.fft.rfft(frame)
            shifted = np.zeros_like(spectrum)
            for k in range(len(spectrum)):
                src_k = int(k / freq_ratio)
                if 0 <= src_k < len(spectrum):
                    shifted[k] = spectrum[src_k]
            frame_out = np.fft.irfft(shifted, n=fft_size) * window
            output[pos:pos + fft_size] += frame_out
            output_win[pos:pos + fft_size] += window ** 2
        mask = output_win > 1e-10
        output[mask] /= output_win[mask]
        return output[:len(audio_mono)].astype(np.float32)

    def reset(self): pass
    def get_latency_samples(self): return 4096
```

### 5.9 AudioEffectChain

```python
class AudioEffectChain:
    """Sirali ses efektleri zinciri."""

    def __init__(self):
        self.effects: List[AudioEffect] = []
        self._total_latency: int = 0

    def add_effect(self, effect, position=None):
        if position is None: self.effects.append(effect)
        else: self.effects.insert(position, effect)
        self._recalculate_latency()

    def remove_effect(self, effect_type) -> bool:
        for i, eff in enumerate(self.effects):
            if eff.effect_type == effect_type:
                self.effects.pop(i)
                self._recalculate_latency()
                return True
        return False

    def process(self, audio, sample_rate):
        result = audio
        for effect in self.effects:
            if effect.enabled and not effect.bypassed:
                result = effect.process(result, sample_rate)
        return result

    def reset_all(self):
        for effect in self.effects: effect.reset()

    def _recalculate_latency(self):
        self._total_latency = sum(e.get_latency_samples() for e in self.effects)

    @property
    def total_latency_samples(self): return self._total_latency
    @property
    def total_latency_ms(self): return self._total_latency / 48.0
```

### 5.10 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|----------|------|-------|
| **Biquad filtre zinciri** | Her EQ bani icin ayri lfilter | Cascaded SOS; tek sosfilt |
| **Kompresor zarf hesabi** | Sample-by-sample = yavas | Vectorized gain computation |
| **Convolution reverb** | Buyuk IR = yuksek bellek | Partitioned convolution |
| **Phase vocoder** | STFT = CPU yogun | FFTW; GPU acceleration |
| **Efekt zinciri gecikmesi** | Biriken gecikme | Lookahead compensation |

---

## 6. Ses-Video Senkronizasyonu

### 6.1 Amaç

Ses-Video senkronizasyon modulu, yayin kaynaklarindan gelen ses ve video akislarinin zamanlamasini kontrol eder ve duzeltir. Lip sync algilama, A/V offset duzeltme ve frame-hassas ses yerlestirme saglar.

### 6.2 Mimari

```
SyncEngine
|
+-- LipSyncDetector
|   +-- AudioOnsetDetector      <- Ses baslangici algilama
|   +-- VideoMotionDetector     <- Hareket algilama
|   +-- CrossCorrelationEngine  <- Capraz korelasyon
|
+-- OffsetCorrector
|   +-- AudioDelayCompensator   <- Gecikme telafisi
|   +-- VideoFrameAdjuster      <- Video zaman duzeltmesi
|   +-- DriftCorrector          <- Saat kaymasi duzeltmesi
|
+-- FrameAccuratePlacer
|   +-- AudioTimeline           <- Ses zaman cizelgesi
|   +-- SampleAccurateAligner   <- Ornek-hassas hizalama
|
+-- SyncMonitor
    +-- RealTimeOffsetTracker   <- Gercek zamanli offset izleme
    +-- SyncQualityReporter     <- Kalite raporu
```

### 6.3 Veri Yapisi Tanimlari

```python
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np


@dataclass
class SyncOffset:
    audio_delay_ms: float = 0.0
    video_delay_ms: float = 0.0
    sample_offset: int = 0
    frame_offset: int = 0
    confidence: float = 0.0
    measurement_method: str = "cross_correlation"
    timestamp: float = 0.0


@dataclass
class SyncCheck:
    is_synced: bool = True
    offset: Optional[SyncOffset] = None
    max_acceptable_offset_ms: float = 45.0
    lip_sync_detected: bool = False
    drift_rate_ppm: float = 0.0
    issues: List[str] = field(default_factory=list)
```

### 6.4 Ana Senkronizasyon Motoru

```python
class SyncEngine:
    """Ses-Video senkronizasyon motoru."""

    def __init__(self, sample_rate=48000, fps=30.0):
        self.sample_rate = sample_rate
        self.fps = fps
        self._drift_accumulator = 0.0
        self._last_sync_time = 0.0

    def detect_offset_cross_correlation(self, audio, reference_audio, max_offset_samples=4800):
        """Capraz korelasyon ile ses-video offset'i algilar."""
        audio_mono = np.mean(audio, axis=1).astype(np.float64) if audio.ndim > 1 else audio.astype(np.float64)
        ref_mono = np.mean(reference_audio, axis=1).astype(np.float64) if reference_audio.ndim > 1 else reference_audio.astype(np.float64)

        n = len(audio_mono) + len(ref_mono) - 1
        fft_size = 1
        while fft_size < n: fft_size *= 2

        cross_corr = np.fft.irfft(np.fft.rfft(audio_mono, fft_size) * np.conj(np.fft.rfft(ref_mono, fft_size)), fft_size)
        search_start = max(0, -max_offset_samples)
        search_end = min(len(cross_corr), max_offset_samples)
        region = cross_corr[search_start:search_end]
        peak_idx = np.argmax(np.abs(region)) + search_start

        offset_samples = peak_idx if peak_idx < len(cross_corr) // 2 else peak_idx - len(cross_corr)
        offset_ms = offset_samples / self.sample_rate * 1000.0
        norm = np.sqrt(np.sum(audio_mono ** 2) * np.sum(ref_mono ** 2))
        confidence = min(np.abs(cross_corr[peak_idx]) / max(norm, 1e-20), 1.0)

        return SyncOffset(audio_delay_ms=offset_ms, sample_offset=offset_samples, confidence=confidence)

    def detect_lip_sync(self, audio, video_frames, frame_times):
        """Lip sync algilama - konusma baslangic noktalarini karsilastirir."""
        audio_onsets = self._detect_audio_onsets(audio)
        video_onsets = self._detect_video_mouth_movement(video_frames, frame_times)

        if not audio_onsets or not video_onsets:
            return SyncCheck(is_synced=True, lip_sync_detected=False, issues=["Yeterli veri yok"])

        offsets = [audio_onset - min(video_onsets, key=lambda v: abs(v - audio_onset)) for audio_onset in audio_onsets]
        avg_offset_ms = np.mean(offsets) * 1000.0
        max_offset_ms = np.max(np.abs(offsets)) * 1000.0
        is_synced = max_offset_ms < 45.0

        check = SyncCheck(is_synced=is_synced, offset=SyncOffset(audio_delay_ms=avg_offset_ms), lip_sync_detected=True)
        if not is_synced:
            check.issues.append(f"Video ile ses arasinda {avg_offset_ms:.1f}ms offset")
        return check

    def correct_offset(self, audio, offset, target_sample_rate=48000):
        """Offset'i duzeltir. Negatif = padding, Pozitif = kirp."""
        if abs(offset.sample_offset) < 1: return audio
        shift = offset.sample_offset
        if shift > 0:
            return audio[shift:]
        else:
            shape = (-shift,) if audio.ndim == 1 else (-shift, audio.shape[1])
            return np.concatenate([np.zeros(shape, dtype=audio.dtype), audio], axis=0)

    def place_audio_frame_accurate(self, audio, target_frame, current_frame, sample_rate, fps):
        """Ses sinyalini belirli bir video karesine hizalar."""
        sample_shift = int((target_frame - current_frame) * sample_rate / fps)
        if sample_shift == 0: return audio
        channels = audio.shape[1] if audio.ndim > 1 else 1
        if sample_shift > 0:
            padding = np.zeros((sample_shift, channels) if audio.ndim > 1 else (sample_shift,), dtype=audio.dtype)
            return np.concatenate([padding, audio], axis=0)
        else:
            return audio[-sample_shift:]

    def compensate_drift(self, audio, drift_rate_ppm, session_duration_seconds):
        """Saat kaymasi (drift) duzeltmesi."""
        total_drift = int(session_duration_seconds * drift_rate_ppm * 1e-6 * self.sample_rate)
        if abs(total_drift) < 1: return audio
        n = len(audio)
        output = audio.copy()
        correction = np.linspace(0, total_drift, n)
        indices = np.arange(n) - correction
        valid = (indices >= 0) & (indices < n)
        if audio.ndim > 1:
            for ch in range(audio.shape[1]):
                output[valid, ch] = np.interp(indices[valid], np.arange(n), audio[:, ch])
        else:
            output[valid] = np.interp(indices[valid], np.arange(n), audio)
        return output

    def _detect_audio_onsets(self, audio, threshold_db=-30.0):
        mono = np.mean(audio, axis=1) if audio.ndim > 1 else audio
        frame_size = int(0.02 * self.sample_rate)
        hop = frame_size // 2
        onsets, prev_db = [], -96.0
        for i in range(0, len(mono) - frame_size, hop):
            db = 20 * np.log10(max(np.sqrt(np.mean(mono[i:i + frame_size] ** 2)), 1e-20))
            if db > threshold_db and prev_db <= threshold_db:
                onsets.append(i / self.sample_rate)
            prev_db = db
        return onsets

    def _detect_video_mouth_movement(self, video_frames, frame_times, motion_threshold=2.0):
        if len(video_frames) < 2: return []
        onsets = []
        for i in range(1, len(video_frames)):
            fa = video_frames[i - 1].astype(np.float64)
            fb = video_frames[i].astype(np.float64)
            if fa.ndim > 2: fa, fb = np.mean(fa, axis=2), np.mean(fb, axis=2)
            if np.mean(np.abs(fb - fa)) > motion_threshold and i < len(frame_times):
                onsets.append(frame_times[i])
        return onsets
```

### 6.5 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|----------|------|-------|
| **Cross-correlation FFT** | Buyuk FFT = bellek | Padded FFT; streaming cross-correlation |
| **Lip sync goruntu isleme** | Yavas video analiz | Yuz algilama ile agiz bolgesi; GPU |
| **Drift telafisi interpolasyonu** | Kayip olusturma | Cubic interpolation; zarf ile yumusatma |
| **Frame-hassas yerlestirme** | Sub-sample hassasiyet | Sinc interpolation |

---

## 7. Performans ve Darboğaz Analizi

### 7.1 Sistem Darboğaz Haritasi

```
CPU Yogunluk Haritasi (yuksek -> dusuk):
1. Phase Vocoder / Time Stretch       [YUKSEK]
2. Convolution Reverb (buyuk IR)      [YUKSEK]
3. Spektral Ducking (coklu band)      [ORTA-YUKSEK]
4. Kompresor (sample-by-sample)       [ORTA]
5. Loudness Measurement (4x oversam.) [ORTA]
6. Biquad EQ (coklu bant)             [ORTA-DUSUK]
7. Pan / Volume interpolation         [DUSUK]
8. Crossfade                          [DUSUK]

Bellek Yogunluk Haritasi:
1. Convolution Reverb IR buffer       [YUKSEK]
2. Buyuk WAV dosyalari                [ORTA-YUKSEK]
3. FFT buffer (phase vocoder)         [ORTA]
4. Multi-track ring buffers           [ORTA]
5. Efekt zinciri state                [DUSUK]
```

### 7.2 Optimizasyon Stratejileri

| Strateji | Uygulama Alani | Kazanc |
|----------|----------------|--------|
| **SIMD Vektor Isleme** | Karistirma, EQ, gain computation | 4-8x hizlanma |
| **Paralel Iz Isleme** | Bagimsiz izler icin thread pool | 2-4x |
| **FFT Tabanli Convolution** | Reverb, spectral processing | N*log(N) vs N^2 |
| **Block-Based Processing** | Tum zincir | Bellek erisim optimizasyonu |
| **Lookahead Buffer** | Limiter, ducking | Gecikme Compensasyonu |
| **Memory-Mapped I/O** | Buyuk dosya okuma | Bellek kullanim azaltma |
| **GPU Acceleration** | FFT, convolution, time stretch | 10-50x |

### 7.3 Gercek Zamanli Isleme Gecikme Hesabi

```
Toplam Gecikme (ms) = Buffer + Efekt + Kodlama

Buffer Gecikmesi:
  - Block size: 4096 ornek @ 48kHz = 85.3ms
  - Ring buffer: 2048 ornek = 42.7ms
  - Minimum teorik: 1024 ornek = 21.3ms

Efekt Gecikmesi (birikimsel):
  - Kompresor attack: ~10ms
  - True peak limiter: ~0ms
  - EQ (IIR): ~0ms
  - Convolution reverb: IR boyutuna bagli
  - Phase vocoder: ~42ms

Kodlama Gecikmesi:
  - AAC-LC: ~40ms
  - Opus: ~5-20ms
  - FLAC: ~0ms

Toplam (Canli Yayin):
  - Minimum: ~21ms (low-latency config)
  - Normal: ~85ms (standart config)
  - Broadcast: ~120ms (yüksek kalite config)
```

---

## 8. Ekler

### 8.1 Referanslar

| Standart | Tam Adi | Kapsam |
|----------|---------|--------|
| ITU-R BS.1770-4 | Algoritmalari ve olcum gereksinimleri | Loudness olcum temeli |
| EBU R128 | EBU Recommendation 128 | Avrupa yayin loudness standardi |
| ATSC A/85 | ATSC A/85:2013 | ABD yayin loudness standardi |
| AES Streaming Loudness | AES TD1004.1.15-10 | Streaming media icin loudness |
| SMPTE ST 202 | Loudness metadata | Broadcast metadata |
| RFC 7845 | Ogg Encoded Audio (Opus) | Opus loudness |

### 8.2 Birim Cevirme Tablosu

| Deger | Formul | Ornek |
|-------|--------|-------|
| dBFS -> Lineer | 10^(dB/20) | -6 dBFS -> 0.501 |
| Lineer -> dBFS | 20 x log10(x) | 0.5 -> -6.02 dBFS |
| LUFS -> dBFS (yaklasik) | LUFS ~ dBFS | -14 LUFS ~ -14 dBFS |
| dBTP | True peak dBFS | Sinyal zirvesi |
| Sample -> Saniye | samples / sample_rate | 48000 / 48000 = 1.0s |
| Saniye -> Sample | seconds x sample_rate | 0.5 x 48000 = 24000 |

### 8.3 Surum Gecmisi

| Surum | Tarih | Degisiklik |
|-------|-------|-----------|
| 1.0.0 | 2026-07-16 | Ilk taslak - tum bolumler dahil |
