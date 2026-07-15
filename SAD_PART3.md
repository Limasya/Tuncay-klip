# SOFTWARE ARCHITECTURE DOCUMENT (SAD) — PART 3
# Audio Pipeline, Chat Analysis, Decision Engine, Scoring & Beyond

---

# PART 9 — AUDIO PIPELINE

## 9.1 Audio Feature Extraction

### Neden Audio Analysis Kritik?

Audio, video'dan daha güçlü bir **highlight indicator**'dür:

```
Signal Strength for Clip Detection:

Audio Scream/Yell  → ████████████ 0.95  (strongest single signal)
Chat Explosion     → ██████████░░ 0.85
Emotion Change     → ████████░░░░ 0.75
Pose Gesture       → ███████░░░░░ 0.65
Audio Energy Spike → ██████░░░░░░ 0.60
Viewer Count Spike → █████░░░░░░░ 0.50
Object Detection   → ████░░░░░░░░ 0.40
OCR Keyword        → ███░░░░░░░░░ 0.30

A streamer yelling "LET'S GOOO" is almost ALWAYS a clip-worthy moment.
Audio analysis catches this even if:
  - Face is not visible (looking at screen)
  - Emotion model is confused
  - No gesture detected
```

### Audio Feature Extraction Pipeline

```python
# services/audio-analysis/feature_extractor.py

import numpy as np
import librosa

class AudioFeatureExtractor:
    """
    Extracts audio features from 1-second chunks.

    Features extracted:
    1. RMS Energy (loudness) — spike detection
    2. Zero Crossing Rate (noisiness) — scream vs speech
    3. Spectral Centroid (brightness) — excitement indicator
    4. Spectral Rolloff (high-freq energy) — scream detection
    5. MFCC (13 coefficients) — timbre fingerprint
    6. Chroma (12 pitch classes) — music detection
    7. Tempo (BPM) — music vs speech segments

    These features feed into:
    - Audio spike detector (immediate event trigger)
    - Speech emotion recognition (SER)
    - Voice activity detection (VAD)
    - Clip quality scorer (audio clarity)
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        n_mfcc: int = 13,
        chunk_duration: float = 1.0,
    ):
        self.sample_rate = sample_rate
        self.n_mfcc = n_mfcc
        self.chunk_samples = int(sample_rate * chunk_duration)

        # Rolling statistics for baseline comparison
        self._energy_history: deque[float] = deque(maxlen=60)  # Last 60 seconds
        self._zcr_history: deque[float] = deque(maxlen=60)

    def extract(self, audio_chunk: np.ndarray) -> AudioFeatures:
        """
        Extract all features from an audio chunk.

        Args:
            audio_chunk: numpy array, shape=(samples,), dtype=float32
                        1 second of audio at 16kHz

        Returns:
            AudioFeatures with all computed features
        """
        # Ensure correct length (pad or truncate)
        if len(audio_chunk) < self.chunk_samples:
            audio_chunk = np.pad(
                audio_chunk,
                (0, self.chunk_samples - len(audio_chunk)),
            )
        elif len(audio_chunk) > self.chunk_samples:
            audio_chunk = audio_chunk[:self.chunk_samples]

        # 1. RMS Energy (loudness)
        rms = float(np.sqrt(np.mean(audio_chunk ** 2)))

        # 2. Zero Crossing Rate (voiced vs unvoiced)
        zcr = float(librosa.feature.zero_crossing_rate(audio_chunk).mean())

        # 3. Spectral features
        spectral_centroid = float(
            librosa.feature.spectral_centroid(
                y=audio_chunk, sr=self.sample_rate
            ).mean()
        )
        spectral_rolloff = float(
            librosa.feature.spectral_rolloff(
                y=audio_chunk, sr=self.sample_rate
            ).mean()
        )

        # 4. MFCC (Mel-frequency cepstral coefficients)
        mfcc = librosa.feature.mfcc(
            y=audio_chunk,
            sr=self.sample_rate,
            n_mfcc=self.n_mfcc,
        ).mean(axis=1).tolist()

        # 5. Chroma (pitch class distribution)
        chroma = librosa.feature.chroma_stft(
            y=audio_chunk, sr=self.sample_rate
        ).mean(axis=1).tolist()

        # 6. Detect spike
        self._energy_history.append(rms)
        self._zcr_history.append(zcr)

        is_spike, spike_magnitude = self._detect_spike(rms)

        return AudioFeatures(
            rms_energy=rms,
            zero_crossing_rate=zcr,
            spectral_centroid=spectral_centroid,
            spectral_rolloff=spectral_rolloff,
            mfcc=mfcc,
            is_spike=is_spike,
            spike_magnitude=spike_magnitude,
        )

    def _detect_spike(self, current_rms: float) -> tuple[bool, float]:
        """
        Detect audio energy spike.

        A spike occurs when current energy is significantly above
        the rolling baseline (last 60 seconds).

        Threshold: current > baseline_mean + 2 * baseline_std
        """
        if len(self._energy_history) < 10:
            return False, 0.0

        baseline_mean = np.mean(self._energy_history)
        baseline_std = np.std(self._energy_history)

        if baseline_std < 1e-6:
            return False, 0.0

        z_score = (current_rms - baseline_mean) / baseline_std
        is_spike = z_score > 2.0  # 2 standard deviations above mean

        # Spike magnitude (0 to 1+)
        magnitude = max(0.0, z_score / 5.0)

        return is_spike, magnitude


class AudioSpikeDetector:
    """
    Specialized spike detection for scream/yell/celebration moments.

    Unlike simple RMS spike detection, this considers:
    1. Duration (a scream lasts 0.5-3 seconds, not a single frame)
    2. Frequency profile (screams have high spectral centroid)
    3. Rate of change (sudden loudness increase, not gradual)
    4. Sustained energy (not a single clap/sound effect)
    """

    def __init__(
        self,
        min_duration: float = 0.5,      # Minimum spike duration
        max_duration: float = 5.0,      # Maximum spike duration
        energy_threshold: float = 2.0,  # Z-score threshold
        spectral_threshold: float = 3000,  # Hz, high-frequency content
    ):
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.energy_threshold = energy_threshold
        self.spectral_threshold = spectral_threshold

        self._spike_start: Optional[float] = None
        self._spike_chunks: list[AudioFeatures] = []

    def process_chunk(self, features: AudioFeatures, timestamp: float) -> Optional[AudioSpikeEvent]:
        """
        Process a chunk and detect sustained spikes.

        State machine:
        IDLE → (spike detected) → TRACKING → (spike ended) → EMIT
        """
        is_current_spike = (
            features.is_spike
            and features.spectral_centroid > self.spectral_threshold * 0.7
        )

        if is_current_spike:
            if self._spike_start is None:
                self._spike_start = timestamp
            self._spike_chunks.append(features)

        elif self._spike_start is not None:
            # Spike ended
            duration = timestamp - self._spike_start

            if self.min_duration <= duration <= self.max_duration:
                # Valid spike
                avg_energy = np.mean([c.rms_energy for c in self._spike_chunks])
                max_magnitude = max(c.spike_magnitude for c in self._spike_chunks)

                event = AudioSpikeEvent(
                    start_time=self._spike_start,
                    end_time=timestamp,
                    duration=duration,
                    peak_magnitude=max_magnitude,
                    avg_energy=avg_energy,
                    chunk_count=len(self._spike_chunks),
                )

                # Reset
                self._spike_start = None
                self._spike_chunks = []

                return event
            else:
                # Too short or too long, discard
                self._spike_start = None
                self._spike_chunks = []

        return None
```

## 9.2 Voice Activity Detection (VAD)

```python
# services/audio-analysis/vad_engine.py

import torch

class VADEngine:
    """
    Voice Activity Detection using Silero VAD.

    Why Silero VAD?
    - Tiny model (2 MB)
    - Extremely fast (<1ms per chunk on CPU)
    - State-of-art accuracy (98%+)
    - Works on 16kHz mono audio
    - ONNX and PyTorch available

    Alternatives:
    - WebRTC VAD: Faster but less accurate, no probability output
    - pyannote VAD: More accurate but much slower, needs GPU
    - Energy threshold: Simple but fails on background noise

    Silero VAD is the best balance of speed and accuracy.
    Used by: OpenAI Whisper, AssemblyAI, Deepgram
    """

    def __init__(self, model_path: str = "models/silero_vad.onnx"):
        import onnxruntime as ort

        self.session = ort.InferenceSession(model_path)
        self.sample_rate = 16000

        # State for streaming VAD
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context_size = 64  # Context samples

    def detect(self, audio_chunk: np.ndarray) -> VADResult:
        """
        Detect voice activity in an audio chunk.

        Args:
            audio_chunk: 16kHz mono audio, 30ms chunks (480 samples)

        Returns:
            VADResult with speech probability
        """
        # Pad to 512 samples (32ms at 16kHz)
        if len(audio_chunk) < 512:
            audio_chunk = np.pad(audio_chunk, (0, 512 - len(audio_chunk)))

        # Prepare input
        input_data = audio_chunk[:512].reshape(1, -1).astype(np.float32)

        # Run VAD
        ort_inputs = {
            "input": input_data,
            "state": self._state,
            "sr": np.array([self.sample_rate], dtype=np.int64),
        }
        output, state = self.session.run(None, ort_inputs)
        self._state = state

        speech_prob = float(output[0][0])

        return VADResult(
            is_speech=speech_prob > 0.5,
            speech_probability=speech_prob,
        )

    def detect_segments(
        self,
        audio: np.ndarray,
        threshold: float = 0.5,
        min_speech_duration: float = 0.25,
        min_silence_duration: float = 0.1,
    ) -> list[tuple[float, float]]:
        """
        Detect speech segments in full audio.

        Returns:
            List of (start_seconds, end_seconds) tuples
        """
        chunk_size = 512  # 32ms chunks
        speech_flags = []

        for i in range(0, len(audio), chunk_size):
            chunk = audio[i:i + chunk_size]
            result = self.detect(chunk)
            speech_flags.append(result.is_speech)

        # Convert flags to segments
        segments = []
        in_speech = False
        start = 0

        for i, flag in enumerate(speech_flags):
            time = i * (chunk_size / self.sample_rate)

            if flag and not in_speech:
                start = time
                in_speech = True
            elif not flag and in_speech:
                duration = time - start
                if duration >= min_speech_duration:
                    segments.append((start, time))
                in_speech = False

        return segments
```

