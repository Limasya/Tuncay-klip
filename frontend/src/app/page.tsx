"use client";

import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { Video, Cpu, Play, Pause, CheckCircle, Activity, Sparkles, TrendingUp, BarChart2, Radio, Power, PowerOff, Mic, Eye, MessageSquare, Zap, Scissors, Type, LayoutTemplate, Image as ImageIcon, Download, Edit3, Clock, HardDrive, Users, ThumbsUp, Film, AlertCircle, Globe, Music, Shield, BrainCircuit, Share2, Layers, Search, Wand2, Smile, Volume2, BookOpen, Database, RefreshCw, X, ExternalLink, FileVideo, Copy, Send } from "lucide-react";
import { useState, useEffect, useCallback, useRef } from "react";
import Hls from "hls.js";

const MICROSERVICES = [
  { id: 'video_analysis', label: 'Face Tracking', icon: Eye, color: 'blue', endpoint: '/api/pipeline/metrics' },
  { id: 'audio_analysis', label: 'VAD Engine', icon: Mic, color: 'purple', endpoint: '/api/pipeline/status' },
  { id: 'chat_analysis', label: 'Chat NLP', icon: MessageSquare, color: 'pink', endpoint: '/api/system/status' },
  { id: 'event_detector', label: 'Event Detector', icon: Zap, color: 'yellow', endpoint: '/api/system/status' },
  { id: 'clip_generator', label: 'Clip Generator', icon: Scissors, color: 'green', endpoint: '/api/kick-clips/stats' },
  { id: 'transcription', label: 'Whisper AI', icon: Type, color: 'indigo', endpoint: '/api/pipeline/status' },
  { id: 'video_editor', label: 'Smart Editor', icon: LayoutTemplate, color: 'cyan', endpoint: '/api/smart-editor/status' },
  { id: 'thumbnail', label: 'Thumbnail AI', icon: ImageIcon, color: 'orange', endpoint: '/api/v1/clips/thumbnail' },
  { id: 'zero_bandwidth', label: 'Zero-BW Engine', icon: Globe, color: 'teal', endpoint: '/api/v1/social/zero-bandwidth/status' },
  { id: 'viral_analyzer', label: 'Viral Predictor', icon: TrendingUp, color: 'red', endpoint: '/api/v1/viral/trends' },
  { id: 'ai_critic', label: 'AI Critic', icon: Shield, color: 'lime', endpoint: '/api/system/status' },
  { id: 'emotion_detector', label: 'Emotion Arc', icon: Smile, color: 'rose', endpoint: '/api/system/status' },
  { id: 'scene_detection', label: 'Scene Detection', icon: Film, color: 'sky', endpoint: '/api/system/status' },
  { id: 'beat_sync', label: 'Beat Sync', icon: Music, color: 'fuchsia', endpoint: '/api/system/status' },
  { id: 'signal_fusion', label: 'Signal Fusion', icon: Layers, color: 'amber', endpoint: '/api/advanced/signal-fusion/correlation' },
  { id: 'knowledge_base', label: 'Knowledge Base', icon: BookOpen, color: 'violet', endpoint: '/kb/stats' },
  { id: 'publisher', label: 'Social Publisher', icon: Share2, color: 'emerald', endpoint: '/api/advanced/publisher/stats' },
  { id: 'quality_control', label: 'Quality Control', icon: Shield, color: 'cyan', endpoint: '/api/advanced/quality/status' },
  { id: 'llm_reasoner', label: 'LLM Reasoner', icon: BrainCircuit, color: 'purple', endpoint: '/api/llm/status' },
  { id: 'clip_scorer', label: 'Clip Scorer', icon: BarChart2, color: 'orange', endpoint: '/api/kick-clips/stats' },
  { id: 'meme_overlay', label: 'Meme Engine', icon: Wand2, color: 'pink', endpoint: '/api/system/status' },
  { id: 'audio_mixer', label: 'Audio Mixer', icon: Volume2, color: 'indigo', endpoint: '/api/pipeline/status' },
  { id: 'vector_store', label: 'Vector Store', icon: Database, color: 'teal', endpoint: '/kb/stats' },
  { id: 'auto_sfx', label: 'Auto SFX', icon: Music, color: 'yellow', endpoint: '/api/system/status' },
  { id: 'split_screen', label: 'Split Screen', icon: LayoutTemplate, color: 'cyan', endpoint: '/api/system/status' },
  { id: 'sticker_engine', label: 'Sticker Engine', icon: Wand2, color: 'rose', endpoint: '/api/system/status' },
];

// Static Tailwind color classes (must be complete strings for JIT compiler)
const COLOR_BG: Record<string, string> = {
  blue: 'bg-blue-500/20', purple: 'bg-purple-500/20', pink: 'bg-pink-500/20',
  yellow: 'bg-yellow-500/20', green: 'bg-green-500/20', indigo: 'bg-indigo-500/20',
  cyan: 'bg-cyan-500/20', orange: 'bg-orange-500/20', teal: 'bg-teal-500/20',
  red: 'bg-red-500/20', lime: 'bg-lime-500/20', rose: 'bg-rose-500/20',
  sky: 'bg-sky-500/20', fuchsia: 'bg-fuchsia-500/20', amber: 'bg-amber-500/20',
  violet: 'bg-violet-500/20', emerald: 'bg-emerald-500/20',
};

const COLOR_TEXT: Record<string, string> = {
  blue: 'text-blue-400', purple: 'text-purple-400', pink: 'text-pink-400',
  yellow: 'text-yellow-400', green: 'text-green-400', indigo: 'text-indigo-400',
  cyan: 'text-cyan-400', orange: 'text-orange-400', teal: 'text-teal-400',
  red: 'text-red-400', lime: 'text-lime-400', rose: 'text-rose-400',
  sky: 'text-sky-400', fuchsia: 'text-fuchsia-400', amber: 'text-amber-400',
  violet: 'text-violet-400', emerald: 'text-emerald-400',
};

