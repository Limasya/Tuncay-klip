"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  Cpu, Home, FlaskConical, BarChart2, Scissors, Radio,
  BookOpen, Settings, ChevronDown, Globe, Zap, Menu, X,
  Mic, Eye, Wand2, Share2, Shield
} from "lucide-react";
import { useState } from "react";

const NAV_ITEMS = [
  {
    id: "dashboard",
    label: "Dashboard",
    icon: Home,
    href: "/",
  },
  {
    id: "studio",
    label: "AI Studio",
    icon: FlaskConical,
    href: "/studio",
    badge: "12 Categories",
    highlight: true,
    children: [
      { label: "⚡ Omni-Engine Pipeline", href: "/studio", desc: "Run all 12 pipeline stages", icon: Globe },
      { label: "Kick & Stream", href: "/studio?cat=stream", desc: "Monitor, VOD, clip management", icon: Radio },
      { label: "Audio & Voice", href: "/studio?cat=audio_voice", desc: "VAD, Whisper, beat sync", icon: Mic },
      { label: "Vision & Face", href: "/studio?cat=vision", desc: "Face track, scene detect, smart crop", icon: Eye },
      { label: "AI Editing & Effects", href: "/studio?cat=editing", desc: "Edit spec, transitions, split screen", icon: Scissors },
      { label: "AI Analysis & Scoring", href: "/studio?cat=ai_analysis", desc: "Viral predictor, signal fusion", icon: BarChart2 },
      { label: "Thumbnail & Visuals", href: "/studio?cat=thumbnail", desc: "AI thumbnails, A/B test, memes", icon: BarChart2 },
      { label: "Zero-Bandwidth Engine", href: "/studio?cat=zero_bandwidth", desc: "0-download VOD analysis", icon: Globe },
      { label: "Auto Effects & Filters", href: "/studio?cat=effects", desc: "Censor, SFX, music, captions", icon: Wand2 },
      { label: "Publishing & Social", href: "/studio?cat=publishing", desc: "Multi-platform export", icon: Share2 },
      { label: "LLM & Knowledge Base", href: "/studio?cat=llm_knowledge", desc: "Vector search, recommendations", icon: BookOpen },
      { label: "Analytics & Quality", href: "/studio?cat=analytics", desc: "Quality control, cost tracking", icon: Shield },
      { label: "System & Admin", href: "/studio?cat=system", desc: "Health, metrics, backups", icon: Settings },
      { label: "Canlı AI Akış (WS)", href: "/ai-stream", desc: "WebSocket canlı analiz akışı", icon: Zap },
    ],
  },
  {
    id: "clips",
    label: "Clips",
    icon: Scissors,
    href: "#clips",
  },
  {
    id: "analytics",
    label: "Analytics",
    icon: BarChart2,
    href: "#analytics",
  },
  {
    id: "monitor",
    label: "Live Monitor",
    icon: Radio,
    href: "#monitor",
  },
  {
    id: "docs",
    label: "API Docs",
    icon: BookOpen,
    href: "/api/docs",
    external: true,
  },
  {
    id: "admin",
    label: "Admin",
    icon: Settings,
    href: "#admin",
  },
];