## 9.3 Speech Recognition — Faster-Whisper

```python
# services/audio-analysis/speech_recognizer.py

from faster_whisper import WhisperModel

class SpeechRecognizer:
    """
    Speech-to-text using Faster-Whisper.

    Why Faster-Whisper over vanilla Whisper?
    - CTranslate2 backend (4x faster, 2x less memory)
    - INT8 quantization support
    - Batch processing
    - Streaming mode

    Model sizes and trade-offs:
    ┌──────────┬────────┬─────────┬──────────┬───────────────┐
    │ Model    │ Size   │ Speed   │ Accuracy │ VRAM          │
    ├──────────┼────────┼─────────┼──────────┼───────────────┤
    │ tiny     │ 75 MB  │ 32x     │ 75.6%    │ ~1 GB         │
    │ base     │ 140 MB │ 16x     │ 81.7%    │ ~1 GB         │
    │ small    │ 460 MB │ 6x      │ 88.3%    │ ~2 GB         │
    │ medium   │ 1.5 GB │ 2x      │ 91.7%    │ ~5 GB         │
    │ large-v3 │ 3 GB   │ 1x      │ 93.5%    │ ~10 GB        │
    └──────────┴────────┴─────────┴──────────┴───────────────┘

    Our strategy:
    - Real-time: "base" model for streaming transcription
    - Post-clip: "small" or "medium" for accurate subtitle generation
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cuda",
        compute_type: str = "float16",
        language: str = None,  # Auto-detect
    ):
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )
        self.language = language

    async def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> TranscriptResult:
        """
        Transcribe audio file to text with timestamps.

        Used for:
        1. Real-time streaming (short chunks)
        2. Post-clip subtitle generation (full clip audio)
        """
        segments, info = self.model.transcribe(
            audio_path,
            language=language or self.language,
            beam_size=5,
            vad_filter=True,         # Filter non-speech
            vad_parameters=dict(
                min_silence_duration_ms=500,
            ),
            word_timestamps=True,    # Per-word timing for subtitles
        )

        words = []
        full_text = []

        for segment in segments:
            full_text.append(segment.text.strip())

            if segment.words:
                for word in segment.words:
                    words.append(WordTimestamp(
                        word=word.word,
                        start=word.start,
                        end=word.end,
                        confidence=word.probability,
                    ))

        return TranscriptResult(
            text=" ".join(full_text),
            language=info.language,
            language_probability=info.language_probability,
            words=words,
            duration=info.duration,
        )

    def generate_srt(self, transcript: TranscriptResult) -> str:
        """Generate SRT subtitle format from transcript"""
        srt_lines = []

        for i, word_group in enumerate(self._group_words(transcript.words, max_words=8)):
            start = self._format_srt_time(word_group[0].start)
            end = self._format_srt_time(word_group[-1].end)
            text = " ".join(w.word for w in word_group)

            srt_lines.append(f"{i+1}")
            srt_lines.append(f"{start} --> {end}")
            srt_lines.append(text)
            srt_lines.append("")

        return "\n".join(srt_lines)

    def _format_srt_time(self, seconds: float) -> str:
        """Convert seconds to SRT time format: HH:MM:SS,mmm"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _group_words(
        self,
        words: list[WordTimestamp],
        max_words: int = 8,
        max_duration: float = 3.0,
    ) -> list[list[WordTimestamp]]:
        """Group words into subtitle lines"""
        groups = []
        current_group = []

        for word in words:
            current_group.append(word)

            if (len(current_group) >= max_words
                or (current_group[-1].end - current_group[0].start) >= max_duration):
                groups.append(current_group)
                current_group = []

        if current_group:
            groups.append(current_group)

        return groups
```

## 9.4 Speech Emotion Recognition (SER)

```python
# services/audio-analysis/emotion_recognizer.py

class SpeechEmotionRecognizer:
    """
    Recognize emotion from voice (not face).

    Why SER when we already have facial emotion?
    1. Face may not be visible (looking at screen)
    2. Voice carries information face doesn't (screaming, whispering)
    3. Multi-modal fusion (face + voice) = higher accuracy
    4. Voice emotion is more reliable for excitement/rage detection

    Model: Wav2Vec2 fine-tuned on emotion dataset
    Input: 16kHz mono audio, 3-5 second segments
    Output: Emotion probabilities (angry, happy, sad, neutral, fearful, disgusted)

    Fusion Strategy:
    ┌──────────────┐    ┌──────────────┐
    │ Face Emotion │    │ Voice Emotion│
    │ (0.7 happy)  │    │ (0.8 excited)│
    └──────┬───────┘    └──────┬───────┘
           │                    │
           └────────┬───────────┘
                    │
                    ▼
           ┌────────────────┐
           │  Fusion Layer  │
           │  (weighted avg)│
           │  0.75 excited  │
           └────────────────┘
    """

    def __init__(
        self,
        model_path: str = "models/wav2vec2-emotion",
        device: str = "cuda:0",
    ):
        from transformers import AutoModelForAudioClassification, AutoFeatureExtractor

        self.model = AutoModelForAudioClassification.from_pretrained(model_path)
        self.feature_extractor = AutoFeatureExtractor.from_pretrained(model_path)
        self.model.to(device)
        self.model.eval()
        self.device = device

    async def recognize(
        self,
        audio_segment: np.ndarray,
        sample_rate: int = 16000,
    ) -> SpeechEmotionResult:
        """Recognize emotion from an audio segment"""
        inputs = self.feature_extractor(
            audio_segment,
            sampling_rate=sample_rate,
            return_tensors="pt",
            padding=True,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)
            probs = torch.softmax(outputs.logits, dim=-1)[0]

        labels = self.model.config.id2label
        scores = {labels[i]: float(probs[i].cpu()) for i in range(len(labels))}

        top_label = max(scores, key=scores.get)
        top_confidence = scores[top_label]

        return SpeechEmotionResult(
            label=top_label,
            confidence=top_confidence,
            scores=scores,
        )
```

## 9.5 Speaker Diarization

```python
# services/audio-analysis/diarizer.py

class SpeakerDiarizer:
    """
    Identify who is speaking in the audio.

    For single-streamer use case, diarization helps:
    1. Separate streamer voice from game audio/sound effects
    2. Detect when streamer talks to chat vs. talks in-game
    3. Identify guest speakers (collab streams)

    Model: pyannote/speaker-diarization-3.1
    Pipeline:
    1. Voice Activity Detection (where is speech?)
    2. Speaker Embedding (who is speaking?)
    3. Clustering (group same speakers)
    4. Assignment (label each segment)

    For our single-streamer case:
    - Speaker 0: Streamer (dominant speaker, ~90% of speech)
    - Speaker 1: Game audio / sound effects
    - Speaker 2: Guest (rare, collab)
    """

    def __init__(self, auth_token: str = None):
        from pyannote.audio import Pipeline

        self.pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=auth_token,
        )
        self.pipeline.to(torch.device("cuda"))

        # Known speaker embeddings (learned over time)
        self._streamer_embedding = None

    async def diarize(
        self,
        audio_path: str,
        num_speakers: Optional[int] = None,
    ) -> list[SpeakerSegment]:
        """
        Run speaker diarization on audio file.

        Returns:
            List of SpeakerSegment with speaker_id and time range
        """
        diarization = self.pipeline(
            audio_path,
            num_speakers=num_speakers,
        )

        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append(SpeakerSegment(
                speaker_id=speaker,
                start=turn.start,
                end=turn.end,
                duration=turn.end - turn.start,
            ))

        return segments
```

---

# PART 10 — CHAT ANALYSIS & NLP

## 10.1 Sentiment Analysis

