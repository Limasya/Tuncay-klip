use anyhow::{Context, Result};
use clap::Parser;
use serde::{Deserialize, Serialize};
use std::io::Read;
use std::path::PathBuf;
use std::process::{Command, Stdio};

/// Tuncay Trim Detector — Native silence + freeze detection for gaming clips.
/// Reads video, detects boring segments (silence + frozen frames), outputs keep segments as JSON.
#[derive(Parser)]
#[command(name = "tuncay-trim-detector")]
struct Args {
    /// Path to JSON spec file
    #[arg(short, long)]
    spec: PathBuf,

    /// Verbose output
    #[arg(short, long)]
    verbose: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
struct Spec {
    video: String,

    #[serde(default = "default_noise_threshold_db")]
    noise_threshold_db: f64,

    #[serde(default = "default_min_silence_duration")]
    min_silence_duration: f64,

    #[serde(default = "default_freeze_noise")]
    freeze_noise: f64,

    #[serde(default = "default_min_freeze_duration")]
    min_freeze_duration: f64,

    #[serde(default = "default_min_segment_duration")]
    min_segment_duration: f64,

    #[serde(default = "default_merge_gap")]
    merge_gap: f64,

    #[serde(default = "default_max_duration")]
    max_duration: f64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "snake_case")]
struct Output {
    total_duration: f64,
    kept_duration: f64,
    removed_duration: f64,
    removed_pct: f64,
    active_segments: Vec<[f64; 2]>,
    boring_segments: Vec<[f64; 2]>,
}

fn default_noise_threshold_db() -> f64 { -28.0 }
fn default_min_silence_duration() -> f64 { 0.5 }
fn default_freeze_noise() -> f64 { 0.001 }
fn default_min_freeze_duration() -> f64 { 0.6 }
fn default_min_segment_duration() -> f64 { 1.5 }
fn default_merge_gap() -> f64 { 0.3 }
fn default_max_duration() -> f64 { 60.0 }

impl Spec {
    fn validate(&self) -> Result<()> {
        let p = PathBuf::from(&self.video);
        anyhow::ensure!(p.exists(), "Video not found: {}", self.video);
        Ok(())
    }
}

/// ── Audio silence detection ─────────────────────────────────────────
/// Pipes PCM f32le mono from FFmpeg, computes RMS energy per block,
/// marks blocks below threshold as silence.

