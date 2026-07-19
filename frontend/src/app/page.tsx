"use client";

import { motion } from "framer-motion";
import { Video, Cpu, Play, CheckCircle, Activity, Sparkles } from "lucide-react";
import { useState } from "react";

export default function Home() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);

  const handleGenerate = () => {
    if (!url) return;
    setLoading(true);
    setTimeout(() => setLoading(false), 3000);
  };

  return (
    <div className="min-h-screen bg-[#0f1015] text-white p-8 relative overflow-hidden">
      {/* Background Gradients */}
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
              <p className="text-sm text-gray-400">Polyglot Microservices V2</p>
            </div>
          </div>
          <div className="flex items-center gap-2 px-4 py-2 bg-green-500/10 rounded-full border border-green-500/20">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            <span className="text-sm font-medium text-green-400">Core API Active</span>
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
              Powered by our new Polyglot Architecture — Python Core · TypeScript AI Agents · Go Render Engine.
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
        </motion.section>

        {/* Architecture Badges */}
        <div className="flex justify-center gap-4 flex-wrap">
          {[
            { label: "Python Core", color: "blue", desc: "FastAPI Orchestrator" },
            { label: "TypeScript AI", color: "purple", desc: "LLM Agent Worker" },
            { label: "Go Engine", color: "cyan", desc: "FFmpeg Render" },
            { label: "Next.js UI", color: "pink", desc: "React Frontend" },
          ].map((badge, i) => (
            <motion.div
              key={badge.label}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.2 + i * 0.07 }}
              className={`px-5 py-3 rounded-xl text-sm font-medium bg-${badge.color}-500/10 border border-${badge.color}-500/20 text-${badge.color}-300 flex flex-col items-center`}
            >
              <span className="font-bold">{badge.label}</span>
              <span className="text-xs opacity-60 mt-0.5">{badge.desc}</span>
            </motion.div>
          ))}
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <StatCard
            icon={<Activity className="w-6 h-6 text-blue-400" />}
            title="Active Workers"
            value="3 / 4"
            delay={0.25}
            color="blue"
          />
          <StatCard
            icon={<CheckCircle className="w-6 h-6 text-green-400" />}
            title="Clips Generated"
            value="1,284"
            delay={0.35}
            color="green"
          />
          <StatCard
            icon={<Play className="w-6 h-6 text-purple-400" />}
            title="Avg. Render Time"
            value="12.4s"
            delay={0.45}
            color="purple"
          />
        </div>
      </main>
    </div>
  );
}

interface StatCardProps {
  icon: React.ReactNode;
  title: string;
  value: string;
  delay: number;
  color: string;
}

function StatCard({ icon, title, value, delay }: StatCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="bg-white/[0.03] backdrop-blur border border-white/[0.06] p-6 rounded-2xl flex items-center gap-4 hover:bg-white/[0.06] transition-colors cursor-pointer group"
    >
      <div className="p-4 bg-black/30 rounded-xl group-hover:scale-110 transition-transform">
        {icon}
      </div>
      <div>
        <p className="text-gray-400 text-sm font-medium">{title}</p>
        <p className="text-2xl font-bold">{value}</p>
      </div>
    </motion.div>
  );
}