```python
# services/chat-analysis/sentiment_analyzer.py

from transformers import pipeline

class ChatSentimentAnalyzer:
    """
    Analyze sentiment of chat messages in real-time.

    Why chat sentiment matters for clip detection:
    - Chat explosion (many messages) + positive sentiment = HYPE moment
    - Chat explosion + negative sentiment = CONTROVERSY (also interesting)
    - Gradual sentiment shift = building tension
    - Emoji floods (🔥🔥🔥) = audience excitement

    Model: distilbert-base-uncased-finetuned-sst-2-english
    Speed: ~5ms per message on CPU
    Accuracy: 92.5% on SST-2

    For Turkish messages, use:
    Model: savasy/bert-base-turkish-sentiment-cased
    """

    def __init__(self):
        self.en_pipeline = pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english",
            device=0,  # GPU
        )
        self.tr_pipeline = pipeline(
            "sentiment-analysis",
            model="savasy/bert-base-turkish-sentiment-cased",
            device=0,
        )

        # Rolling sentiment window
        self._recent_sentiments: deque[float] = deque(maxlen=100)
        self._message_rate: deque[float] = deque(maxlen=100)

    async def analyze(self, message: str, language: str = "en") -> SentimentResult:
        """Analyze sentiment of a single chat message"""
        pipe = self.tr_pipeline if language == "tr" else self.en_pipeline

        result = pipe(message[:512])[0]  # Truncate long messages

        # Convert to numeric score (-1 to +1)
        score = result["score"]
        if result["label"] == "NEGATIVE":
            score = -score

        self._recent_sentiments.append(score)

        return SentimentResult(
            label=result["label"],
            score=score,
            confidence=result["score"],
        )

    def get_sentiment_trend(self) -> SentimentTrend:
        """
        Calculate sentiment trend over recent messages.

        Used by EventDetector to identify:
        - Hype moments (sustained positive + high volume)
        - Controversy (mixed sentiment + high volume)
        - Boredom (neutral + low volume)
        """
        if len(self._recent_sentiments) < 10:
            return SentimentTrend(trend="insufficient_data", score=0.0)

        sentiments = list(self._recent_sentiments)
        avg_sentiment = np.mean(sentiments)
        sentiment_std = np.std(sentiments)

        # Trend detection (linear regression on last 50 messages)
        recent = sentiments[-50:]
        x = np.arange(len(recent))
        slope = np.polyfit(x, recent, 1)[0]

        if slope > 0.01:
            trend = "improving"    # Chat getting more positive
        elif slope < -0.01:
            trend = "declining"    # Chat getting more negative
        else:
            trend = "stable"

        return SentimentTrend(
            trend=trend,
            avg_score=avg_sentiment,
            volatility=sentiment_std,
            slope=slope,
            message_count=len(sentiments),
        )
```

## 10.2 Toxicity Detection

```python
# services/chat-analysis/toxicity_detector.py

class ToxicityDetector:
    """
    Detect toxic/harmful chat messages.

    Not directly used for clip detection, but important for:
    1. Filtering toxic clips (don't publish clips with toxic chat overlay)
    2. Moderation alerts
    3. Chat health monitoring

    Options:
    1. Google Perspective API (cloud, free tier, high accuracy)
    2. Local model (roberta-hate-speech-detector)
    3. Keyword-based fallback
    """

    TOXICITY_THRESHOLD = 0.7

    def __init__(self, use_api: bool = False, api_key: str = None):
        if use_api and api_key:
            self._mode = "api"
            self.api_key = api_key
        else:
            self._mode = "local"
            self.model = pipeline(
                "text-classification",
                model="facebook/roberta-hate-speech-dynabench-r4-target",
                device=0,
            )

    async def detect(self, message: str) -> ToxicityResult:
        """Check message for toxicity"""
        if self._mode == "api":
            return await self._check_perspective_api(message)
        else:
            return self._check_local(message)

    def _check_local(self, message: str) -> ToxicityResult:
        result = self.model(message[:512])[0]
        is_toxic = result["label"] == "hate" and result["score"] > self.TOXICITY_THRESHOLD

        return ToxicityResult(
            is_toxic=is_toxic,
            score=result["score"] if result["label"] == "hate" else 1 - result["score"],
            category=result["label"],
        )
```

## 10.3 Chat Spike Detection

```python
# services/chat-analysis/spike_detector.py

class ChatSpikeDetector:
    """
    Detect sudden increases in chat message rate.

    Chat spike = strong signal for highlight moments:
    - "PogChamp" floods
    - "GG" spam after a win
    - "LUL" spam at funny moments
    - Emoji floods

    Algorithm:
    1. Track message rate (messages per second) using sliding window
    2. Calculate baseline rate (exponential moving average)
    3. Detect when current rate > baseline × threshold
    4. Consider sentiment shift alongside rate spike
    """

    def __init__(
        self,
        window_seconds: int = 10,
        baseline_window: int = 60,
        spike_threshold: float = 3.0,  # 3x above baseline
    ):
        self.window_seconds = window_seconds
        self.spike_threshold = spike_threshold

        self._message_timestamps: deque[float] = deque(maxlen=1000)
        self._rate_history: deque[float] = deque(maxlen=baseline_window)
        self._is_in_spike = False

    def add_message(self, timestamp: float):
        """Register a new chat message"""
        self._message_timestamps.append(timestamp)

    def check_spike(self, current_time: float) -> Optional[ChatSpikeEvent]:
        """Check if a chat spike is occurring"""
        # Clean old messages
        cutoff = current_time - self.window_seconds
        while self._message_timestamps and self._message_timestamps[0] < cutoff:
            self._message_timestamps.popleft()

        # Current rate (messages per second)
        current_rate = len(self._message_timestamps) / self.window_seconds

        # Update baseline
        self._rate_history.append(current_rate)

        if len(self._rate_history) < 10:
            return None

        # Baseline = median of historical rates (robust to outliers)
        baseline_rate = np.median(list(self._rate_history))

        if baseline_rate < 0.1:
            return None  # Too few messages for meaningful detection

        # Spike detection
        ratio = current_rate / max(baseline_rate, 0.1)

        if ratio >= self.spike_threshold and not self._is_in_spike:
            self._is_in_spike = True
            return ChatSpikeEvent(
                timestamp=current_time,
                messages_per_second=current_rate,
                baseline_rate=baseline_rate,
                spike_ratio=ratio,
            )
        elif ratio < self.spike_threshold * 0.5:
            self._is_in_spike = False

        return None
```

---

# PART 11 — HIGHLIGHT SCORING & PREDICTION

## 11.1 Multi-Signal Scoring Algorithm

