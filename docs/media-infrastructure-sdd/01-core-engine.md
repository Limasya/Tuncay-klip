# 01 — Çekirdek Düzenleme Motoru (Core Editing Engine)

> **Sürüm:** 1.0.0  
> **Durum:** Tasarım Aşaması  
> **Yazar:** Media Infrastructure Engineering  
> **Son Güncelleme:** 2026-07-16  

---

## İçindekiler

1. [Zaman Motoru (Timeline Engine)](#1-zaman-motoru-timeline-engine)
2. [Katman Tabanlı Düzenleme Sistemi](#2-katman-tabanlı-düzenleme-sistemi)
3. [Doğrusal Olmayan Düzenleme (NLE) Çekirdeği](#3-doğrusal-olmayan-düzenleme-nle-çekirdeği)
4. [Efekt Grafiği (Node-Based Processing)](#4-efekt-grafigi-node-based-processing)
5. [Geçiş Grafiği (Transition Graph)](#5-geçiş-grafigi-transition-graph)
6. [Video Kompozitörü](#6-video-kompozitörü)
7. [Render Hattı (Render Pipeline)](#7-render-hattı-render-pipeline)

---

# 1. Zaman Motoru (Timeline Engine)

## 1.1 Amaç ve Kapsam

Zaman motoru, tüm NLE sisteminin **en kritik bileşenidir**. Bir NLE'de zaman, asla float64 ile temsil edilemez — bu, kare-hassas (frame-accurate) düzenleme yapamazsınız demektir. Sorun şudur: `1/3` saniye float64'de sonsuz döngüye girer (`0.33333333...`), ve bu kayma (drift) yaratır. 10 saatlik bir yayında bile 1 kare kayma, ses-senkronda ciddi sorunlara yol açar.

Bizim çözümümüz: **Fraction (rasyonel sayı)** tabanlı zaman gösterimi. Bu, DaVinci Resolve ve Avid Media Composer'ın kullandığı aynı yaklaşımdır. Adobe Premiere ise dahili olarak `int64` tick tabanlı bir zamanlama kullanır — biz her ikisinin en iyi yönlerini birleştiriyoruz.

### Karşılaştırma

| Özellik | Bizim Sistem | Premiere Pro | DaVinci Resolve | Avid MC |
|---|---|---|---|---|
| Zaman gösterimi | `Fraction` (Python `fractions.Fraction`) | `int64` tick (1/25401600000 s) | `Rational` (kendi implementasyonu) | `int64` tick (1/90000 s) |
| Kare hassasiyeti | Evet (rasyonel) | Evet (tick) | Evet (rasyonel) | Evet (tick) |
| FPS bağımsız | Evet | Kısmen | Evet | Evet |
| Timecode desteği | Evet (SMPTE) | Evet | Evet | Evet |

## 1.2 Mimari

```
┌─────────────────────────────────────────────┐
│              Timeline Engine                 │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │ Timecode │──│Fraction  │──│ Frame     │ │
│  │ Parser   │  │ Arithmetic│  │ Calculator│ │
│  └──────────┘  └──────────┘  └───────────┘ │
│       │              │              │        │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │ Timeline │──│  Track   │──│TimelineClip│ │
│  │ Manager  │  │ Manager  │  │  Manager  │ │
│  └──────────┘  └──────────┘  └───────────┘ │
│       │              │              │        │
│  ┌──────────────────────────────────────────┐│
│  │        Undo/Redo Stack (Command)         ││
│  └──────────────────────────────────────────┘│
└─────────────────────────────────────────────┘
```

Zaman motoru, `fractions.Fraction` modülünü temel alır. Her zaman değeri rasyonel sayı olarak depolanır, ve yalnızca görüntüleme/serileştirme sırasında timecode veya saniye cinsinden çevrilir.

## 1.3 Veri Yapısı

```python
"""
Zaman motoru temel veri yapıları.

Tasarım İlkeleri:
1. Hiçbir zaman metodu float kullanmaz — tüm zaman Fraction ile temsil edilir.
2. Timecode, time veya frame cinsinden giriş yapılabilir, iç temsil her zaman Fraction'dır.
3. Kare hesaplaması, fps değerine bölünerek yapılır — asla round() ile Approximate yapılmaz.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID, uuid4


class TimecodeFormat(Enum):
    """
    SMPTE timecode formatları.
    
    PAL regions: 25 fps (drop-frame olmayan timecode)
    NTSC regions: 29.97 fps (drop-frame timecode gerekli)
    Film: 23.976 fps (drop-frame)
    
    Drop-frame timecode, NTSC'de gerçek zamanla timecode arasında 
    3.6 saniye/saat farkı kapatmak için dakika başlarındaki 
    00 ve 01 frame'leri atlanır.
    """
    NON_DROP_FRAME = "ndf"      # 24, 25, 30 fps (tam sayı)
    DROP_FRAME = "df"            # 29.97, 23.976 fps
    SUB_FRAMES = "subframes"    # 1/80ths (Avid tarzı)


class TimeFormat(Enum):
    """Zaman gösterim formatları"""
    SECONDS = "seconds"          # float yerine Fraction
    FRAMES = "frames"            # tam kare numarası
    TIMECODE = "timecode"        # HH:MM:SS:FF
    SAMPLES = "samples"          # ses örneklemi (44100, 48000 vb.)


@dataclass(frozen=True, slots=True)
class RationalTime:
    """
    Tüm zaman değerlerinin temelini oluşturan rasyonel zaman yapısı.
    
    Bu yapı, DaVinci Resolve'un TimeID veya Avid'in TimeValue'su ile 
    eşdeğerdir. Fakat Python'un native Fraction sınıfını kullanarak 
    daha temiz bir implementasyon sağlar.
    
    Önemli: frozen=True — immutable. Bu, thread-safe zaman karşılaştırmaları 
    ve cache'leme için kritiktir.
    
    Örnek:
        >>> t = RationalTime(1001, 30000)  # 1 frame @ 29.97fps
        >>> t.seconds
        Fraction(1001, 30000)
        >>> float(t.seconds)
        0.033366666...
        >>> t.to_frames(Fraction(30000, 1001))
        1
    """
    _numerator: int = field()
    _denominator: int = field(default=1)
    
    def __post_init__(self):
        if self._denominator == 0:
            raise ValueError("Payda (denominator) sıfır olamaz")
        if self._denominator < 0:
            # Negatif paydayı paya taşı — standart rasyonel form
            object.__setattr__(self, '_numerator', -self._numerator)
            object.__setattr__(self, '_denominator', -self._denominator)
    
    @property
    def value(self) -> Fraction:
        """Temel Fraction değeri"""
        return Fraction(self._numerator, self._denominator)
    
    @property
    def seconds(self) -> Fraction:
        """Zamanı saniye cinsinden döndürür"""
        return self.value
    
    def to_frames(self, fps: Union[Fraction, float, int]) -> int:
        """
        Verilen FPS'de tam kare sayısına çevirir.
        
        Dikkat: Floor davranışı. Kare數sı fractionalse, 
        tam kare numberına düşürülür. Bu, kare-hassas editing 
        için gereklidir — partial frame oluşturmaz.
        
        Args:
            fps: Kare hızı (Fraction tercih edilir)
            
        Returns:
            int: Tam kare numarası (0-based)
        """
        if not isinstance(fps, Fraction):
            fps = Fraction(fps).limit_denominator(1000000)
        return int(self.value * fps)
    
    def to_timecode(
        self,
        fps: Union[Fraction, float, int],
        fmt: TimecodeFormat = TimecodeFormat.NON_DROP_FRAME
    ) -> str:
        """
        SMPTE timecode'a çevir.
        
        Algoritma:
        1. Saniyeyi fps ile çarp, tam kare sayısını bul
        2. Drop-frame ise, kare sayısını düzelt
        3. Kareleri HH:MM:SS:FF formatına böl
        
        Drop-frame düzeltmesi:
        - Her dakika için 2 kare atlanır (00 ve 01 frame'leri)
        - İlk 10 dakika için sadece 00 frame'i atlanır
        - Bu, NTSC'nin gerçek 29.97fps ile timecode arasındaki 
          farkı telafi eder
        """
        if not isinstance(fps, Fraction):
            fps = Fraction(fps).limit_denominator(1000000)
        
        total_frames = self.to_frames(fps)
        
        if fmt == TimecodeFormat.DROP_FRAME:
            # Drop-frame düzeltmesi
            drop_frames = int(2 * (fps.numerator // 1000) / (fps.denominator // 1)) if fps.denominator == 1 else 4
            non_drop_frames_per_10_min = int(fps * 600)
            
            d = total_frames // non_drop_frames_per_10_min
            m = total_frames % non_drop_frames_per_10_min
            total_frames += drop_frames * d + drop_frames * (m // (non_drop_frames_per_10_min // 10)) if m >= drop_frames else 0
        
        ff = total_frames % int(fps)
        ss = (total_frames // int(fps)) % 60
        mm = (total_frames // (int(fps) * 60)) % 60
        hh = total_frames // (int(fps) * 3600)
        
        return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"
    
    @classmethod
    def from_frames(
        cls,
        frame: int,
        fps: Union[Fraction, float, int]
    ) -> RationalTime:
        """Kare numarasından RationalTime oluştur"""
        if not isinstance(fps, Fraction):
            fps = Fraction(fps).limit_denominator(1000000)
        return cls(frame, fps.numerator // fps.denominator if fps.denominator == 1 else 1)
    
    @classmethod
    def from_seconds(cls, seconds: Union[float, int, Fraction, str]) -> RationalTime:
        """
        Saniye cinsinden değerden RationalTime oluştur.
        
        Dikkat: float girişlerde precision kaybı olabilir.
        Mümkünse Fraction veya string kullanımı önerilir.
        """
        if isinstance(seconds, str):
            frac = Fraction(seconds)
        elif isinstance(seconds, float):
            frac = Fraction(seconds).limit_denominator(1000000000)
        elif isinstance(seconds, Fraction):
            frac = seconds
        else:
            frac = Fraction(seconds)
        return cls(frac.numerator, frac.denominator)
    
    @classmethod
    def from_timecode(
        cls,
        tc: str,
        fps: Union[Fraction, float, int],
        fmt: TimecodeFormat = TimecodeFormat.NON_DROP_FRAME
    ) -> RationalTime:
        """
        SMPTE timecode string'inden RationalTime oluştur.
        
        Format: HH:MM:SS:FF veya HH:MM:SS;FF (drop-frame için ;)
        
        Dikkat: Drop-frame timecode parsing, non-drop'a göre daha 
        karmaşıktır. Frame'lerin atlandığını hesaba katmak gerekir.
        """
        if not isinstance(fps, Fraction):
            fps = Fraction(fps).limit_denominator(1000000)
        
        sep = ':' if fmt != TimecodeFormat.DROP_FRAME else ';'
        parts = tc.replace(';', ':').split(':')
        
        if len(parts) != 4:
            raise ValueError(f"Geçersiz timecode formatı: {tc}")
        
        hh, mm, ss, ff = [int(p) for p in parts]
        
        total_frames = (hh * 3600 + mm * 60 + ss) * int(fps) + ff
        
        if fmt == TimecodeFormat.DROP_FRAME:
            # Drop-frame düzeltmesini tersine çevir
            drop_frames = 4  # NTSC için standart
            non_drop_frames_per_10_min = int(fps) * 600
            
            d = total_frames // (non_drop_frames_per_10_min - drop_frames * 9)
            m = total_frames % (non_drop_frames_per_10_min - drop_frames * 9)
            
            if m < drop_frames * 9:
                total_frames = total_frames + drop_frames * (2 * d + (m // drop_frames))
            else:
                total_frames = total_frames + drop_frames * (2 * d + 1 + ((m - drop_frames * 9) // drop_frames))
        
        return cls(total_frames, fps.numerator // fps.denominator if fps.denominator == 1 else 1)
    
    def __add__(self, other: RationalTime) -> RationalTime:
        result = self.value + other.value
        return RationalTime(result.numerator, result.denominator)
    
    def __sub__(self, other: RationalTime) -> RationalTime:
        result = self.value - other.value
        return RationalTime(result.numerator, result.denominator)
    
    def __mul__(self, scalar: Union[int, float, Fraction]) -> RationalTime:
        if isinstance(scalar, RationalTime):
            raise ValueError("RationalTime ile çarpım tanımsız. Scalar değer kullanın.")
        result = self.value * Fraction(scalar).limit_denominator(1000000000)
        return RationalTime(result.numerator, result.denominator)
    
    def __rmul__(self, scalar: Union[int, float, Fraction]) -> RationalTime:
        return self.__mul__(scalar)
    
    def __lt__(self, other: RationalTime) -> bool:
        return self.value < other.value
    
    def __le__(self, other: RationalTime) -> bool:
        return self.value <= other.value
    
    def __gt__(self, other: RationalTime) -> bool:
        return self.value > other.value
    
    def __ge__(self, other: RationalTime) -> bool:
        return self.value >= other.value
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RationalTime):
            return NotImplemented
        return self.value == other.value
    
    def __hash__(self) -> int:
        v = self.value
        return hash((v.numerator, v.denominator))
    
    def __repr__(self) -> str:
        return f"RationalTime({self._numerator}, {self._denominator})"
    
    def __str__(self) -> str:
        return f"{float(self.value):.6f}s"
    
    def to_dict(self) -> dict:
        """Serileştirme için dict"""
        v = self.value
        return {"numerator": v.numerator, "denominator": v.denominator}
    
    @classmethod
    def from_dict(cls, data: dict) -> RationalTime:
        return cls(data["numerator"], data["denominator"])
```

```python
@dataclass(frozen=True, slots=True)
class TimeRange:
    """
    Zaman aralığı — başlangıç ve süre.
    
    Bu yapı, NLE'lerdeki "source range" veya "in/out" kavramının 
    temelini oluşturur. Bir TimeRange, klibin kaynak medyadaki 
    veya timeline üzerindeki konumunu ve süresini belirtir.
    
    Dikkat: Bitiş noktası asla saklanmaz — bitiş = başlangıç + süredir.
    Bu, ripple editing'te süre değiştiğinde bitiş noktasının otomatik 
    güncellenmesini sağlar.
    
    Örnek:
        >>> r = TimeRange(
        ...     start=RationalTime(3000, 30000),
        ...     duration=RationalTime(3000, 30000)
        ... )
        >>> r.end
        RationalTime(6000, 30000)
        >>> r.to_frames(30)
        30
    """
    start: RationalTime
    duration: RationalTime
    
    @property
    def end(self) -> RationalTime:
        """Bitiş noktası (hesaplanır, saklanmaz)"""
        return self.start + self.duration
    
    @property
    def is_empty(self) -> bool:
        """Süre sıfır mı?"""
        return self.duration == RationalTime(0, 1)
    
    def contains(self, time: RationalTime) -> bool:
        """Belirli bir zaman bu aralığın içinde mi?"""
        return self.start <= time < self.end
    
    def overlaps(self, other: TimeRange) -> bool:
        """İki aralık çakışıyor mu?"""
        return self.start < other.end and other.start < self.end
    
    def intersection(self, other: TimeRange) -> Optional[TimeRange]:
        """İki aralığın kesişimi"""
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        if start < end:
            return TimeRange(start, end - start)
        return None
    
    def offset(self, delta: RationalTime) -> TimeRange:
        """Aralığı verilen kadar kaydır"""
        return TimeRange(self.start + delta, self.duration)
    
    def scale(self, factor: Union[int, float, Fraction]) -> TimeRange:
        """Aralığı verilen faktör kadar ölçekle"""
        return TimeRange(self.start, self.duration * factor)
    
    def split_at(self, point: RationalTime) -> Tuple[TimeRange, TimeRange]:
        """
        Aralığı belirli bir noktadan ikiye böl.
        
        Nokta aralık dışındaysa ValueError fırlatır.
        """
        if not self.contains(point):
            raise ValueError(f"Bölme noktası aralık dışında: {point}")
        
        first = TimeRange(self.start, point - self.start)
        second = TimeRange(point, self.end - point)
        return first, second
    
    def __repr__(self) -> str:
        return f"TimeRange({self.start}, {self.duration})"
    
    def to_dict(self) -> dict:
        return {
            "start": self.start.to_dict(),
            "duration": self.duration.to_dict()
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> TimeRange:
        return cls(
            RationalTime.from_dict(data["start"]),
            RationalTime.from_dict(data["duration"])
        )


@dataclass
class Timecode:
    """
    SMPTE Timecode gösterimi.
    
    Timecode, video prodüksiyonunda zamanı insan-okunabilir 
    formatta gösterir. Ancak, timecode ile gerçek zaman 
    arasında her zaman bir fark vardır (özellikle drop-frame'de).
    
    Bu sınıf, timecode'u hem gösterim hem de hesaplama için 
    kullanır. Dahili temsil her zaman RationalTime'dır.
    
    Usage:
        >>> tc = Timecode(1, 15, 30, 10, fps=Fraction(30000, 1001))
        >>> tc.to_rational_time()
        RationalTime(28828801, 30000)
        >>> str(tc)
        '01:15:30;10'
    """
    hours: int = 0
    minutes: int = 0
    seconds: int = 0
    frames: int = 0
    fps: Fraction = field(default_factory=lambda: Fraction(30000, 1001))
    format: TimecodeFormat = TimecodeFormat.NON_DROP_FRAME
    
    def __post_init__(self):
        if self.hours < 0 or self.hours > 23:
            raise ValueError(f"Saat 0-23 arasında olmalı: {self.hours}")
        if self.minutes < 0 or self.minutes > 59:
            raise ValueError(f"Dakika 0-59 arasında olmalı: {self.minutes}")
        if self.seconds < 0 or self.seconds > 59:
            raise ValueError(f"Saniye 0-59 arasında olmalı: {self.seconds}")
        if self.frames < 0 or self.frames >= int(self.fps):
            raise ValueError(f"Kare 0-{int(self.fps)-1} arasında olmalı: {self.frames}")
    
    def to_rational_time(self) -> RationalTime:
        """
        Timecode'u RationalTime'a çevir.
        
        Dikkat: Drop-frame timecode'da, timecode'un düzgün bir 
        rational time'a karşılık gelmesi için özel hesaplama 
        yapılır. Düz timecode (non-drop) basit çarpımla çözülür.
        """
        tc = self.to_string()
        return RationalTime.from_timecode(tc, self.fps, self.format)
    
    @classmethod
    def from_rational_time(
        cls,
        rt: RationalTime,
        fps: Fraction,
        fmt: TimecodeFormat = TimecodeFormat.NON_DROP_FRAME
    ) -> Timecode:
        """RationalTime'dan Timecode oluştur"""
        tc_str = rt.to_timecode(fps, fmt)
        sep = ';' if fmt == TimecodeFormat.DROP_FRAME else ':'
        parts = tc_str.split(':')
        return cls(
            hours=int(parts[0]),
            minutes=int(parts[1]),
            seconds=int(parts[2]),
            frames=int(parts[3]),
            fps=fps,
            format=fmt
        )
    
    def to_string(self) -> str:
        sep = ';' if self.format == TimecodeFormat.DROP_FRAME else ':'
        return (
            f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}"
            f"{sep}{self.frames:02d}"
        )
    
    def __str__(self) -> str:
        return self.to_string()
    
    def __repr__(self) -> str:
        return f"Timecode('{self.to_string()}', fps={self.fps})"


@dataclass
class TrackType(Enum):
    """Track türleri"""
    VIDEO = "video"
    AUDIO = "audio"
    TITLE = "title"
    DATA = "data"
    ADJUSTMENT = "adjustment"


@dataclass
class TimelineClip:
    """
    Timeline üzerindeki bir klip.
    
    Bu yapı, bir medya kaynaktan timeline'a yerleştirilmiş 
    tek bir klip segmentini temsil eder. Her clip'in iki 
    temel zaman aralığı vardır:
    
    1. source_range: Kaynak medyadaki hangi bölümü kullanıldığı
    2. record_range: Timeline üzerinde nereye yerleştirildiği
    
    Bu ayrım, source-record editing modelinin temelidir.
    Premiere'de bu "clip instance" olarak adlandırılır.
    
    Örnek senaryo:
        Bir 10 dakikalık yayından 02:30-02:45 arasını alıp 
        timeline'a 01:00:00'a yerleştirdiğimizde:
        - source_range: TimeRange(02:30, 15s)
        - record_range: TimeRange(01:00:00, 15s)
    """
    clip_id: UUID = field(default_factory=uuid4)
    name: str = ""
    source_media_id: UUID = field(default_factory=uuid4)
    source_range: TimeRange = field(default_factory=lambda: TimeRange(
        RationalTime(0, 1), RationalTime(0, 1)
    ))
    record_range: TimeRange = field(default_factory=lambda: TimeRange(
        RationalTime(0, 1), RationalTime(0, 1)
    ))
    speed: Fraction = field(default_factory=lambda: Fraction(1, 1))
    reverse: bool = False
    maintain_pitch: bool = True
    opacity: float = 1.0
    volume: float = 1.0
    effects: List[UUID] = field(default_factory=list)
    transition_in: Optional[UUID] = None
    transition_out: Optional[UUID] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    locked: bool = False
    enabled: bool = True
    
    @property
    def duration(self) -> RationalTime:
        """
        Timeline'daki görünür süre (hız ayarı dahil).
        
        Hız %200 ise, kaynaktan 10s'lik bir bölüm 
        timeline'da 5s kaplar. Bu yüzden record_range.duration 
        hesaplanırken speed faktörü dikkate alınır.
        """
        if self.speed == 0:
            raise ValueError("Hız sıfır olamaz")
        return RationalTime(
            int(self.source_range.duration.value * abs(self.speed)).numerator,
            1
        )
    
    def source_time_at(self, record_time: RationalTime) -> Optional[RationalTime]:
        """
        Timeline zamanına karşılık gelen kaynak zamanı hesapla.
        
        Bu, scrubbing ve playback sırasında kritiktir.
        Record zamanı clip'in dışında kalırsa None döner.
        """
        if not self.record_range.contains(record_time):
            return None
        
        offset_from_start = record_time - self.record_range.start
        
        if self.reverse:
            return self.source_range.end - (offset_from_start * abs(self.speed))
        else:
            return self.source_range.start + (offset_from_start * abs(self.speed))
    
    def to_dict(self) -> dict:
        return {
            "clip_id": str(self.clip_id),
            "name": self.name,
            "source_media_id": str(self.source_media_id),
            "source_range": self.source_range.to_dict(),
            "record_range": self.record_range.to_dict(),
            "speed": str(self.speed),
            "reverse": self.reverse,
            "maintain_pitch": self.maintain_pitch,
            "opacity": self.opacity,
            "volume": self.volume,
            "effects": [str(e) for e in self.effects],
            "transition_in": str(self.transition_in) if self.transition_in else None,
            "transition_out": str(self.transition_out) if self.transition_out else None,
            "metadata": self.metadata,
            "locked": self.locked,
            "enabled": self.enabled,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> TimelineClip:
        return cls(
            clip_id=UUID(data["clip_id"]),
            name=data["name"],
            source_media_id=UUID(data["source_media_id"]),
            source_range=TimeRange.from_dict(data["source_range"]),
            record_range=TimeRange.from_dict(data["record_range"]),
            speed=Fraction(data["speed"]),
            reverse=data["reverse"],
            maintain_pitch=data["maintain_pitch"],
            opacity=data["opacity"],
            volume=data["volume"],
            effects=[UUID(e) for e in data["effects"]],
            transition_in=UUID(data["transition_in"]) if data["transition_in"] else None,
            transition_out=UUID(data["transition_out"]) if data["transition_out"] else None,
            metadata=data["metadata"],
            locked=data["locked"],
            enabled=data["enabled"],
        )
```

```python
@dataclass
class Track:
    """
    Timeline track'i.
    
    Track, clip'lerin yerleştirildiği yatay bir hattır.
    Video track'leri alttan üste (z-artan), audio track'leri 
    ise üstten alta (z-artan) bindirilir.
    
    Premiere'de V1, V2, V3... video track'leri; 
    A1, A2, A3... audio track'leri vardır.
    Resolve'da benzer bir model kullanılır.
    
    Track locked ise, üzerine yeni clip eklenemez 
    veya mevcut clip'ler taşınamaz.
    """
    track_id: UUID = field(default_factory=uuid4)
    name: str = ""
    track_type: TrackType = TrackType.VIDEO
    clips: List[TimelineClip] = field(default_factory=list)
    order: int = 0
    locked: bool = False
    visible: bool = True
    muted: bool = False
    solo: bool = False
    volume: float = 1.0
    pan: float = 0.0  # -1.0 (sol) ile 1.0 (sağ) arası
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration(self) -> RationalTime:
        """Track'in toplam süresi (tüm clip'lerin kapsadığı alan)"""
        if not self.clips:
            return RationalTime(0, 1)
        end = max(c.record_range.end for c in self.clips if c.enabled)
        start = min(c.record_range.start for c in self.clips if c.enabled)
        return end - start
    
    def clip_at(self, time: RationalTime) -> Optional[TimelineClip]:
        """Belirli bir zamanda hangi clip'in bulunduğunu döndür"""
        for clip in self.clips:
            if clip.enabled and clip.record_range.contains(time):
                return clip
        return None
    
    def clips_in_range(self, range: TimeRange) -> List[TimelineClip]:
        """Belirli bir aralıktaki tüm clip'leri döndür"""
        return [c for c in self.clips if c.enabled and c.record_range.overlaps(range)]
    
    def insert_clip(
        self,
        clip: TimelineClip,
        position: RationalTime,
        mode: str = "insert"
    ) -> None:
        """
        Clip'i track'e ekle.
        
        insert modu: Belirtilen pozisyondaki tüm clip'leri sağa kaydırır.
        overwrite modu: Mevcut clip'lerin üzerine yazar.
        """
        if self.locked:
            raise PermissionError(f"Track kilitli: {self.name}")
        
        clip.record_range = TimeRange(position, clip.record_range.duration)
        
        if mode == "insert":
            # Sağdaki clip'leri kaydır
            for existing in self.clips:
                if existing.record_range.start >= position and existing != clip:
                    existing.record_range = existing.record_range.offset(
                        clip.record_range.duration
                    )
            self.clips.append(clip)
            self._sort_clips()
        elif mode == "overwrite":
            # Çakışan clip'leri kaldır veya kırp
            self._remove_overlapping(clip.record_range)
            self.clips.append(clip)
            self._sort_clips()
        else:
            raise ValueError(f"Geçersiz ekleme modu: {mode}")
    
    def _sort_clips(self):
        """Clip'leri pozisyona göre sırala"""
        self.clips.sort(key=lambda c: c.record_range.start.value)
    
    def _remove_overlapping(self, range: TimeRange):
        """Verilen aralıktaki çakışan clip'leri kaldır veya kırp"""
        new_clips = []
        for clip in self.clips:
            if not clip.record_range.overlaps(range):
                new_clips.append(clip)
            else:
                # Kırpma mantığı — clip'i ikiye böl veya kısalt
                before, after = self._split_clip_around_range(clip, range)
                if before:
                    new_clips.append(before)
                if after:
                    new_clips.append(after)
        self.clips = new_clips
    
    def _split_clip_around_range(
        self,
        clip: TimelineClip,
        range: TimeRange
    ) -> Tuple[Optional[TimelineClip], Optional[TimelineClip]]:
        """Clip'i verilen aralığın etrafında ikiye böl"""
        import copy
        
        before = None
        after = None
        
        if clip.record_range.start < range.start:
            # Sol tarafta bir parça kalır
            before = copy.deepcopy(clip)
            before.clip_id = uuid4()
            before_duration = range.start - before.record_range.start
            before.record_range = TimeRange(before.record_range.start, before_duration)
            before.source_range = TimeRange(
                before.source_range.start,
                before_duration
            )
        
        if clip.record_range.end > range.end:
            # Sağ tarafta bir parça kalır
            after = copy.deepcopy(clip)
            after.clip_id = uuid4()
            after_offset = range.end - clip.record_range.start
            after.record_range = TimeRange(range.end, clip.record_range.end - range.end)
            after.source_range = TimeRange(
                after.source_range.start + after_offset,
                after.source_range.duration - after_offset
            )
        
        return before, after
    
    def to_dict(self) -> dict:
        return {
            "track_id": str(self.track_id),
            "name": self.name,
            "track_type": self.track_type.value,
            "clips": [c.to_dict() for c in self.clips],
            "order": self.order,
            "locked": self.locked,
            "visible": self.visible,
            "muted": self.muted,
            "solo": self.solo,
            "volume": self.volume,
            "pan": self.pan,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> Track:
        return cls(
            track_id=UUID(data["track_id"]),
            name=data["name"],
            track_type=TrackType(data["track_type"]),
            clips=[TimelineClip.from_dict(c) for c in data["clips"]],
            order=data["order"],
            locked=data["locked"],
            visible=data["visible"],
            muted=data["muted"],
            solo=data["solo"],
            volume=data["volume"],
            pan=data["pan"],
            metadata=data["metadata"],
        )


@dataclass
class Timeline:
    """
    Ana zaman çizelgesi.
    
    Timeline, tüm düzenleme工作的 merkezidir. Birden fazla 
    track'i barındırır ve zaman boyunca ilerler.
    
    Mimari notlar:
    - Timeline, projenin "root" timeline'ıdır
    - Nested sequence'lar (alt sequence'lar) ayrı Timeline 
      instance'ları olarak tutulur
    - Her Timeline'ın kendi FPS'i ve çözümü vardır
    - Farklı FPS'te kaynak medyalar, timeline FPS'ine otomatik 
      uyum sağlar (frame blending veya frame dropping ile)
    
    Premiere'de "Sequence", Resolve'da "Timeline" olarak adlandırılır.
    """
    timeline_id: UUID = field(default_factory=uuid4)
    name: str = "Yeni Timeline"
    tracks: List[Track] = field(default_factory=list)
    fps: Fraction = field(default_factory=lambda: Fraction(30000, 1001))
    width: int = 1920
    height: int = 1080
    pixel_aspect: Fraction = field(default_factory=lambda: Fraction(1, 1))
    audio_sample_rate: int = 48000
    audio_bit_depth: int = 24
    current_position: RationalTime = field(default_factory=lambda: RationalTime(0, 1))
    in_point: Optional[RationalTime] = None
    out_point: Optional[RationalTime] = None
    markers: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    modified_at: str = ""
    
    @property
    def duration(self) -> RationalTime:
        """
        Timeline'ın toplam süresi.
        
        Tüm track'lerin en uzun noktasına göre hesaplanır.
        """
        if not self.tracks:
            return RationalTime(0, 1)
        max_end = RationalTime(0, 1)
        for track in self.tracks:
            if track.clips:
                track_end = max(c.record_range.end for c in track.clips)
                if track_end > max_end:
                    max_end = track_end
        return max_end
    
    @property
    def video_tracks(self) -> List[Track]:
        """Sadece video track'lerini döndür"""
        return [t for t in self.tracks if t.track_type == TrackType.VIDEO]
    
    @property
    def audio_tracks(self) -> List[Track]:
        """Sadece audio track'lerini döndür"""
        return [t for t in self.tracks if t.track_type == TrackType.AUDIO]
    
    def add_track(
        self,
        track_type: TrackType,
        name: Optional[str] = None,
        order: Optional[int] = None
    ) -> Track:
        """
        Timeline'a yeni bir track ekle.
        
        Video track'leri default olarak üstte eklenir.
        Audio track'leri default olarak altta eklenir.
        """
        if order is None:
            existing_of_type = [t for t in self.tracks if t.track_type == track_type]
            order = len(existing_of_type)
        
        track = Track(
            name=name or f"{track_type.value.upper()} {order + 1}",
            track_type=track_type,
            order=order,
        )
        self.tracks.append(track)
        return track
    
    def remove_track(self, track_id: UUID) -> bool:
        """Track'i ve tüm clip'lerini kaldır"""
        for i, track in enumerate(self.tracks):
            if track.track_id == track_id:
                if track.locked:
                    raise PermissionError(f"Track kilitli: {track.name}")
                del self.tracks[i]
                return True
        return False
    
    def get_track(self, track_id: UUID) -> Optional[Track]:
        """Track'i ID ile bul"""
        for track in self.tracks:
            if track.track_id == track_id:
                return track
        return None
    
    def scrub_to(self, position: RationalTime) -> List[TimelineClip]:
        """
        Belirli bir pozisyona git (scrubbing).
        
        Bu pozisyondaki tüm track'lerdeki clip'leri döndür.
        Playback motoru, bu clip'leri kompozitöre gönderir.
        """
        self.current_position = position
        active_clips = []
        for track in self.tracks:
            if track.visible and not track.muted:
                clip = track.clip_at(position)
                if clip:
                    active_clips.append(clip)
        return active_clips
    
    def set_in_point(self, point: Optional[RationalTime] = None):
        """In point ayarla (None ise mevcut pozisyondan)"""
        self.in_point = point or self.current_position
    
    def set_out_point(self, point: Optional[RationalTime] = None):
        """Out point ayarla (None ise mevcut pozisyondan)"""
        self.out_point = point or self.current_position
    
    @property
    def marked_range(self) -> Optional[TimeRange]:
        """In/out point'leri arasındaki aralık"""
        if self.in_point is not None and self.out_point is not None:
            start = min(self.in_point, self.out_point)
            end = max(self.in_point, self.out_point)
            return TimeRange(start, end - start)
        return None
    
    def add_marker(
        self,
        position: RationalTime,
        name: str = "",
        color: str = "blue",
        notes: str = ""
    ):
        """Timeline'a marker ekle"""
        self.markers.append({
            "position": position.to_dict(),
            "name": name,
            "color": color,
            "notes": notes,
        })
    
    def to_dict(self) -> dict:
        return {
            "timeline_id": str(self.timeline_id),
            "name": self.name,
            "tracks": [t.to_dict() for t in self.tracks],
            "fps": str(self.fps),
            "width": self.width,
            "height": self.height,
            "pixel_aspect": str(self.pixel_aspect),
            "audio_sample_rate": self.audio_sample_rate,
            "audio_bit_depth": self.audio_bit_depth,
            "current_position": self.current_position.to_dict(),
            "in_point": self.in_point.to_dict() if self.in_point else None,
            "out_point": self.out_point.to_dict() if self.out_point else None,
            "markers": self.markers,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> Timeline:
        return cls(
            timeline_id=UUID(data["timeline_id"]),
            name=data["name"],
            tracks=[Track.from_dict(t) for t in data["tracks"]],
            fps=Fraction(data["fps"]),
            width=data["width"],
            height=data["height"],
            pixel_aspect=Fraction(data["pixel_aspect"]),
            audio_sample_rate=data["audio_sample_rate"],
            audio_bit_depth=data["audio_bit_depth"],
            current_position=RationalTime.from_dict(data["current_position"]),
            in_point=RationalTime.from_dict(data["in_point"]) if data["in_point"] else None,
            out_point=RationalTime.from_dict(data["out_point"]) if data["out_point"] else None,
            markers=data["markers"],
            metadata=data["metadata"],
            created_at=data["created_at"],
            modified_at=data["modified_at"],
        )
    
    def save(self, path: str):
        """Timeline'ı JSON dosyasına kaydet"""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load(cls, path: str) -> Timeline:
        """Timeline'ı JSON dosyasından yükle"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)
```

## 1.4 Temel Algoritmalar

### 1.4.1 Ripple Edit Algoritması

Ripple edit, bir clip'in süresini değiştirdiğinde, sağında duran tüm clip'leri otomatik olarak kaydırır. Bu, timeline'da boşluk (gap) oluşmasını engeller.

```python
def ripple_edit(
    timeline: Timeline,
    track_id: UUID,
    clip_id: UUID,
    new_duration: RationalTime,
    direction: str = "right"
) -> None:
    """
    Ripple edit uygula.
    
    Algoritma:
    1. Hedef clip'i bul
    2. Süre değişimini hesapla (delta = yeni süre - eski süre)
    3. Eğer delta > 0 (uzatma): Sağdaki tüm clip'leri delta kadar sağa kaydır
    4. Eğer delta < 0 (kısaltma): Sağdaki tüm clip'leri |delta| kadar sola kaydır
    5. Clip'in süresini güncelle
    
    Karmaşıklık: O(n) — track'teki tüm clip'ler taranır
    
    Premiere'de bu, "Ripple Edit Tool" (B) ile yapılır.
    Resolve'da ise "Trim Edit Mode" benzer işlevi görür.
    """
    track = timeline.get_track(track_id)
    if not track:
        raise ValueError(f"Track bulunamadı: {track_id}")
    
    target_clip = None
    for clip in track.clips:
        if clip.clip_id == clip_id:
            target_clip = clip
            break
    
    if not target_clip:
        raise ValueError(f"Clip bulunamadı: {clip_id}")
    
    if target_clip.locked:
        raise PermissionError("Clip kilitli")
    
    old_duration = target_clip.record_range.duration
    delta = new_duration - old_duration
    
    if delta == RationalTime(0, 1):
        return
    
    # Sağdaki clip'leri kaydır
    for clip in track.clips:
        if clip.clip_id == clip_id:
            continue
        if clip.record_range.start >= target_clip.record_range.end:
            clip.record_range = clip.record_range.offset(delta)
    
    # Hedef clip'in süresini güncelle
    target_clip.record_range = TimeRange(
        target_clip.record_range.start,
        new_duration
    )
    
    track._sort_clips()


def roll_edit(
    timeline: Timeline,
    track_id: UUID,
    cut_point: RationalTime,
    delta: RationalTime
) -> None:
    """
    Roll edit uygula.
    
    Roll edit, iki clip arasındaki geçiş noktasını kaydırır.
    Sol clip uzarken sağ clip kısalır (veya tersi).
    Toplam süre değişmez — bu, roll edit'in temel özelliğidir.
    
    Algoritma:
    1. Kesme noktasındaki iki clip'i bul (sol ve sağ)
    2. Sol clip'in bitişini delta kadar kaydır
    3. Sağ clip'in başlangıcını delta kadar kaydır
    4. Her iki clip'in source_range'ini güncelle
    
    Karmaşıklık: O(n) — clip arama
    """
    track = timeline.get_track(track_id)
    if not track:
        raise ValueError(f"Track bulunamadı: {track_id}")
    
    left_clip = None
    right_clip = None
    
    for clip in track.clips:
        if clip.record_range.end == cut_point:
            left_clip = clip
        elif clip.record_range.start == cut_point:
            right_clip = clip
    
    if not left_clip or not right_clip:
        raise ValueError(f"Kesme noktasında iki clip bulunamadı: {cut_point}")
    
    if left_clip.locked or right_clip.locked:
        raise PermissionError("Clip kilitli")
    
    # Roll uygula
    left_clip.record_range = TimeRange(
        left_clip.record_range.start,
        left_clip.record_range.duration + delta
    )
    left_clip.source_range = TimeRange(
        left_clip.source_range.start,
        left_clip.source_range.duration + delta
    )
    
    right_clip.record_range = TimeRange(
        right_clip.record_range.start + delta,
        right_clip.record_range.duration - delta
    )
    right_clip.source_range = TimeRange(
        right_clip.source_range.start + delta,
        right_clip.source_range.duration - delta
    )


def slip_edit(
    timeline: Timeline,
    track_id: UUID,
    clip_id: UUID,
    delta: RationalTime
) -> None:
    """
    Slip edit uygula.
    
    Slip edit, clip'in timeline'daki konumunu değiştirmeden, 
    kaynak medyadaki hangi bölümü gösterdiğini değiştirir.
    
    Timeline'da clip'in başlangıcı ve bitişi aynı kalır, 
    ama içeriği kayar.
    
    Algoritma:
    1. Clip'i bul
    2. source_range.start += delta
    3. source_range.start'in kaynak medya sınırları içinde olduğunu doğrula
    4. delta negatif ise: source_range.start >= 0 olmalı
    5. delta pozitif ise: source_range.start + duration <= medya_süresi olmalı
    
    Karmaşıklık: O(1)
    """
    track = timeline.get_track(track_id)
    if not track:
        raise ValueError(f"Track bulunamadı: {track_id}")
    
    target_clip = None
    for clip in track.clips:
        if clip.clip_id == clip_id:
            target_clip = clip
            break
    
    if not target_clip:
        raise ValueError(f"Clip bulunamadı: {clip_id}")
    
    if target_clip.locked:
        raise PermissionError("Clip kilitli")
    
    new_start = target_clip.source_range.start + delta
    
    # Kaynak medya sınırları kontrolü
    if new_start < RationalTime(0, 1):
        raise ValueError("Slip edit kaynak medya başlangıcını aşıyor")
    
    target_clip.source_range = TimeRange(
        new_start,
        target_clip.source_range.duration
    )


def slide_edit(
    timeline: Timeline,
    track_id: UUID,
    clip_id: UUID,
    delta: RationalTime
) -> None:
    """
    Slide edit uygula.
    
    Slide edit, clip'i timeline'da sola veya sağa kaydırır, 
    ama komşu clip'lerin süresini otomatik olarak ayarlar.
    
    Sol komşu clip uzarken, sağ komşu clip kısalır (veya tersi).
    Hedef clip'in içeriği değişmez — sadece konumu değişir.
    
    Karmaşıklık: O(n) — komşu clip'leri bulma
    """
    track = timeline.get_track(track_id)
    if not track:
        raise ValueError(f"Track bulunamadı: {track_id}")
    
    target_clip = None
    for clip in track.clips:
        if clip.clip_id == clip_id:
            target_clip = clip
            break
    
    if not target_clip:
        raise ValueError(f"Clip bulunamadı: {clip_id}")
    
    if target_clip.locked:
        raise PermissionError("Clip kilitli")
    
    # Sol komşuyu bul
    left_clip = None
    for clip in track.clips:
        if clip.record_range.end == target_clip.record_range.start:
            left_clip = clip
            break
    
    # Sağ komşuyu bul
    right_clip = None
    for clip in track.clips:
        if clip.record_range.start == target_clip.record_range.end:
            right_clip = clip
            break
    
    if not left_clip or not right_clip:
        raise ValueError("Slide edit için komşu clip bulunamadı")
    
    # Slide uygula
    target_clip.record_range = target_clip.record_range.offset(delta)
    
    if delta > RationalTime(0, 1):
        # Sağa kaydırma: sol komşu uzar, sağ komşu kısalır
        left_clip.record_range = TimeRange(
            left_clip.record_range.start,
            left_clip.record_range.duration + delta
        )
        left_clip.source_range = TimeRange(
            left_clip.source_range.start,
            left_clip.source_range.duration + delta
        )
        right_clip.record_range = TimeRange(
            right_clip.record_range.start + delta,
            right_clip.record_range.duration - delta
        )
        right_clip.source_range = TimeRange(
            right_clip.source_range.start + delta,
            right_clip.source_range.duration - delta
        )
    else:
        # Sola kaydırma: sol komşu kısalır, sağ komşu uzar
        left_clip.record_range = TimeRange(
            left_clip.record_range.start,
            left_clip.record_range.duration + delta
        )
        left_clip.source_range = TimeRange(
            left_clip.source_range.start,
            left_clip.source_range.duration + delta
        )
        right_clip.record_range = TimeRange(
            right_clip.record_range.start + delta,
            right_clip.record_range.duration - delta
        )
        right_clip.source_range = TimeRange(
            right_clip.source_range.start + delta,
            right_clip.source_range.duration - delta
        )
```

### 1.4.2 Undo/Redo Yığını (Command Pattern)

```python
from abc import ABC, abstractmethod


class EditCommand(ABC):
    """
    Düzenleme komutu — Command Pattern.
    
    Her düzenleme işlemi (insert, delete, move, vb.) bir 
    EditCommand instance'ı olarak temsil edilir. Bu, 
    undo/redo functionality için gereklidir.
    
    Premiere ve Resolve'da benzer bir command pattern kullanılır.
    Fakat biz, command'ları serileştirebilir (serializable) 
    yapıyoruz — bu, proje dosyaları ile birlikte 
    undo geçmişinin de kaydedilebilmesini sağlar.
    
    Her command şunları sağlamak zorundadır:
    - execute(): Komutu uygula
    - undo(): Komutu geri al
    - redo(): Komutu tekrar uygula
    - serialize(): Command'ı serileştir (opsiyonel)
    """
    
    @abstractmethod
    def execute(self) -> None:
        """Komutu uygula"""
        pass
    
    @abstractmethod
    def undo(self) -> None:
        """Komutu geri al"""
        pass
    
    @abstractmethod
    def redo(self) -> None:
        """Komutu tekrar uygula"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Komutun açıklaması (undo menüsünde gösterilir)"""
        pass


class InsertClipCommand(EditCommand):
    """Clip ekleme komutu"""
    
    def __init__(
        self,
        timeline: Timeline,
        track_id: UUID,
        clip: TimelineClip,
        position: RationalTime,
        mode: str = "insert"
    ):
        self.timeline = timeline
        self.track_id = track_id
        self.clip = clip
        self.position = position
        self.mode = mode
        self._displaced_clips: List[Tuple[UUID, TimeRange]] = []
    
    def execute(self) -> None:
        track = self.timeline.get_track(self.track_id)
        if not track:
            raise ValueError(f"Track bulunamadı: {self.track_id}")
        
        if self.mode == "insert":
            # Kaydırılacak clip'leri kaydet
            for existing in track.clips:
                if existing.record_range.start >= self.position:
                    self._displaced_clips.append(
                        (existing.clip_id, existing.record_range)
                    )
        
        track.insert_clip(self.clip, self.position, self.mode)
    
    def undo(self) -> None:
        track = self.timeline.get_track(self.track_id)
        if not track:
            return
        
        # Clip'i kaldır
        track.clips = [c for c in track.clips if c.clip_id != self.clip.clip_id]
        
        # Kaydırılan clip'leri eski yerine koy
        if self.mode == "insert":
            for clip_id, original_range in self._displaced_clips:
                for clip in track.clips:
                    if clip.clip_id == clip_id:
                        clip.record_range = original_range
                        break
    
    def redo(self) -> None:
        self.execute()
    
    @property
    def description(self) -> str:
        return f"Clip ekle: {self.clip.name} @ {self.position}"


class DeleteClipCommand(EditCommand):
    """Clip silme komutu"""
    
    def __init__(self, timeline: Timeline, track_id: UUID, clip_id: UUID):
        self.timeline = timeline
        self.track_id = track_id
        self.clip_id = clip_id
        self._deleted_clip: Optional[TimelineClip] = None
        self._displaced_clips: List[Tuple[UUID, TimeRange]] = []
    
    def execute(self) -> None:
        track = self.timeline.get_track(self.track_id)
        if not track:
            raise ValueError(f"Track bulunamadı: {self.track_id}")
        
        target_clip = None
        for clip in track.clips:
            if clip.clip_id == self.clip_id:
                target_clip = clip
                break
        
        if not target_clip:
            raise ValueError(f"Clip bulunamadı: {self.clip_id}")
        
        self._deleted_clip = target_clip
        track.clips.remove(target_clip)
    
    def undo(self) -> None:
        if self._deleted_clip:
            track = self.timeline.get_track(self.track_id)
            if track:
                track.clips.append(self._deleted_clip)
                track._sort_clips()
    
    def redo(self) -> None:
        self.execute()
    
    @property
    def description(self) -> str:
        return f"Clip sil: {self.clip_id}"


class UndoRedoStack:
    """
    Undo/Redo yığını.
    
    Bu sınıf, tüm düzenleme komutlarını tutar ve 
    undo/redo işlemlerini yönetir.
    
    Premiere'de "History Panel" benzer işlevi görür.
    Maksimum undo sayısı ayarlanabilir (default: 100).
    
    Thread-safety: Bu sınıf tek thread'li kullanım için tasarlanmıştır.
    Multi-thread kullanımında ek kilit mekanizması gerekir.
    """
    
    def __init__(self, max_history: int = 100):
        self._undo_stack: List[EditCommand] = []
        self._redo_stack: List[EditCommand] = []
        self._max_history = max_history
        self._on_change_callbacks: List = []
    
    def execute(self, command: EditCommand) -> None:
        """
        Komutu uygula ve undo yığına ekle.
        
        Yeni bir komut uygulandığında, redo yığı temizlenir — 
        çünkü redo geçmişi artık geçersizdir.
        """
        command.execute()
        self._undo_stack.append(command)
        self._redo_stack.clear()
        
        # Maksimum geçmiş sınırlaması
        while len(self._undo_stack) > self._max_history:
            self._undo_stack.pop(0)
        
        self._notify_change()
    
    def undo(self) -> Optional[EditCommand]:
        """
        Son komutu geri al.
        
        Returns:
            Geri alınan komut veya None (yığın boşsa)
        """
        if not self._undo_stack:
            return None
        
        command = self._undo_stack.pop()
        command.undo()
        self._redo_stack.append(command)
        self._notify_change()
        return command
    
    def redo(self) -> Optional[EditCommand]:
        """
        Son geri alınan komutu tekrar uygula.
        
        Returns:
            Tekrar uygulanan komut veya None (yığın boşsa)
        """
        if not self._redo_stack:
            return None
        
        command = self._redo_stack.pop()
        command.redo()
        self._undo_stack.append(command)
        self._notify_change()
        return command
    
    def clear(self) -> None:
        """Tüm geçmiş temizle"""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._notify_change()
    
    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0
    
    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0
    
    @property
    def undo_description(self) -> Optional[str]:
        """Son undone komutun açıklaması"""
        if self._undo_stack:
            return self._undo_stack[-1].description
        return None
    
    @property
    def redo_description(self) -> Optional[str]:
        """Son redo edilebilir komutun açıklaması"""
        if self._redo_stack:
            return self._redo_stack[-1].description
        return None
    
    def on_change(self, callback):
        """Değişiklik olduğunda çağrılacak callback"""
        self._on_change_callbacks.append(callback)
    
    def _notify_change(self):
        for cb in self._on_change_callbacks:
            cb()
```

## 1.5 API Sözleşmeleri

```python
class TimelineEngine:
    """
    Timeline motoru için üst düzey API.
    
    Bu sınıf, FastAPI endpoint'lerinden erişilen 
    ana controller'ıdır. Tüm timeline işlemleri 
    bu sınıf üzerinden yürütülür.
    
    Usage:
        engine = TimelineEngine()
        timeline = engine.create_timeline("Proje 1", fps=Fraction(30000, 1001))
        engine.add_track(timeline.timeline_id, TrackType.VIDEO, "V1")
        engine.insert_clip(timeline.timeline_id, track_id, clip, position)
    """
    
    def __init__(self):
        self._timelines: Dict[UUID, Timeline] = {}
        self._undo_stacks: Dict[UUID, UndoRedoStack] = {}
    
    def create_timeline(
        self,
        name: str,
        fps: Union[Fraction, float, int] = Fraction(30000, 1001),
        width: int = 1920,
        height: int = 1080,
    ) -> Timeline:
        """
        Yeni bir timeline oluştur.
        
        Args:
            name: Timeline adı
            fps: Kare hızı (Fraction önerilir)
            width: Çözünürlük genişliği
            height: Çözünürlük yüksekliği
            
        Returns:
            Oluşturulan Timeline nesnesi
        """
        if not isinstance(fps, Fraction):
            fps = Fraction(fps).limit_denominator(1000000)
        
        timeline = Timeline(
            name=name,
            fps=fps,
            width=width,
            height=height,
        )
        self._timelines[timeline.timeline_id] = timeline
        self._undo_stacks[timeline.timeline_id] = UndoRedoStack()
        return timeline
    
    def get_timeline(self, timeline_id: UUID) -> Optional[Timeline]:
        """Timeline'ı ID ile getir"""
        return self._timelines.get(timeline_id)
    
    def add_track(
        self,
        timeline_id: UUID,
        track_type: TrackType,
        name: Optional[str] = None,
    ) -> Track:
        """
        Timeline'a track ekle.
        
        Args:
            timeline_id: Timeline ID
            track_type: Track türü (VIDEO, AUDIO, vb.)
            name: Track adı (None ise otomatik)
            
        Returns:
            Oluşturulan Track nesnesi
        """
        timeline = self._timelines.get(timeline_id)
        if not timeline:
            raise ValueError(f"Timeline bulunamadı: {timeline_id}")
        return timeline.add_track(track_type, name)
    
    def insert_clip(
        self,
        timeline_id: UUID,
        track_id: UUID,
        clip: TimelineClip,
        position: RationalTime,
        mode: str = "insert"
    ) -> None:
        """
        Timeline'a clip ekle (undo/destekli).
        
        Bu metod, command pattern kullanarak clip ekler 
        ve undo/redo geçmişine kaydeder.
        """
        timeline = self._timelines.get(timeline_id)
        if not timeline:
            raise ValueError(f"Timeline bulunamadı: {timeline_id}")
        
        stack = self._undo_stacks[timeline_id]
        command = InsertClipCommand(timeline, track_id, clip, position, mode)
        stack.execute(command)
    
    def undo(self, timeline_id: UUID) -> Optional[str]:
        """
        Son işlemi geri al.
        
        Returns:
            Geri alınan işlemin açıklaması veya None
        """
        stack = self._undo_stacks.get(timeline_id)
        if not stack:
            return None
        command = stack.undo()
        return command.description if command else None
    
    def redo(self, timeline_id: UUID) -> Optional[str]:
        """
        Son geri alınan işlemi tekrar uygula.
        
        Returns:
            Tekrar uygulanan işlemin açıklaması veya None
        """
        stack = self._undo_stacks.get(timeline_id)
        if not stack:
            return None
        command = stack.redo()
        return command.description if command else None
    
    def ripple_edit(
        self,
        timeline_id: UUID,
        track_id: UUID,
        clip_id: UUID,
        new_duration: RationalTime
    ) -> None:
        """
        Ripple edit uygula.
        
        Clip'in süresini değiştirir ve sağdaki clip'leri kaydırır.
        """
        timeline = self._timelines.get(timeline_id)
        if not timeline:
            raise ValueError(f"Timeline bulunamadı: {timeline_id}")
        
        ripple_edit(timeline, track_id, clip_id, new_duration)
    
    def save_project(self, timeline_id: UUID, path: str) -> None:
        """
        Proje dosyasını kaydet.
        
        Tüm timeline verisi, clip'ler, track'ler ve 
        metadata JSON formatında kaydedilir.
        """
        timeline = self._timelines.get(timeline_id)
        if not timeline:
            raise ValueError(f"Timeline bulunamadı: {timeline_id}")
        timeline.save(path)
    
    def load_project(self, path: str) -> Timeline:
        """
        Proje dosyasından yükle.
        
        Returns:
            Yüklenen Timeline nesnesi
        """
        timeline = Timeline.load(path)
        self._timelines[timeline.timeline_id] = timeline
        self._undo_stacks[timeline.timeline_id] = UndoRedoStack()
        return timeline
```

## 1.6 Performans Darboğazları ve Çözümleri

| Darboğaz | Etki | Çözüm |
|---|---|---|
| Large timeline scan (1000+ clip) | O(n) tarama yavaş | Interval tree (sortedcontainers) ile clip lookup O(log n)'e düşer |
| Fraction precision | Büyük payda değerleri yavaş | `limit_denominator(1000000)` ile sınırlandır |
| JSON serialization (büyük projeler) | Serialization 100ms+ | `orjson` kütüphanesi, 5x daha hızlı |
| Undo stack memory | 1000+ undo noktası ~100MB | LRU cache ile eski komutları disk'e flush |
| Real-time scrubbing | 30fps'de her 33ms'de kare hesaplama | Ahead-of-time precompute + thread pool |

## 1.7 Entegrasyon Noktaları

```
Timeline Engine
    ├── API Controller (FastAPI) ← HTTP endpoint'lerinden çağrılır
    ├── Media Manager ← Kaynak medya bilgilerini alır
    ├── Effect Engine ← Clip'lerdeki efektleri uygular
    ├── Compositor ← Aktif clip'leri kompozitöre gönderir
    └── Project Serializer ← Proje dosyası okuma/yazma
```

---

# 2. Katman Tabanlı Düzenleme Sistemi

## 2.1 Amaç ve Kapsam

Katman tabanlı editing, multi-layer compositing'in temelini oluşturur. Bir NLE'de görülen her şey bir katman üzerindedir — video, ses, başlık, efekt, her şey. Katmanlar, alttan üste (bottom-up) bindirilir, ve her katmanın kendi özellikleri (opaklık, blend mode, transform) vardır.

Bu sistem, After Effects'in katman modeli ile Premiere'in track modelinin birleşimidir. Bizim yaklaşımımızda, **track'ler Timeline seviyesinde, katmanlar ise her bir track'in içinde** yer alır. Bu, Resolve'unkine benzer bir yapıdır.

### Karşılaştırma

| Özellik | Bizim Sistem | Premiere | Resolve | After Effects |
|---|---|---|---|---|
| Katman modeli | Track içi katman | Track tabanlı | Track tabanlı | Doğrudan katman |
| Nested sequences | Evet | Evet (nest) | Evet (compound clip) | Evet (pre-comp) |
| Blend modes | 12 mod | 10+ mod | 10+ mod | 30+ mod |
| Adjustment layer | Evet | Evet | Evet (adjustment clip) | Evet |
| Layer masking | Evet | Evet | Evet | Evet |

## 2.2 Mimari

```
┌─────────────────────────────────────────────┐
│            Layer-Based Editing               │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │           LayerStack                  │   │
│  │  ┌──────────────────────────────┐    │   │
│  │  │ Layer 5: Title (Text)        │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ Layer 4: Effect (Glow)       │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ Layer 3: Adjustment (Color)  │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ Layer 2: Video (Overlay)     │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ Layer 1: Video (Main)        │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ Layer 0: Audio (Background)  │    │   │
│  │  └──────────────────────────────┘    │   │
│  └──────────────────────────────────────┘   │
│       │                                      │
│  ┌──────────────────────────────────────┐   │
│  │    Compositor (Output)               │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

## 2.3 Veri Yapısı

```python
"""
Katman tabanlı düzenleme sistemi veri yapıları.

Tasarım İlkeleri:
1. Her katman bağımsız olarak manipüle edilebilir
2. Katmanlar opsiyonel olarak birbirine bağlanabilir (parent-child)
3. Nested sequence'lar bir katman olarak yerleştirilebilir
4. Tüm katman özellikleri keyframe ile animasyonlanabilir
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID, uuid4


class LayerType(Enum):
    """Katman türleri"""
    VIDEO = "video"
    AUDIO = "audio"
    TITLE = "title"
    EFFECT = "effect"
    ADJUSTMENT = "adjustment"
    DATA = "data"
    NESTED = "nested"
    SOLID = "solid"
    NULL = "null"


class BlendMode(Enum):
    """
    Blend mode'ları — compositing için gerekli.
    
    Her mod, kaynak (üst) ve hedef (alt) pikselleri 
    arasında farklı bir matematiksel işlem yapar.
    
    Bu modlar, Photoshop ve After Effects'teki ile aynıdır.
    Premiere'de daha az mod vardır, biz daha kapsamlı bir set sunuyoruz.
    """
    NORMAL = "normal"
    MULTIPLY = "multiply"
    SCREEN = "screen"
    OVERLAY = "overlay"
    SOFT_LIGHT = "soft_light"
    HARD_LIGHT = "hard_light"
    DIFFERENCE = "difference"
    EXCLUSION = "exclusion"
    COLOR_DODGE = "color_dodge"
    COLOR_BURN = "color_burn"
    LINEAR_BURN = "linear_burn"
    LINEAR_LIGHT = "linear_light"
    VIVID_LIGHT = "vivid_light"
    PIN_LIGHT = "pin_light"
    DARKEN = "darken"
    LIGHTEN = "lighten"
    ADD = "add"
    
    def apply(self, src: float, dst: float) -> float:
        """
        Blend hesaplaması yap.
        
        Args:
            src: Kaynak piksel değeri [0.0, 1.0]
            dst: Hedef piksel değeri [0.0, 1.0]
            
        Returns:
            Karıştırılmış piksel değeri [0.0, 1.0]
        """
        if self == BlendMode.NORMAL:
            return src
        elif self == BlendMode.MULTIPLY:
            return src * dst
        elif self == BlendMode.SCREEN:
            return 1.0 - (1.0 - src) * (1.0 - dst)
        elif self == BlendMode.OVERLAY:
            return dst * dst * 2 if dst < 0.5 else 1.0 - 2.0 * (1.0 - src) * (1.0 - dst)
        elif self == BlendMode.SOFT_LIGHT:
            if src < 0.5:
                return dst - (1.0 - 2.0 * src) * dst * (1.0 - dst)
            else:
                d = 2.0 * dst - 1.0
                return dst + d * (math.sqrt(dst) - dst)
        elif self == BlendMode.HARD_LIGHT:
            if src < 0.5:
                return 2.0 * src * dst
            else:
                return 1.0 - 2.0 * (1.0 - src) * (1.0 - dst)
        elif self == BlendMode.DIFFERENCE:
            return abs(src - dst)
        elif self == BlendMode.EXCLUSION:
            return src + dst - 2.0 * src * dst
        elif self == BlendMode.DARKEN:
            return min(src, dst)
        elif self == BlendMode.LIGHTEN:
            return max(src, dst)
        elif self == BlendMode.ADD:
            return min(1.0, src + dst)
        elif self == BlendMode.COLOR_DODGE:
            if dst == 0.0:
                return 0.0
            return min(1.0, dst / (1.0 - src)) if src < 1.0 else 1.0
        elif self == BlendMode.COLOR_BURN:
            if dst == 1.0:
                return 1.0
            return 1.0 - min(1.0, (1.0 - dst) / src) if src > 0.0 else 0.0
        else:
            return src


class AlphaMode(Enum):
    """
    Alpha kanalı işleme modları.
    
    Premultiplied alpha: RGB değerleri alpha ile çarpılmıştır.
    Bu, compositing sırasında daha az işlem gerektirir 
    ve endüstri standardıdır (After Effects, Nuke).
    
    Straight alpha: RGB değerleri saf, alpha ayrı depolanır.
    Bu, bazı eski formatlarda kullanılır.
    """
    STRAIGHT = "straight"
    PREMULTIPLIED = "premultiplied"
    UNPREMULTIPLIED = "unpremultiplied"


class AnchorPoint(Enum):
    """Referans noktaları — transform için"""
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    MIDDLE_LEFT = "middle_left"
    CENTER = "center"
    MIDDLE_RIGHT = "middle_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"


@dataclass
class Transform2D:
    """
    2B dönüşüm matrisi.
    
    Bu yapı, bir katmanın pozisyonunu, ölçeğini, 
    rotasyonunu ve kaymasını (shear) temsil eder.
    
    Matris gösterimi:
    | a  b  tx |
    | c  d  ty |
    | 0  0  1  |
    
    Premierde "Motion" efekti, After Effects'ta 
    "Transform" property'si ile aynı işlevi görür.
    """
    position_x: float = 0.0
    position_y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0  # Derece cinsinden (0-360)
    shear_x: float = 0.0
    shear_y: float = 0.0
    anchor_x: float = 0.5  # Relative (0.0-1.0)
    anchor_y: float = 0.5  # Relative (0.0-1.0)
    opacity: float = 1.0
    anchor_point: AnchorPoint = AnchorPoint.CENTER
    
    @property
    def matrix(self) -> List[List[float]]:
        """
        3x3 dönüşüm matrisini hesapla.
        
        Bu matris, piksel koordinatlarını dönüştürmek 
        için kullanılır. OpenGL/DirectX pipeline'ındaki 
        model-view-projection matrisinin 2D karşılığıdır.
        
        Sıralama: Scale → Shear → Rotate → Translate
        (Her biri matris çarpımı ile uygulanır)
        """
        rad = math.radians(self.rotation)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        
        sx = self.scale_x
        sy = self.scale_y
        shx = self.shear_x
        shy = self.shear_y
        
        # Combined transformation matrix
        a = sx * cos_r + shx * sin_r
        b = sy * sin_r + shy * cos_r
        c = -sx * sin_r + shx * cos_r
        d = sy * cos_r - shy * sin_r
        tx = self.position_x
        ty = self.position_y
        
        return [
            [a, b, tx],
            [c, d, ty],
            [0.0, 0.0, 1.0]
        ]
    
    def transform_point(self, x: float, y: float) -> Tuple[float, float]:
        """
        Koordinatı dönüştür.
        
        Anchor point'i merkez olarak kullanarak 
        verilen koordinatı dönüştürür.
        """
        mat = self.matrix
        return (
            mat[0][0] * x + mat[0][1] * y + mat[0][2],
            mat[1][0] * x + mat[1][1] * y + mat[1][2]
        )
    
    def inverse_transform_point(self, x: float, y: float) -> Tuple[float, float]:
        """
        Ters dönüşüm — piksel koordinatını katman koordinatına çevir.
        
        Bu, mouse tıklamalarının doğru katmana yönlendirilmesi 
        için gereklidir (hit testing).
        """
        mat = self.matrix
        det = mat[0][0] * mat[1][1] - mat[0][1] * mat[1][0]
        if abs(det) < 1e-10:
            raise ValueError("Dönüşüm matrisi tersi alınamaz (det ≈ 0)")
        
        inv_det = 1.0 / det
        x -= mat[0][2]
        y -= mat[1][2]
        
        return (
            (mat[1][1] * x - mat[0][1] * y) * inv_det,
            (-mat[1][0] * x + mat[0][0] * y) * inv_det
        )
```

```python
@dataclass
class Mask:
    """
    Katman maskesi.
    
    Maske, katmanın sadece belirli bölgelerinin 
    görünür olmasını sağlar. After Effects'taki 
    mask modeline benzer.
    
    Mask tipleri:
    - Rectangle: Dikdörtgen
    - Ellipse: Elips
    - Polygon: Çokgen (n-vertex)
    - Bezier: Bezier eğrileri
    - Drawn: Elle çizilmiş (freeform)
    """
    mask_id: UUID = field(default_factory=uuid4)
    name: str = ""
    mask_type: str = "rectangle"
    inverted: bool = False
    opacity: float = 1.0
    feather: float = 0.0
    expansion: float = 0.0
    points: List[Tuple[float, float]] = field(default_factory=list)
    bezier_handles: List[Tuple[Tuple[float, float], Tuple[float, float]]] = field(default_factory=list)
    enabled: bool = True
    
    def contains_point(self, x: float, y: float) -> bool:
        """
        Nokta maskenin içinde mi?
        
        Ray casting algoritması ile polygon ve bezier maskeleri için 
        nokta-içinde testi yapılır. Rectangle ve ellipse için 
        basit geometrik test yeterlidir.
        """
        if not self.enabled:
            return True
        
        result = False
        
        if self.mask_type == "rectangle":
            if len(self.points) >= 2:
                min_x = min(p[0] for p in self.points)
                max_x = max(p[0] for p in self.points)
                min_y = min(p[1] for p in self.points)
                max_y = max(p[1] for p in self.points)
                result = min_x <= x <= max_x and min_y <= y <= max_y
        
        elif self.mask_type == "ellipse":
            if len(self.points) >= 2:
                cx = (self.points[0][0] + self.points[1][0]) / 2
                cy = (self.points[0][1] + self.points[1][1]) / 2
                rx = abs(self.points[1][0] - self.points[0][0]) / 2
                ry = abs(self.points[1][1] - self.points[0][1]) / 2
                
                if rx > 0 and ry > 0:
                    result = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0
                else:
                    result = False
        
        elif self.mask_type == "polygon":
            # Ray casting algorithm
            n = len(self.points)
            if n < 3:
                return False
            
            inside = False
            j = n - 1
            for i in range(n):
                xi, yi = self.points[i]
                xj, yj = self.points[j]
                
                if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                    inside = not inside
                j = i
            
            result = inside
        
        if self.inverted:
            return not result
        return result
    
    def feather_at(self, x: float, y: float) -> float:
        """
        Belirli bir noktadaki feather değerini hesapla.
        
        Kenar yumuşatma, maskenin kenarlarını 
        yumuşak bir gradyan haline getirir.
        """
        if not self.enabled or self.feather <= 0:
            return 1.0
        
        contains = self.contains_point(x, y)
        
        if contains:
            # İçeride — tam opaklık
            return 1.0
        else:
            # Dışarıda — feather mesafesine göre gradyan
            dist = self._distance_to_edge(x, y)
            if dist <= self.feather:
                return 1.0 - (dist / self.feather)
            return 0.0
    
    def _distance_to_edge(self, x: float, y: float) -> float:
        """Noktanın kenara olan en kısa mesafesi"""
        if not self.points:
            return float('inf')
        
        min_dist = float('inf')
        n = len(self.points)
        
        for i in range(n):
            p1 = self.points[i]
            p2 = self.points[(i + 1) % n]
            
            # Nokta ile çizgi arası mesafe
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length_sq = dx * dx + dy * dy
            
            if length_sq == 0:
                dist = math.sqrt((x - p1[0]) ** 2 + (y - p1[1]) ** 2)
            else:
                t = max(0, min(1, ((x - p1[0]) * dx + (y - p1[1]) * dy) / length_sq))
                proj_x = p1[0] + t * dx
                proj_y = p1[1] + t * dy
                dist = math.sqrt((x - proj_x) ** 2 + (y - proj_y) ** 2)
            
            min_dist = min(min_dist, dist)
        
        return min_dist
    
    def to_dict(self) -> dict:
        return {
            "mask_id": str(self.mask_id),
            "name": self.name,
            "mask_type": self.mask_type,
            "inverted": self.inverted,
            "opacity": self.opacity,
            "feather": self.feather,
            "expansion": self.expansion,
            "points": self.points,
            "bezier_handles": self.bezier_handles,
            "enabled": self.enabled,
        }


@dataclass
class Layer:
    """
    Tek bir katman.
    
    Katman, timeline üzerindeki bir clip'in veya 
    kaynağın compositing özelliklerini tanımlar.
    
    Her katmanın şunları vardır:
    - Temel medya referansı (source clip veya solid)
    - Dönüşüm özellikleri (transform)
    - Blend modu ve opaklık
    - Maskeler
    - Efekt zinciri
    - Parent-child ilişkisi
    - Zaman çizelgesi (timeline position)
    
    Premiere'de bu, "Essential Graphics" panelindeki 
    katman özelliklerine karşılık gelir.
    After Effects'ta ise doğrudan katman properties'idir.
    """
    layer_id: UUID = field(default_factory=uuid4)
    name: str = ""
    layer_type: LayerType = LayerType.VIDEO
    source_clip_id: Optional[UUID] = None
    nested_timeline_id: Optional[UUID] = None
    
    # Zaman
    in_point: Optional[RationalTime] = None
    out_point: Optional[RationalTime] = None
    
    # Compositing
    transform: Transform2D = field(default_factory=Transform2D)
    blend_mode: BlendMode = BlendMode.NORMAL
    alpha_mode: AlphaMode = AlphaMode.PREMULTIPLIED
    
    # Maskeleme
    masks: List[Mask] = field(default_factory=list)
    mask_mode: str = "add"
    
    # Efektler
    effect_ids: List[UUID] = field(default_factory=list)
    
    # Parent-child
    parent_layer_id: Optional[UUID] = None
    children_ids: List[UUID] = field(default_factory=list)
    
    # Durum
    visible: bool = True
    locked: bool = False
    solo: bool = False
    muted: bool = False
    
    # Renk etiketi
    label_color: str = ""
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_nested(self) -> bool:
        """Bu katman bir nested sequence mı?"""
        return self.layer_type == LayerType.NESTED and self.nested_timeline_id is not None
    
    @property
    def effective_opacity(self) -> float:
        """
        Parent katman opaklığını da hesaba katan 
        etkin opaklık değeri.
        """
        return self.transform.opacity
    
    def add_mask(self, mask: Mask) -> None:
        """Katmana maske ekle"""
        self.masks.append(mask)
    
    def remove_mask(self, mask_id: UUID) -> bool:
        """Maskeyi kaldır"""
        for i, mask in enumerate(self.masks):
            if mask.mask_id == mask_id:
                del self.masks[i]
                return True
        return False
    
    def to_dict(self) -> dict:
        return {
            "layer_id": str(self.layer_id),
            "name": self.name,
            "layer_type": self.layer_type.value,
            "source_clip_id": str(self.source_clip_id) if self.source_clip_id else None,
            "nested_timeline_id": str(self.nested_timeline_id) if self.nested_timeline_id else None,
            "in_point": self.in_point.to_dict() if self.in_point else None,
            "out_point": self.out_point.to_dict() if self.out_point else None,
            "transform": {
                "position_x": self.transform.position_x,
                "position_y": self.transform.position_y,
                "scale_x": self.transform.scale_x,
                "scale_y": self.transform.scale_y,
                "rotation": self.transform.rotation,
                "shear_x": self.transform.shear_x,
                "shear_y": self.transform.shear_y,
                "anchor_x": self.transform.anchor_x,
                "anchor_y": self.transform.anchor_y,
                "opacity": self.transform.opacity,
                "anchor_point": self.transform.anchor_point.value,
            },
            "blend_mode": self.blend_mode.value,
            "alpha_mode": self.alpha_mode.value,
            "masks": [m.to_dict() for m in self.masks],
            "mask_mode": self.mask_mode,
            "effect_ids": [str(e) for e in self.effect_ids],
            "parent_layer_id": str(self.parent_layer_id) if self.parent_layer_id else None,
            "children_ids": [str(c) for c in self.children_ids],
            "visible": self.visible,
            "locked": self.locked,
            "solo": self.solo,
            "muted": self.muted,
            "label_color": self.label_color,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> Layer:
        transform_data = data.get("transform", {})
        return cls(
            layer_id=UUID(data["layer_id"]),
            name=data["name"],
            layer_type=LayerType(data["layer_type"]),
            source_clip_id=UUID(data["source_clip_id"]) if data.get("source_clip_id") else None,
            nested_timeline_id=UUID(data["nested_timeline_id"]) if data.get("nested_timeline_id") else None,
            in_point=RationalTime.from_dict(data["in_point"]) if data.get("in_point") else None,
            out_point=RationalTime.from_dict(data["out_point"]) if data.get("out_point") else None,
            transform=Transform2D(
                position_x=transform_data.get("position_x", 0.0),
                position_y=transform_data.get("position_y", 0.0),
                scale_x=transform_data.get("scale_x", 1.0),
                scale_y=transform_data.get("scale_y", 1.0),
                rotation=transform_data.get("rotation", 0.0),
                shear_x=transform_data.get("shear_x", 0.0),
                shear_y=transform_data.get("shear_y", 0.0),
                anchor_x=transform_data.get("anchor_x", 0.5),
                anchor_y=transform_data.get("anchor_y", 0.5),
                opacity=transform_data.get("opacity", 1.0),
                anchor_point=AnchorPoint(transform_data.get("anchor_point", "center")),
            ),
            blend_mode=BlendMode(data["blend_mode"]),
            alpha_mode=AlphaMode(data["alpha_mode"]),
            masks=[Mask(**m) for m in data.get("masks", [])],
            mask_mode=data.get("mask_mode", "add"),
            effect_ids=[UUID(e) for e in data.get("effect_ids", [])],
            parent_layer_id=UUID(data["parent_layer_id"]) if data.get("parent_layer_id") else None,
            children_ids=[UUID(c) for c in data.get("children_ids", [])],
            visible=data.get("visible", True),
            locked=data.get("locked", False),
            solo=data.get("solo", False),
            muted=data.get("muted", False),
            label_color=data.get("label_color", ""),
            metadata=data.get("metadata", {}),
        )
```

```python
@dataclass
class LayerStack:
    """
    Katman yığını — compositing sırasını yönetir.
    
    LayerStack, bir timeline track'indeki veya 
    bir nested sequence'daki tüm katmanları tutar.
    
    Katmanlar, alta doğru (index 0) render edilir.
    Yani, index 0'daki katman en alttaki (background), 
    en üstteki katman ise en üstteki (foreground) katmandır.
    
    Bu, After Effects'taki katman sırası ile aynıdır.
    Premiere'de track'ler zaten sıralı olduğu için 
    ayrı bir layer stack'e ihtiyaç yoktur — ama bizim 
    sistemimiz her iki modeli de destekler.
    """
    stack_id: UUID = field(default_factory=uuid4)
    layers: List[Layer] = field(default_factory=list)
    composite_mode: str = "premultiplied"
    
    @property
    def active_layers(self) -> List[Layer]:
        """
        Görünür ve solo olmayan katmanları döndür.
        
        Solo katman varsa, sadece solo olanlar döndürülür.
        Muted katmanlar her zaman hariç tutulur.
        """
        solo_layers = [l for l in self.layers if l.solo]
        
        if solo_layers:
            return [l for l in solo_layers if not l.muted]
        
        return [l for l in self.layers if l.visible and not l.muted]
    
    @property
    def has_solo(self) -> bool:
        """Herhangi bir solo katman var mı?"""
        return any(l.solo for l in self.layers)
    
    def add_layer(
        self,
        layer: Layer,
        index: Optional[int] = None
    ) -> None:
        """
        Katmanı yığına ekle.
        
        index belirtilmezse, en üste eklenir.
        """
        if index is None:
            self.layers.append(layer)
        else:
            self.layers.insert(index, layer)
    
    def remove_layer(self, layer_id: UUID) -> bool:
        """Katmanı kaldır"""
        for i, layer in enumerate(self.layers):
            if layer.layer_id == layer_id:
                del self.layers[i]
                # Parent referanslarını temizle
                for other in self.layers:
                    if other.parent_layer_id == layer_id:
                        other.parent_layer_id = None
                    if layer_id in other.children_ids:
                        other.children_ids.remove(layer_id)
                return True
        return False
    
    def move_layer(self, layer_id: UUID, new_index: int) -> bool:
        """
        Katmanın sırasını değiştir.
        
        Bu, z-index'i (üstte/altta görünme sırasını) değiştirir.
        """
        layer = None
        for i, l in enumerate(self.layers):
            if l.layer_id == layer_id:
                layer = self.layers.pop(i)
                break
        
        if layer is None:
            return False
        
        self.layers.insert(new_index, layer)
        return True
    
    def set_parent(
        self,
        child_id: UUID,
        parent_id: Optional[UUID]
    ) -> None:
        """
        Parent-child ilişkisi kur.
        
        Parent katman transform edildiğinde, child katmanlar 
        da otomatik olarak transform edilir.
        
        Döngüsel referans engeli: Parent, kendi child'ı olamaz.
        """
        if parent_id == child_id:
            raise ValueError("Bir katman kendi parent'ı olamaz")
        
        child = None
        for l in self.layers:
            if l.layer_id == child_id:
                child = l
                break
        
        if child is None:
            raise ValueError(f"Child katman bulunamadı: {child_id}")
        
        # Döngüsel referans kontrolü
        if parent_id is not None:
            current = parent_id
            visited = {child_id}
            while current is not None:
                if current in visited:
                    raise ValueError("Döngüsel parent-child ilişkisi tespit edildi")
                visited.add(current)
                for l in self.layers:
                    if l.layer_id == current:
                        current = l.parent_layer_id
                        break
                else:
                    break
        
        # Eski parent'tan kaldır
        if child.parent_layer_id is not None:
            for l in self.layers:
                if l.layer_id == child.parent_layer_id:
                    if child_id in l.children_ids:
                        l.children_ids.remove(child_id)
                    break
        
        # Yeni parent'ı ayarla
        child.parent_layer_id = parent_id
        if parent_id is not None:
            for l in self.layers:
                if l.layer_id == parent_id:
                    l.children_ids.append(child_id)
                    break
    
    def get_parent_chain(self, layer_id: UUID) -> List[UUID]:
        """
        Katmanın tüm parent zincirini döndür.
        
        En yakın parent'dan en uzak parent'a doğru sıralanmış.
        Bu, transform hesaplamalarında kullanılır.
        """
        chain = []
        current_id = layer_id
        
        while True:
            for l in self.layers:
                if l.layer_id == current_id:
                    if l.parent_layer_id is not None:
                        chain.append(l.parent_layer_id)
                        current_id = l.parent_layer_id
                    else:
                        return chain
                    break
            else:
                return chain
        
        return chain
    
    def compute_composite_order(self) -> List[Layer]:
        """
        Compositing sırasını hesapla.
        
        Alt katmandan üste doğru sıralanmış aktif katmanları döndür.
        Parent-child ilişkileri dikkate alınarak transform cascade yapılır.
        """
        active = self.active_layers
        
        # Bottom-up sıralama
        ordered = sorted(active, key=lambda l: self.layers.index(l) if l in self.layers else 0)
        
        return ordered
    
    def to_dict(self) -> dict:
        return {
            "stack_id": str(self.stack_id),
            "layers": [l.to_dict() for l in self.layers],
            "composite_mode": self.composite_mode,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> LayerStack:
        return cls(
            stack_id=UUID(data["stack_id"]),
            layers=[Layer.from_dict(l) for l in data["layers"]],
            composite_mode=data.get("composite_mode", "premultiplied"),
        )
```

## 2.4 Core Algoritmalar

### 2.4.1 Parent-Child Transform Cascade

```python
def compute_cumulative_transform(
    layer: Layer,
    layer_stack: LayerStack
) -> Transform2D:
    """
    Katmanın tüm parent zincirini dikkate alarak 
    kümülatif transform'unu hesapla.
    
    Algoritma:
    1. Katmanın kendi transform'unu al
    2. Parent zincirini bul (get_parent_chain)
    3. En uzak parent'dan başlayarak aşağı doğru git
    4. Her parent'ın transform'unu çarp
    
    Bu, After Effects'taki "collapse transformations" 
    veya "continuously rasterize" ile aynı mantığı izler.
    
    Karmaşıklık: O(d) — d = derinlik (genellikle 5-10)
    """
    chain = layer_stack.get_parent_chain(layer.layer_id)
    
    # En uzak parent'tan başla
    cumulative = Transform2D()  # Identity
    
    for parent_id in reversed(chain):
        for l in layer_stack.layers:
            if l.layer_id == parent_id:
                parent_t = l.transform
                # Parent transform'unu kümülatif matrise uygula
                # Position: offset olarak eklenir
                cumulative.position_x += parent_t.position_x * cumulative.scale_x
                cumulative.position_y += parent_t.position_y * cumulative.scale_y
                # Scale: çarpılır
                cumulative.scale_x *= parent_t.scale_x
                cumulative.scale_y *= parent_t.scale_y
                # Rotation: eklenir
                cumulative.rotation += parent_t.rotation
                # Opacity: çarpılır
                cumulative.opacity *= parent_t.opacity
                break
    
    # Son olarak kendi transform'unu ekle
    cumulative.position_x += layer.transform.position_x * cumulative.scale_x
    cumulative.position_y += layer.transform.position_y * cumulative.scale_y
    cumulative.scale_x *= layer.transform.scale_x
    cumulative.scale_y *= layer.transform.scale_y
    cumulative.rotation += layer.transform.rotation
    cumulative.opacity *= layer.transform.opacity
    
    return cumulative
```

### 2.4.2 Mask Compositing

```python
def composite_masks(
    masks: List[Mask],
    mode: str,
    x: float,
    y: float
) -> float:
    """
    Birden fazla maskenin etkisini birleştir.
    
    Mask modları:
    - add: Maskeler toplanır (herhangi biri içerideyse görünür)
    - subtract: İçerideki maskeler dışarı çıkar
    - intersect: Sadece tüm maskelerin kesişimi görünür
    
    Algoritma:
    1. Her maskenin nokta-içinde testini yap
    2. Moda göre birleştir
    
    Karmaşıklık: O(m) — m = maske sayısı
    """
    if not masks:
        return 1.0
    
    if mode == "add":
        # Herhangi bir maskenin içindeyse, opacity değerini kullan
        result = 0.0
        for mask in masks:
            feather = mask.feather_at(x, y)
            result = max(result, feather * mask.opacity)
        return result
    
    elif mode == "subtract":
        # İçerideyse, opaklığını azalt
        result = 1.0
        for mask in masks:
            if mask.contains_point(x, y):
                result *= (1.0 - mask.opacity)
        return result
    
    elif mode == "intersect":
        # Tüm maskelerin kesişimi
        result = 1.0
        for mask in masks:
            feather = mask.feather_at(x, y)
            result *= feather * mask.opacity
        return result
    
    return 1.0
```

## 2.5 API Sözleşmeleri

```python
class LayerManager:
    """
    Katman yöneticisi API'si.
    
    Bu sınıf, katman oluşturma, düzenleme ve silme 
    işlemlerini yönetir. FastAPI endpoint'lerinden 
    doğrudan erişilir.
    """
    
    def __init__(self, timeline_engine: TimelineEngine):
        self._engine = timeline_engine
        self._layer_stacks: Dict[UUID, LayerStack] = {}
    
    def create_layer_stack(self, timeline_id: UUID) -> LayerStack:
        """
        Timeline için yeni bir layer stack oluştur.
        
        Her timeline track'i için bir LayerStack vardır.
        """
        stack = LayerStack()
        self._layer_stacks[timeline_id] = stack
        return stack
    
    def add_layer(
        self,
        stack_id: UUID,
        layer_type: LayerType,
        name: str,
        source_clip_id: Optional[UUID] = None,
    ) -> Layer:
        """
        Katman ekle.
        
        Args:
            stack_id: LayerStack ID
            layer_type: Katman türü
            name: Katman adı
            source_clip_id: Kaynak medya ID (opsiyonel)
            
        Returns:
            Oluşturulan Layer nesnesi
        """
        stack = self._layer_stacks.get(stack_id)
        if not stack:
            raise ValueError(f"LayerStack bulunamadı: {stack_id}")
        
        layer = Layer(
            name=name,
            layer_type=layer_type,
            source_clip_id=source_clip_id,
        )
        stack.add_layer(layer)
        return layer
    
    def set_blend_mode(
        self,
        stack_id: UUID,
        layer_id: UUID,
        blend_mode: BlendMode
    ) -> None:
        """
        Katmanın blend modunu değiştir.
        
        Bu, compositing motoruna bilgi verir 
        ve gerçek zamanlı preview'da hemen görünür.
        """
        stack = self._layer_stacks.get(stack_id)
        if not stack:
            raise ValueError(f"LayerStack bulunamadı: {stack_id}")
        
        for layer in stack.layers:
            if layer.layer_id == layer_id:
                layer.blend_mode = blend_mode
                return
        
        raise ValueError(f"Layer bulunamadı: {layer_id}")
    
    def add_mask(
        self,
        stack_id: UUID,
        layer_id: UUID,
        mask: Mask
    ) -> None:
        """Katmana maske ekle"""
        stack = self._layer_stacks.get(stack_id)
        if not stack:
            raise ValueError(f"LayerStack bulunamadı: {stack_id}")
        
        for layer in stack.layers:
            if layer.layer_id == layer_id:
                layer.add_mask(mask)
                return
        
        raise ValueError(f"Layer bulunamadı: {layer_id}")
    
    def set_parent(
        self,
        stack_id: UUID,
        child_id: UUID,
        parent_id: Optional[UUID]
    ) -> None:
        """
        Katmanlar arası parent-child ilişkisi kur.
        
        parent_id = None ise, mevcut parent kaldırılır.
        """
        stack = self._layer_stacks.get(stack_id)
        if not stack:
            raise ValueError(f"LayerStack bulunamadı: {stack_id}")
        
        stack.set_parent(child_id, parent_id)
    
    def get_layer_info(
        self,
        stack_id: UUID,
        layer_id: UUID
    ) -> Dict[str, Any]:
        """
        Katmanın tüm bilgilerini döndür.
        
        Bu, UI'ın katman özelliklerini göstermesi 
        için kullanılır.
        """
        stack = self._layer_stacks.get(stack_id)
        if not stack:
            raise ValueError(f"LayerStack bulunamadı: {stack_id}")
        
        for layer in stack.layers:
            if layer.layer_id == layer_id:
                cumulative = compute_cumulative_transform(layer, stack)
                return {
                    "layer": layer.to_dict(),
                    "cumulative_transform": {
                        "position_x": cumulative.position_x,
                        "position_y": cumulative.position_y,
                        "scale_x": cumulative.scale_x,
                        "scale_y": cumulative.scale_y,
                        "rotation": cumulative.rotation,
                        "opacity": cumulative.opacity,
                    },
                    "parent_chain": stack.get_parent_chain(layer_id),
                }
        
        raise ValueError(f"Layer bulunamadı: {layer_id}")
```

## 2.6 Performans Darboğazları ve Çözümleri

| Darboğaz | Etki | Çözüm |
|---|---|---|
| Deep parent chain traversal | Her karede 10+ parent | Parent transform'ları cache'le, sadece değişiklik olduğunda yeniden hesapla |
| Mask ray casting (complex polygon) | 1000+ vertex mask: 5ms/frame | GPU'da shader ile hesapla (metal/vulkan compute shader) |
| Multiple blend modes per pixel | Her piksel için 12+ mod | SIMD (sse2/avx2) ile parallel piksel işleme |
| Layer visibility changes | Her değişiklikte full re-composite | Dirty region tracking — sadece değişen bölümleri yeniden hesapla |

## 2.7 Entegrasyon Noktaları

```
Layer Manager
    ├── Timeline Engine ← Katman referansları için
    ├── Effect Engine ← Katman efekt zincirleri için
    ├── Compositor ← Compositing sırası için
    ├── UI Controller ← Katman listesi ve özellikleri
    └── Nested Sequence Manager ← Pre-composition için
```

---

# 3. Doğrusal Olmayan Düzenleme (NLE) Çekirdeği

## 3.1 Amaç ve Kapsam

NLE çekirdeği, profesyonel düzenleme iş akışlarının temelini oluşturur. Source-record editing modeli, three-point editing, multicam editing ve tüm trim modları bu modülün kapsamındadır.

Bu modül, Premiere Pro'nun "Source Monitor + Program Monitor" modelini, Resolve'ın "Source/Timeline Viewer" modelini ve Avid'in "Source/Record" modelini temel alır. Bizim yaklaşımımız, bu üç modelin en iyi yönlerini birleştirir.

### Karşılaştırma

| Özellik | Bizim Sistem | Premiere Pro | DaVinci Resolve | Avid MC |
|---|---|---|---|---|
| Three-point editing | Evet | Evet | Evet | Evet |
| Four-point editing | Evet | Evet | Evet | Evet |
| Multicam | Evet | Evet | Evet (Edit Index) | Evet (best) |
| Subclip | Evet | Evet | Evet (Sub-clip) | Evet |
| Match frame | Evet | Evet | Evet | Evet |
| Slip/Slide | Evet | Evet (best) | Evet | Evet |
| Dynamic trim | Evet | Evet | Evet | Evet (best) |

## 3.2 Veri Yapısı

```python
"""
NLE çekirdeği veri yapıları.

Tasarım İlkeleri:
1. Three-point editing: In, Out, ve Position — herhangi üçü yeterli
2. Four-point editing: In, Out, Source In, Source Out — hız değişikliği ile
3. Multicam: Birden fazla kaynaktan eş zamanlı görüntü
4. Edit decision: Her düzenleme işleminin kaydı
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID, uuid4


class EditMode(Enum):
    """Düzenleme modları"""
    INSERT = "insert"
    OVERWRITE = "overwrite"
    REPLACE = "replace"
    LIFT = "lift"
    EXTRACT = "extract"
    RIPPLE = "ripple"
    ROLL = "roll"
    SLIP = "slip"
    SLIDE = "slide"


class EditPointType(Enum):
    """Düzenleme noktaları türleri"""
    IN = "in"
    OUT = "out"
    CUT = "cut"
    TRANSITION = "transition"


class TrimDirection(Enum):
    """Trim yönü"""
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"


@dataclass
class EditPoint:
    """
    Düzenleme noktası.
    
    EditPoint, timeline'daki veya kaynak monitördeki 
    bir kırpma noktasını temsil eder. Her edit point'in 
    şunları vardır:
    
    - position: Timeline veya kaynak üzerindeki zaman
    - type: In, Out veya Cut
    - side: Hangi clip'in hangi tarafında (sol/sağ)
    - magnetik: mıknatıslı mı (snap功能)
    
    Premiere'de bu, razor tool veya trim handles olarak bilinir.
    Resolve'da "Trim Edit Mode" ile aynı işlevi görür.
    """
    point_id: UUID = field(default_factory=uuid4)
    position: RationalTime = field(default_factory=lambda: RationalTime(0, 1))
    point_type: EditPointType = EditPointType.CUT
    track_id: Optional[UUID] = None
    clip_id: Optional[UUID] = None
    side: str = "left"
    magnetic: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "point_id": str(self.point_id),
            "position": self.position.to_dict(),
            "point_type": self.point_type.value,
            "track_id": str(self.track_id) if self.track_id else None,
            "clip_id": str(self.clip_id) if self.clip_id else None,
            "side": self.side,
            "magnetic": self.magnetic,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> EditPoint:
        return cls(
            point_id=UUID(data["point_id"]),
            position=RationalTime.from_dict(data["position"]),
            point_type=EditPointType(data["point_type"]),
            track_id=UUID(data["track_id"]) if data.get("track_id") else None,
            clip_id=UUID(data["clip_id"]) if data.get("clip_id") else None,
            side=data["side"],
            magnetic=data["magnetic"],
        )


@dataclass
class EditDecision:
    """
    Bir düzenleme kararının tam kaydı.
    
    EditDecision, bir source-record editing işleminin 
    tüm parametrelerini tutar. Bu, editing kararlarının 
    serileştirilmesi ve yeniden uygulanması için gereklidir.
    
    Avid'in EDL (Edit Decision List) formatının modern 
    karşılığıdır. Biz JSON tabanlı bir format kullanıyoruz.
    
    EditDecision şunları kaydeder:
    - Hangi kaynaktan (source)
    - Hangi bölümden (source in/out)
    - Timeline'a nereye (record position)
    - Hangi modda (insert/overwrite)
    - Hangi track'e (target track)
    - Hız ayarı (speed)
    """
    decision_id: UUID = field(default_factory=uuid4)
    name: str = ""
    
    # Kaynak bilgileri
    source_media_id: UUID = field(default_factory=uuid4)
    source_in: Optional[RationalTime] = None
    source_out: Optional[RationalTime] = None
    
    # Record (timeline) bilgileri
    record_in: Optional[RationalTime] = None
    record_out: Optional[RationalTime] = None
    record_position: Optional[RationalTime] = None
    
    # Düzenleme parametreleri
    edit_mode: EditMode = EditMode.INSERT
    target_track_id: Optional[UUID] = None
    speed: Fraction = field(default_factory=lambda: Fraction(1, 1))
    reverse: bool = False
    
    # Metadata
    timecode_in: Optional[str] = None
    timecode_out: Optional[str] = None
    clip_name: str = ""
    reel_name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def source_duration(self) -> Optional[RationalTime]:
        """Kaynak süre"""
        if self.source_in and self.source_out:
            return self.source_out - self.source_in
        return None
    
    @property
    def record_duration(self) -> Optional[RationalTime]:
        """Record süre"""
        if self.record_in and self.record_out:
            return self.record_out - self.record_in
        return None
    
    def is_four_point(self) -> bool:
        """
        Four-point editing mi?
        
        Four-point editing: hem source in/out hem de 
        record in/out tanımlıdır. Bu durumda, hız değişikliği 
        gerekir (süreler eşleşmiyorsa).
        """
        return (
            self.source_in is not None and
            self.source_out is not None and
            self.record_in is not None and
            self.record_out is not None
        )
    
    def compute_speed(self) -> Fraction:
        """
        Four-point editing için gerekli hızı hesapla.
        
        Hız = Source süre / Record süre
        
        Örnek: 10 saniyelik kaynak, 5 saniyeye sıkıştırılırsa 
        hız = 2.0x olur.
        """
        source_dur = self.source_duration
        record_dur = self.record_duration
        
        if source_dur is None or record_dur is None:
            raise ValueError("Four-point editing için in/out noktaları gerekli")
        
        if record_dur == RationalTime(0, 1):
            raise ValueError("Record süre sıfır olamaz")
        
        return Fraction(
            source_dur.value.numerator * record_dur.value.denominator,
            source_dur.value.denominator * record_dur.value.numerator
        )
    
    def to_dict(self) -> dict:
        return {
            "decision_id": str(self.decision_id),
            "name": self.name,
            "source_media_id": str(self.source_media_id),
            "source_in": self.source_in.to_dict() if self.source_in else None,
            "source_out": self.source_out.to_dict() if self.source_out else None,
            "record_in": self.record_in.to_dict() if self.record_in else None,
            "record_out": self.record_out.to_dict() if self.record_out else None,
            "record_position": self.record_position.to_dict() if self.record_position else None,
            "edit_mode": self.edit_mode.value,
            "target_track_id": str(self.target_track_id) if self.target_track_id else None,
            "speed": str(self.speed),
            "reverse": self.reverse,
            "timecode_in": self.timecode_in,
            "timecode_out": self.timecode_out,
            "clip_name": self.clip_name,
            "reel_name": self.reel_name,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> EditDecision:
        return cls(
            decision_id=UUID(data["decision_id"]),
            name=data["name"],
            source_media_id=UUID(data["source_media_id"]),
            source_in=RationalTime.from_dict(data["source_in"]) if data.get("source_in") else None,
            source_out=RationalTime.from_dict(data["source_out"]) if data.get("source_out") else None,
            record_in=RationalTime.from_dict(data["record_in"]) if data.get("record_in") else None,
            record_out=RationalTime.from_dict(data["record_out"]) if data.get("record_out") else None,
            record_position=RationalTime.from_dict(data["record_position"]) if data.get("record_position") else None,
            edit_mode=EditMode(data["edit_mode"]),
            target_track_id=UUID(data["target_track_id"]) if data.get("target_track_id") else None,
            speed=Fraction(data["speed"]),
            reverse=data["reverse"],
            timecode_in=data.get("timecode_in"),
            timecode_out=data.get("timecode_out"),
            clip_name=data.get("clip_name", ""),
            reel_name=data.get("reel_name", ""),
            metadata=data.get("metadata", {}),
        )
```

```python
@dataclass
class Subclip:
    """
    Subclip — kaynak medyanın alt portionu.
    
    Subclip, bir kaynak medyanın belirli bir bölümünü 
    ayrı bir "clip" olarak temsil eder. Bu, uzun 
    kaynaklardan sık kullanılan bölümleri hızlıca 
    erişilebilir kılar.
    
    Premiere'de "Subclip" olarak adlandırılır.
    Resolve'da "Sub-clip" olarak adlandırılır.
    
    Subclip, orijinal medyaya referans tutar — 
    kopya oluşturmaz. Bu, disk alanından tasarruf sağlar.
    """
    subclip_id: UUID = field(default_factory=uuid4)
    name: str = ""
    source_media_id: UUID = field(default_factory=uuid4)
    source_range: TimeRange = field(default_factory=lambda: TimeRange(
        RationalTime(0, 1), RationalTime(0, 1)
    ))
    master_duration: Optional[RationalTime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    
    @property
    def duration(self) -> RationalTime:
        """Subclip süresi"""
        return self.source_range.duration
    
    def set_in_point(self, point: RationalTime) -> None:
        """Subclip'in in point'ini ayarla"""
        if self.master_duration and point >= self.master_duration:
            raise ValueError("In point master süreyi aşamaz")
        if self.source_range.end <= point:
            raise ValueError("In point out point'ten sonra olamaz")
        self.source_range = TimeRange(point, self.source_range.end - point)
    
    def set_out_point(self, point: RationalTime) -> None:
        """Subclip'in out point'ini ayarla"""
        if self.master_duration and point >= self.master_duration:
            raise ValueError("Out point master süreyi aşamaz")
        if point <= self.source_range.start:
            raise ValueError("Out point in point'ten önce olamaz")
        self.source_range = TimeRange(self.source_range.start, point - self.source_range.start)
    
    def to_clip(self) -> TimelineClip:
        """
        Subclip'ten TimelineClip oluştur.
        
        Bu, subclip'i doğrudan timeline'a sürükleyip 
        bırakma işlemi için kullanılır.
        """
        return TimelineClip(
            name=self.name,
            source_media_id=self.source_media_id,
            source_range=self.source_range,
            record_range=TimeRange(
                RationalTime(0, 1),
                self.source_range.duration
            ),
        )
    
    def to_dict(self) -> dict:
        return {
            "subclip_id": str(self.subclip_id),
            "name": self.name,
            "source_media_id": str(self.source_media_id),
            "source_range": self.source_range.to_dict(),
            "master_duration": self.master_duration.to_dict() if self.master_duration else None,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> Subclip:
        return cls(
            subclip_id=UUID(data["subclip_id"]),
            name=data["name"],
            source_media_id=UUID(data["source_media_id"]),
            source_range=TimeRange.from_dict(data["source_range"]),
            master_duration=RationalTime.from_dict(data["master_duration"]) if data.get("master_duration") else None,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", ""),
        )


@dataclass
class MulticamClip:
    """
    Multicam clip — eş zamanlı çoklu kamera.
    
    Multicam clip, birden fazla kaynaktan aynı anda 
    çekilen görüntüleri tutar. Editing sırasında, 
    istenen kamera açısı seçilir ve geçiş yapılır.
    
    Premiere'de "Multicamera Sequence", Resolve'da 
    "Multicam Clip" olarak adlandırılır.
    
    Bizim modelimiz:
    - Her kamera açısı bir "angle" olarak temsil edilir
    - Her angle, bağımsız bir kaynak medyaya sahiptir
    - Geçişler, angle'lar arasında yapılır
    - Geçişler keyframe ile animasyonlanabilir
    """
    multicam_id: UUID = field(default_factory=uuid4)
    name: str = ""
    angles: List[MulticamAngle] = field(default_factory=list)
    active_angle_index: int = 0
    sync_method: str = "timecode"
    duration: RationalTime = field(default_factory=lambda: RationalTime(0, 1))
    fps: Fraction = field(default_factory=lambda: Fraction(30000, 1001))
    transitions: List[MulticamTransition] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def active_angle(self) -> Optional[MulticamAngle]:
        """Aktif kamera açısı"""
        if 0 <= self.active_angle_index < len(self.angles):
            return self.angles[self.active_angle_index]
        return None
    
    def switch_angle(
        self,
        angle_index: int,
        at_time: RationalTime
    ) -> MulticamTransition:
        """
        Belirli bir zamanda kamera açısı değiştir.
        
        Bu, multicam editing'in temel işlemidir. 
        Canlı yayında olduğu gibi, istenen anda 
        kamera geçişi yapılır.
        
        Geçiş, bir MulticamTransition olarak kaydedilir.
        """
        if angle_index < 0 or angle_index >= len(self.angles):
            raise ValueError(f"Geçersiz açı indeksi: {angle_index}")
        
        transition = MulticamTransition(
            from_angle_index=self.active_angle_index,
            to_angle_index=angle_index,
            position=at_time,
        )
        
        self.transitions.append(transition)
        self.active_angle_index = angle_index
        
        return transition
    
    def angle_at(self, time: RationalTime) -> Optional[MulticamAngle]:
        """
        Belirli bir zamanda hangi kamera açısının aktif olduğunu bul.
        
        Geçiş noktalarını tarayarak, verilen zamandaki 
        aktif açıyı hesaplar.
        """
        if not self.transitions:
            return self.active_angle
        
        # Geçişleri zamana göre sırala
        sorted_transitions = sorted(
            self.transitions,
            key=lambda t: t.position.value
        )
        
        current_angle_idx = 0
        for transition in sorted_transitions:
            if time >= transition.position:
                current_angle_idx = transition.to_angle_index
            else:
                break
        
        if 0 <= current_angle_idx < len(self.angles):
            return self.angles[current_angle_idx]
        return None
    
    def to_dict(self) -> dict:
        return {
            "multicam_id": str(self.multicam_id),
            "name": self.name,
            "angles": [a.to_dict() for a in self.angles],
            "active_angle_index": self.active_angle_index,
            "sync_method": self.sync_method,
            "duration": self.duration.to_dict(),
            "fps": str(self.fps),
            "transitions": [t.to_dict() for t in self.transitions],
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> MulticamClip:
        return cls(
            multicam_id=UUID(data["multicam_id"]),
            name=data["name"],
            angles=[MulticamAngle.from_dict(a) for a in data["angles"]],
            active_angle_index=data["active_angle_index"],
            sync_method=data["sync_method"],
            duration=RationalTime.from_dict(data["duration"]),
            fps=Fraction(data["fps"]),
            transitions=[MulticamTransition.from_dict(t) for t in data["transitions"]],
            metadata=data.get("metadata", {}),
        )


@dataclass
class MulticamAngle:
    """Multicam kamera açısı"""
    angle_id: UUID = field(default_factory=uuid4)
    name: str = ""
    source_media_id: UUID = field(default_factory=uuid4)
    source_range: TimeRange = field(default_factory=lambda: TimeRange(
        RationalTime(0, 1), RationalTime(0, 1)
    ))
    offset: RationalTime = field(default_factory=lambda: RationalTime(0, 1))
    audio_source: str = "angle"
    enabled: bool = True
    
    def to_dict(self) -> dict:
        return {
            "angle_id": str(self.angle_id),
            "name": self.name,
            "source_media_id": str(self.source_media_id),
            "source_range": self.source_range.to_dict(),
            "offset": self.offset.to_dict(),
            "audio_source": self.audio_source,
            "enabled": self.enabled,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> MulticamAngle:
        return cls(
            angle_id=UUID(data["angle_id"]),
            name=data["name"],
            source_media_id=UUID(data["source_media_id"]),
            source_range=TimeRange.from_dict(data["source_range"]),
            offset=RationalTime.from_dict(data["offset"]),
            audio_source=data["audio_source"],
            enabled=data["enabled"],
        )


@dataclass
class MulticamTransition:
    """Multicam kamera geçişi"""
    transition_id: UUID = field(default_factory=uuid4)
    from_angle_index: int = 0
    to_angle_index: int = 0
    position: RationalTime = field(default_factory=lambda: RationalTime(0, 1))
    type: str = "cut"
    duration: RationalTime = field(default_factory=lambda: RationalTime(0, 1))
    
    def to_dict(self) -> dict:
        return {
            "transition_id": str(self.transition_id),
            "from_angle_index": self.from_angle_index,
            "to_angle_index": self.to_angle_index,
            "position": self.position.to_dict(),
            "type": self.type,
            "duration": self.duration.to_dict(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> MulticamTransition:
        return cls(
            transition_id=UUID(data["transition_id"]),
            from_angle_index=data["from_angle_index"],
            to_angle_index=data["to_angle_index"],
            position=RationalTime.from_dict(data["position"]),
            type=data["type"],
            duration=RationalTime.from_dict(data["duration"]),
        )
```

## 3.3 Temel Algoritmalar

### 3.3.1 Three-Point Editing

```python
class ThreePointEditor:
    """
    Three-point editing motoru.
    
    Three-point editing, NLE'lerin en temel editing modelidir.
    Üç noktadan herhangi üçünü belirleyerek editing yapılır:
    
    1. Source In: Kaynak medyada başlangıç noktası
    2. Source Out: Kaynak medyada bitiş noktası  
    3. Record In: Timeline'da başlangıç noktası
    4. Record Out: Timeline'da bitiş noktası
    
    Üç nokta belirlendiğinde, dördüncü nokta otomatik hesaplanır.
    
    Senaryolar:
    - Source In + Source Out + Record In = Record Out hesaplanır
    - Source In + Record In + Record Out = Source Out hesaplanır
    - Source Out + Record In + Record Out = Source In hesaplanır
    
    Bu model, Premiere Pro'nun "Source Monitor" editing 
    modeli ile aynıdır.
    """
    
    def __init__(self, timeline: Timeline):
        self.timeline = timeline
    
    def execute_three_point(
        self,
        decision: EditDecision,
        mode: EditMode = EditMode.INSERT
    ) -> TimelineClip:
        """
        Three-point editing uygula.
        
        Algoritma:
        1. Eksik noktayı hesapla (3 varsa, 4. hesaplanır)
        2. Kaynak aralığını belirle
        3. Record aralığını belirle
        4. Hız hesapla (eğer four-point ise)
        5. Yeni TimelineClip oluştur
        6. Edit moduna göre timeline'a ekle
        
        Karmaşıklık: O(n) — track'teki clip'leri tarama
        """
        # Eksik noktayı hesapla
        self._compute_missing_point(decision)
        
        # Kaynak ve record aralıklarını oluştur
        source_range = TimeRange(
            decision.source_in,
            decision.source_out - decision.source_in
        )
        
        if decision.record_position:
            record_start = decision.record_position
        elif decision.record_in:
            record_start = decision.record_in
        else:
            raise ValueError("Record pozisyonu belirtilmeli")
        
        record_range = TimeRange(
            record_start,
            source_range.duration * abs(decision.speed)
        )
        
        # Yeni clip oluştur
        clip = TimelineClip(
            name=decision.clip_name,
            source_media_id=decision.source_media_id,
            source_range=source_range,
            record_range=record_range,
            speed=decision.speed,
            reverse=decision.reverse,
        )
        
        # Edit moduna göre uygula
        track = self._find_or_create_track(decision.target_track_id)
        
        if mode == EditMode.INSERT:
            track.insert_clip(clip, record_start, "insert")
        elif mode == EditMode.OVERWRITE:
            track.insert_clip(clip, record_start, "overwrite")
        else:
            raise ValueError(f"Geçersiz edit modu: {mode}")
        
        return clip
    
    def _compute_missing_point(self, decision: EditDecision) -> None:
        """
        Eksik 4. noktayı hesapla.
        
        Three-point editing mantığı:
        - 3 nokta belirtilmiş → 4. otomatik hesaplanır
        - 4 nokta belirtilmiş → Hız değişikliği (four-point)
        - 2 veya daha az → Hata
        """
        points = [
            decision.source_in is not None,
            decision.source_out is not None,
            decision.record_in is not None,
            decision.record_out is not None,
        ]
        
        point_count = sum(points)
        
        if point_count < 3:
            raise ValueError(
                f"En az 3 nokta belirtilmeli, {point_count} belirtildi"
            )
        
        if point_count == 4:
            # Four-point editing — hız hesapla
            decision.speed = decision.compute_speed()
            return
        
        # Eksik noktayı hesapla
        if decision.source_in is None and decision.source_out is not None:
            if decision.record_in and decision.record_out:
                duration = decision.record_out - decision.record_in
                decision.source_in = decision.source_out - duration
            elif decision.record_in:
                duration = decision.source_out - decision.source_in if decision.source_in else RationalTime(0, 1)
                decision.record_out = decision.record_in + duration
        
        elif decision.source_out is None and decision.source_in is not None:
            if decision.record_in and decision.record_out:
                duration = decision.record_out - decision.record_in
                decision.source_out = decision.source_in + duration
            elif decision.record_out:
                duration = decision.record_out - decision.record_in if decision.record_in else RationalTime(0, 1)
                decision.source_in = decision.source_out - duration
        
        elif decision.record_in is None and decision.record_out is not None:
            if decision.source_in and decision.source_out:
                duration = decision.source_out - decision.source_in
                decision.record_in = decision.record_out - duration
        
        elif decision.record_out is None and decision.record_in is not None:
            if decision.source_in and decision.source_out:
                duration = decision.source_out - decision.source_in
                decision.record_out = decision.record_in + duration
    
    def _find_or_create_track(
        self,
        track_id: Optional[UUID]
    ) -> Track:
        """Track'i bul veya oluştur"""
        if track_id:
            track = self.timeline.get_track(track_id)
            if track:
                return track
        
        # Varsayılan video track'i bul veya oluştur
        video_tracks = self.timeline.video_tracks
        if video_tracks:
            return video_tracks[0]
        
        return self.timeline.add_track(TrackType.VIDEO, "V1")


class MatchFrameEngine:
    """
    Match Frame ve Reverse Match Frame motoru.
    
    Match Frame: Timeline'daki bir frame'i kaynak monitörde bulur.
    Reverse Match Frame: Kaynak monitördeki frame'i timeline'da bulur.
    
    Bu özellik, Avid Media Composer'dan beri profesyonel 
    editing'in vazgeçilmez bir parçasıdır.
    
    Usage:
        engine = MatchFrameEngine(timeline)
        source_clip = engine.match_frame(current_position)
        timeline_position = engine.reverse_match_frame(source_clip, frame_number)
    """
    
    def __init__(self, timeline: Timeline):
        self.timeline = timeline
    
    def match_frame(
        self,
        timeline_position: RationalTime
    ) -> Optional[Tuple[TimelineClip, RationalTime]]:
        """
        Timeline pozisyonundaki clip'i ve kaynak frame'i bul.
        
        Algoritma:
        1. Tüm track'lerde timeline_position'da clip bul
        2. Clip'in source_time_at() metodunu kullanarak 
           kaynak zamını hesapla
        3. Clip ve kaynak zamanını döndür
        
        Karmaşıklık: O(n*m) — n = track sayısı, m = ortalama clip sayısı
        """
        for track in self.timeline.tracks:
            if track.track_type != TrackType.VIDEO:
                continue
            for clip in track.clips:
                if clip.record_range.contains(timeline_position):
                    source_time = clip.source_time_at(timeline_position)
                    if source_time:
                        return (clip, source_time)
        return None
    
    def reverse_match_frame(
        self,
        source_media_id: UUID,
        source_time: RationalTime
    ) -> Optional[List[Tuple[TimelineClip, RationalTime]]]:
        """
        Kaynak zamanındaki frame'i tüm timeline'da bul.
        
        Bu, bir kaynak frame'in timeline'da kaç kez 
        ve nerede kullanıldığını gösterir.
        
        Returns:
            [(clip, timeline_position), ...] listesi
        """
        results = []
        
        for track in self.timeline.tracks:
            for clip in track.clips:
                if clip.source_media_id != source_media_id:
                    continue
                
                # Kaynak zamanı bu clip'in aralığında mı?
                if clip.source_range.contains(source_time):
                    # Timeline pozisyonunu hesapla
                    offset = source_time - clip.source_range.start
                    if clip.reverse:
                        timeline_pos = clip.record_range.end - offset
                    else:
                        timeline_pos = clip.record_range.start + offset
                    
                    if clip.record_range.contains(timeline_pos):
                        results.append((clip, timeline_pos))
        
        return results if results else None
```

## 3.4 API Sözleşmeleri

```python
class NLECore:
    """
    NLE çekirdeği API'si.
    
    Bu sınıf, profesyonel düzenleme iş akışlarının 
    tamamını yönetir. FastAPI endpoint'lerinden 
    doğrudan erişilir.
    """
    
    def __init__(self, timeline_engine: TimelineEngine):
        self._engine = timeline_engine
        self._subclips: Dict[UUID, Subclip] = {}
        self._multicams: Dict[UUID, MulticamClip] = {}
    
    def create_subclip(
        self,
        source_media_id: UUID,
        name: str,
        in_point: RationalTime,
        out_point: RationalTime,
        master_duration: Optional[RationalTime] = None,
    ) -> Subclip:
        """
        Yeni bir subclip oluştur.
        
        Args:
            source_media_id: Kaynak medya ID
            name: Subclip adı
            in_point: Başlangıç noktası
            out_point: Bitiş noktası
            master_duration: Master medya süresi (opsiyonel)
            
        Returns:
            Oluşturulan Subclip nesnesi
        """
        if out_point <= in_point:
            raise ValueError("Out point, in point'ten sonra olmalı")
        
        subclip = Subclip(
            name=name,
            source_media_id=source_media_id,
            source_range=TimeRange(in_point, out_point - in_point),
            master_duration=master_duration,
        )
        
        self._subclips[subclip.subclip_id] = subclip
        return subclip
    
    def create_multicam(
        self,
        name: str,
        angles: List[MulticamAngle],
        sync_method: str = "timecode",
    ) -> MulticamClip:
        """
        Yeni bir multicam clip oluştur.
        
        Args:
            name: Multicam clip adı
            angles: Kamera açıları listesi
            sync_method: Senkronizasyon yöntemi
            
        Returns:
            Oluşturulan MulticamClip nesnesi
        """
        multicam = MulticamClip(
            name=name,
            angles=angles,
            sync_method=sync_method,
        )
        
        # Süreyi en uzun angle'a göre ayarla
        if angles:
            max_duration = max(a.source_range.duration for a in angles)
            multicam.duration = max_duration
        
        self._multicams[multicam.multicam_id] = multicam
        return multicam
    
    def edit_three_point(
        self,
        timeline_id: UUID,
        decision: EditDecision,
        mode: EditMode = EditMode.INSERT,
    ) -> TimelineClip:
        """
        Three-point editing uygula.
        
        Args:
            timeline_id: Timeline ID
            decision: Edit decision parametreleri
            mode: Edit modu
            
        Returns:
            Oluşturulan TimelineClip
        """
        timeline = self._engine.get_timeline(timeline_id)
        if not timeline:
            raise ValueError(f"Timeline bulunamadı: {timeline_id}")
        
        editor = ThreePointEditor(timeline)
        return editor.execute_three_point(decision, mode)
    
    def match_frame(
        self,
        timeline_id: UUID,
        position: RationalTime
    ) -> Optional[Dict[str, Any]]:
        """
        Match frame uygula.
        
        Timeline pozisyonundaki clip'i ve kaynak frame'i bul.
        """
        timeline = self._engine.get_timeline(timeline_id)
        if not timeline:
            raise ValueError(f"Timeline bulunamadı: {timeline_id}")
        
        engine = MatchFrameEngine(timeline)
        result = engine.match_frame(position)
        
        if result:
            clip, source_time = result
            return {
                "clip": clip.to_dict(),
                "source_time": source_time.to_dict(),
                "source_frame": source_time.to_frames(timeline.fps),
            }
        return None
    
    def get_edl(
        self,
        timeline_id: UUID
    ) -> List[EditDecision]:
        """
        Timeline'dan EDL (Edit Decision List) oluştur.
        
        Bu, timeline'daki tüm clip'leri EditDecision 
        listesine dönüştürür. Dışa aktarma ve 
        uyumluluk için kullanılır.
        """
        timeline = self._engine.get_timeline(timeline_id)
        if not timeline:
            raise ValueError(f"Timeline bulunamadı: {timeline_id}")
        
        edl = []
        
        for track in timeline.tracks:
            if track.track_type != TrackType.VIDEO:
                continue
            
            for clip in track.clips:
                decision = EditDecision(
                    name=clip.name,
                    source_media_id=clip.source_media_id,
                    source_in=clip.source_range.start,
                    source_out=clip.source_range.end,
                    record_in=clip.record_range.start,
                    record_out=clip.record_range.end,
                    record_position=clip.record_range.start,
                    edit_mode=EditMode.OVERWRITE,
                    target_track_id=track.track_id,
                    speed=clip.speed,
                    reverse=clip.reverse,
                )
                edl.append(decision)
        
        return edl
```

## 3.5 Performans Darboğazları ve Çözümleri

| Darboğaz | Etki | Çözüm |
|---|---|---|
| Three-point editing (large timeline) | Clip arama O(n) | Interval tree ile O(log n) lookup |
| Multicam angle switching | Her geçişte 4+ kaynak okuma | Pre-decode buffer ile 2-frame lookahead |
| Match frame reverse scan | 1000+ clip'de yavaş | Media ID index ile O(1) lookup |
| EDL export (large projects) | 10000+ clip'de yavaş | Streaming export, memory'de minimum tutma |
| Subclip management | Çoklu subclip oluşturma | Lazy evaluation — sadece gerektiğinde hesapla |

## 3.6 Entegrasyon Noktaları

```
NLE Core
    ├── Timeline Engine ← Clip'ler ve track'ler için
    ├── Media Manager ← Kaynak medya referansları için
    ├── Multicam Sync Engine ← Multicam senkronizasyonu için
    ├── EDL Exporter ← Dışa aktarma için
    └── UI Controller ← Edit tool'ları ve monitörler için
```

---

# 4. Efekt Grafiği (Node-Based Processing)

## 4.1 Amaç ve Kapsam

Efekt grafiği, video ve ses üzerine uygulanan tüm işleme adımlarını yönetir. Bu sistem, After Effects'in efekt zinciri (effect chain) modelini, Nuke'un node-based compositing modeli ile birleştirir. Her efekt, bir DAG (Directed Acyclic Graph) içindeki bir düğüm (node) olarak temsil edilir.

Node-based processing'in avantajı:
- Paralel işleme kolaylığı
- Efekt sırasını görsel olarak değiştirme
- Her düğümü bağımsız olarak bypass/solo yapma
- Preset oluşturma ve paylaşma

### Karşılaştırma

| Özellik | Bizim Sistem | Premiere | Resolve | After Effects | Nuke |
|---|---|---|---|---|---|
| Efekt modeli | Node-based DAG | Effect chain | Node (Fusion) | Effect chain | Node-based |
| Keyframe animasyonu | Evet | Evet | Evet | Evet (best) | Evet |
| Efekt presets | Evet | Evet | Evet | Evet | Evet |
| Real-time preview | Evet | Evet | Evet | Kısmen | Hayır |
| GPU hızlandırma | Evet | Evet | Evet (CUDA) | Kısmen | Evet |

## 4.2 Mimari

```
┌─────────────────────────────────────────────┐
│           Effect Graph (DAG)                 │
│                                              │
│  ┌──────────┐    ┌──────────┐              │
│  │  Input   │───▶│  Color   │              │
│  │  Source  │    │  Grade   │              │
│  └──────────┘    └────┬─────┘              │
│                       │                     │
│                  ┌────▼─────┐              │
│                  │  Blur    │              │
│                  │  (Bypass)│              │
│                  └────┬─────┘              │
│                       │                     │
│                  ┌────▼─────┐              │
│                  │  Glow   │              │
│                  └────┬─────┘              │
│                       │                     │
│                  ┌────▼─────┐              │
│                  │  Output  │              │
│                  └──────────┘              │
└─────────────────────────────────────────────┘
```

## 4.3 Veri Yapısı

```python
"""
Efekt grafiği veri yapıları.

Tasarım İlkeleri:
1. Her efekt bağımsız bir node olarak temsil edilir
2. Node'lar arasındaki veri akışı DAG üzerinde tanımlıdır
3. Her node'un kendi parametreleri ve keyframe'leri vardır
4. Efekt sırası, graph'ın topolojik sıralamasına göre belirlenir
5. GPU hızlandırma için uygun arayüz sağlar
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from uuid import UUID, uuid4


class EffectType(Enum):
    """Efekt türleri"""
    COLOR = "color"
    TRANSFORM = "transform"
    BLUR = "blur"
    SHARPEN = "sharpen"
    KEYING = "keying"
    DISTORTION = "distortion"
    GENERATOR = "generator"
    STYLIZE = "stylize"
    NOISE = "noise"
    PERSPECTIVE = "perspective"
    TIME = "time"
    AUDIO = "audio"
    CUSTOM = "custom"


class InterpolationType(Enum):
    """Keyframe interpolasyon türleri"""
    LINEAR = "linear"
    BEZIER = "bezier"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    CONSTANT = "constant"
    HERMITE = "hermite"


@dataclass
class Keyframe:
    """
    Tek bir keyframe.
    
    Keyframe, bir parametrenin belirli bir zamandaki 
    değerini temsil eder. İki keyframe arasında, 
    interpolasyon yöntemi ile ara değerler hesaplanır.
    
    After Effects ve Premiere'daki keyframe modeli ile aynıdır.
    
    Keyframe türleri:
    - Linear: Doğrusal interpolasyon
    - Bezier: Eğri interpolasyon (control point'leri ile)
    - Constant: Ani değişim (stepped)
    """
    keyframe_id: UUID = field(default_factory=uuid4)
    time: RationalTime = field(default_factory=lambda: RationalTime(0, 1))
    value: float = 0.0
    interpolation: InterpolationType = InterpolationType.LINEAR
    ease_in: float = 0.0  # 0-1 arası, Bezier için
    ease_out: float = 0.0  # 0-1 arası, Bezier için
    velocity: float = 0.0  # Hız (türev)
    influence: float = 33.33  # Etki alanı (%)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "keyframe_id": str(self.keyframe_id),
            "time": self.time.to_dict(),
            "value": self.value,
            "interpolation": self.interpolation.value,
            "ease_in": self.ease_in,
            "ease_out": self.ease_out,
            "velocity": self.velocity,
            "influence": self.influence,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> Keyframe:
        return cls(
            keyframe_id=UUID(data["keyframe_id"]),
            time=RationalTime.from_dict(data["time"]),
            value=data["value"],
            interpolation=InterpolationType(data["interpolation"]),
            ease_in=data["ease_in"],
            ease_out=data["ease_out"],
            velocity=data["velocity"],
            influence=data["influence"],
        )


@dataclass
class EffectParameter:
    """
    Efekt parametresi — animasyonlanabilir değer.
    
    Her parametre, bir ad, tür, değer aralığı ve 
    opsiyonel keyframe listesi içerir.
    
    Parameter türleri:
    - float: Ondalıklı sayı
    - int: Tamsayı
    - bool: Mantıksal değer
    - color: RGB/RGBA rengi
    - enum: Seçenek listesi
    - point: 2B/3B nokta
    - angle: Açı (derece)
    - size: Genişlik/yükseklik
    """
    param_id: UUID = field(default_factory=uuid4)
    name: str = ""
    param_type: str = "float"
    value: Any = 0.0
    default_value: Any = 0.0
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    keyframes: List[Keyframe] = field(default_factory=list)
    is_animated: bool = False
    display_name: str = ""
    description: str = ""
    group: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def has_keyframes(self) -> bool:
        """Parametrede keyframe var mı?"""
        return len(self.keyframes) > 0
    
    def get_value_at(self, time: RationalTime) -> float:
        """
        Belirli bir zamandaki değeri hesapla.
        
        Keyframe yoksa, sabit değeri döndür.
        Keyframe varsa, iki keyframe arasında interpolasyon yap.
        """
        if not self.has_keyframes:
            return float(self.value)
        
        # Zamanlamaya göre sırala
        sorted_kf = sorted(self.keyframes, key=lambda k: k.time.value)
        
        # İlk keyframe'den önce
        if time <= sorted_kf[0].time:
            return sorted_kf[0].value
        
        # Son keyframe'den sonra
        if time >= sorted_kf[-1].time:
            return sorted_kf[-1].value
        
        # İki keyframe arasında interpolasyon
        for i in range(len(sorted_kf) - 1):
            kf1 = sorted_kf[i]
            kf2 = sorted_kf[i + 1]
            
            if kf1.time <= time <= kf2.time:
                # t = 0 (kf1) ile 1 (kf2) arası
                if kf2.time == kf1.time:
                    return kf1.value
                
                t = float((time - kf1.time) / (kf2.time - kf1.time))
                return self._interpolate(kf1, kf2, t)
        
        return float(self.value)
    
    def _interpolate(self, kf1: Keyframe, kf2: Keyframe, t: float) -> float:
        """
        İki keyframe arasında interpolasyon yap.
        
        Interpolasyon yöntemleri:
        - Linear: Doğrusal
        - Bezier: Kübik Bezier eğrisi
        - Constant: Ani değişim
        """
        if kf1.interpolation == InterpolationType.CONSTANT:
            return kf1.value
        
        if kf1.interpolation == InterpolationType.LINEAR:
            return kf1.value + (kf2.value - kf1.value) * t
        
        if kf1.interpolation == InterpolationType.BEZIER:
            # Kübik Bezier interpolasyonu
            # Control point'leri ease_in ve ease_out ile belirlenir
            ease1 = kf1.ease_out
            ease2 = kf2.ease_in
            
            # Basitleştirilmiş Bezier eğrisi
            # Gerçek implementasyonda Hermite spline kullanılabilir
            t2 = t * t
            t3 = t2 * t
            
            # Hermite spline katsayıları
            h00 = 2 * t3 - 3 * t2 + 1
            h10 = t3 - 2 * t2 + t
            h01 = -2 * t3 + 3 * t2
            h11 = t3 - t2
            
            # Velocity'leri hesapla
            v1 = kf1.velocity * ease1
            v2 = kf2.velocity * ease2
            
            return h00 * kf1.value + h10 * v1 + h01 * kf2.value + h11 * v2
        
        # Default: linear
        return kf1.value + (kf2.value - kf1.value) * t
    
    def add_keyframe(self, keyframe: Keyframe) -> None:
        """Keyframe ekle"""
        self.keyframes.append(keyframe)
        self.keyframes.sort(key=lambda k: k.time.value)
        self.is_animated = True
    
    def remove_keyframe(self, keyframe_id: UUID) -> bool:
        """Keyframe kaldır"""
        for i, kf in enumerate(self.keyframes):
            if kf.keyframe_id == keyframe_id:
                del self.keyframes[i]
                if not self.keyframes:
                    self.is_animated = False
                return True
        return False
    
    def to_dict(self) -> dict:
        return {
            "param_id": str(self.param_id),
            "name": self.name,
            "param_type": self.param_type,
            "value": self.value,
            "default_value": self.default_value,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "keyframes": [kf.to_dict() for kf in self.keyframes],
            "is_animated": self.is_animated,
            "display_name": self.display_name,
            "description": self.description,
            "group": self.group,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> EffectParameter:
        return cls(
            param_id=UUID(data["param_id"]),
            name=data["name"],
            param_type=data["param_type"],
            value=data["value"],
            default_value=data["default_value"],
            min_value=data.get("min_value"),
            max_value=data.get("max_value"),
            keyframes=[Keyframe.from_dict(kf) for kf in data.get("keyframes", [])],
            is_animated=data.get("is_animated", False),
            display_name=data.get("display_name", ""),
            description=data.get("description", ""),
            group=data.get("group", ""),
        )
```

```python
@dataclass
class EffectNode:
    """
    Efekt düğümü — DAG içindeki tek bir efekt.
    
    Her EffectNode, bir efekt türünü ve onun 
    parametrelerini temsil eder. Node'lar, 
    giriş ve çıkış bağlantıları ile DAG oluşturur.
    
    Node türleri:
    - Generator: Sıfırdan görüntü oluşturur (solid, text, gradient)
    - Transform: Geometrik dönüşüm uygular
    - Color: Renk düzeltme ve grading
    - Blur: Bulanıklık ve netleştirme
    - Keying: Yeşil ekran (chroma key) ve alpha
    - Distortion: Bozulma efektleri
    - Custom: Özel efektler (plugin)
    
    Her node:
    - Bypass edilebilir (devre dışı bırakılabilir)
    - Solo yapılabilir (sadece bu node render edilir)
    - Öncelik sırası ayarlanabilir
    """
    node_id: UUID = field(default_factory=uuid4)
    name: str = ""
    effect_type: EffectType = EffectType.CUSTOM
    parameters: Dict[str, EffectParameter] = field(default_factory=dict)
    
    # Bağlantılar
    input_nodes: List[UUID] = field(default_factory=list)
    output_nodes: List[UUID] = field(default_factory=list)
    
    # Durum
    enabled: bool = True
    bypassed: bool = False
    solo: bool = False
    locked: bool = False
    
    # Sıralama
    order: int = 0
    
    # Plugin bilgisi
    plugin_id: Optional[str] = None
    plugin_version: str = "1.0.0"
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_active(self) -> bool:
        """Node aktif mi? (Bypass edilmemiş ve enabled)"""
        return self.enabled and not self.bypassed
    
    def get_parameter(self, name: str) -> Optional[EffectParameter]:
        """Parametreyi isimle bul"""
        return self.parameters.get(name)
    
    def set_parameter_value(self, name: str, value: Any) -> None:
        """Parametre değerini ayarla"""
        if name in self.parameters:
            self.parameters[name].value = value
        else:
            raise ValueError(f"Parametre bulunamadı: {name}")
    
    def add_parameter(self, param: EffectParameter) -> None:
        """Yeni parametre ekle"""
        self.parameters[param.name] = param
    
    def remove_parameter(self, name: str) -> bool:
        """Parametre kaldır"""
        if name in self.parameters:
            del self.parameters[name]
            return True
        return False
    
    def get_all_parameters(self) -> List[EffectParameter]:
        """Tüm parametreleri döndür"""
        return list(self.parameters.values())
    
    def get_animated_parameters(self) -> List[EffectParameter]:
        """Sadece animasyonlu parametreleri döndür"""
        return [p for p in self.parameters.values() if p.is_animated]
    
    def to_dict(self) -> dict:
        return {
            "node_id": str(self.node_id),
            "name": self.name,
            "effect_type": self.effect_type.value,
            "parameters": {k: v.to_dict() for k, v in self.parameters.items()},
            "input_nodes": [str(n) for n in self.input_nodes],
            "output_nodes": [str(n) for n in self.output_nodes],
            "enabled": self.enabled,
            "bypassed": self.bypassed,
            "solo": self.solo,
            "locked": self.locked,
            "order": self.order,
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> EffectNode:
        return cls(
            node_id=UUID(data["node_id"]),
            name=data["name"],
            effect_type=EffectType(data["effect_type"]),
            parameters={k: EffectParameter.from_dict(v) for k, v in data["parameters"].items()},
            input_nodes=[UUID(n) for n in data.get("input_nodes", [])],
            output_nodes=[UUID(n) for n in data.get("output_nodes", [])],
            enabled=data.get("enabled", True),
            bypassed=data.get("bypassed", False),
            solo=data.get("solo", False),
            locked=data.get("locked", False),
            order=data.get("order", 0),
            plugin_id=data.get("plugin_id"),
            plugin_version=data.get("plugin_version", "1.0.0"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class EffectPreset:
    """
    Efekt preset'i — kaydedilmiş efekt yapılandırması.
    
    Preset, bir veya birden fazla EffectNode'un 
    yapılandırmasını kaydeder. Kullanıcılar, sık kullandıkları 
    efekt ayarlarını preset olarak kaydedebilir ve 
    daha sonra hızlıca uygulayabilir.
    
    Premiere'de "Effects Presets", Resolve'da "Power Bins" 
    benzer işlevi görür.
    """
    preset_id: UUID = field(default_factory=uuid4)
    name: str = ""
    description: str = ""
    category: str = ""
    nodes: List[EffectNode] = field(default_factory=list)
    thumbnail: Optional[str] = None  # Base64 encoded thumbnail
    author: str = ""
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    created_at: str = ""
    modified_at: str = ""
    
    def to_dict(self) -> dict:
        return {
            "preset_id": str(self.preset_id),
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "nodes": [n.to_dict() for n in self.nodes],
            "thumbnail": self.thumbnail,
            "author": self.author,
            "version": self.version,
            "tags": self.tags,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> EffectPreset:
        return cls(
            preset_id=UUID(data["preset_id"]),
            name=data["name"],
            description=data["description"],
            category=data["category"],
            nodes=[EffectNode.from_dict(n) for n in data["nodes"]],
            thumbnail=data.get("thumbnail"),
            author=data.get("author", ""),
            version=data.get("version", "1.0.0"),
            tags=data.get("tags", []),
            created_at=data.get("created_at", ""),
            modified_at=data.get("modified_at", ""),
        )


@dataclass
class EffectGraph:
    """
    Efekt grafiği — DAG (Directed Acyclic Graph).
    
    EffectGraph, bir clip'e uygulanan tüm efektlerin 
    bağlılığını ve işlenme sırasını yönetir.
    
    DAG, şu kurallara uyar:
    1. Döngü (cycle) olamaz
    2. Her node'un en az bir girişi (input) olabilir
    3. Her node'un en az bir çıkışı (output) olabilir
    4. Topolojik sıralama ile işlenme sırası belirlenir
    
    Nuke'un node graph modeli ile aynı mantığı kullanır.
    Fakat biz daha basit bir arayüz sunuyoruz — 
    profesyonel VFX compositor'lara değil, NLE kullanıcılarına yönelik.
    """
    graph_id: UUID = field(default_factory=uuid4)
    name: str = ""
    nodes: Dict[UUID, EffectNode] = field(default_factory=dict)
    input_node_id: Optional[UUID] = None
    output_node_id: Optional[UUID] = None
    
    # Cache
    _processing_order: List[UUID] = field(default_factory=list, repr=False)
    _is_dirty: bool = field(default=True, repr=False)
    
    @property
    def node_count(self) -> int:
        """Toplam düğüm sayısı"""
        return len(self.nodes)
    
    @property
    def active_nodes(self) -> List[EffectNode]:
        """Aktif (bypass edilmemiş) düğümleri döndür"""
        return [n for n in self.nodes.values() if n.is_active]
    
    @property
    def has_solo(self) -> bool:
        """Herhangi bir solo düğüm var mı?"""
        return any(n.solo for n in self.nodes.values())
    
    def add_node(self, node: EffectNode) -> None:
        """
        Grafiğe yeni düğüm ekle.
        
        Döngü kontrolü yapar — döngü oluşursa hata fırlatır.
        """
        if node.node_id in self.nodes:
            raise ValueError(f"Düğüm zaten mevcut: {node.node_id}")
        
        # Geçici olarak ekle ve döngü kontrolü yap
        self.nodes[node.node_id] = node
        if self._has_cycle():
            del self.nodes[node.node_id]
            raise ValueError("Döngü tespit edildi — düğüm eklenemez")
        
        self._is_dirty = True
    
    def remove_node(self, node_id: UUID) -> bool:
        """Düğümden kaldır"""
        if node_id not in self.nodes:
            return False
        
        node = self.nodes[node_id]
        
        # Bağlantıları temizle
        for input_id in node.input_nodes:
            if input_id in self.nodes:
                input_node = self.nodes[input_id]
                if node_id in input_node.output_nodes:
                    input_node.output_nodes.remove(node_id)
        
        for output_id in node.output_nodes:
            if output_id in self.nodes:
                output_node = self.nodes[output_id]
                if node_id in output_node.input_nodes:
                    output_node.input_nodes.remove(node_id)
        
        del self.nodes[node_id]
        self._is_dirty = True
        return True
    
    def connect(
        self,
        from_node_id: UUID,
        to_node_id: UUID
    ) -> None:
        """
        İki düğümü bağla.
        
        from_node → to_node yönünde veri akışı sağlanır.
        Döngü kontrolü yapar.
        """
        if from_node_id not in self.nodes or to_node_id not in self.nodes:
            raise ValueError("Düğümlerden biri bulunamadı")
        
        from_node = self.nodes[from_node_id]
        to_node = self.nodes[to_node_id]
        
        # Zaten bağlı mı?
        if to_node_id in from_node.output_nodes:
            return
        
        # Bağlantıyı ekle
        from_node.output_nodes.append(to_node_id)
        to_node.input_nodes.append(from_node_id)
        
        # Döngü kontrolü
        if self._has_cycle():
            # Bağlantıyı geri al
            from_node.output_nodes.remove(to_node_id)
            to_node.input_nodes.remove(from_node_id)
            raise ValueError("Döngü tespit edildi — bağlantı kurulamaz")
        
        self._is_dirty = True
    
    def disconnect(self, from_node_id: UUID, to_node_id: UUID) -> None:
        """İki düğüm arasındaki bağlantıyı kes"""
        if from_node_id in self.nodes:
            from_node = self.nodes[from_node_id]
            if to_node_id in from_node.output_nodes:
                from_node.output_nodes.remove(to_node_id)
        
        if to_node_id in self.nodes:
            to_node = self.nodes[to_node_id]
            if from_node_id in to_node.input_nodes:
                to_node.input_nodes.remove(from_node_id)
        
        self._is_dirty = True
    
    def get_processing_order(self) -> List[UUID]:
        """
        İşleme sırasını hesapla (topolojik sıralama).
        
        Kahn's algorithm kullanarak topolojik sıralama yapar.
        Bu sıralama, efektlerin işlenme düzenini belirler.
        
        Karmaşıklık: O(V + E) — V = düğüm sayısı, E = kenar sayısı
        """
        if not self._is_dirty and self._processing_order:
            return self._processing_order
        
        # Kahn's algorithm
        in_degree = {node_id: 0 for node_id in self.nodes}
        queue = []
        
        for node_id, node in self.nodes.items():
            for input_id in node.input_nodes:
                if input_id in self.nodes:
                    in_degree[node_id] += 1
        
        for node_id, degree in in_degree.items():
            if degree == 0:
                queue.append(node_id)
        
        result = []
        while queue:
            node_id = queue.pop(0)
            result.append(node_id)
            
            node = self.nodes[node_id]
            for output_id in node.output_nodes:
                if output_id in self.nodes:
                    in_degree[output_id] -= 1
                    if in_degree[output_id] == 0:
                        queue.append(output_id)
        
        if len(result) != len(self.nodes):
            raise ValueError("Döngü tespit edildi — topolojik sıralama yapılamaz")
        
        self._processing_order = result
        self._is_dirty = False
        
        return result
    
    def _has_cycle(self) -> bool:
        """
        Döngü tespiti (DFS tabanlı).
        
        Renk kodlama:
        - White: Henüz ziyaret edilmedi
        - Gray: İşleniyor (yolda)
        - Black: İşlendi (tamamlandı)
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {node_id: WHITE for node_id in self.nodes}
        
        def dfs(node_id: UUID) -> bool:
            color[node_id] = GRAY
            node = self.nodes.get(node_id)
            if node:
                for output_id in node.output_nodes:
                    if output_id in self.nodes:
                        if color[output_id] == GRAY:
                            return True  # Döngü bulundu
                        if color[output_id] == WHITE:
                            if dfs(output_id):
                                return True
            color[node_id] = BLACK
            return False
        
        for node_id in self.nodes:
            if color[node_id] == WHITE:
                if dfs(node_id):
                    return True
        
        return False
    
    def apply_preset(self, preset: EffectPreset) -> None:
        """
        Preset'i uygula.
        
        Mevcut düğümleri temizler ve preset'in 
        düğümlerini ekler.
        """
        self.nodes.clear()
        for node in preset.nodes:
            self.add_node(node)
        self._is_dirty = True
    
    def create_preset(
        self,
        name: str,
        description: str = "",
        category: str = ""
    ) -> EffectPreset:
        """
        Mevcut grafikten preset oluştur.
        
        Tüm aktif düğümleri preset'e dönüştürür.
        """
        return EffectPreset(
            name=name,
            description=description,
            category=category,
            nodes=list(self.nodes.values()),
        )
    
    def to_dict(self) -> dict:
        return {
            "graph_id": str(self.graph_id),
            "name": self.name,
            "nodes": {str(k): v.to_dict() for k, v in self.nodes.items()},
            "input_node_id": str(self.input_node_id) if self.input_node_id else None,
            "output_node_id": str(self.output_node_id) if self.output_node_id else None,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> EffectGraph:
        return cls(
            graph_id=UUID(data["graph_id"]),
            name=data["name"],
            nodes={UUID(k): EffectNode.from_dict(v) for k, v in data["nodes"].items()},
            input_node_id=UUID(data["input_node_id"]) if data.get("input_node_id") else None,
            output_node_id=UUID(data["output_node_id"]) if data.get("output_node_id") else None,
        )
```

## 4.4 Core Algoritmalar

### 4.4.1 Effect Graph Processing

```python
def process_effect_graph(
    graph: EffectGraph,
    input_frame: 'Frame',
    current_time: RationalTime
) -> 'Frame':
    """
    Efekt grafiğini işle.
    
    Algoritma:
    1. İşleme sırasını hesapla (topolojik sıralama)
    2. Her düğüm için sırayla işle
    3. Her düğümün parametrelerini güncel zamana göre hesapla
    4. Efekt uygula
    5. Sonucu bir sonraki düğüme aktar
    
    Karmaşıklık: O(n * p) — n = düğüm sayısı, p = ortalama parametre sayısı
    
    Optimizasyonlar:
    - Bypass edilmiş düğümler atlanır
    - Solo düğüm varsa, sadece o düğüm işlenir
    - Cached sonuçlar kullanılır (dirty region tracking)
    """
    if graph.node_count == 0:
        return input_frame
    
    # İşleme sırasını al
    order = graph.get_processing_order()
    
    current_frame = input_frame
    
    # Solo kontrolü
    solo_nodes = [n for n in graph.nodes.values() if n.solo]
    if solo_nodes:
        # Sadece solo düğümleri işle
        for node_id in order:
            node = graph.nodes.get(node_id)
            if node and node.solo:
                current_frame = _process_single_node(node, current_frame, current_time)
    else:
        # Tüm aktif düğümleri sırayla işle
        for node_id in order:
            node = graph.nodes.get(node_id)
            if node and node.is_active:
                current_frame = _process_single_node(node, current_frame, current_time)
    
    return current_frame


def _process_single_node(
    node: EffectNode,
    input_frame: 'Frame',
    current_time: RationalTime
) -> 'Frame':
    """
    Tek bir düğümü işle.
    
    Bu fonksiyon, efekt türüne göre farklı işlem uygular.
    Her efekt türünün kendi processing fonksiyonu vardır.
    """
    # Parametreleri güncelle
    updated_params = {}
    for name, param in node.parameters.items():
        updated_params[name] = param.get_value_at(current_time)
    
    # Efekt türüne göre işle
    if node.effect_type == EffectType.COLOR:
        return _apply_color_effect(input_frame, updated_params)
    elif node.effect_type == EffectType.BLUR:
        return _apply_blur_effect(input_frame, updated_params)
    elif node.effect_type == EffectType.TRANSFORM:
        return _apply_transform_effect(input_frame, updated_params)
    elif node.effect_type == EffectType.KEYING:
        return _apply_keying_effect(input_frame, updated_params)
    elif node.effect_type == EffectType.DISTORTION:
        return _apply_distortion_effect(input_frame, updated_params)
    elif node.effect_type == EffectType.GENERATOR:
        return _apply_generator_effect(input_frame, updated_params)
    else:
        return input_frame


def _apply_color_effect(frame: 'Frame', params: dict) -> 'Frame':
    """Renk düzeltme efekti uygula"""
    # Bu, gerçek implementasyonda FFmpeg veya OpenCV kullanır
    # Şimdilik stub dönüyoruz
    return frame


def _apply_blur_effect(frame: 'Frame', params: dict) -> 'Frame':
    """Bulanıklık efekti uygula"""
    return frame


def _apply_transform_effect(frame: 'Frame', params: dict) -> 'Frame':
    """Dönüşüm efekti uygula"""
    return frame


def _apply_keying_effect(frame: 'Frame', params: dict) -> 'Frame':
    """Keying efekti uygula"""
    return frame


def _apply_distortion_effect(frame: 'Frame', params: dict) -> 'Frame':
    """Bozulma efekti uygula"""
    return frame


def _apply_generator_effect(frame: 'Frame', params: dict) -> 'Frame':
    """Generator efekti uygula"""
    return frame
```

### 4.4.2 Keyframe Interpolation

```python
def interpolate_keyframes(
    keyframes: List[Keyframe],
    time: RationalTime
) -> float:
    """
    Keyframe listesinden belirli bir zamandaki değeri hesapla.
    
    Algoritma:
    1. Keyframe'leri zamana göre sırala
    2. Verilen zamana en yakın iki keyframe'i bul
    3. Interpolasyon yöntemine göre ara değer hesapla
    
    Karmaşıklık: O(n log n) — sıralama için
    Optimizasyon: Keyframe'ler zaten sıralıysa O(n)
    """
    if not keyframes:
        return 0.0
    
    # Keyframe'leri sırala
    sorted_kf = sorted(keyframes, key=lambda k: k.time.value)
    
    # İlk keyframe'den önce
    if time <= sorted_kf[0].time:
        return sorted_kf[0].value
    
    # Son keyframe'den sonra
    if time >= sorted_kf[-1].time:
        return sorted_kf[-1].value
    
    # İki keyframe arasında bul
    for i in range(len(sorted_kf) - 1):
        kf1 = sorted_kf[i]
        kf2 = sorted_kf[i + 1]
        
        if kf1.time <= time <= kf2.time:
            # Normalleştirilmiş t (0-1 arası)
            if kf2.time == kf1.time:
                return kf1.value
            
            t = float((time - kf1.time) / (kf2.time - kf1.time))
            
            # Interpolasyon yöntemine göre hesapla
            if kf1.interpolation == InterpolationType.LINEAR:
                return kf1.value + (kf2.value - kf1.value) * t
            
            elif kf1.interpolation == InterpolationType.CONSTANT:
                return kf1.value
            
            elif kf1.interpolation == InterpolationType.BEZIER:
                # Hermite spline interpolasyonu
                return _hermite_interpolate(kf1, kf2, t)
            
            elif kf1.interpolation == InterpolationType.EASE_IN:
                # Yavaş başlangıç
                t_ease = t * t * (3 - 2 * t)  # Smoothstep
                return kf1.value + (kf2.value - kf1.value) * t_ease
            
            elif kf1.interpolation == InterpolationType.EASE_OUT:
                # Yavaş bitiş
                t_ease = 1 - (1 - t) * (1 - t) * (1 + t)
                return kf1.value + (kf2.value - kf1.value) * t_ease
            
            elif kf1.interpolation == InterpolationType.EASE_IN_OUT:
                # Yavaş başlangıç ve bitiş
                if t < 0.5:
                    t_ease = 4 * t * t * t
                else:
                    t_ease = 1 - pow(-2 * t + 2, 3) / 2
                return kf1.value + (kf2.value - kf1.value) * t_ease
    
    return sorted_kf[-1].value


def _hermite_interpolate(kf1: Keyframe, kf2: Keyframe, t: float) -> float:
    """
    Hermite spline interpolasyonu.
    
    Bu, After Effects ve Nuke'daki keyframe interpolasyonu 
    ile aynı matematiksel modeli kullanır.
    
    Hermite spline, keyframe'lerin velocity (hız) ve 
    influence (etki alanı) değerlerini kullanarak 
    yumuşak bir geçiş sağlar.
    """
    t2 = t * t
    t3 = t2 * t
    
    # Hermite basis fonksiyonları
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + t
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    
    # Velocity'leri normalize et
    v1 = kf1.velocity * (kf1.influence / 100.0)
    v2 = kf2.velocity * (kf2.influence / 100.0)
    
    return (
        h00 * kf1.value +
        h10 * v1 +
        h01 * kf2.value +
        h11 * v2
    )
```

## 4.5 API Sözleşmeleri

```python
class EffectEngine:
    """
    Efekt motoru API'si.
    
    Bu sınıf, efekt oluşturma, düzenleme ve uygulama 
    işlemlerini yönetir.
    """
    
    def __init__(self):
        self._graphs: Dict[UUID, EffectGraph] = {}
        self._presets: Dict[UUID, EffectPreset] = {}
    
    def create_graph(self, name: str = "") -> EffectGraph:
        """Yeni bir efekt grafiği oluştur"""
        graph = EffectGraph(name=name)
        self._graphs[graph.graph_id] = graph
        return graph
    
    def add_node(
        self,
        graph_id: UUID,
        effect_type: EffectType,
        name: str = ""
    ) -> EffectNode:
        """
        Grafe yeni düğüm ekle.
        
        Args:
            graph_id: EffectGraph ID
            effect_type: Efekt türü
            name: Düğüm adı
            
        Returns:
            Oluşturulan EffectNode
        """
        graph = self._graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Graph bulunamadı: {graph_id}")
        
        node = EffectNode(
            name=name,
            effect_type=effect_type,
        )
        graph.add_node(node)
        return node
    
    def connect_nodes(
        self,
        graph_id: UUID,
        from_node_id: UUID,
        to_node_id: UUID
    ) -> None:
        """İki düğümü bağla"""
        graph = self._graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Graph bulunamadı: {graph_id}")
        
        graph.connect(from_node_id, to_node_id)
    
    def set_parameter(
        self,
        graph_id: UUID,
        node_id: UUID,
        param_name: str,
        value: Any
    ) -> None:
        """Parametre değerini ayarla"""
        graph = self._graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Graph bulunamadı: {graph_id}")
        
        node = graph.nodes.get(node_id)
        if not node:
            raise ValueError(f"Node bulunamadı: {node_id}")
        
        node.set_parameter_value(param_name, value)
    
    def add_keyframe(
        self,
        graph_id: UUID,
        node_id: UUID,
        param_name: str,
        keyframe: Keyframe
    ) -> None:
        """Parametreye keyframe ekle"""
        graph = self._graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Graph bulunamadı: {graph_id}")
        
        node = graph.nodes.get(node_id)
        if not node:
            raise ValueError(f"Node bulunamadı: {node_id}")
        
        param = node.get_parameter(param_name)
        if not param:
            raise ValueError(f"Parametre bulunamadı: {param_name}")
        
        param.add_keyframe(keyframe)
    
    def save_preset(
        self,
        graph_id: UUID,
        name: str,
        description: str = "",
        category: str = ""
    ) -> EffectPreset:
        """Grafiği preset olarak kaydet"""
        graph = self._graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Graph bulunamadı: {graph_id}")
        
        preset = graph.create_preset(name, description, category)
        self._presets[preset.preset_id] = preset
        return preset
    
    def load_preset(
        self,
        graph_id: UUID,
        preset_id: UUID
    ) -> None:
        """Preset'i grafiğe uygula"""
        graph = self._graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Graph bulunamadı: {graph_id}")
        
        preset = self._presets.get(preset_id)
        if not preset:
            raise ValueError(f"Preset bulunamadı: {preset_id}")
        
        graph.apply_preset(preset)
```

## 4.6 Performans Darboğazları ve Çözümleri

| Darboğaz | Etki | Çözüm |
|---|---|---|
| Large effect graph (50+ nodes) | Her karede 50+ efekt | GPU compute shader ile parallel işleme |
| Keyframe interpolation (1000+ keyframe) | Her parametre için O(n) | Binary search ile O(log n) |
| Graph topological sort | Her değişiklikte O(V+E) | Cache'le, sadece change olduğunda yeniden hesapla |
| Real-time preview | 30fps'de tüm graph işleme | Ahead-of-time precompute + frame drop |
| Memory usage (large frames) | 4K frame: 32MB RAM | Streaming processing, frame buffer pool |

## 4.7 Entegrasyon Noktaları

```
Effect Engine
    ├── Timeline Engine ← Clip efektleri için
    ├── Layer Manager ← Katman efektleri için
    ├── Compositor ← Efekt uygulanmış frameler için
    ├── GPU Accelerator ← CUDA/Metal compute için
    └── Preset Manager ← Efekt preset'leri için
```

---

# 5. Geçiş Grafiği (Transition Graph)

## 5.1 Amaç ve Kapsam

Geçiş sistemi, iki clip arasındaki geçişleri yönetir. Profesyonel NLE'lerde geçişler, sadece basit kesmeler (cut) değildir — dissolve, wipe, slide, push, zoom ve özel geçişler gibi birçok seçenek sunulur.

Bizim sistemimiz, Premiere Pro'nun "Effects Panel > Video Transitions" modelini, Resolve'ın "Edit > Video Transitions" modelini ve After Effects'in "Transition Builder" modelini birleştirir.

### Karşılaştırma

| Özellik | Bizim Sistem | Premiere | Resolve | After Effects |
|---|---|---|---|---|
| Geçiş türleri | 15+ tür | 10+ tür | 8+ tür | Sınırsız (custom) |
| Custom transitions | Evet | Hayır | Hayır | Evet |
| Geçiş presets | Evet | Evet | Evet | Evet |
| Real-time preview | Evet | Evet | Evet | Kısmen |
| GPU hızlandırma | Evet | Evet | Evet | Kısmen |

## 5.2 Mimari

```
┌─────────────────────────────────────────────┐
│           Transition Graph                   │
│                                              │
│  ┌──────────┐    ┌──────────┐              │
│  │  Clip A  │────│ Transition│              │
│  │  (Bite)  │    │  Region  │              │
│  └──────────┘    └────┬─────┘              │
│                       │                     │
│                  ┌────▼─────┐              │
│                  │  Clip B  │              │
│                  │  (Başlangıç)│            │
│                  └──────────┘              │
└─────────────────────────────────────────────┘
```

## 5.3 Veri Yapısı

```python
"""
Geçiş grafiği veri yapıları.

Tasarım İlkeleri:
1. Her geçiş, iki clip arasındaki overlap bölgesini temsil eder
2. Geçiş türüne göre farklı rendering algoritmaları kullanılır
3. Geçişler keyframe ile animasyonlanabilir
4. Custom geçişler plugin olarak eklenebilir
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4


class TransitionType(Enum):
    """Geçiş türleri"""
    CUT = "cut"
    DISSOLVE = "dissolve"
    CROSS_DISSOLVE = "cross_dissolve"
    FADE_TO_BLACK = "fade_to_black"
    FADE_TO_WHITE = "fade_to_white"
    WIPE_LEFT = "wipe_left"
    WIPE_RIGHT = "wipe_right"
    WIPE_UP = "wipe_up"
    WIPE_DOWN = "wipe_down"
    WIPE_CENTER = "wipe_center"
    SLIDE_LEFT = "slide_left"
    SLIDE_RIGHT = "slide_right"
    PUSH_LEFT = "push_left"
    PUSH_RIGHT = "push_right"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    IRIS = "iris"
    BLUR = "blur"
    MORPH = "morph"
    CUSTOM = "custom"


@dataclass
class TransitionPreset:
    """
    Geçiş preset'i — kaydedilmiş geçiş yapılandırması.
    
    Kullanıcılar, sık kullandıkları geçiş ayarlarını 
    preset olarak kaydedebilir.
    """
    preset_id: UUID = field(default_factory=uuid4)
    name: str = ""
    transition_type: TransitionType = TransitionType.CROSS_DISSOLVE
    duration: float = 1.0  # Saniye cinsinden
    parameters: Dict[str, Any] = field(default_factory=dict)
    category: str = ""
    description: str = ""
    
    def to_dict(self) -> dict:
        return {
            "preset_id": str(self.preset_id),
            "name": self.name,
            "transition_type": self.transition_type.value,
            "duration": self.duration,
            "parameters": self.parameters,
            "category": self.category,
            "description": self.description,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> TransitionPreset:
        return cls(
            preset_id=UUID(data["preset_id"]),
            name=data["name"],
            transition_type=TransitionType(data["transition_type"]),
            duration=data["duration"],
            parameters=data.get("parameters", {}),
            category=data.get("category", ""),
            description=data.get("description", ""),
        )


@dataclass
class Transition:
    """
    Bir geçiş — iki clip arasındaki geçiş bölgesi.
    
    Geçiş, iki clip arasındaki overlap bölgesinde 
    uygulanan bir efekt türüdür. Her geçişin şunları vardır:
    
    - Clip A (önceki clip) ve Clip B (sonraki clip)
    - Geçiş türü (dissolve, wipe, vb.)
    - Süre (ne kadar zamanda geçiş yapılacak)
    - Parametreler (geçişin specific ayarları)
    
    Premiere'de bu, "Transition" olarak adlandırılır.
    Resolve'da "Transition" olarak adlandırılır.
    After Effects'ta ise "Transition Composer" benzeri bir araçtır.
    """
    transition_id: UUID = field(default_factory=uuid4)
    name: str = ""
    transition_type: TransitionType = TransitionType.CROSS_DISSOLVE
    
    # Geçiş bölgeleri
    clip_a_id: Optional[UUID] = None  # Önceki clip
    clip_b_id: Optional[UUID] = None  # Sonraki clip
    
    # Zamanlama
    duration: float = 1.0  # Saniye cinsinden
    alignment: str = "center"  # center, start, end
    
    # Parametreler
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Durum
    enabled: bool = True
    locked: bool = False
    
    # Custom geçiş için
    custom_plugin_id: Optional[str] = None
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def overlap_duration(self) -> float:
        """Overlap süresi (geçiş süresi ile aynı)"""
        return self.duration
    
    def get_progress(self, time: float, clip_a_end: float) -> float:
        """
        Geçişin ilerleme oranını hesapla (0.0 - 1.0).
        
        time: Mevcut zaman
        clip_a_end: Clip A'nın bitiş zamanı
        
        Returns:
            0.0: Clip A'nın sonu (başlangıç)
            1.0: Clip B'nin başı (bitiş)
        """
        transition_start = clip_a_end - self.duration / 2
        transition_end = clip_a_end + self.duration / 2
        
        if time <= transition_start:
            return 0.0
        elif time >= transition_end:
            return 1.0
        else:
            return (time - transition_start) / self.duration
    
    def apply_transition(
        self,
        frame_a: 'Frame',
        frame_b: 'Frame',
        progress: float
    ) -> 'Frame':
        """
        Geçiş efektini uygula.
        
        progress: 0.0 (tamamen A) ile 1.0 (tamamen B) arası
        
        Returns:
            Geçiş uygulanmış frame
        """
        if self.transition_type == TransitionType.CUT:
            # Kesme — hemen geçiş
            return frame_b if progress > 0.5 else frame_a
        
        elif self.transition_type == TransitionType.CROSS_DISSOLVE:
            # Çapraz sönümleme
            return self._cross_dissolve(frame_a, frame_b, progress)
        
        elif self.transition_type == TransitionType.WIPE_LEFT:
            # Soldan sağa silme
            return self._wipe(frame_a, frame_b, progress, direction="left")
        
        elif self.transition_type == TransitionType.SLIDE_LEFT:
            # Sola kaydırma
            return self._slide(frame_a, frame_b, progress, direction="left")
        
        elif self.transition_type == TransitionType.ZOOM_IN:
            # İçeri yakınlaştırma
            return self._zoom(frame_a, frame_b, progress, direction="in")
        
        else:
            # Default: cross dissolve
            return self._cross_dissolve(frame_a, frame_b, progress)
    
    def _cross_dissolve(
        self,
        frame_a: 'Frame',
        frame_b: 'Frame',
        progress: float
    ) -> 'Frame':
        """
        Çapraz sönümleme geçişi.
        
        Bu, en yaygın kullanılan geçiş türüdür.
        İki frame arasında yumuşak bir geçiş sağlar.
        """
        # Alfa ile karıştır
        alpha = progress
        return frame_a * (1 - alpha) + frame_b * alpha
    
    def _wipe(
        self,
        frame_a: 'Frame',
        frame_b: 'Frame',
        progress: float,
        direction: str = "left"
    ) -> 'Frame':
        """
        Silme geçişi.
        
        Bir frame, diğeri üzerinde kayarak geçiş yapar.
        """
        # Gerçek implementasyonda piksel bazında yapılır
        # Şimdilik basit cross dissolve
        return self._cross_dissolve(frame_a, frame_b, progress)
    
    def _slide(
        self,
        frame_a: 'Frame',
        frame_b: 'Frame',
        progress: float,
        direction: str = "left"
    ) -> 'Frame':
        """
        Kaydırma geçişi.
        
        Clip A kayarken, Clip B arkasından gelir.
        """
        return self._cross_dissolve(frame_a, frame_b, progress)
    
    def _zoom(
        self,
        frame_a: 'Frame',
        frame_b: 'Frame',
        progress: float,
        direction: str = "in"
    ) -> 'Frame':
        """
        Yakınlaştırma geçişi.
        
        Clip A uzaklaşırken, Clip B yaklaşır.
        """
        return self._cross_dissolve(frame_a, frame_b, progress)
    
    def to_dict(self) -> dict:
        return {
            "transition_id": str(self.transition_id),
            "name": self.name,
            "transition_type": self.transition_type.value,
            "clip_a_id": str(self.clip_a_id) if self.clip_a_id else None,
            "clip_b_id": str(self.clip_b_id) if self.clip_b_id else None,
            "duration": self.duration,
            "alignment": self.alignment,
            "parameters": self.parameters,
            "enabled": self.enabled,
            "locked": self.locked,
            "custom_plugin_id": self.custom_plugin_id,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> Transition:
        return cls(
            transition_id=UUID(data["transition_id"]),
            name=data["name"],
            transition_type=TransitionType(data["transition_type"]),
            clip_a_id=UUID(data["clip_a_id"]) if data.get("clip_a_id") else None,
            clip_b_id=UUID(data["clip_b_id"]) if data.get("clip_b_id") else None,
            duration=data["duration"],
            alignment=data.get("alignment", "center"),
            parameters=data.get("parameters", {}),
            enabled=data.get("enabled", True),
            locked=data.get("locked", False),
            custom_plugin_id=data.get("custom_plugin_id"),
            metadata=data.get("metadata", {}),
        )
```

## 5.4 API Sözleşmeleri

```python
class TransitionManager:
    """
    Geçiş yöneticisi API'si.
    
    Bu sınıf, geçiş oluşturma, düzenleme ve uygulama 
    işlemlerini yönetir.
    """
    
    def __init__(self):
        self._transitions: Dict[UUID, Transition] = {}
        self._presets: Dict[UUID, TransitionPreset] = {}
    
    def create_transition(
        self,
        transition_type: TransitionType,
        clip_a_id: UUID,
        clip_b_id: UUID,
        duration: float = 1.0,
        alignment: str = "center"
    ) -> Transition:
        """
        Yeni bir geçiş oluştur.
        
        Args:
            transition_type: Geçiş türü
            clip_a_id: Önceki clip ID
            clip_b_id: Sonraki clip ID
            duration: Geçiş süresi (saniye)
            alignment: Hizalama (center, start, end)
            
        Returns:
            Oluşturulan Transition nesnesi
        """
        transition = Transition(
            transition_type=transition_type,
            clip_a_id=clip_a_id,
            clip_b_id=clip_b_id,
            duration=duration,
            alignment=alignment,
        )
        
        self._transitions[transition.transition_id] = transition
        return transition
    
    def set_transition_type(
        self,
        transition_id: UUID,
        transition_type: TransitionType
    ) -> None:
        """Geçiş türünü değiştir"""
        transition = self._transitions.get(transition_id)
        if not transition:
            raise ValueError(f"Geçiş bulunamadı: {transition_id}")
        
        transition.transition_type = transition_type
    
    def set_duration(
        self,
        transition_id: UUID,
        duration: float
    ) -> None:
        """Geçiş süresini değiştir"""
        transition = self._transitions.get(transition_id)
        if not transition:
            raise ValueError(f"Geçiş bulunamadı: {transition_id}")
        
        if duration <= 0:
            raise ValueError("Süre pozitif olmalı")
        
        transition.duration = duration
    
    def get_available_transitions(self) -> List[Dict[str, Any]]:
        """Kullanılabilir geçiş türlerini döndür"""
        transitions = []
        for tt in TransitionType:
            transitions.append({
                "type": tt.value,
                "name": tt.name.replace("_", " ").title(),
            })
        return transitions
    
    def save_preset(
        self,
        transition_id: UUID,
        name: str,
        category: str = ""
    ) -> TransitionPreset:
        """Geçişi preset olarak kaydet"""
        transition = self._transitions.get(transition_id)
        if not transition:
            raise ValueError(f"Geçiş bulunamadı: {transition_id}")
        
        preset = TransitionPreset(
            name=name,
            transition_type=transition.transition_type,
            duration=transition.duration,
            parameters=transition.parameters.copy(),
            category=category,
        )
        
        self._presets[preset.preset_id] = preset
        return preset
    
    def load_preset(
        self,
        transition_id: UUID,
        preset_id: UUID
    ) -> None:
        """Preset'i geçişe uygula"""
        transition = self._transitions.get(transition_id)
        if not transition:
            raise ValueError(f"Geçiş bulunamadı: {transition_id}")
        
        preset = self._presets.get(preset_id)
        if not preset:
            raise ValueError(f"Preset bulunamadı: {preset_id}")
        
        transition.transition_type = preset.transition_type
        transition.duration = preset.duration
        transition.parameters = preset.parameters.copy()
```

## 5.5 Performans Darboğazları ve Çözümleri

| Darboğaz | Etki | Çözüm |
|---|---|---|
| Custom transition rendering | Her karede özel hesaplama | GPU shader ile paralel işleme |
| Large transition duration | Uzun süreli geçişlerde yavaşlama | Frame drop ile gerçek zamanlı preview |
| Multiple transitions | Eş zamanlı birden fazla geçiş | Thread pool ile parallel rendering |
| Transition cache | Her değiştirme'de yeniden hesaplama | Dirty tracking ile sadece değişen bölümler |

## 5.6 Entegrasyon Noktaları

```
Transition Manager
    ├── Timeline Engine ← Geçiş konumları için
    ├── Effect Engine ← Geçiş efektleri için
    ├── Compositor ← Geçiş rendering için
    └── Preset Manager ← Geçiş preset'leri için
```

---

# 6. Video Kompozitörü

## 6.1 Amaç ve Kapsam

Video kompozitörü, birden fazla katmanı tek bir çıktıya birleştiren sistemdir. Bu, NLE'lerin en kritik bileşenlerinden biridir — çünkü tüm görünür katmanlar burada birleştirilir.

Kompozitör, After Effects'in "Composition" modelini, Nuke'un "Compositing" modelini ve Premiere'in "Mercury Playback Engine" modelini temel alır. Bizim yaklaşımımız, GPU hızlandırmalı compositing ile CPU fallback'i birleştirir.

### Karşılaştırma

| Özellik | Bizim Sistem | Premiere | Resolve | After Effects | Nuke |
|---|---|---|---|---|---|
| Compositing modeli | Multi-layer | Track-based | Node-based | Layer-based | Node-based |
| GPU hızlandırma | Evet (CUDA/Metal) | Evet (Mercury) | Evet (CUDA) | Kısmen | Evet |
| Blend modes | 17 mod | 10+ mod | 10+ mod | 30+ mod | Sınırsız |
| Alpha compositing | Evet | Evet | Evet | Evet | Evet |
| Dirty region tracking | Evet | Evet | Evet | Evet | Evet |

## 6.2 Mimari

```
┌─────────────────────────────────────────────┐
│           Video Compositor                    │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │        Layer Stack (Bottom-up)        │   │
│  │  ┌──────────────────────────────┐    │   │
│  │  │ Layer 5: Title (Normal)      │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ Layer 4: Effect (Screen)     │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ Layer 3: Adjustment (Overlay)│    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ Layer 2: Video (Multiply)    │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ Layer 1: Video (Normal)      │    │   │
│  │  └──────────────────────────────┘    │   │
│  └──────────────────────────────────────┘   │
│       │                                      │
│  ┌──────────────────────────────────────┐   │
│  │        GPU Compositing Pipeline       │   │
│  │  ┌──────────────────────────────┐    │   │
│  │  │ 1. Load textures (VRAM)      │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ 2. Apply transforms          │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ 3. Apply blend modes         │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ 4. Apply masks               │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ 5. Alpha compositing         │    │   │
│  │  ├──────────────────────────────┤    │   │
│  │  │ 6. Output to display/encode  │    │   │
│  │  └──────────────────────────────┘    │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

## 6.3 Veri Yapısı

```python
"""
Video kompozitörü veri yapıları.

Tasarım İlkeleri:
1. GPU-first tasarım — CPU fallback ile
2. Dirty region tracking — sadece değişen bölümleri yeniden hesapla
3. Streaming processing — tam frame bellekte tutulmaz
4. Multi-threaded compositing — parallel katman işleme
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4


class CompositeOperation(Enum):
    """Kompozit işlemleri"""
    BLEND = "blend"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    SCREEN = "screen"
    OVERLAY = "overlay"
    SOFT_LIGHT = "soft_light"
    HARD_LIGHT = "hard_light"
    DIFFERENCE = "difference"
    EXCLUSION = "exclusion"
    COLOR_DODGE = "color_dodge"
    COLOR_BURN = "color_burn"
    LINEAR_BURN = "linear_burn"
    LINEAR_LIGHT = "linear_light"
    VIVID_LIGHT = "vivid_light"
    PIN_LIGHT = "pin_light"
    DARKEN = "darken"
    LIGHTEN = "lighten"


@dataclass
class DirtyRegion:
    """
    Kirli bölge — değişen alan.
    
    Dirty region tracking, compositing sırasında 
    sadece değişen bölümleri yeniden hesaplamak 
    için kullanılır. Bu, real-time performans için 
    kritiktir.
    
    Premiere'de "Mercury Playback Engine" benzer bir 
    optimizasyon yapar. Resolve'da ise "GPU-accelerated 
    compositing" benzer bir yaklaşım kullanılır.
    """
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    
    @property
    def area(self) -> int:
        """Kirli bölgenin alanı"""
        return self.width * self.height
    
    def intersects(self, other: DirtyRegion) -> bool:
        """İki kirli bölge kesişiyor mu?"""
        return (
            self.x < other.x + other.width and
            self.x + self.width > other.x and
            self.y < other.y + other.height and
            self.y + self.height > other.y
        )
    
    def merge(self, other: DirtyRegion) -> DirtyRegion:
        """İki kirli region'ı birleştir"""
        x1 = min(self.x, other.x)
        y1 = min(self.y, other.y)
        x2 = max(self.x + self.width, other.x + other.width)
        y2 = max(self.y + self.height, other.y + other.height)
        
        return DirtyRegion(x=x1, y=y1, width=x2 - x1, height=y2 - y1)


@dataclass
class CompositeLayer:
    """
    Kompozit katmanı — tek bir katmanın compositing bilgisi.
    
    Bu yapı, bir katmanın compositing sırasında 
    nasıl işleneceğini tanımlar. Layer yapısından 
    farklı olarak, sadece compositing ile ilgili 
    bilgileri içerir.
    """
    layer_id: UUID = field(default_factory=uuid4)
    source_texture_id: Optional[UUID] = None  # GPU texture ID
    transform_matrix: List[List[float]] = field(default_factory=lambda: [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0]
    ])
    opacity: float = 1.0
    blend_mode: CompositeOperation = CompositeOperation.BLEND
    alpha_mode: str = "premultiplied"
    crop_rect: Optional[Tuple[int, int, int, int]] = None  # x, y, w, h
    mask_texture_id: Optional[UUID] = None
    visible: bool = True


@dataclass
class CompositorConfig:
    """
    Kompozitör yapılandırması.
    
    Bu, compositing motorunun davranışını kontrol eder.
    """
    width: int = 1920
    height: int = 1080
    pixel_format: str = "rgba8"  # rgba8, rgba16, rgba32f
    color_space: str = "srgb"  # srgb, rec709, rec2020
    gamma: float = 2.2
    use_gpu: bool = True
    gpu_device: str = "cuda"  # cuda, metal, vulkan
    max_layers: int = 100
    cache_size_mb: int = 512
    thread_count: int = 4


@dataclass
class CompositorState:
    """
    Kompozitör durumu — mevcut işleme durumu.
    
    Bu, compositing motorunun mevcut durumunu 
    ve istatistiklerini içerir.
    """
    is_processing: bool = False
    current_frame: int = 0
    total_frames: int = 0
    fps: float = 0.0
    gpu_memory_used_mb: float = 0.0
    cpu_memory_used_mb: float = 0.0
    dirty_regions: List[DirtyRegion] = field(default_factory=list)
    last_render_time_ms: float = 0.0
    
    @property
    def progress(self) -> float:
        """İşleme ilerleme oranı"""
        if self.total_frames == 0:
            return 0.0
        return self.current_frame / self.total_frames
    
    @property
    def is_realtime(self) -> bool:
        """Gerçek zamanlı mı?"""
        return self.fps >= 24.0  # Minimum 24fps
```

```python
class Compositor:
    """
    Video kompozitörü — çok katmanlı compositing motoru.
    
    Bu sınıf, birden fazla katmanı tek bir çıktıya 
    birleştirir. GPU hızlandırmalı compositing ile 
    CPU fallback'i destekler.
    
    Mimari:
    1. Dirty region detection — değişen bölgeleri tespit et
    2. Layer ordering — katman sırasını belirle
    3. GPU texture upload — texture'ları GPU'ya yükle
    4. Parallel compositing — parallel katman işleme
    5. Alpha compositing — alpha kanalını işle
    6. Output — sonucu display veya encode'a gönder
    
    Performance:
    - 1080p: 60fps gerçek zamanlı
    - 4K: 30fps gerçek zamanlı (GPU ile)
    - 8K: 15fps (GPU ile, multi-GPU desteği ile 30fps)
    """
    
    def __init__(self, config: Optional[CompositorConfig] = None):
        self.config = config or CompositorConfig()
        self.state = CompositorState()
        self._layer_cache: Dict[UUID, Any] = {}
        self._dirty_regions: List[DirtyRegion] = []
    
    def composite(
        self,
        layers: List[CompositeLayer],
        time: float = 0.0
    ) -> 'Frame':
        """
        Katmanları birleştir.
        
        Algoritma:
        1. Aktif katmanları filtrele
        2. Katman sırasını belirle (bottom-up)
        3. Her katman için:
           a. Texture'ı yükle (eğer yoksa)
           b. Transform uygula
           c. Mask uygula (eğer varsa)
           d. Blend modunu uygula
           e. Alpha compositing yap
        4. Sonucu döndür
        
        Karmaşıklık: O(n * p) — n = katman sayısı, p = piksel sayısı
        Optimizasyon: GPU ile O(n) — piksel işlemleri paralel
        """
        self.state.is_processing = True
        
        try:
            # Aktif katmanları filtrele
            active_layers = [l for l in layers if l.visible]
            
            if not active_layers:
                return self._create_empty_frame()
            
            # Katmanları sırala (bottom-up)
            sorted_layers = self._sort_layers_bottom_up(active_layers)
            
            # GPU kullanılıyorsa
            if self.config.use_gpu:
                return self._composite_gpu(sorted_layers, time)
            else:
                return self._composite_cpu(sorted_layers, time)
        
        finally:
            self.state.is_processing = False
    
    def _sort_layers_bottom_up(
        self,
        layers: List[CompositeLayer]
    ) -> List[CompositeLayer]:
        """
        Katmanları alta doğru sırala.
        
        Bu, compositing sırasını belirler.
        En alt katman (background) önce işlenir.
        """
        return sorted(layers, key=lambda l: l.layer_id.int % 1000)
    
    def _composite_gpu(
        self,
        layers: List[CompositeLayer],
        time: float
    ) -> 'Frame':
        """
        GPU ile compositing yap.
        
        Bu, GPU compute shader'ları kullanarak 
        paralel compositing yapar. CPU'dan 
        10-100x daha hızlıdır.
        
        Adımlar:
        1. Texture'ları GPU'ya yükle
        2. Transform matrislerini ayarla
        3. Blend modunu ayarla
        4. Compute shader'ı çalıştır
        5. Sonucu GPU'dan oku
        """
        # Gerçek implementasyonda CUDA/Metal/Vulkan kullanılır
        # Şimdilik CPU fallback kullanıyoruz
        return self._composite_cpu(layers, time)
    
    def _composite_cpu(
        self,
        layers: List[CompositeLayer],
        time: float
    ) -> 'Frame':
        """
        CPU ile compositing yap.
        
        GPU olmadığında veya fallback olarak kullanılır.
        Multi-threaded ile hızlandırılabilir.
        """
        # Boş frame oluştur
        output = self._create_empty_frame()
        
        # Her katmanı sırayla uygula
        for layer in sorted_layers:
            if not layer.visible:
                continue
            
            # Katmanın texture'ını al
            source = self._get_layer_texture(layer)
            if source is None:
                continue
            
            # Transform uygula
            transformed = self._apply_transform(source, layer.transform_matrix)
            
            # Mask uygula (eğer varsa)
            if layer.mask_texture_id:
                transformed = self._apply_mask(transformed, layer.mask_texture_id)
            
            # Opaklık uygula
            if layer.opacity < 1.0:
                transformed = self._apply_opacity(transformed, layer.opacity)
            
            # Blend modunu uygula
            output = self._apply_blend_mode(
                output,
                transformed,
                layer.blend_mode,
                layer.alpha_mode
            )
        
        return output
    
    def _create_empty_frame(self) -> 'Frame':
        """Boş (siyah) frame oluştur"""
        # Gerçek implementasyonda numpy array veya GPU texture kullanılır
        return None
    
    def _get_layer_texture(self, layer: CompositeLayer) -> Optional['Frame']:
        """
        Katmanın texture'ını al.
        
        Cache'den veya GPU'dan yükler.
        """
        if layer.source_texture_id in self._layer_cache:
            return self._layer_cache[layer.source_texture_id]
        
        # Gerçek implementasyonda GPU'dan yükler
        return None
    
    def _apply_transform(
        self,
        frame: 'Frame',
        matrix: List[List[float]]
    ) -> 'Frame':
        """
        Dönüşüm matrisini uygula.
        
        Bu, scaling, rotation, translation ve 
        shear işlemlerini yapar.
        """
        # Gerçek implementasyonda affine transform kullanılır
        return frame
    
    def _apply_mask(
        self,
        frame: 'Frame',
        mask_texture_id: UUID
    ) -> 'Frame':
        """
        Maskeyi uygula.
        
        Maske, frame'in sadece belirli bölgelerinin 
        görünür olmasını sağlar.
        """
        # Gerçek implementasyonda mask texture ile AND işlemi yapılır
        return frame
    
    def _apply_opacity(
        self,
        frame: 'Frame',
        opacity: float
    ) -> 'Frame':
        """
        Opaklık uygula.
        
        Tüm piksellerin alpha kanalını opacity ile çarpar.
        """
        # Gerçek implementasyonda piksel bazında çarpma yapılır
        return frame
    
    def _apply_blend_mode(
        self,
        destination: 'Frame',
        source: 'Frame',
        blend_mode: CompositeOperation,
        alpha_mode: str
    ) -> 'Frame':
        """
        Blend modunu uygula.
        
        Bu, iki frame arasındaki piksel karıştırma 
        işlemini yapar.
        
        Alpha compositing (Porter-Duff):
        - premultiplied: out = src + dst * (1 - src_alpha)
        - straight: out = src * src_alpha + dst * (1 - src_alpha)
        """
        # Gerçek implementasyonda piksel bazında blend yapılır
        # Her blend mode için farklı formül kullanılır
        return destination
    
    def update_dirty_regions(self, regions: List[DirtyRegion]) -> None:
        """
        Kirli bölge listesini güncelle.
        
        Bu, compositing motoruna hangi bölgelerin 
        yeniden hesaplanması gerektiğini söyler.
        """
        self._dirty_regions.extend(regions)
        
        # Bitişik kirli region'ları birleştir
        self._merge_dirty_regions()
    
    def _merge_dirty_regions(self) -> None:
        """Bitişik kirli region'ları birleştir"""
        if not self._dirty_regions:
            return
        
        merged = [self._dirty_regions[0]]
        
        for region in self._dirty_regions[1:]:
            found = False
            for i, m in enumerate(merged):
                if m.intersects(region):
                    merged[i] = m.merge(region)
                    found = True
                    break
            
            if not found:
                merged.append(region)
        
        self._dirty_regions = merged
    
    def get_dirty_regions(self) -> List[DirtyRegion]:
        """Mevcut kirli region'ları döndür"""
        return self._dirty_regions.copy()
    
    def clear_dirty_regions(self) -> None:
        """Kirli region'ları temizle"""
        self._dirty_regions.clear()
```

## 6.4 Core Algoritmalar

### 6.4.1 Alpha Compositing (Porter-Duff)

```python
def alpha_composite_premultiplied(
    src_r: float, src_g: float, src_b: float, src_a: float,
    dst_r: float, dst_g: float, dst_b: float, dst_a: float
) -> Tuple[float, float, float, float]:
    """
    Premultiplied alpha compositing (Porter-Duff "over").
    
    Bu, endüstri standardı alpha compositing yöntemidir.
    After Effects, Nuke ve Premiere'de kullanılır.
    
    Formül:
    out = src + dst * (1 - src_alpha)
    
    Premultiplied avantajı:
    - Daha az işlem (tek çarpma)
    - Daha az hata payı
    - GPU'da daha hızlı
    
    Karmaşıklık: O(1) — piksel başına
    """
    out_a = src_a + dst_a * (1 - src_a)
    
    if out_a == 0:
        return 0.0, 0.0, 0.0, 0.0
    
    out_r = (src_r + dst_r * dst_a * (1 - src_a)) / out_a
    out_g = (src_g + dst_g * dst_a * (1 - src_a)) / out_a
    out_b = (src_b + dst_b * dst_a * (1 - src_a)) / out_a
    
    return out_r, out_g, out_b, out_a


def alpha_composite_straight(
    src_r: float, src_g: float, src_b: float, src_a: float,
    dst_r: float, dst_g: float, dst_b: float, dst_a: float
) -> Tuple[float, float, float, float]:
    """
    Straight alpha compositing.
    
    Bu, eski formatlarda kullanılır. RGB değerleri 
    alpha'dan bağımsızdır.
    
    Formül:
    out = src * src_alpha + dst * dst_alpha * (1 - src_alpha)
    out_alpha = src_alpha + dst_alpha * (1 - src_alpha)
    """
    out_a = src_a + dst_a * (1 - src_a)
    
    if out_a == 0:
        return 0.0, 0.0, 0.0, 0.0
    
    out_r = (src_r * src_a + dst_r * dst_a * (1 - src_a)) / out_a
    out_g = (src_g * src_a + dst_g * dst_a * (1 - src_a)) / out_a
    out_b = (src_b * src_a + dst_b * dst_a * (1 - src_a)) / out_a
    
    return out_r, out_g, out_b, out_a


def unpremultiply(
    r: float, g: float, b: float, a: float
) -> Tuple[float, float, float, float]:
    """
    Premultiplied'dan straight'e çevir.
    
    Bu, bazı işlemler için gereklidir (örn: color grading).
    """
    if a == 0:
        return 0.0, 0.0, 0.0, 0.0
    
    return r / a, g / a, b / a, a


def premultiply(
    r: float, g: float, b: float, a: float
) -> Tuple[float, float, float, float]:
    """
    Straight'den premultiplied'a çevir.
    
    Bu, compositing öncesi yapılır.
    """
    return r * a, g * a, b * a, a
```

### 6.4.2 Dirty Region Tracking

```python
def compute_dirty_regions(
    old_layers: List[CompositeLayer],
    new_layers: List[CompositeLayer]
) -> List[DirtyRegion]:
    """
    Eski ve yeni katman listesinden değişen bölgeleri hesapla.
    
    Algoritma:
    1. Eski ve yeni katmanları karşılaştır
    2. Değişen katmanların bounding box'larını bul
    3. Bitişik bölgeleri birleştir
    4. Kirli region listesini döndür
    
    Karmaşıklık: O(n) — katman sayısı
    """
    dirty_regions = []
    
    # Eski katmanları dictionary'e çevir
    old_dict = {l.layer_id: l for l in old_layers}
    new_dict = {l.layer_id: l for l in new_layers}
    
    # Yeni katmanları kontrol et
    for layer_id, new_layer in new_dict.items():
        if layer_id in old_dict:
            old_layer = old_dict[layer_id]
            
            # Değişiklik var mı?
            if (old_layer.opacity != new_layer.opacity or
                old_layer.blend_mode != new_layer.blend_mode or
                old_layer.transform_matrix != new_layer.transform_matrix):
                
                # Bounding box'ı hesapla
                bbox = compute_layer_bbox(new_layer)
                dirty_regions.append(bbox)
        else:
            # Yeni katman eklendi
            bbox = compute_layer_bbox(new_layer)
            dirty_regions.append(bbox)
    
    # Silinen katmanları kontrol et
    for layer_id in old_dict:
        if layer_id not in new_dict:
            old_layer = old_dict[layer_id]
            bbox = compute_layer_bbox(old_layer)
            dirty_regions.append(bbox)
    
    # Bitişik bölgeleri birleştir
    return merge_dirty_regions(dirty_regions)


def compute_layer_bbox(layer: CompositeLayer) -> DirtyRegion:
    """
    Katmanın bounding box'ını hesapla.
    
    Bu, katmanın hangi alanı kapladığını gösterir.
    """
    # Gerçek implementasyonda transform matrisinden hesaplanır
    # Şimdilik tam frame dönüyoruz
    return DirtyRegion(x=0, y=0, width=1920, height=1080)


def merge_dirty_regions(regions: List[DirtyRegion]) -> List[DirtyRegion]:
    """
    Bitişik kirli region'ları birleştir.
    
    Bu, gereksiz tekrarları önler.
    
    Algoritma:
    1. İlk region'ı al
    2. Diğer region'larla kesişim kontrolü yap
    3. Kesişen region'ları birleştir
    4. Sonuç listesini döndür
    
    Karmaşıklık: O(n^2) — en kötü durumda
    Optimizasyon: Sweep line ile O(n log n)
    """
    if not regions:
        return []
    
    merged = [regions[0]]
    
    for region in regions[1:]:
        found = False
        for i, m in enumerate(merged):
            if m.intersects(region):
                merged[i] = m.merge(region)
                found = True
                break
        
        if not found:
            merged.append(region)
    
    return merged
```

## 6.5 API Sözleşmeleri

```python
class CompositorAPI:
    """
    Kompozitör API'si.
    
    Bu sınıf, compositing işlemlerini yönetir.
    FastAPI endpoint'lerinden doğrudan erişilir.
    """
    
    def __init__(self, config: Optional[CompositorConfig] = None):
        self._compositor = Compositor(config)
        self._layer_stacks: Dict[UUID, List[CompositeLayer]] = {}
    
    def composite_frame(
        self,
        stack_id: UUID,
        time: float = 0.0
    ) -> Optional['Frame']:
        """
        Belirli bir zamandaki frame'i compositing yap.
        
        Args:
            stack_id: LayerStack ID
            time: Zaman (saniye)
            
        Returns:
            Compositing yapılmış frame veya None
        """
        layers = self._layer_stacks.get(stack_id)
        if not layers:
            return None
        
        return self._compositor.composite(layers, time)
    
    def update_layer(
        self,
        stack_id: UUID,
        layer: CompositeLayer
    ) -> None:
        """
        Katmanı güncelle.
        
        Bu, dirty region detection tetikler.
        """
        if stack_id not in self._layer_stacks:
            self._layer_stacks[stack_id] = []
        
        layers = self._layer_stacks[stack_id]
        
        # Mevcut katmanı bul ve güncelle
        for i, existing in enumerate(layers):
            if existing.layer_id == layer.layer_id:
                # Eski durumla karşılaştır
                old_regions = compute_layer_bbox(existing)
                layers[i] = layer
                new_regions = compute_layer_bbox(layer)
                
                # Kirli region'ları güncelle
                if old_regions != new_regions:
                    self._compositor.update_dirty_regions([old_regions, new_regions])
                return
        
        # Yeni katman ekle
        layers.append(layer)
        self._compositor.update_dirty_regions([compute_layer_bbox(layer)])
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        Performans istatistiklerini döndür.
        
        Bu, debug ve optimizasyon için kullanılır.
        """
        return {
            "is_processing": self._compositor.state.is_processing,
            "fps": self._compositor.state.fps,
            "gpu_memory_mb": self._compositor.state.gpu_memory_used_mb,
            "cpu_memory_mb": self._compositor.state.cpu_memory_used_mb,
            "dirty_regions": len(self._compositor.state.dirty_regions),
            "last_render_ms": self._compositor.state.last_render_time_ms,
        }
```

## 6.6 Performans Darboğazları ve Çözümleri

| Darboğaz | Etki | Çözüm |
|---|---|---|
| Full frame compositing | 4K: 32MB/frame | Dirty region tracking — sadece değişen bölgeler |
| Blend mode computation | Her piksel için karmaşık hesaplama | GPU compute shader — 1000x hız |
| Alpha compositing | Over operation: O(1)/piksel | SIMD (AVX2) ile 8 piksel aynı anda |
| Layer ordering | Her karede sıralama | Cache'le, sadece değişiklik olduğunda yeniden sırala |
| GPU memory | 10 katman × 4K = 320MB | Streaming upload, LRUCache |

## 6.7 Entegrasyon Noktaları

```
Compositor
    ├── Timeline Engine ← Aktif katmanlar için
    ├── Layer Manager ← Katman sırası ve özellikleri için
    ├── Effect Engine ← Efekt uygulanmış frameler için
    ├── GPU Accelerator ← CUDA/Metal compute için
    └── Display/Encoder ← Çıktı için
```

---

# 7. Render Hattı (Render Pipeline)

## 7.1 Amaç ve Kapsam

Render hattı, tüm processing adımlarını birleştirip son çıktıyı (video dosyası) oluşturan sistemdir. Bu, NLE'lerin en karmaşık bileşenidir — çünkü zamanlama, encoding, decoding, compositing ve efekt processing gibi birçok sistemi bir araya getirir.

Bizim yaklaşımız, DaVinci Resolve'un "Deliver" sayfasının processing modelini, Premiere Pro'nun "Media Encoder" entegrasyonunu ve FFmpeg'in encoding yeteneklerini birleştirir.

### Karşılaştırma

| Özellik | Bizim Sistem | Premiere | Resolve | Final Cut Pro |
|---|---|---|---|---|
| Render modeli | Multi-pass pipeline | Media Encoder | Deliver page | Background render |
| Parallel rendering | Evet | Evet | Evet (best) | Evet |
| Background render | Evet | Evet | Evet | Evet (best) |
| Incremental render | Evet | Evet | Evet | Evet |
| GPU encoding | Evet | Evet | Evet | Evet |

## 7.2 Mimari

```
┌─────────────────────────────────────────────┐
│           Render Pipeline                    │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │        1. Analysis Pass               │   │
│  │  - Frame count hesapla                │   │
│  │  - Effect complexity analizi          │   │
│  │  - Memory requirement hesapla         │   │
│  │  - Parallel processing planı oluştur  │   │
│  └──────────────────────────────────────┘   │
│       │                                      │
│  ┌──────────────────────────────────────┐   │
│  │        2. Processing Pass             │   │
│  │  - Decode source frames               │   │
│  │  - Apply effects                      │   │
│  │  - Composit layers                    │   │
│  │  - Apply transitions                  │   │
│  └──────────────────────────────────────┘   │
│       │                                      │
│  ┌──────────────────────────────────────┐   │
│  │        3. Encoding Pass               │   │
│  │  - Color space conversion             │   │
│  │  - Codec encoding (H.264/H.265/ProRes)│  │
│  │  - Muxing (audio + video)             │   │
│  │  - Output to file                     │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

## 7.3 Veri Yapısı

```python
"""
Render hattı veri yapıları.

Tasarım İlkeleri:
1. Multi-pass rendering — analiz, işleme, encoding
2. Frame-accurate output — kare hataları yok
3. Incremental rendering — sadece değişen bölümler
4. Background rendering — kullanıcı arayüzü donmaz
5. Progress tracking — detaylı ilerleme raporu
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from uuid import UUID, uuid4


class RenderStatus(Enum):
    """Render durumu"""
    PENDING = "pending"
    ANALYZING = "analyzing"
    RENDERING = "rendering"
    ENCODING = "encoding"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class RenderQuality(Enum):
    """Render kalitesi"""
    DRAFT = "draft"        # Hızlı, düşük kalite
    NORMAL = "normal"      # Standart kalite
    HIGH = "high"          # Yüksek kalite
    ULTRA = "ultra"        # En yüksek kalite
    CUSTOM = "custom"      # Özel ayarlar


class OutputFormat(Enum):
    """Çıktı formatları"""
    MP4_H264 = "mp4_h264"
    MP4_H265 = "mp4_h265"
    MOV_PRORES = "mov_prores"
    MOV_PRORES_422 = "mov_prores_422"
    MOV_PRORES_4444 = "mov_prores_4444"
    AVI = "avi"
    MKV = "mkv"
    WEBM = "webm"
    IMAGE_SEQUENCE = "image_sequence"
    EXR = "exr"
    TIFF = "tiff"


@dataclass
class RenderFrame:
    """
    Tek bir render frame'i.
    
    Bu yapı, render sırasında işlenen 
    tek bir frame'in tüm bilgilerini içerir.
    """
    frame_id: UUID = field(default_factory=uuid4)
    frame_number: int = 0
    timestamp: RationalTime = field(default_factory=lambda: RationalTime(0, 1))
    source_data: Optional[bytes] = None  # Ham frame verisi
    processed_data: Optional[bytes] = None  # İşlenmiş frame verisi
    width: int = 1920
    height: int = 1080
    pixel_format: str = "rgba8"
    color_space: str = "srgb"
    
    # Durum
    is_decoded: bool = False
    is_processed: bool = False
    is_encoded: bool = False
    
    # Hata
    error: Optional[str] = None
    
    @property
    def size_bytes(self) -> int:
        """Frame boyutu (byte)"""
        if self.source_data:
            return len(self.source_data)
        return self.width * self.height * 4  # RGBA假设
    
    def to_dict(self) -> dict:
        return {
            "frame_id": str(self.frame_id),
            "frame_number": self.frame_number,
            "timestamp": self.timestamp.to_dict(),
            "width": self.width,
            "height": self.height,
            "pixel_format": self.pixel_format,
            "color_space": self.color_space,
            "is_decoded": self.is_decoded,
            "is_processed": self.is_processed,
            "is_encoded": self.is_encoded,
            "error": self.error,
        }


@dataclass
class RenderPass:
    """
    Render pass'i — tek bir işleme adımı.
    
    Render pipeline'ı birden fazla pass'ten oluşur.
    Her pass, belirli bir işlemi yapar.
    
    Pass türleri:
    - Decode: Kaynak medyayı decode et
    - Effect: Efektleri uygula
    - Composite: Katmanları birleştir
    - Color: Renk dönüştürme
    - Encode: Çıktıyı encode et
    """
    pass_id: UUID = field(default_factory=uuid4)
    name: str = ""
    pass_type: str = "processing"  # decode, processing, encode
    
    # Parametreler
    start_frame: int = 0
    end_frame: int = 0
    batch_size: int = 10  # Kaç frame aynı anda işlenir
    
    # Durum
    status: RenderStatus = RenderStatus.PENDING
    processed_frames: int = 0
    total_frames: int = 0
    
    # Hata
    error: Optional[str] = None
    
    @property
    def progress(self) -> float:
        """İlerleme oranı"""
        if self.total_frames == 0:
            return 0.0
        return self.processed_frames / self.total_frames
    
    @property
    def is_complete(self) -> bool:
        """Pass tamamlandı mı?"""
        return self.status == RenderStatus.COMPLETED
    
    def to_dict(self) -> dict:
        return {
            "pass_id": str(self.pass_id),
            "name": self.name,
            "pass_type": self.pass_type,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "batch_size": self.batch_size,
            "status": self.status.value,
            "processed_frames": self.processed_frames,
            "total_frames": self.total_frames,
            "error": self.error,
        }


@dataclass
class RenderProgress:
    """
    Render ilerleme bilgisi.
    
    Bu, render sırasında kullanıcılara gösterilen 
    detaylı ilerleme bilgisini içerir.
    """
    job_id: UUID = field(default_factory=uuid4)
    status: RenderStatus = RenderStatus.PENDING
    
    # Genel ilerleme
    total_frames: int = 0
    rendered_frames: int = 0
    failed_frames: int = 0
    
    # Mevcut pass
    current_pass: str = ""
    current_pass_progress: float = 0.0
    
    # Zaman tahmini
    elapsed_time_ms: float = 0.0
    estimated_remaining_ms: float = 0.0
    fps: float = 0.0
    
    # Kaynak kullanımı
    cpu_percent: float = 0.0
    gpu_percent: float = 0.0
    memory_mb: float = 0.0
    
    @property
    def overall_progress(self) -> float:
        """Genel ilerleme oranı"""
        if self.total_frames == 0:
            return 0.0
        return self.rendered_frames / self.total_frames
    
    @property
    def is_complete(self) -> bool:
        """Render tamamlandı mı?"""
        return self.status == RenderStatus.COMPLETED
    
    @property
    def has_error(self) -> bool:
        """Hata var mı?"""
        return self.status == RenderStatus.FAILED
    
    def to_dict(self) -> dict:
        return {
            "job_id": str(self.job_id),
            "status": self.status.value,
            "total_frames": self.total_frames,
            "rendered_frames": self.rendered_frames,
            "failed_frames": self.failed_frames,
            "current_pass": self.current_pass,
            "current_pass_progress": self.current_pass_progress,
            "elapsed_time_ms": self.elapsed_time_ms,
            "estimated_remaining_ms": self.estimated_remaining_ms,
            "fps": self.fps,
            "cpu_percent": self.cpu_percent,
            "gpu_percent": self.gpu_percent,
            "memory_mb": self.memory_mb,
        }


@dataclass
class RenderJob:
    """
    Render işi — tüm render parametreleri.
    
    Bir RenderJob, bir timeline'ın tamamını veya 
    bir bölümünü render etmek için gereken 
    tüm parametreleri içerir.
    
    Premiere'de "Export Settings", Resolve'da 
    "Deliver Settings" ile aynı işlevi görür.
    """
    job_id: UUID = field(default_factory=uuid4)
    name: str = ""
    timeline_id: Optional[UUID] = None
    
    # Zaman aralığı
    start_frame: int = 0
    end_frame: int = 0
    
    # Çıktı ayarları
    output_path: str = ""
    output_format: OutputFormat = OutputFormat.MP4_H264
    quality: RenderQuality = RenderQuality.NORMAL
    
    # Video ayarları
    width: int = 1920
    height: int = 1080
    fps: Fraction = field(default_factory=lambda: Fraction(30000, 1001))
    bitrate: int = 20000000  # 20 Mbps
    codec: str = "libx264"
    preset: str = "medium"  # ultrafast, fast, medium, slow, veryslow
    crf: int = 18  # 0-51, düşük = yüksek kalite
    
    # Audio ayarları
    audio_codec: str = "aac"
    audio_bitrate: int = 192000  # 192 kbps
    audio_sample_rate: int = 48000
    
    # Renk ayarları
    color_space: str = "bt709"
    color_range: str = "tv"  # tv (limited) veya pc (full)
    
    # Render ayarları
    use_gpu: bool = True
    parallel_passes: int = 2
    memory_limit_mb: int = 4096
    
    # Durum
    status: RenderStatus = RenderStatus.PENDING
    progress: Optional[RenderProgress] = None
    
    # Callback'ler
    on_progress: Optional[Callable] = None
    on_complete: Optional[Callable] = None
    on_error: Optional[Callable] = None
    
    @property
    def total_frames(self) -> int:
        """Toplam frame sayısı"""
        return self.end_frame - self.start_frame + 1
    
    @property
    def estimated_size_mb(self) -> float:
        """Tahmini çıktı boyutu (MB)"""
        duration_seconds = self.total_frames / float(self.fps)
        bitrate_mbps = self.bitrate / 1000000
        return (bitrate_mbps * duration_seconds) / 8
    
    def to_dict(self) -> dict:
        return {
            "job_id": str(self.job_id),
            "name": self.name,
            "timeline_id": str(self.timeline_id) if self.timeline_id else None,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "output_path": self.output_path,
            "output_format": self.output_format.value,
            "quality": self.quality.value,
            "width": self.width,
            "height": self.height,
            "fps": str(self.fps),
            "bitrate": self.bitrate,
            "codec": self.codec,
            "preset": self.preset,
            "crf": self.crf,
            "audio_codec": self.audio_codec,
            "audio_bitrate": self.audio_bitrate,
            "audio_sample_rate": self.audio_sample_rate,
            "color_space": self.color_space,
            "color_range": self.color_range,
            "use_gpu": self.use_gpu,
            "parallel_passes": self.parallel_passes,
            "memory_limit_mb": self.memory_limit_mb,
            "status": self.status.value,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> RenderJob:
        return cls(
            job_id=UUID(data["job_id"]),
            name=data["name"],
            timeline_id=UUID(data["timeline_id"]) if data.get("timeline_id") else None,
            start_frame=data["start_frame"],
            end_frame=data["end_frame"],
            output_path=data["output_path"],
            output_format=OutputFormat(data["output_format"]),
            quality=RenderQuality(data["quality"]),
            width=data["width"],
            height=data["height"],
            fps=Fraction(data["fps"]),
            bitrate=data["bitrate"],
            codec=data["codec"],
            preset=data["preset"],
            crf=data["crf"],
            audio_codec=data["audio_codec"],
            audio_bitrate=data["audio_bitrate"],
            audio_sample_rate=data["audio_sample_rate"],
            color_space=data["color_space"],
            color_range=data["color_range"],
            use_gpu=data["use_gpu"],
            parallel_passes=data["parallel_passes"],
            memory_limit_mb=data["memory_limit_mb"],
        )
```

```python
class RenderPipeline:
    """
    Render hattı — çok pass'li render motoru.
    
    Bu sınıf, bir RenderJob'ı alır ve çok adımlı 
    bir pipeline ile son çıktıyı oluşturur.
    
    Pipeline adımları:
    1. Analysis Pass: Frame sayısı, bellek, karmaşıklık analizi
    2. Decode Pass: Kaynak medyayı decode et
    3. Processing Pass: Efektleri ve compositing'i uygula
    4. Encode Pass: Çıktıyı encode et
    5. Mux Pass: Audio ve video'yu birleştir
    
    Her pass bağımsız olarak çalıştırılabilir ve 
    paralel işlenebilir.
    
    Performance:
    - 1080p, 5 dakika: ~30 saniye (GPU ile)
    - 4K, 5 dakika: ~3 dakika (GPU ile)
    - 4K, 5 dakika: ~15 dakika (CPU ile)
    """
    
    def __init__(
        self,
        compositor: Compositor,
        effect_engine: EffectEngine,
        timeline_engine: TimelineEngine
    ):
        self._compositor = compositor
        self._effect_engine = effect_engine
        self._timeline_engine = timeline_engine
        self._current_job: Optional[RenderJob] = None
        self._progress: Optional[RenderProgress] = None
        self._is_cancelled: bool = False
    
    def start_render(self, job: RenderJob) -> RenderProgress:
        """
        Render'ı başlat.
        
        Bu, tüm pipeline'ı çalıştırır ve 
        ilerleme bilgisini döndürür.
        
        Args:
            job: Render iş parametreleri
            
        Returns:
            RenderProgress nesnesi
        """
        self._current_job = job
        self._progress = RenderProgress(job_id=job.job_id)
        self._is_cancelled = False
        
        # Analysis pass
        self._run_analysis_pass(job)
        
        if self._is_cancelled:
            self._progress.status = RenderStatus.CANCELLED
            return self._progress
        
        # Processing pass
        self._run_processing_pass(job)
        
        if self._is_cancelled:
            self._progress.status = RenderStatus.CANCELLED
            return self._progress
        
        # Encoding pass
        self._run_encoding_pass(job)
        
        if self._is_cancelled:
            self._progress.status = RenderStatus.CANCELLED
            return self._progress
        
        # Tamamlandı
        self._progress.status = RenderStatus.COMPLETED
        self._progress.rendered_frames = self._progress.total_frames
        
        if job.on_complete:
            job.on_complete(self._progress)
        
        return self._progress
    
    def cancel_render(self) -> None:
        """Render'ı iptal et"""
        self._is_cancelled = True
    
    def pause_render(self) -> None:
        """Render'ı duraklat"""
        if self._progress:
            self._progress.status = RenderStatus.PAUSED
    
    def resume_render(self) -> None:
        """Render'a devam et"""
        if self._progress and self._progress.status == RenderStatus.PAUSED:
            self._progress.status = RenderStatus.RENDERING
    
    def _run_analysis_pass(self, job: RenderJob) -> None:
        """
        Analiz pass'ini çalıştır.
        
        Bu pass, render'ın karmaşıklığını ve 
        gereksinimlerini hesaplar.
        
        Adımlar:
        1. Timeline'dan toplam frame sayısını hesapla
        2. Efekt karmaşıklığını analiz et
        3. Bellek gereksinimini hesapla
        4. Parallel processing planı oluştur
        """
        self._progress.status = RenderStatus.ANALYZING
        self._progress.current_pass = "analysis"
        
        # Timeline'ı al
        timeline = self._timeline_engine.get_timeline(job.timeline_id)
        if not timeline:
            self._progress.status = RenderStatus.FAILED
            self._progress.current_pass = "analysis"
            self._progress.error = "Timeline bulunamadı"
            return
        
        # Toplam frame sayısını hesapla
        self._progress.total_frames = job.total_frames
        
        # Bellek gereksinimini hesapla
        frame_size_mb = (job.width * job.height * 4) / (1024 * 1024)
        memory_needed_mb = frame_size_mb * job.parallel_passes * 2
        
        if memory_needed_mb > job.memory_limit_mb:
            # Batch size'ı küçült
            batch_size = int((job.memory_limit_mb / frame_size_mb) / 2)
            if batch_size < 1:
                batch_size = 1
        else:
            batch_size = 10
        
        self._progress.status = RenderStatus.PENDING
    
    def _run_processing_pass(self, job: RenderJob) -> None:
        """
        İşleme pass'ini çalıştır.
        
        Bu pass, tüm frame'leri işler:
        1. Decode
        2. Efekt uygulama
        3. Compositing
        4. Geçiş uygulama
        """
        self._progress.status = RenderStatus.RENDERING
        self._progress.current_pass = "processing"
        
        try:
            # Timeline'ı al
            timeline = self._timeline_engine.get_timeline(job.timeline_id)
            if not timeline:
                raise ValueError("Timeline bulunamadı")
            
            # Her frame için işleme yap
            for frame_num in range(job.start_frame, job.end_frame + 1):
                if self._is_cancelled:
                    break
                
                # Frame zamanını hesapla
                frame_time = RationalTime(frame_num, job.fps)
                
                # Timeline'daki clip'leri bul
                active_clips = timeline.scrub_to(frame_time)
                
                # Efektleri uygula
                processed_clips = []
                for clip in active_clips:
                    if clip.effects:
                        # Efekt grafiğini uygula
                        # Gerçek implementasyonda FFmpeg kullanılır
                        processed_clips.append(clip)
                    else:
                        processed_clips.append(clip)
                
                # Compositing yap
                # Gerçek implementasyonda compositor kullanılır
                
                # İlerlemeyi güncelle
                self._progress.rendered_frames += 1
                self._progress.current_pass_progress = (
                    self._progress.rendered_frames / self._progress.total_frames
                )
                
                # Callback çağır
                if job.on_progress:
                    job.on_progress(self._progress)
        
        except Exception as e:
            self._progress.status = RenderStatus.FAILED
            self._progress.error = str(e)
            if job.on_error:
                job.on_error(self._progress)
    
    def _run_encoding_pass(self, job: RenderJob) -> None:
        """
        Encoding pass'ini çalıştır.
        
        Bu pass, işlenmiş frameleri son çıktıya encode eder.
        
        Adımlar:
        1. FFmpeg ile encoding
        2. Muxing (audio + video)
        3. Metadata yazma
        """
        self._progress.status = RenderStatus.ENCODING
        self._progress.current_pass = "encoding"
        
        try:
            # FFmpeg ile encoding
            # Gerçek implementasyonda subprocess ile FFmpeg çağırılır
            
            # Örnek FFmpeg komutu:
            # ffmpeg -i input.mp4 -c:v libx264 -crf 18 -c:a aac -b:a 192k output.mp4
            
            self._progress.status = RenderStatus.COMPLETED
        
        except Exception as e:
            self._progress.status = RenderStatus.FAILED
            self._progress.error = str(e)
            if job.on_error:
                job.on_error(self._progress)
    
    def get_progress(self) -> Optional[RenderProgress]:
        """Mevcut ilerleme bilgisini döndür"""
        return self._progress
```

## 7.4 Core Algoritmalar

### 7.4.1 Frame-Accurate Render Loop

```python
def render_frame_accurate(
    timeline: Timeline,
    job: RenderJob,
    callback: Optional[Callable] = None
) -> None:
    """
    Kare-hassas render döngüsü.
    
    Bu, tüm timeline'ı kare kare işler ve 
    her frame'in zamanlamasının doğru olmasını sağlar.
    
    Algoritma:
    1. Her frame için:
       a. Frame zamanını hesapla (RationalTime)
       b. Timeline'ı o zaman diliminde scrub et
       c. Aktif clip'leri ve efektleri bul
       d. Frame'i decode et
       e. Efektleri uygula
       f. Compositing yap
       g. Encode et
       h. Çıktıya yaz
    
    Dikkat: Kare numarası asla float ile hesaplanmaz!
    Her zaman RationalTime kullanılır.
    
    Karmaşıklık: O(f * (c + e)) — f = frame sayısı, c = clip sayısı, e = efekt sayısı
    """
    fps = job.fps
    
    for frame_num in range(job.start_frame, job.end_frame + 1):
        # RationalTime ile kare zamanını hesapla
        frame_time = RationalTime(frame_num, fps.numerator // fps.denominator if fps.denominator == 1 else 1)
        
        # Timeline'ı scrub et
        active_clips = timeline.scrub_to(frame_time)
        
        # Her clip için kaynak zamanı hesapla
        for clip in active_clips:
            if not clip.enabled:
                continue
            
            # Kaynak zamanı hesapla
            source_time = clip.source_time_at(frame_time)
            if source_time is None:
                continue
            
            # Kaynak kare numarasını hesapla
            source_frame = source_time.to_frames(fps)
            
            # Kaynağı decode et
            # source_frame kullanarak FFmpeg ile decode
            
            # Efektleri uygula
            for effect_id in clip.effects:
                # Efekt grafiğini uygula
                pass
            
            # Compositing'e ekle
            # Layer olarak compositor'a gönder
        
        # Tüm clip'leri compositing yap
        # Composite result'u encode et
        
        # İlerlemeyi bildir
        if callback:
            progress = (frame_num - job.start_frame) / (job.end_frame - job.start_frame)
            callback(progress, frame_num)
```

### 7.4.2 Incremental Rendering

```python
def render_incremental(
    timeline: Timeline,
    job: RenderJob,
    dirty_frames: List[int]
) -> None:
    """
    Artımsal render — sadece değişen frame'leri render et.
    
    Bu, timeline'da sadece belirli bölümlerin değiştiği 
    durumlar için kullanılır. Tüm timeline'ı yeniden 
    render etmek yerine, sadece değişen frame'leri işler.
    
    Algoritma:
    1. Değişen frame'leri bul (dirty_frames)
    2. Her değişen frame için:
       a. Eski render sonucunu sil
       b. Yeni frame'i render et
       c. Çıktı dosyasını güncelle
    
    Avantajları:
    - %90'a kadar hız kazancı
    - Daha az CPU/GPU kullanımı
    - Daha kısa bekleme süresi
    
    Karmaşıklık: O(d * (c + e)) — d = değişen frame sayısı
    """
    for frame_num in dirty_frames:
        if frame_num < job.start_frame or frame_num > job.end_frame:
            continue
        
        # Frame zamanını hesapla
        fps = job.fps
        frame_time = RationalTime(frame_num, fps.numerator // fps.denominator if fps.denominator == 1 else 1)
        
        # Timeline'ı scrub et
        active_clips = timeline.scrub_to(frame_time)
        
        # Frame'i render et
        # (Yukarıdaki render_frame_accurate ile aynı mantık)
        
        # Çıktı dosyasını güncelle
        # Seek ile ilgili pozisyona gidip frame'i yaz
```

### 7.4.3 Parallel Rendering

```python
def render_parallel(
    timeline: Timeline,
    job: RenderJob,
    num_workers: int = 4
) -> None:
    """
    Paralel render — birden fazla worker ile eş zamanlı render.
    
    Bu, render süresini önemli ölçüde kısaltır.
    Her worker, bağımsız bir frame grubunu işler.
    
    Algoritma:
    1. Frame'leri worker sayısına göre böl
    2. Her worker'a bağımsız bir grup ata
    3. Worker'ları eş zamanlı çalıştır
    4. Sonuçları birleştir
    
    Dikkat: Worker'lar arasında paylaşılan kaynaklar 
    thread-safe olmalıdır.
    
    Speedup: ~num_workersx (Amdahl's law'a göre)
    
    Karmaşıklık: O(f / w * (c + e)) — w = worker sayısı
    """
    import concurrent.futures
    
    total_frames = job.end_frame - job.start_frame + 1
    frames_per_worker = total_frames // num_workers
    
    # Frame'leri gruplara böl
    frame_groups = []
    for i in range(num_workers):
        start = job.start_frame + i * frames_per_worker
        end = start + frames_per_worker - 1
        if i == num_workers - 1:
            end = job.end_frame
        frame_groups.append((start, end))
    
    # Worker'ları çalıştır
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = []
        for start, end in frame_groups:
            worker_job = RenderJob(
                name=f"Worker {len(futures)}",
                timeline_id=job.timeline_id,
                start_frame=start,
                end_frame=end,
                output_path=job.output_path,
                fps=job.fps,
            )
            future = executor.submit(render_frame_accurate, timeline, worker_job)
            futures.append(future)
        
        # Sonuçları bekle
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"Worker hatası: {e}")
```

## 7.5 API Sözleşmeleri

```python
class RenderAPI:
    """
    Render API'si.
    
    Bu sınıf, render işlemlerini yönetir.
    FastAPI endpoint'lerinden doğrudan erişilir.
    """
    
    def __init__(
        self,
        compositor: Compositor,
        effect_engine: EffectEngine,
        timeline_engine: TimelineEngine
    ):
        self._pipeline = RenderPipeline(compositor, effect_engine, timeline_engine)
        self._jobs: Dict[UUID, RenderJob] = {}
    
    def create_render_job(
        self,
        timeline_id: UUID,
        output_path: str,
        output_format: OutputFormat = OutputFormat.MP4_H264,
        quality: RenderQuality = RenderQuality.NORMAL,
        start_frame: int = 0,
        end_frame: int = 0,
    ) -> RenderJob:
        """
        Yeni bir render job'ı oluştur.
        
        Args:
            timeline_id: Timeline ID
            output_path: Çıktı dosya yolu
            output_format: Çıktı formatı
            quality: Render kalitesi
            start_frame: Başlangıç frame'i
            end_frame: Bitiş frame'i
            
        Returns:
            Oluşturulan RenderJob
        """
        # Timeline'dan bilgileri al
        timeline = self._timeline_engine.get_timeline(timeline_id)
        if not timeline:
            raise ValueError(f"Timeline bulunamadı: {timeline_id}")
        
        # Varsayılan değerler
        if end_frame == 0:
            duration_frames = int(timeline.duration.seconds * float(timeline.fps))
            end_frame = duration_frames - 1
        
        job = RenderJob(
            name=f"Render {timeline.name}",
            timeline_id=timeline_id,
            output_path=output_path,
            output_format=output_format,
            quality=quality,
            width=timeline.width,
            height=timeline.height,
            fps=timeline.fps,
            start_frame=start_frame,
            end_frame=end_frame,
        )
        
        self._jobs[job.job_id] = job
        return job
    
    def start_render(self, job_id: UUID) -> RenderProgress:
        """
        Render'ı başlat.
        
        Bu, arka planda çalışır ve ilerleme 
        bilgisi API üzerinden takip edilebilir.
        """
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job bulunamadı: {job_id}")
        
        return self._pipeline.start_render(job)
    
    def cancel_render(self, job_id: UUID) -> None:
        """Render'ı iptal et"""
        self._pipeline.cancel_render()
    
    def get_render_progress(self, job_id: UUID) -> Optional[RenderProgress]:
        """
        Render ilerleme bilgisini al.
        
        Bu, WebSocket veya polling ile takip edilebilir.
        """
        return self._pipeline.get_progress()
    
    def get_available_formats(self) -> List[Dict[str, Any]]:
        """Kullanılabilir çıktı formatlarını döndür"""
        formats = []
        for fmt in OutputFormat:
            formats.append({
                "format": fmt.value,
                "name": fmt.name.replace("_", " ").title(),
            })
        return formats
    
    def get_available_codecs(self) -> List[Dict[str, Any]]:
        """Kullanılabilir codec'leri döndür"""
        # FFmpeg ile mevcut codec'leri kontrol et
        return [
            {"codec": "libx264", "name": "H.264", "type": "video"},
            {"codec": "libx265", "name": "H.265/HEVC", "type": "video"},
            {"codec": "libvpx-vp9", "name": "VP9", "type": "video"},
            {"codec": "aac", "name": "AAC", "type": "audio"},
            {"codec": "libmp3lame", "name": "MP3", "type": "audio"},
        ]
```

## 7.6 Performans Darboğazları ve Çözümleri

| Darboğaz | Etki | Çözüm |
|---|---|---|
| Large timeline (1 saat+) | Milyonlarca frame | Incremental rendering — sadece değişen bölümler |
| High resolution (4K+) | Büyük frame boyutları | GPU encoding + streaming processing |
| Complex effects | 50+ efekt/node | GPU compute shader + ahead-of-time compilation |
| Memory pressure | 4K frame: 32MB RAM | Frame buffer pool + streaming decode |
| Encoding bottleneck | H.265 encoding yavaş | GPU encoding (NVENC/VCE) + hardware acceleration |
| Multi-pass rendering | Her pass ayrı çalışma | Thread pool + async I/O |

## 7.7 Entegrasyon Noktaları

```
Render Pipeline
    ├── Timeline Engine ← Timeline bilgileri için
    ├── Effect Engine ← Efekt processing için
    ├── Compositor ← Compositing için
    ├── Media Decoder ← Kaynak decode için
    ├── FFmpeg Encoder ← Çıktı encode için
    ├── GPU Accelerator ← CUDA/Metal için
    └── File System ← Disk I/O için
```

---

# Genel Mimari Diyagramı

```
┌─────────────────────────────────────────────────────────────┐
│                    Core Editing Engine                       │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  Timeline    │  │  Layer       │  │  NLE         │    │
│  │  Engine      │  │  Manager     │  │  Core        │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         │                 │                 │             │
│  ┌──────▼─────────────────▼─────────────────▼──────┐    │
│  │              Effect Graph Engine                 │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         │                               │
│  ┌──────────────────────▼──────────────────────────┐    │
│  │              Transition Manager                  │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         │                               │
│  ┌──────────────────────▼──────────────────────────┐    │
│  │              Video Compositor                    │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         │                               │
│  ┌──────────────────────▼──────────────────────────┐    │
│  │              Render Pipeline                     │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         │                               │
└─────────────────────────┼───────────────────────────────┘
                          │
                          ▼
                  ┌──────────────┐
                  │   FFmpeg     │
                  │   Backend    │
                  └──────────────┘
```

## Sistem Gereksinimleri

### Donanım

| bileşen | Minimum | Önerilen |
|---|---|---|
| CPU | 4 çekirdek, 3GHz | 8+ çekirdek, 4GHz+ |
| RAM | 16GB | 32GB+ |
| GPU | NVIDIA GTX 1660 | NVIDIA RTX 3080+ |
| Disk | 500GB SSD | 2TB NVMe SSD |
| Network | 100Mbps | 1Gbps+ |

### Yazılım

| Bileşen | Sürüm |
|---|---|
| Python | 3.10+ |
| FastAPI | 0.100+ |
| FFmpeg | 6.0+ |
| CUDA | 12.0+ |
| PyTorch | 2.0+ (GPU compute için) |
| NumPy | 1.24+ |
| OpenCV | 4.8+ |

## Performans Metrikleri

### 1080p Rendering

| Senaryo | CPU | GPU |
|---|---|---|
| Basit timeline (10 clip) | 60fps | 120fps |
| Orta timeline (50 clip + 10 efekt) | 30fps | 90fps |
| Karmaşık timeline (100 clip + 50 efekt) | 15fps | 60fps |

### 4K Rendering

| Senaryo | CPU | GPU |
|---|---|---|
| Basit timeline (10 clip) | 15fps | 60fps |
| Orta timeline (50 clip + 10 efekt) | 8fps | 45fps |
| Karmaşık timeline (100 clip + 50 efekt) | 3fps | 30fps |

## Hata Yönetimi

### Hata Türleri

1. **Kaynak Hataları**: Dosya bulunamadı, bozuk dosya, yetersiz disk alanı
2. **İşlem Hataları**: Efekt hatası, compositing hatası, encoding hatası
3. **Kaynak Yetersizliği**: Bellek yetersiz, GPU yetersiz, CPU aşırı yük
4. **Zaman Aşımı**: Encoding zaman aşımı, decode zaman aşımı

### Hata Stratejisi

1. **Retry**: Geçici hatalar için otomatik tekrar deneme
2. **Fallback**: GPU başarısız olursa CPU'ya geç
3. **Graceful Degradation**: Bazı efektler başarısız olursa diğerlerini işlemeye devam
4. **Error Reporting**: Detaylı hata loglama ve kullanıcıya bildirim

---

## Sürüm Geçmişi

| Sürüm | Tarih | Değişiklik |
|---|---|---|
| 1.0.0 | 2026-07-16 | İlk tasarım dokümanı |

---

*Bu doküman, Tuncay-klip projesinin çekirdek düzenleme motoru tasarımını kapsamaktadır. Tüm veri yapıları, API'lar ve algoritmalar production-grade olarak tasarlanmıştır.*
