"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import AiStreamPanel from "../components/AiStreamPanel";

export default function AIStreamPage() {
  return (
    <div className="min-h-screen bg-[#0f1015] text-white p-8">
      <div className="max-w-4xl mx-auto space-y-6">
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="p-2 bg-white/[0.07] hover:bg-white/[0.12] rounded-xl transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
            </Link>
            <div>
              <h1 className="text-3xl font-bold bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent tracking-tight">
                Canli AI Analiz Akisi
              </h1>
              <p className="text-sm text-gray-400 mt-1">
                Edit pipeline asamalarini WebSocket uzerinden canli izleyin
              </p>
            </div>
          </div>
          <Link
            href="/studio"
            className="text-sm px-4 py-2 bg-white/[0.07] hover:bg-white/[0.12] rounded-xl text-gray-300 transition-colors"
          >
            AI Studio
          </Link>
        </header>

        <AiStreamPanel />
      </div>
    </div>
  );
}