```python
# services/event-detector/scoring_engine.py

class HighlightScoringEngine:
    """
    Computes a composite highlight score from multiple signals.

    This is the CORE of the clip decision system.
    Each signal contributes a weighted score to the final composite.

    Signal Weights (tuned empirically):
    ┌────────────────────────┬────────┬────────────────────────────────────┐
    │ Signal                 │ Weight │ Rationale                          │
    ├────────────────────────┼────────┼────────────────────────────────────┤
    │ Audio Energy Spike     │ 0.20   │ Screaming/yelling = strong signal  │
    │ Chat Velocity Spike    │ 0.18   │ Audience reaction = crowd wisdom   │
    │ Emotion Intensity      │ 0.15   │ Facial expressions                 │
    │ Emotion Change Rate    │ 0.10   │ Sudden shifts = surprising events  │
    │ Pose Gesture           │ 0.12   │ Physical reactions (hand raises)   │
    │ Pose Motion            │ 0.08   │ Body movement intensity            │
    │ Chat Sentiment Shift   │ 0.07   │ Audience mood change               │
    │ Viewer Count Delta     │ 0.05   │ Audience growth/loss               │
    │ OCR Keywords           │ 0.03   │ On-screen text (VICTORY, etc.)     │
    │ Speech Content         │ 0.02   │ Keywords in transcription          │
    └────────────────────────┴────────┴────────────────────────────────────┘
    Total: 1.00
    """

    # Signal weights
    WEIGHTS = {
        "audio_spike": 0.20,
        "chat_velocity": 0.18,
        "emotion_intensity": 0.15,
        "emotion_change": 0.10,
        "pose_gesture": 0.12,
        "pose_motion": 0.08,
        "chat_sentiment": 0.07,
        "viewer_delta": 0.05,
        "ocr_keyword": 0.03,
        "speech_content": 0.02,
    }

    # Temporal decay (recent events matter more)
    DECAY_HALFLIFE_SECONDS = 5.0

    def __init__(self):
        self._signal_history: dict[str, deque] = {
            signal: deque(maxlen=120)  # Last 120 seconds
            for signal in self.WEIGHTS
        }

    def compute_score(
        self,
        signals: dict[str, float],
        window_seconds: float = 10.0,
    ) -> HighlightScore:
        """
        Compute composite highlight score.

        Args:
            signals: dict of signal_name → current_value (0-1 normalized)
            window_seconds: Time window for score computation

        Returns:
            HighlightScore with composite and per-signal breakdown
        """
        # Update signal history
        for signal_name, value in signals.items():
            if signal_name in self._signal_history:
                self._signal_history[signal_name].append((time.time(), value))

        # Compute weighted score with temporal decay
        composite = 0.0
        breakdown = {}
        now = time.time()

        for signal_name, weight in self.WEIGHTS.items():
            history = self._signal_history.get(signal_name, deque())

            if not history:
                breakdown[signal_name] = 0.0
                continue

            # Get values within window
            window_values = [
                (ts, val) for ts, val in history
                if now - ts <= window_seconds
            ]

            if not window_values:
                breakdown[signal_name] = 0.0
                continue

            # Temporal decay: more recent = higher weight
            decayed_sum = 0.0
            for ts, val in window_values:
                age = now - ts
                decay = 2 ** (-age / self.DECAY_HALFLIFE_SECONDS)
                decayed_sum += val * decay

            # Normalize by number of samples
            signal_score = decayed_sum / max(len(window_values), 1)
            signal_score = min(signal_score, 1.0)  # Cap at 1.0

            breakdown[signal_name] = signal_score
            composite += signal_score * weight

        return HighlightScore(
            composite_score=composite,
            breakdown=breakdown,
            timestamp=now,
        )


class DecisionEngine:
    """
    Makes the final clip/no-clip decision.

    Architecture:
    ┌─────────────────────────────────────────────────────┐
    │                  DECISION ENGINE                     │
    │                                                      │
    │  Input: HighlightScore (composite + breakdown)       │
    │                                                      │
    │  ┌─────────────────────────────────────────────┐    │
    │  │ Layer 1: Threshold Gate                      │    │
    │  │   composite_score > clip_threshold?          │    │
    │  │   (default: 0.65)                            │    │
    │  └──────────────┬──────────────────────────────┘    │
    │                 │ pass                                │
    │  ┌──────────────▼──────────────────────────────┐    │
    │  │ Layer 2: Cooldown Check                      │    │
    │  │   last_clip_time + cooldown < now?           │    │
    │  │   (default: 15 seconds)                      │    │
    │  └──────────────┬──────────────────────────────┘    │
    │                 │ pass                                │
    │  ┌──────────────▼──────────────────────────────┐    │
    │  │ Layer 3: Minimum Evidence                    │    │
    │  │   At least 2 signals above their threshold?  │    │
    │  │   (prevents single-signal false positives)   │    │
    │  └──────────────┬──────────────────────────────┘    │
    │                 │ pass                                │
    │  ┌──────────────▼──────────────────────────────┐    │
    │  │ Layer 4: LLM Validation (optional)           │    │
    │  │   Ask LLM: "Is this clip-worthy?"            │    │
    │  │   Provides context-aware final decision      │    │
    │  └──────────────┬──────────────────────────────┘    │
    │                 │                                     │
    │                 ▼                                     │
    │          CREATE CLIP or REJECT                       │
    └─────────────────────────────────────────────────────┘
    """

    def __init__(
        self,
        clip_threshold: float = 0.65,
        cooldown_seconds: float = 15.0,
        min_evidence_signals: int = 2,
        use_llm_validation: bool = False,
    ):
        self.clip_threshold = clip_threshold
        self.cooldown_seconds = cooldown_seconds
        self.min_evidence_signals = min_evidence_signals
        self.use_llm_validation = use_llm_validation

        self._last_clip_time: Optional[float] = None
        self._scoring_engine = HighlightScoringEngine()

    async def evaluate(self, score: HighlightScore) -> DecisionResult:
        """Evaluate whether to create a clip"""

        # Layer 1: Threshold gate
        if score.composite_score < self.clip_threshold:
            return DecisionResult(
                decision="REJECT",
                reason=f"Score {score.composite_score:.3f} below threshold {self.clip_threshold}",
                score=score,
            )

        # Layer 2: Cooldown check
        now = time.time()
        if self._last_clip_time is not None:
            elapsed = now - self._last_clip_time
            if elapsed < self.cooldown_seconds:
                return DecisionResult(
                    decision="REJECT",
                    reason=f"Cooldown: {elapsed:.1f}s < {self.cooldown_seconds}s",
                    score=score,
                )

        # Layer 3: Minimum evidence
        evidence_count = sum(
            1 for signal, value in score.breakdown.items()
            if value > 0.3  # Individual signal threshold
        )
        if evidence_count < self.min_evidence_signals:
            return DecisionResult(
                decision="REJECT",
                reason=f"Only {evidence_count} evidence signals (need {self.min_evidence_signals})",
                score=score,
            )

        # Layer 4: LLM validation (optional)
        if self.use_llm_validation:
            llm_decision = await self._llm_validate(score)
            if llm_decision == "reject":
                return DecisionResult(
                    decision="REJECT",
                    reason="LLM determined not clip-worthy",
                    score=score,
                )

        # APPROVED — create clip
        self._last_clip_time = now
        return DecisionResult(
            decision="CREATE_CLIP",
            reason=f"Score {score.composite_score:.3f} with {evidence_count} evidence signals",
            score=score,
            priority=score.composite_score,  # Higher score = higher priority
        )

    async def _llm_validate(self, score: HighlightScore) -> str:
        """Ask LLM for context-aware validation"""
        prompt = f"""You are a clip curation assistant for a live streamer.
Given the following highlight signals, decide if this moment is worth clipping.

Signals:
- Composite Score: {score.composite_score:.3f}
- Audio Spike: {score.breakdown.get('audio_spike', 0):.3f}
- Chat Velocity: {score.breakdown.get('chat_velocity', 0):.3f}
- Emotion Intensity: {score.breakdown.get('emotion_intensity', 0):.3f}
- Pose Gesture: {score.breakdown.get('pose_gesture', 0):.3f}

Is this a clip-worthy moment? Reply with CLIP or SKIP and a brief reason."""

        # Call LLM (local or API)
        response = await self.llm_client.complete(prompt, max_tokens=50)

        return "clip" if "CLIP" in response.upper() else "reject"
```

## 11.2 Clip Ranking

```python
# services/decision-engine/clip_ranker.py

class ClipRanker:
    """
    Rank clip candidates by quality for prioritization.

    When multiple clip candidates are generated in a short time,
    ranking determines which ones to process first and which to discard.

    Ranking factors:
    1. Composite highlight score (primary)
    2. Signal diversity (more signals = more interesting)
    3. Temporal uniqueness (avoid similar clips)
    4. Clip quality predictors (audio clarity, face visibility)
    """

    def __init__(
        self,
        max_clips_per_hour: int = 10,
        similarity_threshold: float = 0.7,
    ):
        self.max_clips_per_hour = max_clips_per_hour
        self.similarity_threshold = similarity_threshold

        self._recent_clips: deque[ClipCandidate] = deque(maxlen=max_clips_per_hour)

    def rank(self, candidates: list[ClipCandidate]) -> list[ClipCandidate]:
        """Rank and filter clip candidates"""

        # Score each candidate
        scored = []
        for candidate in candidates:
            rank_score = self._compute_rank_score(candidate)
            scored.append((rank_score, candidate))

        # Sort by rank score (descending)
        scored.sort(key=lambda x: x[0], reverse=True)

        # Filter duplicates (similar timestamps)
        filtered = []
        for rank_score, candidate in scored:
            if self._is_similar_to_recent(candidate):
                continue
            if len(filtered) >= self.max_clips_per_hour:
                break
            candidate.rank_score = rank_score
            filtered.append(candidate)
            self._recent_clips.append(candidate)

        return filtered

    def _compute_rank_score(self, candidate: ClipCandidate) -> float:
        """Compute ranking score for a clip candidate"""
        score = candidate.highlight_score.composite_score

        # Bonus for signal diversity
        active_signals = sum(
            1 for v in candidate.highlight_score.breakdown.values()
            if v > 0.2
        )
        diversity_bonus = min(active_signals / 5.0, 0.2)  # Max 0.2 bonus

        return score + diversity_bonus

    def _is_similar_to_recent(self, candidate: ClipCandidate) -> bool:
        """Check if candidate overlaps with recent clips"""
        for recent in self._recent_clips:
            time_diff = abs(candidate.timestamp - recent.timestamp)
            if time_diff < 30:  # Within 30 seconds = similar moment
                return True
        return False
```

---

# PART 12 — FEATURE ENGINEERING & VECTOR DATABASE

## 12.1 Feature Engineering for Clip Quality

```python
# shared/features/clip_features.py

class ClipFeatureExtractor:
    """
    Extract feature vectors for each clip candidate.

    These features are used for:
    1. Clip ranking (quality prediction)
    2. Semantic search (find similar clips)
    3. Analytics (what makes a good clip?)
    4. Recommendation (similar clip suggestions)

    Feature categories:
    - Visual features (CLIP embeddings, color histogram)
    - Audio features (energy profile, speech ratio)
    - Temporal features (time of stream, duration)
    - Social features (chat velocity, viewer count)
    - Content features (game state, detected objects)
    """

    def __init__(self):
        from transformers import CLIPModel, CLIPProcessor

        self.clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        self.clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        self.clip_model.eval()

    def extract_features(self, clip_path: str, metadata: dict) -> ClipFeatureVector:
        """Extract all features for a clip"""

        # 1. Visual embedding (CLIP)
        frames = self._sample_frames(clip_path, n=5)
        visual_embedding = self._compute_clip_embedding(frames)

        # 2. Audio features
        audio_features = self._compute_audio_features(clip_path)

        # 3. Temporal features
        temporal_features = {
            "stream_time_normalized": metadata.get("stream_time", 0) / 3600,
            "duration": metadata.get("duration", 0),
            "hour_of_day": datetime.now().hour / 24,
        }

        # 4. Social features
        social_features = {
            "chat_velocity": metadata.get("chat_velocity", 0),
            "viewer_count": metadata.get("viewer_count", 0),
            "sentiment_score": metadata.get("avg_sentiment", 0),
        }

        # Combine into single vector
        combined = np.concatenate([
            visual_embedding,          # 512 dims
            audio_features["vector"],  # 64 dims
            np.array(list(temporal_features.values())),  # 3 dims
            np.array(list(social_features.values())),     # 3 dims
        ])

        return ClipFeatureVector(
            clip_id=metadata.get("clip_id"),
            vector=combined,           # 582 dimensions
            metadata=metadata,
        )

    def _compute_clip_embedding(self, frames: list[np.ndarray]) -> np.ndarray:
        """Compute CLIP embedding from representative frames"""
        images = [Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)) for f in frames]

        inputs = self.clip_processor(images=images, return_tensors="pt")

        with torch.no_grad():
            features = self.clip_model.get_image_features(**inputs)
            # Average pooling across frames
            avg_embedding = features.mean(dim=0)
            # Normalize
            avg_embedding = avg_embedding / avg_embedding.norm()

        return avg_embedding.numpy()
```