fn detect_silence(
    video: &str,
    noise_threshold_db: f64,
    min_duration: f64,
    verbose: bool,
) -> Result<Vec<[f64; 2]>> {
    let threshold_linear = 10.0_f64.powf(noise_threshold_db / 20.0);
    let sample_rate = 22050;
    let block_size = 1024;
    let block_dur = block_size as f64 / sample_rate as f64;

    let mut child = Command::new("ffmpeg")
        .args(&[
            "-y", "-i", video,
            "-af", &format!("aformat=sample_fmts=fltp:sample_rates={}:channel_layouts=mono", sample_rate),
            "-f", "f32le",
            "-",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .context("Failed to spawn FFmpeg for audio pipe")?;

    let mut stdout = child.stdout.take().context("No audio stdout")?;
    let mut samples: Vec<f32> = Vec::new();

    loop {
        let mut chunk = vec![0u8; 8192 * 4];
        let n = stdout.read(&mut chunk).context("Audio pipe read error")?;
        if n == 0 { break; }
        chunk.truncate(n);
        let floats: &[f32] = unsafe {
            std::slice::from_raw_parts(
                chunk.as_ptr() as *const f32,
                chunk.len() / 4,
            )
        };
        samples.extend_from_slice(floats);
    }

    let _ = child.wait();

    let mut silence_segments: Vec<[f64; 2]> = Vec::new();
    let mut in_silence = false;
    let mut seg_start = 0.0;
    let mut seg_end = 0.0;

    for (i, chunk) in samples.chunks(block_size).enumerate() {
        let rms = (chunk.iter().map(|s| s * s).sum::<f32>() / chunk.len() as f32).sqrt() as f64;
        let t = i as f64 * block_dur;

        if rms < threshold_linear {
            if !in_silence {
                in_silence = true;
                seg_start = t;
            }
            seg_end = t + block_dur;
        } else {
            if in_silence {
                let dur = seg_end - seg_start;
                if dur >= min_duration {
                    silence_segments.push([seg_start, seg_end]);
                    if verbose {
                        eprintln!("  silence: {:.2}s – {:.2}s (dur={:.2}s)", seg_start, seg_end, dur);
                    }
                }
                in_silence = false;
            }
        }
    }
    if in_silence {
        let dur = seg_end - seg_start;
        if dur >= min_duration {
            silence_segments.push([seg_start, seg_end]);
        }
    }

    if verbose {
        eprintln!("Audio silence: {} segments", silence_segments.len());
    }
    Ok(silence_segments)
}

/// ── Video freeze detection ──────────────────────────────────────────
/// Pipes rawvideo RGB24 at low resolution + FPS, computes mean per-pixel
/// difference between consecutive frames.

fn detect_freeze(
    video: &str,
    freeze_noise: f64,
    min_duration: f64,
    verbose: bool,
) -> Result<Vec<[f64; 2]>> {
    let width = 160u32;
    let height = 90u32;
    let fps = 2;
    let frame_size = (width * height * 3) as usize;
    let frame_dur = 1.0 / fps as f64;

    let mut child = Command::new("ffmpeg")
        .args(&[
            "-y", "-i", video,
            "-vf", &format!("scale={}:{},fps={}", width, height, fps),
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .context("Failed to spawn FFmpeg for video pipe")?;

    let mut stdout = child.stdout.take().context("No video stdout")?;
    let mut freeze_segments: Vec<[f64; 2]> = Vec::new();
    let mut prev_frame: Option<Vec<u8>> = None;
    let mut in_freeze = false;
    let mut seg_start = 0.0;
    let mut seg_end = 0.0;
    let mut frame_idx = 0usize;

    loop {
        let mut frame = vec![0u8; frame_size];
        let mut offset = 0;
        while offset < frame_size {
            let n = stdout.read(&mut frame[offset..]).context("Video pipe read error")?;
            if n == 0 { break; }
            offset += n;
        }
        if offset < frame_size { break; }

        let t = frame_idx as f64 * frame_dur;

        if let Some(ref prev) = prev_frame {
            let diff: f64 = prev.iter()
                .zip(frame.iter())
                .map(|(a, b)| {
                    let d = (*a as i16 - *b as i16).abs() as f64;
                    d * d
                })
                .sum::<f64>()
                / frame.len() as f64;

            if diff < freeze_noise * 255.0 * 255.0 {
                if !in_freeze {
                    in_freeze = true;
                    seg_start = t;
                }
                seg_end = t + frame_dur;
            } else {
                if in_freeze {
                    let dur = seg_end - seg_start;
                    if dur >= min_duration {
                        freeze_segments.push([seg_start, seg_end]);
                        if verbose {
                            eprintln!("  freeze: {:.2}s – {:.2}s (dur={:.2}s)", seg_start, seg_end, dur);
                        }
                    }
                    in_freeze = false;
                }
            }
        }

        prev_frame = Some(frame);
        frame_idx += 1;
    }

    if in_freeze {
        let dur = seg_end - seg_start;
        if dur >= min_duration {
            freeze_segments.push([seg_start, seg_end]);
        }
    }

    let _ = child.wait();

    if verbose {
        eprintln!("Video freeze: {} segments", freeze_segments.len());
    }
    Ok(freeze_segments)
}

/// ── Segment merge + invert ──────────────────────────────────────────

fn merge_segments(segs: &[[f64; 2]], gap: f64) -> Vec<[f64; 2]> {
    if segs.is_empty() { return Vec::new(); }
    let mut sorted = segs.to_vec();
    sorted.sort_by(|a, b| a[0].partial_cmp(&b[0]).unwrap());

    let mut merged = Vec::new();
    let mut cur = sorted[0];
    for &s in &sorted[1..] {
        if s[0] - cur[1] <= gap {
            cur[1] = cur[1].max(s[1]);
        } else {
            merged.push(cur);
            cur = s;
        }
    }
    merged.push(cur);
    merged
}

fn invert_segments(
    boring: &[[f64; 2]],
    total_dur: f64,
    min_seg_dur: f64,
    max_dur: f64,
    merge_gap: f64,
) -> Vec<[f64; 2]> {
    let mut active = Vec::new();
    let mut prev_end = 0.0;

    for &[bs, be] in boring {
        if bs - prev_end >= min_seg_dur {
            active.push([prev_end, bs]);
        }
        prev_end = prev_end.max(be);
    }
    if total_dur - prev_end >= min_seg_dur {
        active.push([prev_end, total_dur]);
    }

    // Merge nearby active segments
    let merged = merge_segments(&active, merge_gap);

    // Cap total duration
    let mut total = 0.0;
    let mut capped = Vec::new();
    for &[s, e] in &merged {
        let dur = e - s;
        if total + dur > max_dur {
            let remain = max_dur - total;
            if remain >= min_seg_dur {
                capped.push([s, s + remain]);
            }
            break;
        }
        capped.push([s, e]);
        total += dur;
    }
    capped
}

fn get_video_duration(video: &str) -> Result<f64> {
    let output = Command::new("ffprobe")
        .args(&[
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            video,
        ])
        .output()
        .context("Failed to run ffprobe")?;
    let s = String::from_utf8_lossy(&output.stdout).trim().to_string();
    s.parse::<f64>().context("Failed to parse duration")
}

/// ── Main ────────────────────────────────────────────────────────────

fn run(spec: &Spec, verbose: bool) -> Result<Output> {
    spec.validate()?;

    let total_dur = get_video_duration(&spec.video)?;

    let silence = detect_silence(&spec.video, spec.noise_threshold_db, spec.min_silence_duration, verbose)?;
    let freeze = detect_freeze(&spec.video, spec.freeze_noise, spec.min_freeze_duration, verbose)?;

    let all_boring: Vec<[f64; 2]> = silence.into_iter().chain(freeze).collect();
    let merged_boring = merge_segments(&all_boring, spec.min_silence_duration.max(spec.min_freeze_duration));
    let active = invert_segments(&merged_boring, total_dur, spec.min_segment_duration, spec.max_duration, spec.merge_gap);

    let kept: f64 = active.iter().map(|&[s, e]| e - s).sum();
    let removed = total_dur - kept;

    if verbose {
        eprintln!("Total: {:.1}s → Kept: {:.1}s (removed {:.1}s, {:.0}%)",
                   total_dur, kept, removed, removed / total_dur * 100.0);
        eprintln!("Active segments: {}", active.len());
    }

    Ok(Output {
        total_duration: total_dur,
        kept_duration: kept,
        removed_duration: removed,
        removed_pct: if total_dur > 0.0 { removed / total_dur * 100.0 } else { 0.0 },
        active_segments: active,
        boring_segments: merged_boring,
    })
}

fn main() -> Result<()> {
    let args = Args::parse();

    let spec_content = std::fs::read_to_string(&args.spec)
        .with_context(|| format!("Failed to read spec: {}", args.spec.display()))?;

    let spec: Spec = serde_json::from_str(&spec_content)
        .with_context(|| "Failed to parse JSON spec")?;

    if args.verbose {
        eprintln!("🎬 Tuncay Trim Detector v0.1.0");
        eprintln!("📥 Input: {}", spec.video);
        eprintln!("🔇 Noise threshold: {} dB", spec.noise_threshold_db);
        eprintln!("❄️  Freeze noise: {}", spec.freeze_noise);
    }

    let output = run(&spec, args.verbose)?;

    serde_json::to_writer(std::io::stdout(), &output)
        .context("Failed to write JSON output")?;
    println!();

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_defaults() {
        assert!((default_noise_threshold_db() - (-28.0)).abs() < 0.01);
        assert!((default_min_silence_duration() - 0.5).abs() < 0.01);
        assert!((default_freeze_noise() - 0.001).abs() < 0.001);
        assert!((default_min_freeze_duration() - 0.6).abs() < 0.01);
        assert!((default_min_segment_duration() - 1.5).abs() < 0.01);
        assert!((default_merge_gap() - 0.3).abs() < 0.01);
        assert!((default_max_duration() - 60.0).abs() < 0.01);
    }

    #[test]
    fn test_merge_segments() {
        let segs = vec![[0.0, 2.0], [2.5, 4.0], [10.0, 12.0]];
        let merged = merge_segments(&segs, 1.0);
        assert_eq!(merged.len(), 2);
        assert!((merged[0][1] - 4.0).abs() < 0.01);
    }

    #[test]
    fn test_invert_segments() {
        let boring = vec![[2.0, 4.0], [8.0, 10.0]];
        let active = invert_segments(&boring, 15.0, 1.0, 60.0, 0.3);
        assert_eq!(active.len(), 3);
        assert!((active[0][0] - 0.0).abs() < 0.01);
        assert!((active[0][1] - 2.0).abs() < 0.01);
        assert!((active[1][0] - 4.0).abs() < 0.01);
        assert!((active[1][1] - 8.0).abs() < 0.01);
        assert!((active[2][0] - 10.0).abs() < 0.01);
        assert!((active[2][1] - 15.0).abs() < 0.01);
    }

    #[test]
    fn test_empty_segments() {
        let merged = merge_segments(&[], 0.5);
        assert!(merged.is_empty());
        let active = invert_segments(&[], 30.0, 1.0, 60.0, 0.3);
        assert_eq!(active.len(), 1);
        assert!((active[0][1] - 30.0).abs() < 0.01);
    }
}
