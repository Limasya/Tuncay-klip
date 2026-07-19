# Tuncay Klip AI — Polyglot Microservices Architecture

Bu proje 3 farklı yazılım dili ve 2 farklı çalıştırma ortamı kullanan bir **Enterprise Mikroservis Mimarisine** sahiptir.

## Servisler ve Portlar

| Servis | Dil | Port | Görev |
|---|---|---|---|
| Python Core API | Python 3.11+ | 8000 | FastAPI Orkestratör, Veritabanı, Kick/YouTube entegrasyonu, FFmpeg Render |
| TypeScript AI Worker | Node.js / TypeScript | 3001 | LLM Chain-of-Thought Ajan Mimarisi |
| Next.js Frontend | React / Next.js 16 | 3000 | Premium Glassmorphism Web Arayüzü |

### Native Extensions (in-process)
| Extension | Dil | Görev |
|---|---|---|
| C++ signal_engine | C++20 / MSVC | FFT, beat detection, motion analysis, scene detection (ctypes FFI) |
| Rust video-processor | Rust | VOD clip, probe, validate, export, batch (subprocess CLI) |

## Mimari Akışı

```
[Kullanıcı / Next.js UI]
         │ HTTP
         ▼
[Python Core API :8000]   ←── Kick/Twitch VOD İndirme
         │
         ├──► [C++ signal_engine] (in-process ctypes)
         │         FFT, beat detection, motion analysis
         │
         ├──► [Rust video-processor] (subprocess)
         │         VOD clip, probe, validate, export
         │
         ├──► [TypeScript AI Worker :3001]
         │         Analyzer Agent → Critic Agent → Editor Agent
         │         (Chain-of-Thought klip seçimi)
         │
         └──► [Python render pipeline]
                   FFmpeg rendering, effects, beat-sync, subtitles
```

## Hızlı Başlangıç

### 1. Python Core API
```bash
pip install -r requirements-base.txt
python main.py
```

### 2. TypeScript AI Worker
```bash
cd ai_worker
npm install
npm run dev   # Geliştirme modu
# veya
npm run build && npm start  # Production
```
**Gerekli env değişkenleri** (`.env` dosyası oluştur):
```
GROQ_API_KEY=gsk_xxx       # Ücretsiz: groq.com
# veya
OPENAI_API_KEY=sk-xxx
# veya  
OPENROUTER_API_KEY=sk-xxx
```

### 3. Next.js Frontend
```bash
cd frontend
npm run dev    # http://localhost:3000
```

### 4. Build All (PowerShell)
```powershell
.\build.ps1              # Tüm dilleri derle
.\build.ps1 -SkipTests   # Testleri atla
```

## Ortam Değişkenleri

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `AI_WORKER_URL` | `http://localhost:3001` | TypeScript servis URL |
| `GROQ_API_KEY` | - | Ücretsiz LLM (önerilen) |
| `OPENAI_API_KEY` | - | OpenAI LLM (ödeme gerektirir) |

## Graceful Fallback

AI Worker çevrimdışı olduğunda sistem otomatik olarak Python fallback'e geçer:
- AI Worker offline → `services.llm_reasoner.LLMReasoner` kullanılır