## 12.2 Vector Database — Semantic Search

```python
# shared/vector_db/chroma_client.py

import chromadb

class VectorStore:
    """
    Vector database for clip storage and semantic search.

    Why ChromaDB?
    - Embedded (no separate server needed)
    - Python-native API
    - HNSW indexing (fast approximate search)
    - Metadata filtering
    - Good enough for single-streamer scale (~10K clips)

    Alternatives:
    - Pinecone: Managed, scalable, expensive
    - Weaviate: Feature-rich, complex setup
    - Milvus: High-scale, needs infrastructure
    - Qdrant: Fast, Rust-based, good API
    - FAISS: Library only, no server features

    For our scale (single streamer, ~10K clips):
    ChromaDB is sufficient and simplest.
    """

    def __init__(self, persist_directory: str = "data/vector_db"):
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(
            name="clips",
            metadata={"hnsw:space": "cosine"},
        )

    def add_clip(self, feature_vector: ClipFeatureVector):
        """Store a clip's feature vector"""
        self.collection.add(
            ids=[feature_vector.clip_id],
            embeddings=[feature_vector.vector.tolist()],
            metadatas=[feature_vector.metadata],
        )

    def search_similar(
        self,
        query_vector: np.ndarray,
        n_results: int = 10,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """
        Find clips similar to a query.

        Use cases:
        - "Find clips like this one"
        - "Find funny moments" (query = funny clip embedding)
        - "Find clips from today" (metadata filter)
        """
        results = self.collection.query(
            query_embeddings=[query_vector.tolist()],
            n_results=n_results,
            where=where,
            include=["metadatas", "distances"],
        )

        clips = []
        for i in range(len(results["ids"][0])):
            clips.append({
                "clip_id": results["ids"][0][i],
                "metadata": results["metadatas"][0][i],
                "similarity": 1 - results["distances"][0][i],  # cosine distance → similarity
            })

        return clips

    def search_by_text(
        self,
        text_query: str,
        n_results: int = 10,
    ) -> list[dict]:
        """
        Search clips by text description using CLIP text encoder.

        Examples:
        - "funny reaction to losing"
        - "excited celebration after winning"
        - "rage moment at game"
        """
        from transformers import CLIPProcessor, CLIPModel

        model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

        inputs = processor(text=[text_query], return_tensors="pt", padding=True)

        with torch.no_grad():
            text_features = model.get_text_features(**inputs)
            text_features = text_features / text_features.norm()

        return self.search_similar(
            query_vector=text_features.numpy()[0],
            n_results=n_results,
        )
```

---

# PART 13 — MODEL ENSEMBLE & CONFIDENCE

## 13.1 Model Ensemble Strategy

```python
# services/decision-engine/ensemble_scorer.py

class EnsembleScorer:
    """
    Combines multiple model outputs into a single confidence score.

    Why ensemble?
    - Single models can be wrong (false positives/negatives)
    - Different models capture different aspects
    - Ensemble is more robust than any single model

    Ensemble methods:
    1. Weighted Average (our default)
    2. Voting (majority vote)
    3. Stacking (meta-model on top of base models)
    4. Cascading (fast model first, expensive model only if uncertain)

    Our cascade approach:
    ┌─────────────────────────────────────────────────┐
    │ Step 1: Fast models (audio + chat)              │
    │   Score > 0.8? → CREATE CLIP (high confidence)  │
    │   Score < 0.3? → REJECT (high confidence)       │
    │   Otherwise → Step 2                             │
    └────────────────────┬────────────────────────────┘
                         │ uncertain
                         ▼
    ┌─────────────────────────────────────────────────┐
    │ Step 2: Expensive models (face + pose + OCR)    │
    │   Recalculate with all signals                  │
    │   Score > 0.65? → CREATE CLIP                   │
    │   Score < 0.4? → REJECT                         │
    │   Otherwise → Step 3                             │
    └────────────────────┬────────────────────────────┘
                         │ still uncertain
                         ▼
    ┌─────────────────────────────────────────────────┐
    │ Step 3: LLM validation                          │
    │   Ask LLM for final decision                    │
    │   Most expensive, used only when needed         │
    └─────────────────────────────────────────────────┘

    This cascade saves ~60% of GPU inference cost
    because most decisions are made in Step 1.
    """

    def __init__(
        self,
        fast_threshold_high: float = 0.8,
        fast_threshold_low: float = 0.3,
        full_threshold: float = 0.65,
    ):
        self.fast_threshold_high = fast_threshold_high
        self.fast_threshold_low = fast_threshold_low
        self.full_threshold = full_threshold

    async def score(
        self,
        fast_signals: dict[str, float],
        full_signals: Optional[dict[str, float]] = None,
    ) -> EnsembleResult:
        """Cascade scoring"""

        # Step 1: Fast signals only (audio + chat)
        fast_score = self._weighted_average(fast_signals)

        if fast_score > self.fast_threshold_high:
            return EnsembleResult(
                score=fast_score,
                decision="CREATE_CLIP",
                confidence="HIGH",
                method="fast_cascade",
            )

        if fast_score < self.fast_threshold_low:
            return EnsembleResult(
                score=fast_score,
                decision="REJECT",
                confidence="HIGH",
                method="fast_cascade",
            )

        # Step 2: Full signals (need expensive models)
        if full_signals is None:
            return EnsembleResult(
                score=fast_score,
                decision="NEEDS_MORE_DATA",
                confidence="LOW",
                method="fast_cascade",
            )

        all_signals = {**fast_signals, **full_signals}
        full_score = self._weighted_average(all_signals)

        if full_score > self.full_threshold:
            return EnsembleResult(
                score=full_score,
                decision="CREATE_CLIP",
                confidence="MEDIUM",
                method="full_ensemble",
            )

        return EnsembleResult(
            score=full_score,
            decision="REJECT",
            confidence="MEDIUM",
            method="full_ensemble",
        )

    def _weighted_average(self, signals: dict[str, float]) -> float:
        """Compute weighted average of signals"""
        weights = HighlightScoringEngine.WEIGHTS
        total_weight = sum(weights.get(k, 0.01) for k in signals)
        if total_weight == 0:
            return 0.0

        weighted_sum = sum(
            signals[k] * weights.get(k, 0.01)
            for k in signals
        )
        return weighted_sum / total_weight
```

---

# PART 14 — EVENT GRAPH & STATE MACHINE

## 14.1 Event Graph

```python
# services/event-detector/event_graph.py

from dataclasses import dataclass
from typing import Optional
from enum import Enum

class EventNode:
    """
    Represents a node in the event graph.

    The event graph tracks causal relationships:
    - Audio Spike CAUSED BY game event
    - Chat Explosion CAUSED BY audio spike
    - Clip Candidate CAUSED BY multiple events

    This enables:
    1. Root cause analysis (why was this clip created?)
    2. Deduplication (same cause → same clip)
    3. Explainability (clip metadata includes cause chain)
    """

    def __init__(
        self,
        event_id: str,
        event_type: str,
        timestamp: float,
        score: float,
        parent_ids: list[str] = None,
    ):
        self.event_id = event_id
        self.event_type = event_type
        self.timestamp = timestamp
        self.score = score
        self.parent_ids = parent_ids or []
        self.child_ids: list[str] = []

class EventGraph:
    """
    Directed acyclic graph of events.

    Example event chain:
    AUDIO_SPIKE (t=100)
        │
        ├── EMOTION_SURPRISE (t=100.5)
        │       │
        │       └── HAND_RAISE (t=101)
        │
        ├── CHAT_SPIKE (t=102)
        │
        └── CLIP_CANDIDATE (t=105)
                │
                └── CLIP_CREATED (t=110)
    """

    def __init__(self, max_age_seconds: float = 300):
        self.nodes: dict[str, EventNode] = {}
        self.max_age_seconds = max_age_seconds

    def add_event(
        self,
        event_id: str,
        event_type: str,
        timestamp: float,
        score: float,
        parent_ids: list[str] = None,
    ):
        node = EventNode(event_id, event_type, timestamp, score, parent_ids)
        self.nodes[event_id] = node

        for parent_id in node.parent_ids:
            if parent_id in self.nodes:
                self.nodes[parent_id].child_ids.append(event_id)

    def get_causal_chain(self, event_id: str) -> list[EventNode]:
        """Get the full causal chain leading to an event"""
        chain = []
        visited = set()
        self._traverse_parents(event_id, chain, visited)
        return list(reversed(chain))

    def _traverse_parents(self, event_id, chain, visited):
        if event_id in visited or event_id not in self.nodes:
            return
        visited.add(event_id)
        node = self.nodes[event_id]
        chain.append(node)
        for parent_id in node.parent_ids:
            self._traverse_parents(parent_id, chain, visited)
```