const COLOR_BORDER: Record<string, string> = {
  blue: 'border-blue-500/30', purple: 'border-purple-500/30', pink: 'border-pink-500/30',
  yellow: 'border-yellow-500/30', green: 'border-green-500/30', indigo: 'border-indigo-500/30',
  cyan: 'border-cyan-500/30', orange: 'border-orange-500/30', teal: 'border-teal-500/30',
  red: 'border-red-500/30', lime: 'border-lime-500/30', rose: 'border-rose-500/30',
  sky: 'border-sky-500/30', fuchsia: 'border-fuchsia-500/30', amber: 'border-amber-500/30',
  violet: 'border-violet-500/30', emerald: 'border-emerald-500/30',
};

export default function Home() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [clips, setClips] = useState<any[]>([]);
  const [loadingClips, setLoadingClips] = useState(false);
  const [analyzingId, setAnalyzingId] = useState<string | null>(null);
  const [clipTasks, setClipTasks] = useState<Record<string, { step: "download" | "edit" }>>({});

  const setClipTask = (id: string, step: "download" | "edit") =>
    setClipTasks(prev => ({ ...prev, [id]: { step } }));
  const clearClipTask = (id: string) =>
    setClipTasks(prev => { const n = { ...prev }; delete n[id]; return n; });

  // Monitor State
  const [monitorStatus, setMonitorStatus] = useState<any>(null);
  const [orchStatus, setOrchStatus] = useState<any>(null);
  const [serviceHealth, setServiceHealth] = useState<Record<string, boolean>>({});

  // Real Stats State
  const [clipStats, setClipStats] = useState<any>(null);
  const [systemHealth, setSystemHealth] = useState<any>(null);
  const [renderStatus, setRenderStatus] = useState<any>(null);
  const [editResults, setEditResults] = useState<any[]>([]);
  const [selectedResult, setSelectedResult] = useState<any | null>(null);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" | "info"; sticky?: boolean } | null>(null);
  const toastTimer = useRef<NodeJS.Timeout | null>(null);
  const [zbStatus, setZbStatus] = useState<any>(null);
  const [viralStats, setViralStats] = useState<any>(null);
  const [qualityStatus, setQualityStatus] = useState<any>(null);
  const [knowledgeStats, setKnowledgeStats] = useState<any>(null);

  // Clip Detail Modal State
  const [activeClip, setActiveClip] = useState<any | null>(null);
  const [chatMessages, setChatMessages] = useState<{ role: string; content: string }[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<Hls | null>(null);

  useEffect(() => {
    fetchRecentClips();
    fetchStats();
    fetchExtraStats();

    const interval = setInterval(fetchMonitorStatus, 3000);
    fetchMonitorStatus();
    return () => clearInterval(interval);
  }, []);

  // Poll orchestrator status every 10s for service grid
  useEffect(() => {
    const interval = setInterval(fetchOrchStatus, 10000);
    fetchOrchStatus();
    return () => clearInterval(interval);
  }, []);

  // Ping each service to check real availability
  useEffect(() => {
    const checkAll = async () => {
      const entries = await Promise.all(
        MICROSERVICES.map(async (svc) => {
          try {
            const res = await fetch(svc.endpoint, { signal: AbortSignal.timeout(3000) });
            // 200-299: healthy
            // 405 Method Not Allowed: endpoint exists but is POST-only → still healthy
            return [svc.id, res.ok || res.status === 405] as const;
          } catch {
            return [svc.id, false] as const;
          }
        })
      );
      setServiceHealth(Object.fromEntries(entries));
    };
    checkAll();
    const interval = setInterval(checkAll, 15000);
    return () => clearInterval(interval);
  }, []);

  // Poll edit results every 5s
  useEffect(() => {
    const interval = setInterval(fetchEditResults, 5000);
    fetchEditResults();
    return () => clearInterval(interval);
  }, []);

  // HLS Player init when activeClip changes
  useEffect(() => {
    if (!activeClip || !videoRef.current) return;
    const video = videoRef.current;
    const url = activeClip.clip_url;
    if (!url) return;

    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }

    if (url.includes(".m3u8") && Hls.isSupported()) {
      const hls = new Hls({ enableWorker: true, lowLatencyMode: true });
      hlsRef.current = hls;
      hls.loadSource(url);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {}));
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = url;
      video.addEventListener("loadedmetadata", () => video.play().catch(() => {}));
    } else {
      video.src = url;
    }

    return () => { if (hlsRef.current) { hlsRef.current.destroy(); hlsRef.current = null; } };
  }, [activeClip]);

  // Scroll chat to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  const handleClipChat = async () => {
    if (!chatInput.trim() || !activeClip) return;
    const userMsg = { role: "user", content: chatInput.trim() };
    setChatMessages(prev => [...prev, userMsg]);
    setChatInput("");
    setChatLoading(true);
    try {
      const res = await fetch(`/api/kick-clips/${activeClip.clip_id}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg.content, history: chatMessages }),
      });
      const text = await res.text();
      setChatMessages(prev => [...prev, { role: "assistant", content: text }]);
    } catch {
      setChatMessages(prev => [...prev, { role: "assistant", content: "[Backend baglanamadi]" }]);
    } finally {
      setChatLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const [statsRes, systemRes, renderRes] = await Promise.all([
        fetch("/api/kick-clips/stats"),
        fetch("/api/system/status"),
        fetch("/api/kick-clips/render-status"),
      ]);
      if (statsRes.ok) setClipStats(await statsRes.json());
      if (systemRes.ok) setSystemHealth(await systemRes.json());
      if (renderRes.ok) setRenderStatus(await renderRes.json());
    } catch (e) {
      console.error("Failed to fetch stats", e);
    }
  };

  const fetchOrchStatus = async () => {
    try {
      const res = await fetch("/api/pipeline/status");
      if (res.ok) setOrchStatus(await res.json());
    } catch (e) {
      // pipeline status requires auth, it's optional
    }
  };

  const fetchEditResults = async () => {
    try {
      const res = await fetch("/api/kick-clips/edit-results");
      if (res.ok) {
        const data = await res.json();
        const newResults: any[] = data.results || [];
        setEditResults(prev => {
          const fresh = prev.length < newResults.length
            ? newResults.slice(prev.length).filter(r => r.status === "ready" || r.status === "completed")
            : [];
          // Schedule notification outside state updater via setTimeout
          if (fresh.length > 0) {
            const clip = fresh[0];
            setTimeout(() => {
              showToast(`Duzenleme tamam: ${clip.title || clip.clip_id}`, "success", true);
              setTimeout(() => {
                openPreview(clip);
                showToast(`${clip.title || clip.clip_id} hazir!`, "success");
              }, 600);
            }, 0);
          }
          return newResults;
        });
      }
    } catch (e) {
      console.error("Failed to fetch edit results", e);
    }
  };

  const fetchExtraStats = async () => {
    try {
      const [zbRes, viralRes, qualityRes, kbRes] = await Promise.all([
        fetch("/api/v1/social/zero-bandwidth/status"),
        fetch("/api/v1/viral/trends"),
        fetch("/api/advanced/quality/status"),
        fetch("/kb/stats"),
      ]);
      if (zbRes.ok) setZbStatus(await zbRes.json());
      if (viralRes.ok) setViralStats(await viralRes.json());
      if (qualityRes.ok) setQualityStatus(await qualityRes.json());
      if (kbRes.ok) setKnowledgeStats(await kbRes.json());
    } catch (e) {
      // optional stats — silent fail
    }
  };

  const fetchMonitorStatus = async () => {
    try {
      const res = await fetch("/api/system/status");
      setMonitorStatus(await res.json());
    } catch (e) {
      console.error("Failed to fetch monitor status");
    }
  };

  const toggleMonitor = async (action: 'start' | 'stop') => {
    try {
      await fetch(`/api/system/${action}`, { method: 'POST' });
      fetchMonitorStatus();
    } catch (e) {
      showToast("Backend'e ulaşılamadı.", "error");
    }
  };

  const showToast = useCallback((message: string, type: "success" | "error" | "info" = "info", sticky = false) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ message, type, sticky });
    if (!sticky) {
      toastTimer.current = setTimeout(() => setToast(null), 4000);
    }
  }, []);

  const fetchRecentClips = async () => {
    setLoadingClips(true);
    try {
      const res = await fetch("/api/kick-clips/");
      const data = await res.json();
      if (Array.isArray(data)) {
        setClips(data);
      } else if (data.clips && Array.isArray(data.clips)) {
        setClips(data.clips);
      } else if (data.status === "success" && data.clips) {
        setClips(data.clips);
      }
    } catch (e) {
      console.error("Failed to fetch clips", e);
    } finally {
      setLoadingClips(false);
    }
  };

  const handleAnalyze = async (clip: any) => {
    setAnalyzingId(clip.clip_id);
    try {
      const res = await fetch(`/api/kick-clips/analyze/${clip.clip_id}`);
      const data = await res.json();
      if (data.analysis) {
        const a = data.analysis;
        showToast(`AI Viral Skor: ${a.viral_potential ?? "—"}/100 — ${a.hook_suggestion ?? ""}`, "success");
      } else if (data.error) {
        showToast(`Analiz hatasi: ${data.error}`, "error");
      } else {
        showToast("Analiz basarisiz oldu.", "error");
      }
    } catch (e) {
      showToast("Backend'e ulasilamadi.", "error");
    } finally {
      setAnalyzingId(null);
    }
  };

  const handleDownloadAndEdit = async (clip: any) => {
    const cid = clip.clip_id;
    setClipTask(cid, "download");
    try {
      const dlRes = await fetch(`/api/kick-clips/${cid}/download`, { method: "POST" });
      const dlData = await dlRes.json();
      if (dlData.status !== "ok") {
        showToast(`Indirme basarisiz: ${dlData.message || "?"}`, "error", true);
        clearClipTask(cid);
        return;
      }
      showToast(`Indirildi: ${clip.title} — Duzenleniyor...`, "success");
      setClipTask(cid, "edit");
      fetchStats();
      const editRes = await fetch("/api/kick-clips/edit?min_score=0&max_clips=5", { method: "POST" });
      const editData = await editRes.json();
      if (editData.status === "started") {
        showToast(editData.message, "info");
        fetchEditResults();
      } else {
        showToast(`Duzenleme baslatilamadi: ${editData.message || "?"}`, "error", true);
      }
    } catch (e) {
      showToast("Backend'e ulasilamadi.", "error");
    } finally {
      clearClipTask(cid);
    }
  };

  const handleGenerate = async () => {
    if (!url) return;
    setLoading(true);
    try {
      const res = await fetch("/api/polyglot-generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url })
      });
      const data = await res.json();
      showToast(data.message, data.status === "error" ? "error" : "success");
    } catch (e) {
      showToast("Backend'e ulasilamadi. Python sunucusu calisiyor mu?", "error");
    } finally {
      setLoading(false);
    }
  };

  const openPreview = useCallback((result: any) => {
    setSelectedResult(result);
  }, []);

  const closePreview = useCallback(() => {
    setSelectedResult(null);
  }, []);

  const totalViews = clipStats?.total_views?.toLocaleString() || "—";
  const totalLikes = clipStats?.total_likes?.toLocaleString() || "—";
  const totalClips = clipStats?.total_clips?.toLocaleString() || "—";
  const resultsCount = renderStatus?.results_count ?? editResults.length;
  const isProcessing = renderStatus?.processing || false;
  const cpuUsage = systemHealth?.cpu_usage ?? null;
  const memUsage = systemHealth?.memory_usage ?? null;
  const zbAnalyses = zbStatus?.total_analyses ?? zbStatus?.analyses_count ?? 0;
  const zbClipsSuggested = zbStatus?.total_suggestions ?? zbStatus?.clips_suggested ?? 0;
  const viralScore = viralStats?.overall_score ?? viralStats?.trend_score ?? null;
  const qualityPassRate = qualityStatus?.pass_rate ?? qualityStatus?.overall_quality ?? null;
  const kbEntries = knowledgeStats?.total_facts ?? knowledgeStats?.document_count ?? 0;

  return (
    <div className="min-h-screen bg-[#0f1015] text-white p-8 relative overflow-hidden">
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-purple-600/20 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[30%] h-[30%] bg-blue-600/20 blur-[100px] rounded-full pointer-events-none" />

      <main className="max-w-7xl mx-auto relative z-10 space-y-10">
        {/* Header */}
        <motion.header
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex justify-between items-center bg-white/[0.03] backdrop-blur border border-white/[0.06] rounded-2xl p-6"
        >
          <div className="flex items-center gap-3">
            <div className="p-3 bg-purple-500/20 rounded-xl">
              <Video className="w-8 h-8 text-purple-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent tracking-tight">
                Tuncay Klip AI
              </h1>
              <p className="text-sm text-gray-400">Adobe-Level Monolith V2</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {isProcessing && (
              <div className="flex items-center gap-2 px-4 py-2 bg-yellow-500/10 rounded-full border border-yellow-500/20">
                <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1.5, ease: "linear" }}>
                  <Cpu className="w-4 h-4 text-yellow-400" />
                </motion.div>
                <span className="text-sm font-medium text-yellow-400">Editing...</span>
              </div>
            )}
            <div className="flex items-center gap-2 px-4 py-2 bg-green-500/10 rounded-full border border-green-500/20">
              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span className="text-sm font-medium text-green-400">Core API Active</span>
            </div>
          </div>
        </motion.header>

        {/* Hero Section */}
        <motion.section
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.1 }}
          className="bg-white/[0.03] backdrop-blur border border-white/[0.06] rounded-3xl p-12 text-center space-y-8 relative overflow-hidden"
        >
          <div className="absolute inset-0 bg-gradient-to-br from-purple-500/5 to-transparent pointer-events-none" />

          <div className="space-y-4 relative z-10">
            <h2 className="text-5xl font-extrabold tracking-tight">
              Create{" "}
              <span className="bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">
                Viral Clips
              </span>{" "}
              in Seconds
            </h2>
            <p className="text-lg text-gray-400 max-w-2xl mx-auto">
              Zero-BW Engine · Viral Predictor · AI Critic · Signal Fusion · Whisper AI · Beat Sync · Smart Crop · Knowledge Base · Social Publisher · 26+ Engines
            </p>
          </div>

          <div className="flex justify-center max-w-3xl mx-auto relative z-10">
            <input
              type="text"
              placeholder="https://kick.com/tuncay/videos/..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="w-full bg-black/40 border border-white/10 rounded-full py-4 pl-6 pr-44 text-white placeholder:text-gray-500 focus:outline-none focus:border-purple-500/60 transition-colors"
            />
            <button
              onClick={handleGenerate}
              disabled={loading}
              className="absolute right-2 top-2 bottom-2 bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 px-8 rounded-full font-semibold transition-all flex items-center gap-2 disabled:opacity-50 cursor-pointer"
            >
              {loading ? (
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ repeat: Infinity, duration: 1, ease: "linear" }}
                >
                  <Cpu className="w-5 h-5" />
                </motion.div>
              ) : (
                <>
                  <Sparkles className="w-5 h-5" />
                  Generate
                </>
              )}
            </button>
          </div>

          {/* AI Studio + Stream Buttons */}
          <div className="flex justify-center mt-6 gap-4">
            <Link href="/studio">
              <motion.button
                whileHover={{ scale: 1.04, boxShadow: "0 0 40px rgba(99,102,241,0.6)" }}
                whileTap={{ scale: 0.97 }}
                className="inline-flex items-center gap-3 px-8 py-3 rounded-full bg-gradient-to-r from-indigo-600 to-purple-700 font-bold text-white shadow-[0_0_25px_rgba(99,102,241,0.4)] transition-all"
              >
                <Cpu className="w-5 h-5" />
                🚀 ENTER AI STUDIO
                <span className="text-xs font-normal opacity-70">· 26+ Engines</span>
              </motion.button>
            </Link>
            <Link href="/ai-stream">
              <motion.button
                whileHover={{ scale: 1.04, boxShadow: "0 0 40px rgba(168,85,247,0.6)" }}
                whileTap={{ scale: 0.97 }}
                className="inline-flex items-center gap-3 px-8 py-3 rounded-full bg-gradient-to-r from-purple-600 to-cyan-600 font-bold text-white shadow-[0_0_25px_rgba(168,85,247,0.4)] transition-all"
              >
                <Zap className="w-5 h-5" />
                ⚡ CANLI AI AKIS
              </motion.button>
            </Link>
          </div>
        </motion.section>

        {/* Live Stream Radar */}
        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
          className="bg-white/[0.03] backdrop-blur border border-white/[0.06] rounded-3xl p-8 relative overflow-hidden"
        >
          <div className="absolute inset-0 bg-blue-500/5 pointer-events-none" />
          <div className="flex flex-col md:flex-row justify-between items-center gap-6 relative z-10">
            <div className="flex items-center gap-4">
              <div className={`p-4 rounded-full ${monitorStatus?.running ? 'bg-red-500/20 text-red-400 animate-pulse' : 'bg-gray-500/20 text-gray-400'}`}>
                <Radio className="w-8 h-8" />
              </div>
              <div>
                <h3 className="text-2xl font-bold">Live Stream Radar</h3>
                <p className="text-gray-400 text-sm mt-1">
                  {monitorStatus?.running ? (
                    <span className="text-green-400">Active (Monitoring {monitorStatus?.channel || "Kick"})</span>
                  ) : (
                    <span className="text-gray-500">Inactive</span>
                  )}
                  {monitorStatus?.is_live && <span className="text-red-400 font-bold ml-2">LIVE</span>}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-6">
              {monitorStatus?.running && (
                <div className="text-xs text-gray-400 flex gap-4">
                  <span>Buffer: <span className="text-white font-mono">30s</span></span>
                  <span>AI: <span className="text-purple-400 font-mono">Ready</span></span>
                </div>
              )}
              
              {!monitorStatus?.running ? (
                <button
                  onClick={() => toggleMonitor('start')}
                  className="bg-green-500/20 hover:bg-green-500/30 text-green-300 px-6 py-3 rounded-xl font-medium transition-colors flex items-center gap-2 cursor-pointer"
                >
                  <Power className="w-5 h-5" /> Start Radar
                </button>
              ) : (
                <button
                  onClick={() => toggleMonitor('stop')}
                  className="bg-red-500/20 hover:bg-red-500/30 text-red-300 px-6 py-3 rounded-xl font-medium transition-colors flex items-center gap-2 cursor-pointer"
                >
                  <PowerOff className="w-5 h-5" /> Stop Radar
                </button>
              )}
            </div>
          </div>
        </motion.section>

        {/* Microservices Orchestration Grid */}
        <section className="space-y-4">
          <h3 className="text-xl font-bold flex items-center gap-2 text-gray-300 px-2">
            <Cpu className="w-5 h-5 text-gray-400" />
            Core Microservices Status
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {MICROSERVICES.map((svc, i) => {
              const Icon = svc.icon;
              const isActive = serviceHealth[svc.id] ?? false;
              return (
                <motion.div
                  key={svc.id}
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: 0.2 + i * 0.05 }}
                  className={`px-4 py-4 rounded-xl border flex items-center gap-3 transition-colors ${
                    isActive
                      ? `bg-white/[0.05] ${COLOR_BORDER[svc.color]} text-white shadow-[0_0_15px_rgba(255,255,255,0.05)]`
                      : `bg-white/[0.02] border-white/5 text-gray-500`
                  }`}
                >
                  <div className={`p-2 rounded-lg ${
                    isActive
                      ? `${COLOR_BG[svc.color]} ${COLOR_TEXT[svc.color]}`
                      : 'bg-gray-800 text-gray-600'
                  }`}>
                    <Icon className="w-5 h-5" />
                  </div>
                  <div className="flex flex-col min-w-0">
                    <span className="font-bold text-sm truncate">{svc.label}</span>
                    <span className="text-[10px] uppercase tracking-wider mt-0.5">
                      {isActive ? (
                        <span className="text-green-400 font-semibold">Online</span>
                      ) : (
                        <span className="text-gray-600">Offline</span>
                      )}
                    </span>
                  </div>
                </motion.div>
              );
            })}
          </div>
          {clips.filter(c => c.downloaded).length > 0 && (
            <div className="flex justify-end">
              <button
                onClick={async () => {
                  const res = await fetch("/api/kick-clips/edit?min_score=0&max_clips=50", { method: 'POST' });
                  const data = await res.json();
                  showToast(data.message || "Edit queue started", "info");
                  fetchEditResults();
                }}
                className="text-sm bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 px-5 py-2.5 rounded-xl font-medium transition-colors flex items-center gap-2"
                disabled={isProcessing}
              >
                {isProcessing ? (
                  <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }}>
                    <Cpu className="w-4 h-4" />
                  </motion.div>
                ) : (
                  <Scissors className="w-4 h-4" />
                )}
                Toplu Duzenle ({clips.filter(c => c.downloaded).length})
              </button>
            </div>
          )}
        </section>

        {/* Real Stats Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard
            icon={<Film className="w-6 h-6 text-purple-400" />}
            title="Total Clips"
            value={totalClips}
            delay={0.2}
          />
          <StatCard
            icon={<Eye className="w-6 h-6 text-blue-400" />}
            title="Total Views"
            value={totalViews}
            delay={0.25}
          />
          <StatCard
            icon={<ThumbsUp className="w-6 h-6 text-green-400" />}
            title="Total Likes"
            value={totalLikes}
            delay={0.3}
          />
          <StatCard
            icon={<CheckCircle className="w-6 h-6 text-cyan-400" />}
            title="Edited Clips"
            value={String(resultsCount)}
            delay={0.35}
            subtitle={isProcessing ? "Processing..." : undefined}
          />
          <StatCard
            icon={<Globe className="w-6 h-6 text-teal-400" />}
            title="Zero-BW Analyses"
            value={String(zbAnalyses)}
            delay={0.4}
          />
          <StatCard
            icon={<TrendingUp className="w-6 h-6 text-red-400" />}
            title="Viral Score"
            value={viralScore !== null ? `${viralScore}/100` : "—"}
            delay={0.45}
          />
          <StatCard
            icon={<Shield className="w-6 h-6 text-green-400" />}
            title="Quality Pass"
            value={qualityPassRate !== null ? `${qualityPassRate}%` : "—"}
            delay={0.5}
          />
          <StatCard
            icon={<BookOpen className="w-6 h-6 text-violet-400" />}
            title="KB Entries"
            value={String(kbEntries)}
            delay={0.55}
          />
        </div>

        {/* System Health Row */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <SystemHealthCard
            icon={<Cpu className="w-5 h-5" />}
            label="CPU"
            value={cpuUsage !== null ? `${cpuUsage}%` : "—"}
            delay={0.4}
            color={cpuUsage !== null && cpuUsage > 80 ? "red" : "green"}
          />
          <SystemHealthCard
            icon={<HardDrive className="w-5 h-5" />}
            label="Memory"
            value={memUsage !== null ? `${memUsage}%` : "—"}
            delay={0.45}
            color={memUsage !== null && memUsage > 80 ? "red" : "green"}
          />
          <SystemHealthCard
            icon={<Activity className="w-5 h-5" />}
            label="Pipeline"
            value={isProcessing ? "Editing" : "Idle"}
            delay={0.5}
            color={isProcessing ? "yellow" : "green"}
            pulse={isProcessing}
          />
        </div>

        {/* Pipeline Activity Timeline */}
        {editResults.length > 0 && (
          <motion.section
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.55 }}
            className="bg-white/[0.03] backdrop-blur border border-white/[0.06] rounded-3xl p-8 space-y-5"
          >
            <h3 className="text-xl font-bold flex items-center gap-2">
              <Activity className="w-5 h-5 text-purple-400" />
              Pipeline Activity
            </h3>
            <div className="space-y-3 max-h-80 overflow-y-auto">
              {editResults.slice().reverse().map((result: any, i: number) => (
                <div
                  key={i}
                  onClick={() => (result.status === 'ready' || result.status === 'completed') && openPreview(result)}
                  className={`flex items-start gap-4 bg-black/30 rounded-xl p-4 border border-white/5 transition-colors ${
                    (result.status === 'ready' || result.status === 'completed') ? 'cursor-pointer hover:bg-black/50 hover:border-purple-500/30' : ''
                  }`}
                >
                  <div className={`p-2 rounded-full ${(result.status === 'ready' || result.status === 'completed') ? 'bg-green-500/20 text-green-400' : 'bg-yellow-500/20 text-yellow-400'}`}>
                    {(result.status === 'ready' || result.status === 'completed') ? <CheckCircle className="w-4 h-4" /> : <Clock className="w-4 h-4" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{result.title || result.clip_id || "Unknown clip"}</p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Score: {result.score ?? "—"} | Platform: {result.platform || "tiktok"} | {result.status}
                      {(result.status === 'ready' || result.status === 'completed') && <span className="text-green-400 ml-2">[Preview]</span>}
                    </p>
                    {result.output_path && (
                      <p className="text-xs text-gray-600 truncate mt-0.5">{result.output_path}</p>
                    )}
                  </div>
                  {result.elapsed && (
                    <span className="text-xs text-gray-500 whitespace-nowrap">{(result.elapsed).toFixed(1)}s</span>
                  )}
                </div>
              ))}
            </div>
          </motion.section>
        )}

        {/* Clip Discovery Gallery */}
        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          className="bg-white/[0.03] backdrop-blur border border-white/[0.06] rounded-3xl p-8 space-y-6"
        >
          <div className="flex justify-between items-center">
            <h3 className="text-2xl font-bold flex items-center gap-2">
              <TrendingUp className="w-6 h-6 text-purple-400" />
              Recent Kick Clips
            </h3>
            <button
              onClick={fetchRecentClips}
              disabled={loadingClips}
              className="text-sm bg-white/10 hover:bg-white/20 px-4 py-2 rounded-full transition-colors disabled:opacity-50 cursor-pointer"
            >
              {loadingClips ? "Yukleniyor..." : "Yenile"}
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
            {/* Loading skeletons */}
            {loadingClips && clips.length === 0 && Array.from({ length: 8 }).map((_, i) => (
              <div key={`skel-${i}`} className="bg-black/40 rounded-xl overflow-hidden border border-white/5 animate-pulse">
                <div className="aspect-video bg-white/5" />
                <div className="p-4 space-y-3">
                  <div className="h-3 bg-white/10 rounded w-3/4" />
                  <div className="h-2 bg-white/5 rounded w-1/2" />
                  <div className="flex gap-2 pt-2">
                    <div className="h-8 bg-white/10 rounded-lg flex-1" />
                    <div className="h-8 bg-white/10 rounded-lg flex-1" />
                  </div>
                </div>
              </div>
            ))}
            {clips.map((clip, i) => (
              <motion.div
                key={clip.clip_id}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.6 + i * 0.05 }}
                className="bg-black/40 rounded-xl overflow-hidden border border-white/5 hover:border-purple-500/30 transition-all group"
              >
                <div className="relative aspect-video cursor-pointer" onClick={() => { setActiveClip(clip); setChatMessages([]); }}>
                  <img src={clip.thumbnail_url} alt={clip.title} className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity" loading="lazy" />
                  <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                    <div className="w-14 h-14 rounded-full bg-black/60 backdrop-blur flex items-center justify-center border border-white/20 hover:scale-110 transition-transform">
                      <Play className="w-6 h-6 text-white ml-1" />
                    </div>
                  </div>
                  <div className="absolute inset-0 bg-gradient-to-t from-black/80 to-transparent flex flex-col justify-end p-4">
                    <p className="font-semibold text-sm line-clamp-2">{clip.title}</p>
                    <div className="flex justify-between items-center mt-2 text-xs text-gray-400">
                      <span className="flex items-center gap-1"><Eye className="w-3 h-3" />{clip.views ?? "—"}</span>
                      <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{clip.duration ? `${Math.round(clip.duration)}s` : "—"}</span>
                    </div>
                  </div>
                </div>
                <div className="p-4 flex gap-2">
                  <button
                    onClick={() => handleAnalyze(clip)}
                    disabled={analyzingId === clip.clip_id}
                    className="flex-1 bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 py-2 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
                  >
                    {analyzingId === clip.clip_id ? (
                      <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }}>
                        <Cpu className="w-4 h-4" />
                      </motion.div>
                    ) : (
                      <>
                        <BarChart2 className="w-4 h-4" />
                        AI Analiz
                      </>
                    )}
                  </button>
                  <button
                    onClick={() => handleDownloadAndEdit(clip)}
                    disabled={!!clipTasks[clip.clip_id]}
                    className="flex-1 bg-blue-500/20 hover:bg-blue-500/30 text-blue-300 py-2 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
                  >
                    {clipTasks[clip.clip_id] ? (
                      <>
                        <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }}>
                          <Download className="w-4 h-4" />
                        </motion.div>
                        {clipTasks[clip.clip_id]!.step === "download" ? "Indiriliyor..." : "Duzenleniyor..."}
                      </>
                    ) : (
                      <>
                        <Edit3 className="w-4 h-4" />
                        Indir & Duzenle
                      </>
                    )}
                  </button>
                </div>
              </motion.div>
            ))}
            {!loadingClips && clips.length === 0 && (
              <div className="col-span-full text-center py-12 text-gray-500">
                <AlertCircle className="w-8 h-8 mx-auto mb-3 opacity-50" />
                Hic klip bulunamadi. Kick API'den veri cekilemedi.
              </div>
            )}
          </div>
        </motion.section>
      </main>

      {/* Clip Detail Modal — HLS Player + AI Kurgu Chat */}
      <AnimatePresence>
        {activeClip && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4"
            onClick={() => { setActiveClip(null); if (hlsRef.current) { hlsRef.current.destroy(); hlsRef.current = null; } }}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.92, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.92, y: 20 }}
              transition={{ type: "spring", damping: 25, stiffness: 300 }}
              onClick={(e) => e.stopPropagation()}
              className="bg-[#12131a] border border-white/10 rounded-3xl w-full max-w-6xl max-h-[90vh] flex flex-col lg:flex-row overflow-hidden shadow-2xl"
            >
              {/* Left: Player + Info */}
              <div className="lg:w-[58%] flex flex-col">
                {/* Video Player */}
                <div className="relative bg-black aspect-video w-full">
                  <video
                    ref={videoRef}
                    className="w-full h-full object-contain"
                    controls
                    autoPlay
                    playsInline
                  />
                  <button
                    onClick={() => { setActiveClip(null); if (hlsRef.current) { hlsRef.current.destroy(); hlsRef.current = null; } }}
                    className="absolute top-3 right-3 p-2 rounded-full bg-black/60 hover:bg-black/80 transition-colors cursor-pointer z-10"
                  >
                    <X className="w-4 h-4 text-white" />
                  </button>
                </div>

                {/* Clip Info */}
                <div className="p-5 space-y-3 border-t border-white/5 flex-1 overflow-y-auto">
                  <h3 className="font-bold text-lg leading-tight">{activeClip.title || "Klip"}</h3>
                  <div className="flex flex-wrap gap-2 text-xs text-gray-400">
                    <span className="flex items-center gap-1 bg-white/5 px-2.5 py-1 rounded-full">
                      <Eye className="w-3 h-3" />{activeClip.views ?? 0} goruntulenme
                    </span>
                    <span className="flex items-center gap-1 bg-white/5 px-2.5 py-1 rounded-full">
                      <ThumbsUp className="w-3 h-3" />{activeClip.likes ?? 0} like
                    </span>
                    <span className="flex items-center gap-1 bg-white/5 px-2.5 py-1 rounded-full">
                      <Clock className="w-3 h-3" />{activeClip.duration ? `${Math.round(activeClip.duration)}s` : "—"}
                    </span>
                    <span className="flex items-center gap-1 bg-white/5 px-2.5 py-1 rounded-full">
                      <Users className="w-3 h-3" />{activeClip.creator_username || "—"}
                    </span>
                  </div>
                  {activeClip.clip_url && (
                    <div className="flex gap-2 pt-1">
                      <a
                        href={activeClip.clip_url}
                        target="_blank"
                        rel="noopener"
                        className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 transition-colors"
                      >
                        <ExternalLink className="w-3 h-3" /> Kick'te Ac
                      </a>
                      {activeClip.thumbnail_url && (
                        <button
                          onClick={() => {
                            const a = document.createElement("a");
                            a.href = activeClip.clip_url;
                            a.download = `${activeClip.clip_id}.m3u8`;
                            a.click();
                          }}
                          className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1 transition-colors cursor-pointer"
                        >
                          <Download className="w-3 h-3" /> Indir
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Right: AI Kurgu Chat */}
              <div className="lg:w-[42%] flex flex-col border-t lg:border-t-0 lg:border-l border-white/5">
                <div className="px-5 py-3 border-b border-white/5 flex items-center gap-2">
                  <BrainCircuit className="w-4 h-4 text-purple-400" />
                  <span className="text-sm font-semibold text-purple-300">AI Kurgu Asistani</span>
                </div>

                {/* Chat Messages */}
                <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0 max-h-[50vh] lg:max-h-none">
                  {chatMessages.length === 0 && (
                    <div className="text-center text-gray-500 text-sm py-8 space-y-2">
                      <Scissors className="w-8 h-8 mx-auto opacity-40" />
                      <p>Bu klib hakkinda kurgu sorusu sorun.</p>
                      <p className="text-xs text-gray-600">Ornek: "Bu klibe nasil hook eklerim?"</p>
                    </div>
                  )}
                  {chatMessages.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[85%] px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed ${
                        msg.role === "user"
                          ? "bg-purple-600/30 text-purple-100 rounded-br-md"
                          : "bg-white/5 text-gray-200 rounded-bl-md"
                      }`}>
                        {msg.content}
                      </div>
                    </div>
                  ))}
                  {chatLoading && (
                    <div className="flex justify-start">
                      <div className="bg-white/5 px-4 py-2.5 rounded-2xl rounded-bl-md text-sm text-gray-400 flex items-center gap-2">
                        <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }}>
                          <Cpu className="w-3.5 h-3.5" />
                        </motion.div>
                        Dusunuyor...
                      </div>
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>

                {/* Chat Input */}
                <div className="p-3 border-t border-white/5">
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleClipChat()}
                      placeholder="Kurgu sorusu sor..."
                      disabled={chatLoading}
                      className="flex-1 bg-white/5 border border-white/10 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-purple-500/50 transition-colors disabled:opacity-50"
                    />
                    <button
                      onClick={handleClipChat}
                      disabled={chatLoading || !chatInput.trim()}
                      className="p-2.5 rounded-xl bg-purple-600/30 hover:bg-purple-600/50 text-purple-300 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <Send className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Clip Preview Modal */}
      <AnimatePresence>
        {selectedResult && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md p-4"
            onClick={closePreview}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: 30 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 30 }}
              transition={{ type: "spring", damping: 25, stiffness: 300 }}
              onClick={(e) => e.stopPropagation()}
              className="bg-[#1a1b23] border border-white/10 rounded-3xl max-w-lg w-full p-8 space-y-6 relative shadow-2xl"
            >
              <button
                onClick={closePreview}
                className="absolute top-4 right-4 p-2 rounded-full bg-black/40 hover:bg-black/60 transition-colors cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>

              <div className="flex items-center gap-3">
                <div className="p-3 bg-purple-500/20 rounded-xl">
                  <FileVideo className="w-6 h-6 text-purple-400" />
                </div>
                <div className="min-w-0">
                  <h3 className="font-bold text-lg truncate">{selectedResult.title || selectedResult.clip_id || "Edited Clip"}</h3>
                  <p className="text-xs text-gray-400">{selectedResult.format || "1080x1920"} @ {selectedResult.fps || 30}fps</p>
                </div>
              </div>

              {/* Thumbnail Preview */}
              <div className="bg-black/50 rounded-2xl overflow-hidden aspect-video flex items-center justify-center border border-white/5">
                {selectedResult.thumbnail_path ? (
                  <img src={selectedResult.thumbnail_path} alt="Thumbnail" className="w-full h-full object-cover" />
                ) : (
                  <FileVideo className="w-16 h-16 text-gray-600" />
                )}
              </div>

              {/* Metadata Grid */}
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="bg-black/30 rounded-xl p-3">
                  <p className="text-gray-500 text-xs">Score</p>
                  <p className="font-bold">{selectedResult.score ?? "—"}</p>
                </div>
                <div className="bg-black/30 rounded-xl p-3">
                  <p className="text-gray-500 text-xs">Platform</p>
                  <p className="font-bold capitalize">{selectedResult.platform || "tiktok"}</p>
                </div>
                <div className="bg-black/30 rounded-xl p-3">
                  <p className="text-gray-500 text-xs">Subtitles</p>
                  <p className="font-bold">{selectedResult.has_subtitles ? "Yes" : "No"}</p>
                </div>
                <div className="bg-black/30 rounded-xl p-3">
                  <p className="text-gray-500 text-xs">Effects</p>
                  <p className="font-bold text-xs truncate">
                    {[
                      selectedResult.has_music && "Music",
                      selectedResult.has_meme && "Meme",
                      selectedResult.has_sfx && "SFX",
                      selectedResult.watermarked && "WM",
                    ].filter(Boolean).join(", ") || "None"}
                  </p>
                </div>
              </div>

              {/* Download Button */}
              {selectedResult.output_path && (
                <a
                  href={selectedResult.output_path}
                  download
                  className="flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 font-semibold transition-all"
                >
                  <Download className="w-5 h-5" />
                  Download Clip
                </a>
              )}

              {/* Action Buttons Row */}
              <div className="flex gap-3">
                <Link
                  href={`/studio?tool=edit_spec`}
                  className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-sm font-medium transition-colors"
                >
                  <Wand2 className="w-4 h-4" />
                  Studio'da Ac
                </Link>
                <button
                  onClick={() => {
                    if (selectedResult.output_path) {
                      navigator.clipboard.writeText(selectedResult.output_path);
                      showToast("Dosya yolu kopyalandi!", "success");
                    }
                  }}
                  className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-sm font-medium transition-colors cursor-pointer"
                >
                  <Copy className="w-4 h-4" />
                  Yolu Kopyala
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Toast Notifications */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 50, x: "-50%" }}
            animate={{ opacity: 1, y: 0, x: "-50%" }}
            exit={{ opacity: 0, y: 20, x: "-50%" }}
            className={`fixed bottom-8 left-1/2 z-50 px-6 py-3 rounded-2xl shadow-2xl border backdrop-blur-md text-sm font-medium flex items-center gap-3 ${
              toast.type === "success"
                ? "bg-green-500/20 border-green-500/30 text-green-300"
                : toast.type === "error"
                ? "bg-red-500/20 border-red-500/30 text-red-300"
                : "bg-blue-500/20 border-blue-500/30 text-blue-300"
            }`}
          >
            {toast.type === "success" && <CheckCircle className="w-4 h-4 flex-shrink-0" />}
            {toast.type === "error" && <AlertCircle className="w-4 h-4 flex-shrink-0" />}
            {toast.type === "info" && <Sparkles className="w-4 h-4 flex-shrink-0" />}
            <span className="flex-1">{toast.message}</span>
              <button
                onClick={() => { setToast(null); if (toastTimer.current) clearTimeout(toastTimer.current); }}
                className="p-1 rounded-lg hover:bg-white/10 transition-colors cursor-pointer flex-shrink-0"
              >
              <X className="w-3 h-3 opacity-60" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────

