"use client";

import { useState, useRef, useCallback } from "react";
import { motion } from "framer-motion";
import {
  Play, Pause, AlertCircle, CheckCircle, Clock,
  Video, Mic, Music, BookOpen, Zap
} from "lucide-react";

interface StreamEvent {
  type: string;
  ts: number;
  percent?: number;
  payload?: Record<string, any>;
}

const STAGE_ICONS: Record<string, any> = {
  scene_detection: Video,
  audio_analysis: Mic,
  beat_sync: Music,
  knowledge_base: BookOpen,
};

const STAGE_LABELS: Record<string, string> = {
  scene_detection: "Sahne Tespiti",
  audio_analysis: "Ses Analizi",
  beat_sync: "Beat Sync",
  knowledge_base: "Bilgi Bankası",
};

const STAGE_COLORS: Record<string, string> = {
  scene_detection: "text-teal-400",
  audio_analysis: "text-purple-400",
  beat_sync: "text-pink-400",
  knowledge_base: "text-violet-400",
};

export default function AiStreamPanel({
  sourcePath = "/data/clips/clip.mp4",
}: {
  sourcePath?: string;
}) {
  const wsRef = useRef<WebSocket | null>(null);
  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [percent, setPercent] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [completed, setCompleted] = useState(false);
  const eventsEndRef = useRef<HTMLDivElement>(null);

  const scrollEvents = useCallback(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const startStream = () => {
    setError(null);
    setEvents([]);
    setPercent(0);
    setCompleted(false);

    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${window.location.hostname}:8000/ws/ai_stream?source_path=${encodeURIComponent(sourcePath)}`;

    const socket = new WebSocket(url);
    wsRef.current = socket;
    setRunning(true);

    socket.onopen = () => {
      console.log("[AI Stream] connected");
    };

    socket.onmessage = (msg) => {
      try {
        const data: StreamEvent = JSON.parse(msg.data);
        setEvents((prev) => [...prev, data]);
        if (typeof data.percent === "number") setPercent(data.percent);
        if (data.type === "complete") {
          setRunning(false);
          setCompleted(true);
        }
        if (data.type === "error") {
          setError(data.payload?.detail || "Bilinmeyen hata");
          setRunning(false);
        }
        setTimeout(scrollEvents, 50);
      } catch {
        console.error("[AI Stream] invalid payload", msg.data);
      }
    };

    socket.onerror = () => {
      setError("WebSocket baglanti hatasi");
      setRunning(false);
    };

    socket.onclose = () => {
      setRunning(false);
    };
  };

  const stopStream = () => {
    wsRef.current?.close();
    setRunning(false);
  };

  const reset = () => {
    wsRef.current?.close();
    setRunning(false);
    setEvents([]);
    setPercent(0);
    setError(null);
    setCompleted(false);
  };

  return (
    <div className="bg-white/[0.03] border border-white/[0.06] rounded-2xl p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-purple-500/20 rounded-xl">
            <Zap className="w-5 h-5 text-purple-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">
              Canli AI Analiz Akisi
            </h2>
            <p className="text-xs text-gray-400">
              WebSocket ile sahne, ses, beat ve bilgi tabanini canli izleyin
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {!running ? (
            <button
              onClick={startStream}
              className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-xl text-white text-sm font-medium flex items-center gap-2 transition-colors"
            >
              <Play className="w-4 h-4" /> Baslat
            </button>
          ) : (
            <button
              onClick={stopStream}
              className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded-xl text-white text-sm font-medium flex items-center gap-2 transition-colors"
            >
              <Pause className="w-4 h-4" /> Durdur
            </button>
          )}
          {events.length > 0 && !running && (
            <button
              onClick={reset}
              className="px-3 py-2 bg-white/[0.07] hover:bg-white/[0.12] rounded-xl text-gray-300 text-sm transition-colors"
            >
              Sifirla
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-500/10 text-red-400 p-3 rounded-xl flex items-center gap-2 text-sm">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {/* Completed */}
      {completed && (
        <div className="bg-green-500/10 text-green-400 p-3 rounded-xl flex items-center gap-2 text-sm">
          <CheckCircle className="w-4 h-4 shrink-0" /> Analiz tamamlandi!
        </div>
      )}

      {/* Progress Bar */}
      <div>
        <div className="flex justify-between items-center mb-1">
          <span className="text-xs text-gray-400">Ilerleme</span>
          <span className="text-xs text-gray-400 font-mono">{percent}%</span>
        </div>
        <div className="h-2 bg-white/[0.05] rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-purple-500 via-blue-500 to-cyan-400"
            initial={{ width: 0 }}
            animate={{ width: `${percent}%` }}
            transition={{ ease: "easeOut", duration: 0.4 }}
          />
        </div>
      </div>

      {/* Stage Indicators */}
      <div className="grid grid-cols-4 gap-3">
        {Object.entries(STAGE_LABELS).map(([key, label]) => {
          const done = events.some((e) => e.type === key);
          const active = running && events.length > 0 && !done
            && events[events.length - 1]?.type === "progress"
            && events[events.length - 1]?.payload?.step === key;
          const Icon = STAGE_ICONS[key];
          return (
            <div
              key={key}
              className={`p-3 rounded-xl border text-center transition-all ${
                done
                  ? "border-green-500/30 bg-green-500/10"
                  : active
                    ? "border-purple-500/30 bg-purple-500/10"
                    : "border-white/[0.06] bg-white/[0.02]"
              }`}
            >
              <Icon
                className={`w-5 h-5 mx-auto mb-1 ${
                  done ? "text-green-400" : active ? "text-purple-400" : "text-gray-500"
                }`}
              />
              <div className="text-[11px] text-gray-300">{label}</div>
              <div className="text-[10px] text-gray-500 mt-0.5">
                {done ? "Tamam" : active ? "Calisiyor..." : "Bekliyor"}
              </div>
            </div>
          );
        })}
      </div>

      {/* Event Log */}
      <div className="bg-black/30 rounded-xl p-3 max-h-56 overflow-y-auto font-mono text-xs space-y-1">
        {events.length === 0 && (
          <div className="text-gray-500 text-center py-4">
            Henuz olay yok — Baslat'a tikla
          </div>
        )}
        {events.map((e, idx) => {
          const Icon = STAGE_ICONS[e.type];
          return (
            <div key={idx} className="flex items-start gap-2 py-0.5">
              <span className="text-gray-600 w-12 shrink-0">
                {new Date(e.ts * 1000).toLocaleTimeString("tr-TR", {
                  hour12: false,
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </span>
              {Icon && (
                <Icon className={`w-3 h-3 mt-0.5 shrink-0 ${STAGE_COLORS[e.type] || "text-gray-400"}`} />
              )}
              <span
                className={`font-semibold w-32 shrink-0 ${
                  e.type === "complete"
                    ? "text-green-400"
                    : e.type === "error"
                      ? "text-red-400"
                      : "text-blue-400"
                }`}
              >
                [{e.type}]
              </span>
              <span className="text-gray-300 break-all">
                {e.percent !== undefined && (
                  <span className="text-purple-400 mr-2">{e.percent}%</span>
                )}
                {e.payload && (
                  <span>{JSON.stringify(e.payload).slice(0, 140)}</span>
                )}
              </span>
            </div>
          );
        })}
        <div ref={eventsEndRef} />
      </div>
    </div>
  );
}