## 14.2 Stream State Machine

```python
# services/event-detector/state_machine.py

class StreamState(Enum):
    OFFLINE = "offline"
    STARTING = "starting"          # Stream just went live
    WARMING_UP = "warming_up"      # First 5 minutes, building audience
    STEADY = "steady"              # Normal streaming
    HIGH_ENERGY = "high_energy"    # Sustained high signals
    PEAK_MOMENT = "peak_moment"    # Extreme spike (rare)
    COOLING_DOWN = "cooling_down"  # After peak, returning to normal
    ENDING = "ending"              # Stream wrapping up

class StreamStateMachine:
    """
    Tracks the stream's state based on multiple signals.

    State transitions affect:
    - Clip threshold (lower during high_energy)
    - Analysis frequency (higher during peak moments)
    - Notification urgency
    - Resource allocation

    State Diagram:
    OFFLINE → STARTING → WARMING_UP → STEADY ←→ HIGH_ENERGY → PEAK_MOMENT
                                        ↑            │              │
                                        └────────────┘              │
                                              COOLING_DOWN ←────────┘
                                                  │
                                            ENDING → OFFLINE
    """

    def __init__(self):
        self.current_state = StreamState.OFFLINE
        self.state_history: list[tuple[StreamState, float]] = []
        self._state_entered_at: float = 0

        # Transition rules
        self._transitions = {
            (StreamState.OFFLINE, "stream_started"): StreamState.STARTING,
            (StreamState.STARTING, "models_ready"): StreamState.WARMING_UP,
            (StreamState.WARMING_UP, "audience_settled"): StreamState.STEADY,
            (StreamState.STEADY, "sustained_high_signals"): StreamState.HIGH_ENERGY,
            (StreamState.HIGH_ENERGY, "extreme_spike"): StreamState.PEAK_MOMENT,
            (StreamState.PEAK_MOMENT, "signals_normalizing"): StreamState.COOLING_DOWN,
            (StreamState.COOLING_DOWN, "sustained_low_signals"): StreamState.STEADY,
            (StreamState.HIGH_ENERGY, "sustained_low_signals"): StreamState.STEADY,
            (StreamState.STEADY, "stream_ending"): StreamState.ENDING,
            (StreamState.ENDING, "stream_ended"): StreamState.OFFLINE,
        }

    def transition(self, trigger: str) -> Optional[StreamState]:
        """Attempt a state transition"""
        key = (self.current_state, trigger)
        new_state = self._transitions.get(key)

        if new_state and new_state != self.current_state:
            old_state = self.current_state
            self.current_state = new_state
            self._state_entered_at = time.time()
            self.state_history.append((new_state, time.time()))

            logger.info(f"State transition: {old_state.value} → {new_state.value} (trigger: {trigger})")
            return new_state

        return None

    def get_clip_threshold_adjustment(self) -> float:
        """
        Adjust clip threshold based on current state.

        During high energy: lower threshold (catch more moments)
        During steady state: normal threshold
        During warm-up: higher threshold (avoid noise)
        """
        adjustments = {
            StreamState.OFFLINE: 1.0,       # No clips
            StreamState.STARTING: 1.0,       # No clips
            StreamState.WARMING_UP: 1.2,     # Higher threshold
            StreamState.STEADY: 1.0,         # Normal
            StreamState.HIGH_ENERGY: 0.8,    # Lower threshold (more clips)
            StreamState.PEAK_MOMENT: 0.6,    # Much lower (capture everything)
            StreamState.COOLING_DOWN: 1.1,   # Slightly higher
            StreamState.ENDING: 1.3,         # Higher (only best moments)
        }
        return adjustments.get(self.current_state, 1.0)
```

---

# PART 15 — RULE ENGINE

```python
# services/event-detector/rule_engine.py

class RuleEngine:
    """
    Configurable rule engine for custom clip detection rules.

    Users can define rules like:
    - "Create clip when chat says 'PogChamp' more than 10 times in 5 seconds"
    - "Create clip when streamer says a specific word"
    - "Create clip at specific game events"
    - "Never create clips during 'Just Chatting' segments"

    Rule format:
    {
        "name": "pogchamp_flood",
        "condition": {
            "type": "chat_keyword_count",
            "keywords": ["pogchamp", "pog", "poggers"],
            "count_threshold": 10,
            "window_seconds": 5,
        },
        "action": "create_clip",
        "priority": 8,
        "cooldown_seconds": 30,
    }
    """

    def __init__(self):
        self.rules: list[Rule] = []
        self._rule_results: dict[str, deque] = {}

    def add_rule(self, rule: Rule):
        self.rules.append(rule)
        self._rule_results[rule.name] = deque(maxlen=100)

    def evaluate(
        self,
        events: list[SystemEvent],
        context: dict,
    ) -> list[RuleResult]:
        """Evaluate all rules against current events"""
        results = []

        for rule in self.rules:
            if not rule.enabled:
                continue

            # Check cooldown
            if self._is_in_cooldown(rule):
                continue

            # Evaluate condition
            triggered = self._evaluate_condition(rule.condition, events, context)

            if triggered:
                results.append(RuleResult(
                    rule_name=rule.name,
                    triggered=True,
                    action=rule.action,
                    priority=rule.priority,
                    context=context,
                ))
                self._rule_results[rule.name].append(time.time())

        return results

    def _evaluate_condition(
        self,
        condition: dict,
        events: list[SystemEvent],
        context: dict,
    ) -> bool:
        """Evaluate a single rule condition"""
        cond_type = condition["type"]

        if cond_type == "chat_keyword_count":
            return self._eval_chat_keyword_count(condition, events)
        elif cond_type == "audio_energy_threshold":
            return self._eval_audio_energy(condition, events)
        elif cond_type == "emotion_label":
            return self._eval_emotion(condition, events)
        elif cond_type == "combined_score":
            return self._eval_combined_score(condition, context)
        elif cond_type == "time_range":
            return self._eval_time_range(condition)

        return False
```

---

# PART 16 — MONITORING & OBSERVABILITY

## 16.1 Metrics Collection

```python
# shared/utils/metrics.py

from prometheus_client import Counter, Histogram, Gauge, Summary

class SystemMetrics:
    """
    Prometheus metrics for system observability.

    Key metrics to monitor:
    1. Frame processing latency (p50, p95, p99)
    2. Model inference time per model
    3. Event detection rate
    4. Clip creation rate
    5. Kafka consumer lag
    6. GPU utilization and VRAM
    7. Queue depths
    8. Error rates per service
    """

    # Frame processing
    frames_processed = Counter(
        "klip_frames_processed_total",
        "Total frames processed",
        ["service"],
    )
    frame_latency = Histogram(
        "klip_frame_processing_seconds",
        "Frame processing latency",
        ["stage"],
        buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
    )

    # Model inference
    inference_time = Histogram(
        "klip_inference_seconds",
        "Model inference time",
        ["model_name"],
        buckets=[0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1],
    )
    inference_batch_size = Summary(
        "klip_inference_batch_size",
        "Batch size for inference",
    )

    # Events
    events_detected = Counter(
        "klip_events_detected_total",
        "Total events detected",
        ["event_type"],
    )

    # Clips
    clips_created = Counter(
        "klip_clips_created_total",
        "Total clips created",
        ["category"],
    )
    clip_score = Histogram(
        "klip_clip_score",
        "Clip highlight scores",
        buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    )

    # System
    gpu_utilization = Gauge(
        "klip_gpu_utilization_percent",
        "GPU utilization percentage",
    )
    gpu_memory_used = Gauge(
        "klip_gpu_memory_used_gb",
        "GPU memory used in GB",
    )
    queue_depth = Gauge(
        "klip_queue_depth",
        "Current queue depth",
        ["queue_name"],
    )
    kafka_lag = Gauge(
        "klip_kafka_consumer_lag",
        "Kafka consumer group lag",
        ["topic", "group"],
    )
```

## 16.2 Structured Logging

```python
# shared/utils/logging.py

import structlog

def setup_logging(service_name: str, log_level: str = "INFO"):
    """
    Configure structured logging (JSON format).

    Why structured logging?
    - Machine-parseable (Grafana Loki, ELK stack)
    - Consistent fields across services
    - Easy filtering and alerting
    - Correlation IDs for distributed tracing

    Example log entry:
    {
        "timestamp": "2024-01-15T10:30:00.123Z",
        "level": "info",
        "service": "video-analysis",
        "event": "inference_complete",
        "model": "face_detector",
        "frame_id": "frame_00001234",
        "inference_ms": 3.2,
        "detections": 2,
        "correlation_id": "abc-123",
    }
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    return structlog.get_logger(
        service=service_name,
    )
```

---

# PART 17 — PERFORMANCE OPTIMIZATION & SCALING

## 17.1 Profiling

