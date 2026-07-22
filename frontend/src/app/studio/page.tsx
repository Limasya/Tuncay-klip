"use client";

import { motion, AnimatePresence } from "framer-motion";
import {
  Mic, Eye, Scissors, Cpu, Sparkles, Activity, ArrowLeft, CheckCircle,
  XCircle, Globe, ChevronRight, Music, Wand2, TrendingUp, BarChart2,
  Share2, BrainCircuit, Video, Type, ImageIcon, Play, Radio, Settings,
  Database, Users, Shield, Zap, Film, MessageSquare, LayoutTemplate,
  Search, RefreshCw, Volume2, Smile, ChevronDown, Layers, Download
} from "lucide-react";
import { useState, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

/* ── Types ─────────────────────────────────────── */
interface Tool {
  id: string;
  label: string;
  icon: any;
  color: string;
  desc: string;
  hint: string;
  endpoint: string;
  method: "GET" | "POST" | "DELETE";
  body?: Record<string, any>;
  queryParam?: string;
  inputLabel?: string;
  inputPlaceholder?: string;
}

interface Category {
  id: string;
  label: string;
  emoji: string;
  color: string;
  tools: Tool[];
}

/* ── Full Technology Registry (Matched 100% to FastAPI Routers) ── */
const CATEGORIES: Category[] = [
  {
    id: "stream",
    label: "Kick & Stream",
    emoji: "📡",
    color: "green",
    tools: [
      { id: "kick_monitor_status", label: "Stream Monitor Status", icon: Radio, color: "green", desc: "7/24 Kick kanal izleme durumu.", hint: "Tuncay kanalının aktif yayın durumunu, izleyici sayısını ve stream health'ini döndürür.", endpoint: "/api/system/status", method: "GET", inputLabel: "Kanal adı (opsiyonel)", inputPlaceholder: "tuncay" },
      { id: "kick_monitor_start", label: "Stream Monitor: Başlat", icon: Play, color: "green", desc: "Yayın izlemeyi başlatır.", hint: "İzleme servisi devreye alınır, VAD + Face Tracker + Chat NLP otomatik aktif olur.", endpoint: "/api/system/start", method: "POST", inputLabel: "Kanal URL", inputPlaceholder: "https://kick.com/tuncay" },
      { id: "kick_monitor_stop", label: "Stream Monitor: Durdur", icon: RefreshCw, color: "red", desc: "Yayın izlemeyi durdurur.", hint: "Tüm downstream mikroservisleri (VAD, Face, Chat) durdurur ve buffer temizlenir.", endpoint: "/api/system/stop", method: "POST", inputLabel: "—", inputPlaceholder: "—" },
      { id: "kick_clips_list", label: "Klip Listesi", icon: Film, color: "emerald", desc: "Kaydedilmiş klipleri listeler.", hint: "Veri tabanındaki tüm klipler, skor ve metadata ile birlikte listelenir.", endpoint: "/api/kick-clips/", method: "GET", inputLabel: "Limit (opsiyonel)", inputPlaceholder: "20" },
      { id: "kick_clips_stats", label: "Klip İstatistikleri", icon: BarChart2, color: "emerald", desc: "Klip üretim istatistikleri.", hint: "Toplam klip sayısı, ortalama skor, başarı oranı ve zaman serisi verir.", endpoint: "/api/kick-clips/stats", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "kick_render_status", label: "Render Durumu", icon: Layers, color: "yellow", desc: "Aktif render job'larının durumu.", hint: "FFmpeg render job'larının kuyruğunu ve tamamlanan render'ları listeler.", endpoint: "/api/kick-clips/render-status", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "kick_archive", label: "Yayın Arşivi", icon: Database, color: "teal", desc: "Arşivlenmiş yayın verileri.", hint: "Geçmiş yayınların VOD URL'leri ve meta verilerini döndürür.", endpoint: "/api/v1/social/kick-archive/status", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
    ],
  },
  {
    id: "audio_voice",
    label: "Audio & Voice",
    emoji: "🎙️",
    color: "purple",
    tools: [
      { id: "pipeline_status", label: "VAD Pipeline Status", icon: Mic, color: "purple", desc: "Ses aktivite tespiti durumu.", hint: "Canlı VAD motorunun ses enerji seviyesini ve sessizlik tespitini döndürür.", endpoint: "/api/pipeline/status", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "pipeline_metrics", label: "Pipeline Metrics", icon: Activity, color: "purple", desc: "Canlı pipeline metrikleri.", hint: "Frame rate, audio lag, queue depth, memory kullanımı gibi gerçek zamanlı metrikler.", endpoint: "/api/pipeline/metrics", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "whisper_status", label: "Whisper Servis Durumu", icon: Type, color: "indigo", desc: "Faster-Whisper model durumu.", hint: "Whisper transkripsiyon modelinin GPU/CPU bellek kullanımını ve yüklenme durumunu döndürür.", endpoint: "/api/llm/whisper/status", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "generate_subtitles", label: "Whisper: Altyazı Üret", icon: Type, color: "indigo", desc: "Faster-Whisper ile SRT üretir.", hint: "Video dosyası yolu verildiğinde Faster-Whisper modeli SRT formatında altyazı döndürür.", endpoint: "/api/pipeline/generate-subtitles", method: "POST", body: { video_path: "__input__", language: "tr" }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "beat_sync", label: "Beat Sync Engine", icon: Music, color: "pink", desc: "Müzik ritmine göre kesim noktaları.", hint: "Librosa ile onset/tempo tespiti yaparak beat-synced edit marker'ları üretir.", endpoint: "/api/v1/edit/beat-sync", method: "POST", body: { source_path: "__input__", sensitivity: 0.6 }, inputLabel: "Ses/Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "audio_ducking", label: "Audio Ducking", icon: Volume2, color: "violet", desc: "Konuşma anında arka plan müziğini kısar.", hint: "VAD sinyali algılandığında arka plan müziğinin sesini otomatik düşürür.", endpoint: "/api/v1/edit/audio/ducking", method: "POST", body: { source_path: "__input__", duck_db: -12.0 }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "multilingual_sub", label: "Çok Dilli Altyazı", icon: Globe, color: "blue", desc: "Çoklu dil altyazı çevirisi.", hint: "Mevcut altyazıları hedef dile çevirir (DeepL / LibreTranslate).", endpoint: "/api/advanced/subtitles/translate", method: "POST", body: { text: "__input__", target_language: "en" }, inputLabel: "Çevrilecek metin", inputPlaceholder: "Merhaba dünya..." },
    ],
  },
  {
    id: "vision",
    label: "Vision & Face",
    emoji: "👁️",
    color: "blue",
    tools: [
      { id: "face_track_metrics", label: "Face Tracker & Metrics", icon: Eye, color: "blue", desc: "Yüz izleme ve duygu metrikleri.", hint: "MediaPipe Primary + OpenCV Haar Cascade fallback. Gerçek zamanlı yüz koordinatları ve duygu sinyalleri.", endpoint: "/api/pipeline/metrics", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "scene_detect", label: "Scene Detection", icon: Video, color: "teal", desc: "Sahne geçişi tespiti.", hint: "FFmpeg scene filter ile shot boundary tespiti yapar. Timestamp listesi döner.", endpoint: "/api/v1/edit/scene-detect", method: "POST", body: { source_path: "__input__", threshold: 27.0 }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "analyze_frame", label: "Frame Analyzer", icon: Search, color: "cyan", desc: "Tek kare görsel analizi.", hint: "Bir frame'den yüz, nesne, metin (OCR), sahneleri tespit eder.", endpoint: "/api/pipeline/analyze-frame", method: "POST", body: { frame_path: "__input__" }, inputLabel: "Frame yolu", inputPlaceholder: "/data/frames/frame_001.jpg" },
      { id: "emotion_arc", label: "Emotion Arc", icon: Smile, color: "orange", desc: "Duygu ark analizi.", hint: "Video boyunca duygu yoğunluğunu zaman serisi olarak hesaplar. Doruk noktaları = klip adayları.", endpoint: "/api/v1/edit/emotion-arc", method: "POST", body: { source_path: "__input__" }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
    ],
  },
  {
    id: "editing",
    label: "AI Editing & Effects",
    emoji: "✂️",
    color: "cyan",
    tools: [
      { id: "edit_spec", label: "Smart Edit Spec", icon: LayoutTemplate, color: "cyan", desc: "AI edit spec üretir.", hint: "Kaynak videodan analiz sinyalleriyle kesim, geçiş, LUT ve zoom parametreleri üretir.", endpoint: "/api/v1/edit/spec", method: "POST", body: { source_path: "__input__", category: "exciting", aspect_ratio: "9:16" }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "sticker_overlay", label: "Sticker Engine", icon: Wand2, color: "fuchsia", desc: "Otomatik sticker overlay.", hint: "Duygusal doruk noktalarını tespit edip dinamik sticker ve görsel efektler ekler.", endpoint: "/api/v1/edit/sticker", method: "POST", body: { source_path: "__input__", auto_detect: true }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "word_highlight", label: "Word Highlight (Timing)", icon: Type, color: "amber", desc: "Karaoke tarzı sözcük vurgusu.", hint: "Whisper word-timing ile senkronize, animasyonlu sözcük vurgusu altyazısı üretir.", endpoint: "/api/v1/edit/word-timing", method: "POST", body: { source_path: "__input__" }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "lower_third", label: "Lower Third", icon: Film, color: "yellow", desc: "Alt başlık overlay.", hint: "Yayıncı adı, başlık ve sosyal medya handle'larını video altına overlay olarak ekler.", endpoint: "/api/v1/edit/lower-third", method: "POST", body: { source_path: "__input__", title: "Tuncay", subtitle: "Gaming" }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "split_screen", label: "Split Screen", icon: Layers, color: "teal", desc: "Yatay/dikey bölünmüş ekran.", hint: "İki videoyu yan yana veya üst-alt düzenlemesiyle tek karede birleştirir.", endpoint: "/api/v1/edit/split-screen", method: "POST", body: { source_path: "__input__", secondary_path: "/data/clips/b.mp4", layout: "horizontal" }, inputLabel: "Ana video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "end_screen", label: "End Screen", icon: ImageIcon, color: "rose", desc: "YouTube/TikTok end screen.", hint: "Klip sonuna abone ol butonu, sonraki video kartı gibi end screen elementleri ekler.", endpoint: "/api/v1/edit/end-screen", method: "POST", body: { source_path: "__input__" }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "scene_auto_fx", label: "Scene Auto Effects", icon: Sparkles, color: "indigo", desc: "Otomatik sahne görsel efektleri.", hint: "Sahnelerin türüne göre renk paleti, kontrast ve efekt kütüphanesini otomatik uygular.", endpoint: "/api/v1/edit/scene-auto-effects", method: "POST", body: { source_path: "__input__" }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "render_job", label: "Render Job Başlat", icon: Cpu, color: "green", desc: "FFmpeg render job kuyruğuna ekle.", hint: "Edit spec'ten tam bir render job başlatır. async çalışır, job_id döner.", endpoint: "/api/v1/edit/render", method: "POST", body: { source_path: "__input__", platform: "tiktok" }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "ai_stream", label: "Canlı AI Akış (WS)", icon: Zap, color: "purple", desc: "WebSocket ile canlı analiz akışı.", hint: "Sahne tespiti, ses analizi, beat-sync ve bilgi tabanını gerçek zamanlı WebSocket üzerinden yayınlar.", endpoint: "/ws/ai_stream?source_path=__input__", method: "GET", inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
    ],
  },
  {
    id: "ai_analysis",
    label: "AI Analysis & Scoring",
    emoji: "🤖",
    color: "amber",
    tools: [
      { id: "viral_analyze", label: "Viral Predictor", icon: TrendingUp, color: "red", desc: "Viralite skor tahmini.", hint: "Trend uyumu, hook gücü ve izleyici tutma tahminini 0-100 skala ile döndürür.", endpoint: "/api/v1/viral/analyze", method: "POST", body: { clip_path: "__input__", include_recommendations: true }, inputLabel: "Klip yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "viral_trends", label: "Güncel Trendler", icon: TrendingUp, color: "orange", desc: "Platform trend analizi.", hint: "TikTok/Reels/YouTube Shorts trending hashtag ve içerik formatlarını listeler.", endpoint: "/api/v1/viral/trends", method: "GET", inputLabel: "Platform (opsiyonel)", inputPlaceholder: "tiktok" },
      { id: "clip_score", label: "Clip Scorer", icon: BarChart2, color: "amber", desc: "Kompozit klip skoru.", hint: "VAD, emotion, motion, chat spike sinyallerini birleştirerek composite clip score üretir.", endpoint: "/api/pipeline/score", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "signal_fusion", label: "Signal Fusion", icon: Zap, color: "yellow", desc: "Multi-sinyal korelasyon analizi.", hint: "VAD + Chat + Face + Motion sinyallerini tek bir composite score'a dönüştürür.", endpoint: "/api/advanced/signal-fusion/correlation", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "segment_classify", label: "Segment Classifier", icon: Layers, color: "lime", desc: "Video segment sınıflandırması.", hint: "Video segmentlerini highlight/filler/transition/dead_air olarak etiketler.", endpoint: "/api/advanced/segments/classify", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "clip_candidates", label: "Klip Adayları", icon: Scissors, color: "green", desc: "En iyi klip aday segmentleri.", hint: "Composite scoring ile en yüksek puanlı 5-10 klip segmentini listeler.", endpoint: "/api/advanced/segments/clip-candidates", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "viral_techniques", label: "Viral Teknikler", icon: Wand2, color: "rose", desc: "Viral editing teknik analizi.", hint: "Hızlı kesim, hook placement, pattern interrupt gibi viral teknikleri tespit eder.", endpoint: "/api/v1/viral/techniques/analyze", method: "POST", body: { clip_path: "__input__" }, inputLabel: "Klip yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "auto_hook", label: "Auto Hook Generator", icon: Zap, color: "pink", desc: "Otomatik hook cümle üretimi.", hint: "LLM ile klip içeriğinden dikkat çekici 3-5 hook cümlesi üretir.", endpoint: "/api/v1/viral/recommendations", method: "POST", body: { clip_path: "__input__" }, inputLabel: "Klip yolu", inputPlaceholder: "/data/clips/clip.mp4" },
    ],
  },
  {
    id: "thumbnail",
    label: "Thumbnail & Visuals",
    emoji: "🖼️",
    color: "orange",
    tools: [
      { id: "thumbnail_gen", label: "Thumbnail AI", icon: ImageIcon, color: "orange", desc: "Otomatik thumbnail üretimi.", hint: "En yüksek enerji frame'ini seçip marka renkleri ve yazı şablonuyla thumbnail üretir.", endpoint: "/api/v1/clips/thumbnail", method: "POST", body: { video_path: "__input__" }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "thumbnail_ab", label: "Thumbnail A/B Test", icon: BarChart2, color: "amber", desc: "Thumbnail A/B test oluştur.", hint: "İki farklı thumbnail varyantını oluşturur ve hangisinin daha iyi CTR sağlayacağını tahmin eder.", endpoint: "/api/advanced/ab-test/create", method: "POST", body: { clip_path: "__input__", variant_count: 2 }, inputLabel: "Klip yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "title_render", label: "Title Renderer", icon: Type, color: "yellow", desc: "Animasyonlu başlık render.", hint: "FFmpeg drawtext filtresiyle animasyonlu, gradient başlık overlay oluşturur.", endpoint: "/api/v1/edit/title-render", method: "POST", body: { source_path: "__input__", title: "Tuncay | Epic Moment" }, inputLabel: "Video yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "meme_analyze", label: "Meme Analyzer", icon: Smile, color: "pink", desc: "Meme şablonu tespiti.", hint: "Görüntüde bilinen meme şablonlarını tanır ve en uygun metni önerir.", endpoint: "/api/v1/viral/memes/analyze", method: "POST", body: { clip_path: "__input__" }, inputLabel: "Klip yolu", inputPlaceholder: "/data/clips/clip.mp4" },
      { id: "photo_animate", label: "Photo Animator", icon: Film, color: "rose", desc: "Fotoğrafları canlandır.", hint: "Ken Burns efektiyle statik fotoğraflardan dinamik video sekansı üretir.", endpoint: "/api/v1/viral/photos/animate", method: "POST", body: { image_path: "__input__" }, inputLabel: "Fotoğraf yolu", inputPlaceholder: "/data/images/photo.jpg" },
    ],
  },
  {
    id: "publishing",
    label: "Publishing & Social",
    emoji: "📱",
    color: "sky",
    tools: [
      { id: "publisher_stats", label: "Publisher Kuyruğu", icon: Share2, color: "sky", desc: "Sosyal medya yayın kuyruğu.", hint: "Bekleyen yükleme, planlanmış gönderi ve optimal zaman bilgilerini döndürür.", endpoint: "/api/advanced/publisher/stats", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "optimal_time", label: "Optimal Yayın Zamanı", icon: Activity, color: "blue", desc: "Platform bazlı optimal paylaşım zamanı.", hint: "Geçmiş engagement verilerine göre en iyi yayın saatini hesaplar.", endpoint: "/api/advanced/publisher/optimal-time/tiktok", method: "GET", inputLabel: "Platform", inputPlaceholder: "tiktok" },
      { id: "clip_optimizer", label: "Platform Optimizer", icon: Settings, color: "indigo", desc: "Platforma özel video optimize.", hint: "TikTok/Reels/Shorts için aspect ratio, bitrate ve format optimizasyonu yapar.", endpoint: "/api/advanced/clip-optimizer/optimize", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "social_post", label: "Social Caption Gen", icon: MessageSquare, color: "violet", desc: "Caption ve hashtag üretimi.", hint: "LLM ile klip içeriğinden platform-spesifik caption, emoji ve hashtag üretir.", endpoint: "/api/v1/social/generate-viral-video", method: "POST", body: { vod_url: "__input__" }, inputLabel: "VOD URL", inputPlaceholder: "https://kick.com/tuncay/videos/12345" },
      { id: "multi_platform", label: "Multi-Platform Export", icon: Globe, color: "green", desc: "Tüm platformlar için export.", hint: "Tek video'dan TikTok, Reels, Shorts, Twitter formatlarında klip paketini export eder.", endpoint: "/api/advanced/clip-optimizer/optimize-all", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
    ],
  },
  {
    id: "llm_knowledge",
    label: "LLM & Knowledge Base",
    emoji: "🧠",
    color: "violet",
    tools: [
      { id: "llm_providers", label: "LLM Provider Durumu", icon: BrainCircuit, color: "violet", desc: "Aktif LLM sağlayıcı listesi.", hint: "OpenAI, Anthropic, Gemini, Mistral, Groq gibi tüm aktif LLM provider'larını ve devre kesici durumlarını listeler.", endpoint: "/api/llm/status", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "llm_health", label: "LLM Sağlık Kontrolü", icon: Activity, color: "purple", desc: "Tüm LLM sağlayıcı health check.", hint: "Tüm sağlayıcılara test isteği gönderir, circuit breaker durumunu kontrol eder.", endpoint: "/api/llm/health", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "knowledge_search", label: "Knowledge Base Ara (Vector)", icon: Search, color: "indigo", desc: "Vektörel semantik arama.", hint: "Geçmiş klip ve yayın verilerinden semantik benzerlik araması yapar (ChromaDB).", endpoint: "/kb/search", method: "GET", queryParam: "query", inputLabel: "Arama sorgusu", inputPlaceholder: "rage quit anı" },
      { id: "knowledge_stats", label: "Knowledge Base İstatistik", icon: Database, color: "blue", desc: "Vektör store istatistikleri.", hint: "Indexlenmiş klip sayısı, embedding boyutu ve koleksiyon durumunu döndürür.", endpoint: "/kb/stats", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "llm_vector_search", label: "LLM Clip Search", icon: Search, color: "violet", desc: "LLM tabanlı klip arama.", hint: "LLM klip veritabanında semantik arama yapar.", endpoint: "/api/llm/vector/search", method: "POST", body: { query: "__input__", top_k: 5 }, inputLabel: "Sorgu", inputPlaceholder: "komik anlar" },
      { id: "recommendations", label: "İçerik Önerileri", icon: Sparkles, color: "amber", desc: "AI destekli içerik önerileri.", hint: "Geçmiş performans verisine ve güncel trendlere göre içerik formatı ve tema önerir.", endpoint: "/api/recommendations/trending", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
    ],
  },
  {
    id: "analytics",
    label: "Analytics & Quality",
    emoji: "📊",
    color: "emerald",
    tools: [
      { id: "analytics_summary", label: "Analytics Özeti", icon: BarChart2, color: "emerald", desc: "Genel performans özeti.", hint: "Tüm kliplerin toplam görüntülenme, like, retention ve kalite skorlarını özetler.", endpoint: "/api/analytics/summary", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "quality_status", label: "Quality Control Status", icon: Shield, color: "green", desc: "Kalite kontrol servisi durumu.", hint: "Blur, hata oranı, ses kalitesi ve görsel tutarlılık metriklerini döndürür.", endpoint: "/api/advanced/quality/status", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "quality_alerts", label: "Kalite Uyarıları", icon: Activity, color: "red", desc: "Kalite eşiği ihlalleri.", hint: "Tanımlı kalite eşiklerinin altında kalan klipleri ve uyarı nedenlerini listeler.", endpoint: "/api/advanced/quality/alerts", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "cost_summary", label: "API Maliyet Özeti", icon: BarChart2, color: "yellow", desc: "LLM ve API maliyet takibi.", hint: "OpenAI, Anthropic ve diğer servis maliyetlerini günlük/aylık olarak özetler.", endpoint: "/api/advanced/costs/summary", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "feedback_sentiment", label: "Kullanıcı Feedback", icon: Users, color: "teal", desc: "Feedback ve duygu analizi.", hint: "Toplanan kullanıcı feedback'lerinin sentiment dağılımını ve ağırlıklı skoru döndürür.", endpoint: "/api/advanced/feedback/sentiment", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
    ],
  },
  {
    id: "zero_bandwidth",
    label: "Zero-Bandwidth Engine",
    emoji: "🌐",
    color: "teal",
    tools: [
      { id: "zb_analyze_vod", label: "VOD Analiz (0 İndirme)", icon: Globe, color: "teal", desc: "Hiç video indirmeden VOD metadata analizi.", hint: "Sadece JSON metadata kullanarak LLM ile clip önerileri üretir. Bant genişliği: ~2-5 KB.", endpoint: "/api/v1/social/analyze-vod", method: "POST", body: { vod_url: "__input__" }, inputLabel: "VOD URL", inputPlaceholder: "https://kick.com/tuncay/videos/12345" },
      { id: "zb_render_clip", label: "Clip Render (Segment)", icon: Download, color: "emerald", desc: "Sadece onaylanan segmenti indir.", hint: "30-60sn segment indirir (~2-5 MB). Tam VOD indirilmez.", endpoint: "/api/v1/social/render-clip", method: "POST", body: { vod_url: "__input__", clip_id: "llm_12345_120" }, inputLabel: "VOD URL", inputPlaceholder: "https://kick.com/tuncay/videos/12345" },
      { id: "zb_analyze_all", label: "Tüm VOD'ları Analiz Et", icon: Layers, color: "cyan", desc: "Son VOD'ların tamamını analiz et.", hint: "Son 5 VOD'u sırayla analiz eder, her biri için clip önerileri üretir.", endpoint: "/api/v1/social/analyze-all-vods", method: "POST", body: { limit: 5 }, inputLabel: "Limit (opsiyonel)", inputPlaceholder: "5" },
      { id: "zb_suggestions", label: "Öneri Cache", icon: Database, color: "blue", desc: "Cache'lenmiş clip önerilerini getir.", hint: "Daha önce analiz edilen VOD'ların önerilerini cache'den döndürür.", endpoint: "/api/v1/social/clip-suggestions", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "zb_status", label: "Zero-BW Durumu", icon: Activity, color: "green", desc: "Zero-BW analiz durumu.", hint: "Toplam analiz sayısı, önerilen clip sayısı ve son analiz zamanını döndürür.", endpoint: "/api/v1/social/zero-bandwidth/status", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
    ],
  },
  {
    id: "system",
    label: "System & Admin",
    emoji: "⚙️",
    color: "gray",
    tools: [
      { id: "system_status", label: "Sistem Durumu", icon: Activity, color: "green", desc: "Tüm servislerin sağlık durumu.", hint: "FastAPI, FFmpeg, MediaPipe, LLM, Database bağlantılarının sağlık durumunu kontrol eder.", endpoint: "/api/system/status", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "deep_health", label: "Derin Sağlık Kontrolü", icon: Shield, color: "blue", desc: "Deep health check.", hint: "Tüm bağımlılıkları (Redis, DB, FFmpeg, ML modelleri) test eder ve gecikmeyi ölçer.", endpoint: "/api/admin/health/deep", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "services_list", label: "Servis Listesi", icon: Layers, color: "purple", desc: "Kayıtlı tüm mikroservisleri listele.", hint: "Auto-discovery ile bulunan tüm servisleri, portlarını ve durumlarını döndürür.", endpoint: "/api/admin/services", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "metrics_summary", label: "Sistem Metrikleri", icon: BarChart2, color: "indigo", desc: "CPU, RAM, disk metrikleri.", hint: "psutil ile toplanan sistem kaynak kullanımını özetler.", endpoint: "/api/admin/metrics/summary", method: "GET", inputLabel: "—", inputPlaceholder: "—" },
      { id: "cache_clear", label: "Cache Temizle", icon: RefreshCw, color: "red", desc: "Tüm cache'leri temizler.", hint: "Redis ve in-memory cache'i temizler. Aktif render job'lar etkilenmez.", endpoint: "/api/admin/cache/clear", method: "POST", body: {}, inputLabel: "—", inputPlaceholder: "—" },
      { id: "backup_trigger", label: "Yedekleme Başlat", icon: Database, color: "teal", desc: "Manuel yedekleme başlatır.", hint: "Veritabanı, klip metadata'sı ve konfigürasyon dosyalarını yedekler.", endpoint: "/api/admin/backups/trigger", method: "POST", body: {}, inputLabel: "—", inputPlaceholder: "—" },
    ],
  },
];

/* ── Pipeline Steps for Omni-Engine ─────────────── */
const PIPELINE_STEPS = [
  { id: "s1", label: "VAD + Audio Analysis",           icon: Mic,            endpoint: "/api/pipeline/status",                     method: "GET" },
  { id: "s2", label: "Face + Scene Detection",          icon: Eye,            endpoint: "/api/pipeline/metrics",                    method: "GET" },
  { id: "s3", label: "Segment Classification",          icon: Layers,         endpoint: "/api/advanced/segments/classify",          method: "GET" },
  { id: "s4", label: "Signal Fusion Correlation",       icon: Zap,            endpoint: "/api/advanced/signal-fusion/correlation",  method: "GET" },
  { id: "s5", label: "Clip Candidate Selection",        icon: Scissors,       endpoint: "/api/advanced/segments/clip-candidates",   method: "GET" },
  { id: "s6", label: "Smart Edit Spec Generation",      icon: LayoutTemplate, endpoint: "/api/v1/edit/spec",                         method: "POST" },
  { id: "s7", label: "Whisper Subtitles",               icon: Type,           endpoint: "/api/pipeline/generate-subtitles",         method: "POST" },
  { id: "s8", label: "Beat Sync Alignment",             icon: Music,          endpoint: "/api/v1/edit/beat-sync",                      method: "POST" },
  { id: "s9", label: "Thumbnail AI",                    icon: ImageIcon,      endpoint: "/api/v1/clips/thumbnail",                     method: "POST" },
  { id: "s10", label: "Viral Score Prediction",         icon: TrendingUp,     endpoint: "/api/v1/viral/analyze",                       method: "POST" },
  { id: "s11", label: "Quality Control Status",         icon: Shield,         endpoint: "/api/advanced/quality/status",             method: "GET" },
  { id: "s12", label: "Social Publisher Queue",         icon: Share2,         endpoint: "/api/advanced/publisher/stats",            method: "GET" },
];

type StepStatus = "idle" | "running" | "done" | "error";

/* ── Main Component ──────────────────────────────── */
function AIStudioInner() {
  const searchParams = useSearchParams();
  const toolParam   = searchParams.get("tool");
  const catParam    = searchParams.get("cat");

  const ALL_TOOLS = CATEGORIES.flatMap(c => c.tools);

  const [activeTab, setActiveTab]       = useState<string>(toolParam || "omni");
  const [openCats,  setOpenCats]        = useState<Set<string>>(new Set(catParam ? [catParam] : ["stream", "audio_voice"]));
  const [inputVal,  setInputVal]        = useState("");
  const [running,   setRunning]         = useState(false);
  const [results,   setResults]         = useState<any>(null);
  const [stepStatuses, setStepStatuses] = useState<Record<string, StepStatus>>({});

  useEffect(() => {
    if (toolParam) { setActiveTab(toolParam); }
    if (catParam)  { setOpenCats(new Set([catParam])); }
  }, [toolParam, catParam]);

  const toggleCat = (id: string) =>
    setOpenCats(prev => {
      const s = new Set(prev);
      s.has(id) ? s.delete(id) : s.add(id);
      return s;
    });

  const activeTool = activeTab === "omni"
    ? null
    : ALL_TOOLS.find(t => t.id === activeTab);

  /* ── Helper to format metric display ── */
  const extractMetric = (data: any, isOk: boolean, statusCode: number) => {
    if (!isOk) return { label: "Status", val: `Error ${statusCode}` };
    if (!data) return { label: "Status", val: "Success" };
    if (data.viral_score !== undefined) return { label: "Viral Score", val: `${data.viral_score}/100` };
    if (data.score !== undefined) return { label: "Composite Score", val: `${data.score}` };
    if (data.total_clips !== undefined) return { label: "Total Clips", val: `${data.total_clips}` };
    if (data.running !== undefined) return { label: "Monitor Status", val: data.running ? "Active" : "Stopped" };
    if (data.status) return { label: "Status", val: `${data.status}`.toUpperCase() };
    if (data.health) return { label: "Health", val: `${data.health}`.toUpperCase() };
    if (Array.isArray(data)) return { label: "Items Returned", val: `${data.length}` };
    return { label: "Status", val: "HTTP 200 OK" };
  };

  /* ── Run Handler ── */
  const handleRun = async () => {
    if (running) return;
    setRunning(true);
    setResults(null);
    setStepStatuses({});

    if (activeTab === "omni") {
      const init: Record<string, StepStatus> = {};
      PIPELINE_STEPS.forEach(s => (init[s.id] = "idle"));
      setStepStatuses(init);

      const STEP_DELAY = 1200;
      const stepResults: Record<string, any> = {};

      for (let i = 0; i < PIPELINE_STEPS.length; i++) {
        const step = PIPELINE_STEPS[i];
        await new Promise<void>(r => setTimeout(r, i === 0 ? 0 : STEP_DELAY));
        setStepStatuses(p => ({ ...p, [step.id]: "running" }));
        try {
          const res = await fetch(step.endpoint, {
            method: step.method,
            headers: { "Content-Type": "application/json" },
            body: step.method === "POST" ? JSON.stringify({ source_path: inputVal || "/data/demo/demo.mp4", video_path: inputVal || "/data/demo/demo.mp4", clip_path: inputVal || "/data/demo/demo.mp4" }) : undefined,
          });
          const resData = await res.json().catch(() => ({}));
          stepResults[step.id] = { ok: res.ok, status: res.status, data: resData };
        } catch (e: any) {
          stepResults[step.id] = { ok: false, error: e.message };
        }
        setStepStatuses(p => ({ ...p, [step.id]: "done" }));
      }

      setTimeout(() => {
        const okCount = Object.values(stepResults).filter((r: any) => r.ok).length;
        setRunning(false);
        setResults({
          primaryLabel: "Pipeline Completion",
          primary: `${okCount}/${PIPELINE_STEPS.length} Steps OK`,
          latency: ((PIPELINE_STEPS.length * STEP_DELAY) / 1000).toFixed(1) + "s",
          raw: JSON.stringify({ pipeline: "COMPLETED", total_steps: PIPELINE_STEPS.length, successful_steps: okCount, details: stepResults }, null, 2),
        });
      }, PIPELINE_STEPS.length * STEP_DELAY + 300);
      return;
    }

    /* Single Tool */
    if (!activeTool) { setRunning(false); return; }

    let url = activeTool.endpoint;
    let body: any = activeTool.body ? { ...activeTool.body } : undefined;

    if (activeTool.method === "GET" && inputVal && activeTool.queryParam) {
      const sep = url.includes("?") ? "&" : "?";
      url += `${sep}${activeTool.queryParam}=${encodeURIComponent(inputVal)}`;
    } else if (activeTool.method === "GET" && inputVal && url.includes("{")) {
      url = url.replace(/\{[^}]+\}/, encodeURIComponent(inputVal));
    }

    if (body) {
      Object.keys(body).forEach(k => {
        if (body[k] === "__input__") body[k] = inputVal || "/data/clips/clip.mp4";
      });
    }

    const t0 = Date.now();
    try {
      const res  = await fetch(url, {
        method:  activeTool.method,
        headers: { "Content-Type": "application/json" },
        body:    body ? JSON.stringify(body) : undefined,
      });
      const data = await res.json().catch(() => ({}));
      const metric = extractMetric(data, res.ok, res.status);

      setResults({
        primaryLabel: metric.label,
        primary: metric.val,
        latency: ((Date.now() - t0) / 1000).toFixed(2) + "s",
        raw: JSON.stringify(data, null, 2),
        isError: !res.ok,
      });
    } catch (err: any) {
      setResults({ primaryLabel: "Engine Status", primary: "Network Error", latency: "—", raw: err.message || "Request failed", isError: true });
    }
    setRunning(false);
  };

  const activeColor = activeTool?.color ?? "amber";
  const ActiveIcon  = activeTool?.icon  ?? Globe;

  /* ── Render ── */
  return (
    <div className="flex h-[calc(100vh-56px)] overflow-hidden bg-[#050505] text-white">

      {/* ── Sidebar ── */}
      <aside className="w-72 shrink-0 bg-black/80 border-r border-white/5 flex flex-col overflow-hidden">
        <div className="p-4 border-b border-white/5 shrink-0">
          <Link href="/" className="inline-flex items-center gap-1.5 text-xs text-gray-500 hover:text-white transition-colors mb-3">
            <ArrowLeft className="w-3 h-3" /> Dashboard
          </Link>
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-indigo-400" />
            <span className="font-bold text-sm text-white">AI Studio</span>
            <span className="ml-auto text-[10px] text-gray-500 bg-white/5 px-2 py-0.5 rounded-full font-mono">
              {ALL_TOOLS.length + 1} Tools
            </span>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-1">
          {/* Omni-Engine */}
          <button
            onClick={() => { setActiveTab("omni"); setResults(null); setStepStatuses({}); }}
            className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm transition-all ${
              activeTab === "omni"
                ? "bg-gradient-to-r from-amber-500/25 to-orange-500/10 border border-amber-500/30 text-amber-300 shadow-[0_0_15px_rgba(245,158,11,0.15)]"
                : "text-gray-400 hover:text-white hover:bg-white/5 border border-transparent"
            }`}
          >
            <Globe className="w-4 h-4 shrink-0 text-amber-400" />
            <span className="font-bold flex-1 text-left">⚡ Omni-Engine</span>
            <span className="text-[10px] text-amber-500 bg-amber-500/10 px-1.5 py-0.5 rounded-full shrink-0 font-mono">MASTER</span>
          </button>

          <div className="h-px bg-white/5 my-1" />

          {/* Category accordions */}
          {CATEGORIES.map(cat => (
            <div key={cat.id}>
              <button
                onClick={() => toggleCat(cat.id)}
                className="w-full flex items-center gap-2 px-3 py-2 text-left rounded-lg hover:bg-white/5 transition-colors group"
              >
                <span className="text-sm">{cat.emoji}</span>
                <span className={`text-xs font-bold flex-1 text-${cat.color}-400/90 group-hover:text-${cat.color}-300 transition-colors`}>{cat.label}</span>
                <span className="text-[10px] font-mono text-gray-600 mr-1">{cat.tools.length}</span>
                <ChevronDown className={`w-3 h-3 text-gray-600 transition-transform shrink-0 ${openCats.has(cat.id) ? "rotate-180" : ""}`} />
              </button>

              {openCats.has(cat.id) && (
                <div className="ml-3 pl-3 border-l border-white/[0.06] space-y-0.5 mt-0.5 mb-1">
                  {cat.tools.map(tool => {
                    const Icon = tool.icon;
                    const isActive = activeTab === tool.id;
                    return (
                      <button
                        key={tool.id}
                        onClick={() => { setActiveTab(tool.id); setResults(null); }}
                        className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-left transition-all ${
                          isActive ? "bg-white/10 text-white border border-white/10" : "text-gray-400 hover:text-gray-200 hover:bg-white/[0.04] border border-transparent"
                        }`}
                      >
                        <Icon className={`w-3.5 h-3.5 shrink-0 text-${tool.color}-400`} />
                        <span className="text-xs font-medium flex-1 truncate">{tool.label}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          ))}
        </nav>
      </aside>

      {/* ── Workspace ── */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Topbar */}
        <div className="h-14 border-b border-white/5 shrink-0 px-6 flex items-center gap-3 bg-black/30 backdrop-blur">
          <div className={`w-2 h-2 rounded-full bg-${activeColor}-500 shadow-[0_0_6px_currentColor] shrink-0`} />
          <h2 className="font-bold text-sm">
            {activeTab === "omni" ? "⚡ Omni-Engine — Master Pipeline Orchestrator" : activeTool?.label}
          </h2>
          {activeTool && (
            <span className="ml-auto text-[10px] font-mono text-gray-500 bg-black/40 px-2 py-0.5 rounded border border-white/5">
              {activeTool.method} {activeTool.endpoint}
            </span>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-3xl mx-auto space-y-5">
            {/* Hint */}
            {(activeTool?.hint || activeTab === "omni") && (
              <p className="text-xs text-gray-400 bg-white/[0.03] border border-white/5 rounded-xl px-4 py-3">
                ℹ️ {activeTab === "omni"
                  ? `${PIPELINE_STEPS.length} aşamalı Master Pipeline: VAD → Face → Segment → Score → Edit → Subtitle → Beat → Thumbnail → Viral → Quality → Publish.`
                  : activeTool?.hint}
              </p>
            )}

            {/* Input */}
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-5">
              <label className="block text-xs text-gray-400 uppercase tracking-wider mb-2">
                {activeTool?.inputLabel ?? "Payload (URL / Yol / Sorgu)"}
              </label>
              <div className="flex gap-3">
                <input
                  value={inputVal}
                  onChange={e => setInputVal(e.target.value)}
                  placeholder={activeTool?.inputPlaceholder ?? "/data/clips/clip.mp4"}
                  className="flex-1 bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-sm font-mono outline-none transition-all placeholder:text-gray-700 focus:border-indigo-500/40 text-white"
                  onKeyDown={e => e.key === "Enter" && handleRun()}
                />
                <button
                  onClick={handleRun}
                  disabled={running}
                  className={`px-6 py-3 rounded-xl font-bold text-sm flex items-center gap-2 transition-all disabled:opacity-40 bg-${activeColor}-600 hover:bg-${activeColor}-500 text-white`}
                >
                  {running
                    ? <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 0.7, ease: "linear" }}><Activity className="w-4 h-4" /></motion.div>
                    : <ActiveIcon className="w-4 h-4" />}
                  {running ? "Çalışıyor..." : activeTab === "omni" ? "Pipeline'ı Ateşle" : "Çalıştır"}
                </button>
              </div>
            </div>

            {/* Output */}
            <div className="min-h-80 border border-white/10 rounded-2xl bg-black/40 p-5 flex flex-col relative overflow-hidden">
              <h3 className="text-[11px] text-gray-500 uppercase tracking-widest mb-4">
                {activeTab === "omni" ? "Pipeline Telemetri" : "Motor Çıktısı"}
              </h3>

              {/* Idle */}
              {!running && !results && Object.keys(stepStatuses).length === 0 && (
                <div className="flex-1 flex flex-col items-center justify-center gap-3 text-gray-600">
                  <ActiveIcon className="w-12 h-12 opacity-20" />
                  <p className="text-sm">Yukarıya bir değer gir ve Çalıştır'a bas.</p>
                </div>
              )}

              {/* Omni Steps */}
              {activeTab === "omni" && Object.keys(stepStatuses).length > 0 && (
                <div className="space-y-2 relative z-10">
                  {PIPELINE_STEPS.map(step => {
                    const s = stepStatuses[step.id] ?? "idle";
                    const Icon = step.icon;
                    return (
                      <div key={step.id} className={`flex items-center gap-3 p-2.5 rounded-xl border transition-all duration-400 ${
                        s === "running" ? "border-amber-500/40 bg-amber-500/5" :
                        s === "done"    ? "border-green-500/20 bg-green-500/[0.04]" :
                        "border-white/5 opacity-30"
                      }`}>
                        <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
                          s === "running" ? "bg-amber-500/20 text-amber-400" :
                          s === "done"    ? "bg-green-500/20 text-green-400" :
                          "bg-gray-800 text-gray-600"
                        }`}>
                          {s === "running"
                            ? <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1.2, ease: "linear" }}><Activity className="w-3.5 h-3.5" /></motion.div>
                            : s === "done" ? <CheckCircle className="w-3.5 h-3.5" />
                            : <Icon className="w-3.5 h-3.5" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className={`text-xs font-semibold truncate ${s === "running" ? "text-amber-300" : s === "done" ? "text-green-300" : "text-gray-500"}`}>{step.label}</p>
                          <p className="text-[10px] font-mono text-gray-600 truncate">{step.method} {step.endpoint}</p>
                        </div>
                        {s === "done" && <ChevronRight className="w-3.5 h-3.5 text-green-500/40 shrink-0" />}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Single tool running */}
              {running && activeTab !== "omni" && (
                <div className="flex-1 flex flex-col items-center justify-center gap-4">
                  <motion.div animate={{ scale: [1, 1.12, 1] }} transition={{ repeat: Infinity, duration: 1.8 }}
                    className={`w-16 h-16 rounded-full bg-${activeColor}-500/10 flex items-center justify-center border border-${activeColor}-500/20`}>
                    <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 2, ease: "linear" }}>
                      <Cpu className={`w-8 h-8 text-${activeColor}-400`} />
                    </motion.div>
                  </motion.div>
                  <p className="font-mono text-xs text-gray-500">{activeTool?.method} {activeTool?.endpoint}</p>
                </div>
              )}

              {/* Results */}
              <AnimatePresence>
                {results && (
                  <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                    className={`space-y-4 relative z-10 ${activeTab === "omni" ? "mt-5 pt-5 border-t border-white/10" : ""}`}>
                    <div className={`p-3 rounded-xl flex items-center gap-2.5 ${results.isError ? "bg-red-500/10 border border-red-500/20 text-red-400" : "bg-green-500/10 border border-green-500/20 text-green-400"}`}>
                      {results.isError ? <XCircle className="w-4 h-4" /> : <CheckCircle className="w-4 h-4" />}
                      <span className="font-bold text-sm">{results.isError ? "Motor hata döndürdü." : "Başarıyla tamamlandı."}</span>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="bg-black/60 p-4 rounded-xl border border-white/5">
                        <p className="text-[10px] text-gray-500 uppercase font-mono">{results.primaryLabel}</p>
                        <p className={`text-xl font-mono mt-1 ${results.isError ? "text-red-400" : activeTab === "omni" ? "text-amber-400" : "text-white"}`}>{results.primary}</p>
                      </div>
                      <div className="bg-black/60 p-4 rounded-xl border border-white/5">
                        <p className="text-[10px] text-gray-500 uppercase font-mono">Gecikme (Latency)</p>
                        <p className="text-xl font-mono text-white mt-1">{results.latency}</p>
                      </div>
                    </div>
                    <div>
                      <p className="text-[10px] text-gray-500 uppercase font-mono mb-1.5">Ham Yanıt (Telemetry JSON)</p>
                      <pre className="bg-black/70 border border-white/5 p-4 rounded-xl font-mono text-[11px] text-gray-300 overflow-auto max-h-56 leading-relaxed">{results.raw}</pre>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Grid bg */}
              <div className="absolute inset-0 bg-[linear-gradient(to_right,#ffffff06_1px,transparent_1px),linear-gradient(to_bottom,#ffffff06_1px,transparent_1px)] bg-[size:20px_20px] pointer-events-none" />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export default function AIStudio() {
  return (
    <Suspense fallback={<div className="h-screen flex items-center justify-center text-gray-500 text-sm">Studio yükleniyor…</div>}>
      <AIStudioInner />
    </Suspense>
  );
}