function StatCard({ icon, title, value, delay, subtitle }: {
  icon: React.ReactNode;
  title: string;
  value: string;
  delay: number;
  subtitle?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="bg-white/[0.03] backdrop-blur border border-white/[0.06] p-5 rounded-2xl flex items-center gap-4 hover:bg-white/[0.06] transition-colors group"
    >
      <div className="p-3 bg-black/30 rounded-xl group-hover:scale-110 transition-transform">
        {icon}
      </div>
      <div>
        <p className="text-gray-400 text-xs font-medium">{title}</p>
        <p className="text-xl font-bold">{value}</p>
        {subtitle && <p className="text-xs text-yellow-500 mt-0.5">{subtitle}</p>}
      </div>
    </motion.div>
  );
}

function SystemHealthCard({ icon, label, value, delay, color, pulse }: {
  icon: React.ReactNode;
  label: string;
  value: string;
  delay: number;
  color: string;
  pulse?: boolean;
}) {
  const dotColor = color === "red" ? "bg-red-500" : color === "yellow" ? "bg-yellow-500" : "bg-green-500";
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="bg-white/[0.03] backdrop-blur border border-white/[0.06] p-4 rounded-2xl flex items-center justify-between hover:bg-white/[0.06] transition-colors"
    >
      <div className="flex items-center gap-3">
        <div className="p-2 bg-black/30 rounded-lg">{icon}</div>
        <div>
          <p className="text-gray-400 text-xs">{label}</p>
          <p className="text-lg font-bold">{value}</p>
        </div>
      </div>
      <div className={`w-2 h-2 rounded-full ${dotColor} ${pulse ? 'animate-pulse' : ''}`} />
    </motion.div>
  );
}
