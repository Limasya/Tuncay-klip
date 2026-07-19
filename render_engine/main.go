/*
Tuncay Klip AI — Go Render Engine
===================================
Lightweight HTTP microservice for parallel FFmpeg rendering.

Features:
  - Concurrent worker pool (goroutines) for multi-job rendering
  - Job queue via buffered channel
  - Clip cutting, scaling (9:16), watermarking via FFmpeg
  - Status tracking per job (pending → running → done/failed)

Usage:
  go run main.go

Endpoints:
  POST /render  — Queue a new render job
  GET  /status/{id} — Get job status
  GET  /health  — Health check

NOTE: Requires Go 1.21+ and FFmpeg on PATH.
      Install Go: https://go.dev/dl/
*/

package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"time"

	"github.com/google/uuid"
)

// ─── Types ────────────────────────────────────────────────────────────────────

type RenderJob struct {
	ID         string    `json:"id"`
	VideoPath  string    `json:"video_path"`
	OutputPath string    `json:"output_path"`
	Start      float64   `json:"start"`
	End        float64   `json:"end"`
	Platform   string    `json:"platform"` // "tiktok", "youtube_shorts", "youtube"
	Status     string    `json:"status"`   // "pending" | "running" | "done" | "failed"
	Error      string    `json:"error,omitempty"`
	CreatedAt  time.Time `json:"created_at"`
	FinishedAt time.Time `json:"finished_at,omitempty"`
}

type RenderRequest struct {
	VideoPath  string  `json:"video_path"`
	OutputPath string  `json:"output_path"`
	Start      float64 `json:"start"`
	End        float64 `json:"end"`
	Platform   string  `json:"platform"`
}

// ─── Job Store ────────────────────────────────────────────────────────────────

type JobStore struct {
	mu   sync.RWMutex
	jobs map[string]*RenderJob
}

func NewJobStore() *JobStore {
	return &JobStore{jobs: make(map[string]*RenderJob)}
}

func (s *JobStore) Add(job *RenderJob) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.jobs[job.ID] = job
}

func (s *JobStore) Get(id string) (*RenderJob, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	j, ok := s.jobs[id]
	return j, ok
}

func (s *JobStore) SetStatus(id, status, errMsg string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if j, ok := s.jobs[id]; ok {
		j.Status = status
		j.Error = errMsg
		if status == "done" || status == "failed" {
			j.FinishedAt = time.Now()
		}
	}
}

// ─── FFmpeg Render ────────────────────────────────────────────────────────────

func buildFFmpegArgs(job *RenderJob) []string {
	duration := job.End - job.Start

	// Platform-specific output dimensions
	var vf string
	switch job.Platform {
	case "tiktok", "youtube_shorts", "instagram_reels":
		// Crop to 9:16 and scale to 1080x1920
		vf = "crop=ih*9/16:ih,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,eq=contrast=1.1:saturation=1.2,vignette=PI/4"
	case "youtube":
		vf = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black"
	default:
		vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
	}

	// Ensure output dir exists
	_ = os.MkdirAll(filepath.Dir(job.OutputPath), 0755)

	return []string{
		"-y",
		"-ss", fmt.Sprintf("%.3f", job.Start),
		"-i", job.VideoPath,
		"-t", fmt.Sprintf("%.3f", duration),
		"-vf", vf,
		"-c:v", "libx264",
		"-preset", "fast",
		"-crf", "23",
		"-c:a", "aac",
		"-b:a", "192k",
		"-movflags", "+faststart",
		job.OutputPath,
	}
}

func runRender(job *RenderJob, store *JobStore) {
	store.SetStatus(job.ID, "running", "")
	log.Printf("[Render] Starting job %s — %s [%.1f → %.1f]", job.ID, job.Platform, job.Start, job.End)

	args := buildFFmpegArgs(job)
	cmd := exec.Command("ffmpeg", args...)
	output, err := cmd.CombinedOutput()

	if err != nil {
		errMsg := fmt.Sprintf("FFmpeg error: %v\n%s", err, string(output))
		log.Printf("[Render] Job %s FAILED: %s", job.ID, errMsg)
		store.SetStatus(job.ID, "failed", errMsg)
		return
	}

	log.Printf("[Render] Job %s DONE → %s", job.ID, job.OutputPath)
	store.SetStatus(job.ID, "done", "")
}

// ─── Worker Pool ──────────────────────────────────────────────────────────────

func startWorkerPool(queue <-chan *RenderJob, store *JobStore, workers int) {
	for i := 0; i < workers; i++ {
		go func(workerID int) {
			log.Printf("[Pool] Worker %d started", workerID)
			for job := range queue {
				runRender(job, store)
			}
		}(i)
	}
}

// ─── HTTP Handlers ────────────────────────────────────────────────────────────

func main() {
	store := NewJobStore()
	queue := make(chan *RenderJob, 50)

	workers := 4
	if w := os.Getenv("RENDER_WORKERS"); w != "" {
		fmt.Sscanf(w, "%d", &workers)
	}
	startWorkerPool(queue, store, workers)

	port := os.Getenv("PORT")
	if port == "" {
		port = "3002"
	}

	mux := http.NewServeMux()

	// Health
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]string{"status": "ok", "service": "render_engine", "workers": fmt.Sprint(workers)})
	})

	// Queue a render job
	mux.HandleFunc("POST /render", func(w http.ResponseWriter, r *http.Request) {
		var req RenderRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid JSON", http.StatusBadRequest)
			return
		}

		job := &RenderJob{
			ID:         uuid.New().String(),
			VideoPath:  req.VideoPath,
			OutputPath: req.OutputPath,
			Start:      req.Start,
			End:        req.End,
			Platform:   req.Platform,
			Status:     "pending",
			CreatedAt:  time.Now(),
		}

		store.Add(job)
		queue <- job

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusAccepted)
		json.NewEncoder(w).Encode(map[string]string{"job_id": job.ID, "status": "pending"})
	})

	// Get job status
	mux.HandleFunc("GET /status/{id}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		job, ok := store.Get(id)
		if !ok {
			http.Error(w, "job not found", http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(job)
	})

	log.Printf("\n⚡ Go Render Engine starting on http://localhost:%s", port)
	log.Printf("   Worker pool: %d concurrent goroutines\n", workers)

	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatal("Server failed:", err)
	}
}