```python
# scripts/benchmark.py

import cProfile
import pstats
from torch.profiler import profile, record_function, ProfilerActivity

class PipelineProfiler:
    """
    Profile the inference pipeline to find bottlenecks.

    Common bottlenecks:
    1. CPU→GPU data transfer (solution: pinned memory)
    2. Model inference (solution: TensorRT, batch, FP16)
    3. Post-processing (solution: vectorize with numpy)
    4. I/O wait (solution: async, pre-fetch)
    """

    @staticmethod
    def profile_inference(model, input_data, iterations: int = 100):
        """Profile model inference with PyTorch profiler"""
        with profile(
            activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA],
            record_shapes=True,
            profile_memory=True,
        ) as prof:
            for _ in range(iterations):
                with record_function("inference"):
                    _ = model(input_data)

        print(prof.key_averages().table(
            sort_by="cuda_time_total",
            row_limit=20,
        ))

    @staticmethod
    def profile_pipeline(pipeline, frame, iterations: int = 50):
        """Profile the full analysis pipeline"""
        profiler = cProfile.Profile()
        profiler.enable()

        for _ in range(iterations):
            pipeline.process_frame_sync(frame)

        profiler.disable()
        stats = pstats.Stats(profiler)
        stats.sort_stats("cumulative")
        stats.print_stats(30)
```

## 17.2 Scaling Strategies

```
SCALING DECISION TREE:

Is the bottleneck CPU?
  ├── Yes → Horizontal scaling (add more pods)
  │         Each pod handles different streams/partitions
  │
Is the bottleneck GPU?
  ├── Yes → Can we optimize the model?
  │     ├── Yes → TensorRT FP16/INT8, batch inference
  │     └── No  → Add more GPU pods (expensive)
  │               OR: Reduce analysis FPS
  │               OR: Use smaller model
  │
Is the bottleneck I/O?
  ├── Yes → Can we cache?
  │     ├── Yes → Redis for frequent reads
  │     └── No  → Optimize network, use local SSD
  │
Is the bottleneck Kafka?
  ├── Yes → Increase partitions
  │         Increase consumer group size
  │         Compress messages (lz4)
  │
Is the bottleneck Database?
  ├── Yes → Read replicas
  │         Connection pooling
  │         Caching layer (Redis)
  │         Time-series DB for metrics (InfluxDB/TimescaleDB)
```

---

# PART 18 — DOCKER & KUBERNETES

## 18.1 Docker Configuration

```dockerfile
# services/video-analysis/Dockerfile

# Multi-stage build for smaller image
FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04 AS base

# System dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (separate layer for caching)
COPY requirements-gpu.txt .
RUN pip3 install --no-cache-dir -r requirements-gpu.txt

# Pre-download ML models (baked into image)
COPY scripts/download_models.py .
RUN python3 download_models.py --models face_detector emotion_recognizer pose_estimator

# Application code
COPY services/video-analysis/ ./video-analysis/
COPY shared/ ./shared/
COPY proto/ ./proto/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python3 -c "import httpx; r = httpx.get('http://localhost:8081/health'); assert r.status_code == 200"

# Run with GPU
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,video

CMD ["python3", "-m", "video_analysis.main"]
```

```yaml
# deploy/docker/docker-compose.prod.yml

version: "3.9"

services:
  # Message Broker
  kafka:
    image: bitnami/kafka:3.6
    environment:
      KAFKA_CFG_NODE_ID: 0
      KAFKA_CFG_PROCESS_ROLES: controller,broker
      KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
    volumes:
      - kafka_data:/bitnami/kafka
    healthcheck:
      test: ["CMD", "kafka-topics.sh", "--bootstrap-server", "localhost:9092", "--list"]
      interval: 10s
      timeout: 5s
      retries: 5

  rabbitmq:
    image: rabbitmq:3.12-management
    environment:
      RABBITMQ_DEFAULT_USER: klip
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASSWORD}
    ports:
      - "15672:15672"  # Management UI
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "check_running"]
      interval: 10s

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s

  # GPU Services
  video-analysis:
    build:
      context: .
      dockerfile: services/video-analysis/Dockerfile
    depends_on:
      kafka:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      REDIS_URL: redis://redis:6379/0
    restart: unless-stopped

  audio-analysis:
    build:
      context: .
      dockerfile: services/audio-analysis/Dockerfile
    depends_on:
      kafka:
        condition: service_healthy
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  # CPU Services
  chat-analysis:
    build:
      context: .
      dockerfile: services/chat-analysis/Dockerfile
    depends_on:
      kafka:
        condition: service_healthy
    deploy:
      replicas: 2

  event-detector:
    build:
      context: .
      dockerfile: services/event-detector/Dockerfile
    depends_on:
      kafka:
        condition: service_healthy
      redis:
        condition: service_healthy

  decision-engine:
    build:
      context: .
      dockerfile: services/decision-engine/Dockerfile
    depends_on:
      kafka:
        condition: service_healthy

  clip-generator:
    build:
      context: .
      dockerfile: services/clip-generator/Dockerfile
    depends_on:
      rabbitmq:
        condition: service_healthy
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  upload-service:
    build:
      context: .
      dockerfile: services/upload-service/Dockerfile
    depends_on:
      rabbitmq:
        condition: service_healthy

  api-gateway:
    build:
      context: .
      dockerfile: services/api-gateway/Dockerfile
    ports:
      - "8000:8000"
    depends_on:
      redis:
        condition: service_healthy

  stream-capture:
    build:
      context: .
      dockerfile: services/stream-capture/Dockerfile
    depends_on:
      kafka:
        condition: service_healthy

  # Monitoring
  prometheus:
    image: prom/prometheus:v2.48.0
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:10.2.0
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana

volumes:
  kafka_data:
  rabbitmq_data:
  grafana_data:
```

---

# PART 19 — TESTING, LOGGING & ERROR RECOVERY

## 19.1 Testing Strategy

```python
# tests/integration/test_pipeline_integration.py

import pytest
import pytest_asyncio
import numpy as np

class TestVideoAnalysisPipeline:
    """Integration tests for the video analysis pipeline"""

    @pytest_asyncio.fixture
    async def pipeline(self):
        """Create pipeline with mock models"""
        face_detector = MockFaceDetector()
        emotion_recognizer = MockEmotionRecognizer()
        pose_estimator = MockPoseEstimator()
        object_detector = MockObjectDetector()
        ocr_engine = MockOCREngine()
        event_producer = MockEventProducer()

        return AnalysisPipeline(
            face_detector=face_detector,
            emotion_recognizer=emotion_recognizer,
            pose_estimator=pose_estimator,
            object_detector=object_detector,
            ocr_engine=ocr_engine,
            event_producer=event_producer,
        )

    @pytest.mark.asyncio
    async def test_pipeline_processes_frame(self, pipeline):
        """Test that pipeline processes a frame without errors"""
        frame = Frame(
            frame_id="test_001",
            timestamp=datetime.utcnow(),
            image=np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8),
            width=1280,
            height=720,
            fps=2.0,
            stream_time_seconds=10.0,
        )

        await pipeline.process_frame(frame)

        # Verify event was published
        assert len(pipeline.event_producer.published_events) == 1
        event = pipeline.event_producer.published_events[0]
        assert event["event_type"] == "analysis.complete"

    @pytest.mark.asyncio
    async def test_pipeline_handles_model_failure(self, pipeline):
        """Test graceful degradation when a model fails"""
        pipeline.pose_estimator = FailingModel()

        frame = create_test_frame()
        await pipeline.process_frame(frame)

        # Should still produce results (without pose data)
        event = pipeline.event_producer.published_events[0]
        assert event["payload"]["poses"] == []

    @pytest.mark.asyncio
    async def test_backpressure_drops_frames(self, pipeline):
        """Test that backpressure mechanism drops frames under load"""
        pipeline.backpressure.max_queue_size = 2

        # Flood the pipeline
        for i in range(20):
            frame = create_test_frame(frame_id=f"flood_{i}")
            await pipeline.process_frame(frame)

        # Not all frames should be processed
        assert pipeline._frames_processed < 20
```

## 19.2 Error Recovery & Retry Strategy

```python
# shared/utils/retry.py

import asyncio
from functools import wraps
from typing import Optional

def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple = (Exception,),
):
    """
    Decorator for exponential backoff retry.

    Pattern:
    Attempt 1: immediate
    Attempt 2: wait 1s (+ random jitter)
    Attempt 3: wait 2s (+ random jitter)
    Attempt 4: wait 4s (+ random jitter)
    ...

    Used for:
    - API calls (Kick API, upload services)
    - Database operations (connection timeouts)
    - External service calls (Perspective API)
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        logger.error(
                            f"All {max_retries} retries exhausted for {func.__name__}: {e}"
                        )
                        raise

                    delay = min(
                        base_delay * (exponential_base ** attempt),
                        max_delay,
                    )
                    if jitter:
                        delay += random.uniform(0, delay * 0.1)

                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                        f"after {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)

            raise last_exception
        return wrapper
    return decorator


class CircuitBreaker:
    """
    Circuit breaker pattern for external service calls.

    States:
    CLOSED → Normal operation, requests pass through
    OPEN → Service failing, requests rejected immediately
    HALF_OPEN → Testing if service recovered

    Prevents cascade failures:
    If upload service is down, don't keep sending requests.
    Queue them and retry when circuit closes.

    ┌─────────┐  success  ┌─────────┐
    │ CLOSED  │ ◄──────── │HALF_OPEN│
    └────┬────┘           └────┬────┘
         │                     │
    failure               failure
         │                     │
         ▼                     ▼
    ┌─────────┐  timeout  ┌─────────┐
    │  OPEN   │ ────────► │HALF_OPEN│
    └─────────┘           └─────────┘
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "default",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name

        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._state = "CLOSED"

    @property
    def state(self) -> str:
        if self._state == "OPEN":
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = "HALF_OPEN"
        return self._state

    def record_success(self):
        self._failure_count = 0
        self._state = "CLOSED"

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = "OPEN"
            logger.error(f"Circuit breaker {self.name} OPENED after {self._failure_count} failures")

    def allow_request(self) -> bool:
        state = self.state
        if state == "CLOSED":
            return True
        elif state == "HALF_OPEN":
            return True  # Allow one test request
        else:
            return False  # OPEN — reject
```

