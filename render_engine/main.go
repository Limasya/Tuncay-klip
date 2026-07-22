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

type RenderJob struct {
	ID         string    `json:"id"`
	VideoPath  string    `json:"video_path"`
	OutputPath string    `json:"output_path"`
	Start      float64   `json:"start"`
	End        float64   `json:"end"`
	Platform   string    `json:"platform"`
	Status     string    `json:"status"`
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

func buildFFmpegArgs(job *RenderJob) []string {
	duration := job.End - job.Start
	var vf string
	switch job.Platform {
	case "tiktok", "youtube_shorts", "instagram_reels":
		vf = "crop=ih*9/16:ih,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
	case "youtube":
		vf = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black"
	default:
		vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
	}
	_ = os.MkdirAll(filepath.Dir(job.OutputPath), 0755)
	return []string{
		"-y", "-ss", fmt.Sprintf("%.3f", job.Start), "-i", job.VideoPath,
		"-t", fmt.Sprintf("%.3f", duration), "-vf", vf,
		"-c:v", "libx264", "-preset", "fast", "-crf", "23",
		"-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", job.OutputPath,
	}
}

func runRender(job *RenderJob, store *JobStore) {
	store.SetStatus(job.ID, "running", "")
	log.Printf("[Render] Starting job %s", job.ID)
	cmd := exec.Command("ffmpeg", buildFFmpegArgs(job)...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		store.SetStatus(job.ID, "failed", fmt.Sprintf("err: %v out: %s", err, string(out)))
		return
	}
	store.SetStatus(job.ID, "done", "")
}

func main() {
	store := NewJobStore()
	queue := make(chan *RenderJob, 50)
	workers := 4
	for i := 0; i < workers; i++ {
		go func() {
			for job := range queue {
				runRender(job, store)
			}
		}()
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	})
	mux.HandleFunc("POST /render", func(w http.ResponseWriter, r *http.Request) {
		var req RenderRequest
		json.NewDecoder(r.Body).Decode(&req)
		job := &RenderJob{
			ID: uuid.New().String(), VideoPath: req.VideoPath, OutputPath: req.OutputPath,
			Start: req.Start, End: req.End, Platform: req.Platform, Status: "pending", CreatedAt: time.Now(),
		}
		store.Add(job)
		queue <- job
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"job_id": job.ID, "status": "pending"})
	})
	mux.HandleFunc("GET /status/{id}", func(w http.ResponseWriter, r *http.Request) {
		job, ok := store.Get(r.PathValue("id"))
		if !ok {
			http.Error(w, "not found", 404)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(job)
	})

	log.Println("⚡ Go Render Engine running on :3002")
	http.ListenAndServe(":3002", mux)
}