export default function Navbar() {
  const pathname = usePathname();
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  const toggle = (id: string) =>
    setOpenDropdown(prev => (prev === id ? null : id));

  return (
    <>
      <nav className="fixed top-0 left-0 right-0 z-50 h-14 bg-black/70 backdrop-blur-xl border-b border-white/[0.06] flex items-center px-6 gap-2">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 mr-6 shrink-0">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-[0_0_12px_rgba(99,102,241,0.5)]">
            <Cpu className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold text-sm tracking-tight text-white">Tuncay<span className="text-indigo-400">Klip</span></span>
        </Link>

        {/* Desktop Nav */}
        <div className="hidden md:flex items-center gap-1 flex-1">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const hasChildren = (item as any).children?.length > 0;

            return (
              <div key={item.id} className="relative">
                {hasChildren ? (
                  <button
                    onClick={() => toggle(item.id)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                      isActive || openDropdown === item.id
                        ? "bg-white/10 text-white"
                        : "text-gray-400 hover:text-white hover:bg-white/5"
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {item.label}
                    {(item as any).badge && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-500/30 text-indigo-300 font-semibold">
                        {(item as any).badge}
                      </span>
                    )}
                    <ChevronDown className={`w-3 h-3 transition-transform ${openDropdown === item.id ? "rotate-180" : ""}`} />
                  </button>
                ) : (item as any).external ? (
                  <a
                    href={item.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-gray-400 hover:text-white hover:bg-white/5 transition-all"
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {item.label}
                  </a>
                ) : (
                  <Link
                    href={item.href}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                      isActive ? "bg-white/10 text-white" : "text-gray-400 hover:text-white hover:bg-white/5"
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {item.label}
                  </Link>
                )}

                {/* Dropdown */}
                <AnimatePresence>
                  {hasChildren && openDropdown === item.id && (
                    <motion.div
                      initial={{ opacity: 0, y: 8, scale: 0.96 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 8, scale: 0.96 }}
                      transition={{ duration: 0.15 }}
                      className="absolute top-full left-0 mt-2 w-64 bg-[#0f0f0f] border border-white/10 rounded-xl shadow-2xl overflow-hidden"
                    >
                      <div className="p-2 space-y-0.5">
                        {(item as any).children.map((child: any) => (
                          <Link
                            key={child.href}
                            href={child.href}
                            onClick={() => setOpenDropdown(null)}
                            className="flex items-start gap-3 px-3 py-2.5 rounded-lg hover:bg-white/5 transition-colors group"
                          >
                            <div className="p-1 rounded-md bg-indigo-500/10 text-indigo-400 group-hover:bg-indigo-500/20 transition-colors mt-0.5">
                              <child.icon className="w-3 h-3" />
                            </div>
                            <div>
                              <div className="text-sm font-medium text-gray-300 group-hover:text-white transition-colors">{child.label}</div>
                              <div className="text-[11px] text-gray-600">{child.desc}</div>
                            </div>
                          </Link>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </div>

        {/* Right side — status pill */}
        <div className="hidden md:flex ml-auto items-center gap-3">
          <div className="flex items-center gap-2 text-[11px] text-gray-500 bg-white/[0.03] border border-white/5 px-3 py-1.5 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.8)] animate-pulse" />
            System Online
          </div>
          <a
            href="/api/docs"
            target="_blank"
            className="text-[11px] font-medium text-indigo-400 hover:text-indigo-300 transition-colors"
          >
            API Docs →
          </a>
        </div>

        {/* Mobile hamburger */}
        <button
          onClick={() => setMobileOpen(v => !v)}
          className="md:hidden ml-auto p-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
        >
          {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      </nav>

      {/* Mobile Drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, x: "100%" }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="fixed inset-y-0 right-0 z-40 w-72 bg-[#0a0a0a] border-l border-white/5 md:hidden pt-16"
          >
            <div className="p-4 space-y-1 overflow-y-auto h-full">
              {NAV_ITEMS.map((item) => {
                const Icon = item.icon;
                return (
                  <div key={item.id}>
                    <Link
                      href={item.href}
                      onClick={() => setMobileOpen(false)}
                      className="flex items-center gap-3 px-4 py-3 rounded-xl text-gray-300 hover:text-white hover:bg-white/5 transition-all"
                    >
                      <Icon className="w-4 h-4" />
                      <span className="font-medium">{item.label}</span>
                      {(item as any).badge && (
                        <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-500/30 text-indigo-300">
                          {(item as any).badge}
                        </span>
                      )}
                    </Link>
                    {(item as any).children && (
                      <div className="ml-7 mt-1 space-y-0.5 border-l border-white/5 pl-4">
                        {(item as any).children.map((child: any) => (
                          <Link
                            key={child.href}
                            href={child.href}
                            onClick={() => setMobileOpen(false)}
                            className="block py-1.5 text-sm text-gray-500 hover:text-gray-300 transition-colors"
                          >
                            {child.label}
                          </Link>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Overlay for dropdown/mobile close */}
      {(openDropdown || mobileOpen) && (
        <div
          className="fixed inset-0 z-30"
          onClick={() => { setOpenDropdown(null); setMobileOpen(false); }}
        />
      )}
    </>
  );
}