---

# PART 20 — SECURITY & SECRETS MANAGEMENT

## 20.1 OAuth2 with Kick

```python
# shared/auth/kick_oauth.py

class KickOAuthManager:
    """
    OAuth2 flow for Kick API.

    Flow:
    1. Redirect user to Kick authorization page
    2. User approves → redirect back with code
    3. Exchange code for access token
    4. Use access token for API calls
    5. Auto-refresh before expiry

    Security:
    - Client secret stored in environment variable (never in code)
    - Access token stored encrypted in database
    - Refresh token rotated on each use
    - PKCE (Proof Key for Code Exchange) for additional security
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

        self.auth_url = "https://kick.com/oauth/authorize"
        self.token_url = "https://api.kick.app/oauth/token"

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expiry: Optional[float] = None

    def get_authorization_url(self, state: str = None) -> str:
        """Generate OAuth authorization URL"""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "user:read channel:read chat:read",
            "state": state or generate_random_state(),
        }
        query = urllib.parse.urlencode(params)
        return f"{self.auth_url}?{query}"

    async def exchange_code(self, code: str) -> TokenResponse:
        """Exchange authorization code for tokens"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            response.raise_for_status()
            data = response.json()

        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token")
        self._token_expiry = time.time() + data.get("expires_in", 3600)

        return TokenResponse(**data)

    async def get_valid_token(self) -> str:
        """Get a valid access token, refreshing if needed"""
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token

        if self._refresh_token:
            await self._refresh_access_token()
            return self._access_token

        raise RuntimeError("No valid token available. Re-authorize.")

    @retry_with_backoff(max_retries=3)
    async def _refresh_access_token(self):
        """Refresh access token using refresh token"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            response.raise_for_status()
            data = response.json()

        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        self._token_expiry = time.time() + data.get("expires_in", 3600)
```

## 20.2 Secrets Management

```
SECRETS MANAGEMENT STRATEGY:

Development (.env file):
  ✅ .env file in project root
  ✅ .env in .gitignore (never committed)
  ✅ .env.example as template (committed)

Staging/Production (Kubernetes Secrets):
  ✅ Secrets stored in K8s Secret objects
  ✅ Mounted as environment variables
  ✅ Encrypted at rest (etcd encryption)
  ✅ Rotated via K8s secret rotation

Alternative: HashiCorp Vault
  ✅ Dynamic secrets (auto-expire)
  ✅ Secret rotation without restart
  ✅ Audit logging
  ✅ Encryption as a service
  Use when: multi-team, compliance requirements

NEVER:
  ❌ Hardcode secrets in source code
  ❌ Store secrets in Docker images
  ❌ Log secrets to stdout/files
  ❌ Send secrets over unencrypted connections
  ❌ Share secrets via chat/email
```

---

# PART 21 — DATABASE DESIGN

## 21.1 Schema Design

```sql
-- Core tables

CREATE TABLE clips (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stream_id       UUID NOT NULL REFERENCES streams(id),
    title           VARCHAR(500),
    description     TEXT,
    file_path       VARCHAR(1000) NOT NULL,
    thumbnail_path  VARCHAR(1000),
    duration_seconds FLOAT NOT NULL,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    highlight_score  FLOAT NOT NULL,
    category        VARCHAR(50),
    tags            JSONB DEFAULT '[]',
    status          VARCHAR(20) DEFAULT 'processing',
    -- processing, ready, published, failed, archived
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    -- Indexes for common queries
    INDEX idx_clips_stream (stream_id),
    INDEX idx_clips_score (highlight_score DESC),
    INDEX idx_clips_status (status),
    INDEX idx_clips_created (created_at DESC),
    INDEX idx_clips_category (category),
);

CREATE TABLE streams (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform        VARCHAR(20) NOT NULL,
    channel_slug    VARCHAR(100) NOT NULL,
    title           VARCHAR(500),
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    peak_viewers    INT DEFAULT 0,
    total_clips     INT DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
);

CREATE TABLE analysis_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stream_id       UUID NOT NULL REFERENCES streams(id),
    frame_id        VARCHAR(50) NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    -- Analysis data
    faces           JSONB DEFAULT '[]',
    emotions        JSONB DEFAULT '[]',
    poses           JSONB DEFAULT '[]',
    objects         JSONB DEFAULT '[]',
    texts           JSONB DEFAULT '[]',
    audio_features  JSONB DEFAULT '{}',
    -- Scores
    highlight_score FLOAT,
    inference_ms    FLOAT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    INDEX idx_analysis_stream_time (stream_id, timestamp),
);

CREATE TABLE events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stream_id       UUID NOT NULL REFERENCES streams(id),
    event_type      VARCHAR(100) NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    score           FLOAT,
    evidence        JSONB DEFAULT '[]',
    causal_chain    JSONB DEFAULT '[]',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    INDEX idx_events_stream_type (stream_id, event_type),
    INDEX idx_events_time (timestamp),
);

CREATE TABLE clip_publications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clip_id         UUID NOT NULL REFERENCES clips(id),
    platform        VARCHAR(50) NOT NULL,
    platform_url    VARCHAR(1000),
    status          VARCHAR(20) DEFAULT 'pending',
    -- pending, uploading, published, failed
    error_message   TEXT,
    published_at    TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
);

CREATE TABLE user_preferences (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key             VARCHAR(100) NOT NULL UNIQUE,
    value           JSONB NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
);
```

## 21.2 Time-Series Data for Analytics

```
For metrics and analytics, use a time-series optimized storage:

Option 1: TimescaleDB (PostgreSQL extension)
  - Hypertable for automatic partitioning
  - Compression for old data
  - Continuous aggregates for dashboards

Option 2: InfluxDB
  - Purpose-built for time series
  - High write throughput
  - Built-in retention policies

For our scale: PostgreSQL with time-based partitioning is sufficient.

CREATE TABLE metrics_minute (
    stream_id       UUID NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    metric_name     VARCHAR(100) NOT NULL,
    value           FLOAT NOT NULL,
    tags            JSONB DEFAULT '{}',
    PRIMARY KEY (stream_id, timestamp, metric_name)
) PARTITION BY RANGE (timestamp);

-- Monthly partitions
CREATE TABLE metrics_minute_2024_01 PARTITION OF metrics_minute
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
```

---

## DEPLOYMENT SUMMARY

```
┌─────────────────────────────────────────────────────────────────┐
│                    PRODUCTION DEPLOYMENT                         │
│                                                                  │
│  ┌─────────────┐                                                │
│  │   Nginx     │ ← SSL termination, rate limiting, static files │
│  │  (Ingress)  │                                                │
│  └──────┬──────┘                                                │
│         │                                                        │
│  ┌──────▼──────────────────────────────────────────────┐        │
│  │               KUBERNETES CLUSTER                     │        │
│  │                                                      │        │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐    │        │
│  │  │stream-     │  │video-      │  │audio-      │    │        │
│  │  │capture     │  │analysis    │  │analysis    │    │        │
│  │  │(1 pod)     │  │(1-3 pods)  │  │(1-2 pods)  │    │        │
│  │  │CPU: 2      │  │GPU: 1      │  │GPU: 1      │    │        │
│  │  └────────────┘  └────────────┘  └────────────┘    │        │
│  │                                                      │        │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐    │        │
│  │  │chat-       │  │event-      │  │decision-   │    │        │
│  │  │analysis    │  │detector    │  │engine      │    │        │
│  │  │(1-5 pods)  │  │(1 pod)     │  │(1 pod)     │    │        │
│  │  │CPU: 1      │  │CPU: 2      │  │CPU: 1      │    │        │
│  │  └────────────┘  └────────────┘  └────────────┘    │        │
│  │                                                      │        │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐    │        │
│  │  │clip-       │  │upload-     │  │api-        │    │        │
│  │  │generator   │  │service     │  │gateway     │    │        │
│  │  │(1-3 pods)  │  │(1-3 pods)  │  │(2 pods)    │    │        │
│  │  │GPU: 1      │  │CPU: 1      │  │CPU: 1      │    │        │
│  │  └────────────┘  └────────────┘  └────────────┘    │        │
│  │                                                      │        │
│  │  ┌──────────────────────────────────────────────┐   │        │
│  │  │          INFRASTRUCTURE                       │   │        │
│  │  │  Kafka │ RabbitMQ │ Redis │ PostgreSQL        │   │        │
│  │  │  Prometheus │ Grafana │ Loki                  │   │        │
│  │  └──────────────────────────────────────────────┘   │        │
│  └──────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

---

*END OF SOFTWARE ARCHITECTURE DOCUMENT*
*Total: 70 topics covered across 21 parts*
*This document serves as the definitive reference for implementing, deploying, and operating the Klip AI System.*
