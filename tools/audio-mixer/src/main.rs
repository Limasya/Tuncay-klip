use anyhow::{Context, Result};
use clap::Parser;
use serde::Deserialize;
use std::path::PathBuf;
use std::process::Stdio;
use tokio::process::Command;

/// Tuncay Audio Mixer — Single-pass audio mixing for viral Reels.
/// Replaces multiple sequential FFmpeg calls with one optimized pass.
#[derive(Parser)]
#[command(name = "tuncay-audio-mixer")]
struct Args {
    /// Path to JSON mix specification file
    #[arg(short, long)]
    spec: PathBuf,

    /// Verbose output
    #[arg(short, long)]
    verbose: bool,
}

#[derive(Debug, Deserialize)]
struct MixSpec {
    video: String,
    output: String,

    #[serde(default)]
    music: Option<String>,

    #[serde(default = "default_music_volume")]
    music_volume_db: f64,

    #[serde(default)]
    sfx_events: Vec<SfxEvent>,

    #[serde(default = "default_enable_ducking")]
    enable_ducking: bool,

    #[serde(default = "default_video_bitrate")]
    video_bitrate: String,

    #[serde(default = "default_audio_bitrate")]
    audio_bitrate: String,
}

#[derive(Debug, Deserialize)]
struct SfxEvent {
    file: String,
    timestamp: f64,

    #[serde(default = "default_sfx_volume")]
    volume_db: f64,

    #[serde(default = "default_sfx_mix")]
    mix_ratio: f64,
}

fn default_music_volume() -> f64 {
    -18.0
}

fn default_enable_ducking() -> bool {
    true
}

fn default_sfx_volume() -> f64 {
    -8.0
}

fn default_sfx_mix() -> f64 {
    0.6
}

fn default_video_bitrate() -> String {
    "copy".to_string()
}

fn default_audio_bitrate() -> String {
    "192k".to_string()
}

impl MixSpec {
    /// Verify all input files exist
    fn validate(&self) -> Result<()> {
        let video_path = PathBuf::from(&self.video);
        anyhow::ensure!(video_path.exists(), "Video not found: {}", self.video);

        if let Some(ref music) = self.music {
            let music_path = PathBuf::from(music);
            anyhow::ensure!(music_path.exists(), "Music not found: {}", music);
        }

        for sfx in &self.sfx_events {
            let sfx_path = PathBuf::from(&sfx.file);
            anyhow::ensure!(sfx_path.exists(), "SFX not found: {}", sfx.file);
        }

        Ok(())
    }

    /// Build a single optimized FFmpeg filter_complex string
    fn build_filter_graph(&self) -> (String, Vec<String>) {
        let mut inputs = vec![self.video.clone()];
        let mut filter_parts: Vec<String> = Vec::new();
        let mut audio_maps: Vec<String> = Vec::new();
        let mut sfx_count = 0;

        // --- Background music input ---
        let music_label = if let Some(ref music_path) = self.music {
            inputs.push(music_path.clone());
            let label = "music".to_string();
            filter_parts.push(format!(
                "[1:a]volume={}dB[{}]",
                self.music_volume_db, label
            ));
            Some(label)
        } else {
            None
        };

        // --- SFX events with timing ---
        for (i, sfx) in self.sfx_events.iter().enumerate() {
            inputs.push(sfx.file.clone());
            let sfx_label = format!("sfx{}", i);
            let delay_ms = (sfx.timestamp * 1000.0) as i64;

            if sfx.mix_ratio >= 1.0 {
                // Pure SFX — replace video audio for the duration
                filter_parts.push(format!(
                    "[{}:a]adelay={}|{},volume={}dB[{}]",
                    inputs.len() - 1,
                    delay_ms,
                    delay_ms,
                    sfx.volume_db,
                    sfx_label
                ));
            } else {
                // Mix SFX with video audio
                filter_parts.push(format!(
                    "[{}:a]adelay={}|{},volume={}dB[{}]",
                    inputs.len() - 1,
                    delay_ms,
                    delay_ms,
                    sfx.volume_db,
                    sfx_label
                ));
            }
            sfx_count += 1;
        }

        // --- Build the audio mix chain ---
        // Strategy: music + video audio → ducked mix, then layer SFX on top
        let mut audio_sources = vec!["0:a".to_string()]; // video's original audio

        if let Some(ref label) = music_label {
            audio_sources.push(format!("[{}]", label));
        }

        for i in 0..sfx_count {
            audio_sources.push(format!("[sfx{}]", i));
        }

        // Use amix to blend all audio sources
        let total_inputs = audio_sources.len();
        if total_inputs > 1 {
            // Build the amix inputs
            let weights: Vec<String> = if self.enable_ducking && music_label.is_some() {
                // Ducking: video audio gets full weight, music gets reduced
                let mut w = vec!["1".to_string()]; // video audio = full
                for _ in 0..sfx_count + 1 {
                    // music + SFX
                    w.push("0.5".to_string());
                }
                w
            } else {
                vec!["1".to_string(); total_inputs]
            };

            let amix = format!(
                "{}amix=inputs={}:duration=first:weights={}[aout]",
                audio_sources.join(""),
                total_inputs,
                weights.join(" ")
            );
            filter_parts.push(amix);
            audio_maps.push("[aout]".to_string());
        }

        let filter_complex = filter_parts.join(";");
        (filter_complex, audio_maps)
    }

    /// Execute FFmpeg with the built filter graph
    async fn execute(&self, verbose: bool) -> Result<()> {
        self.validate()?;

        let (filter_complex, audio_maps) = self.build_filter_graph();

        let mut cmd = Command::new("ffmpeg");
        cmd.arg("-y");

        // Add all input files
        cmd.arg("-i").arg(&self.video);

        if let Some(ref music) = self.music {
            cmd.arg("-i").arg(music);
        }

        for sfx in &self.sfx_events {
            cmd.arg("-i").arg(&sfx.file);
        }

        // Filter complex
        if !filter_complex.is_empty() {
            cmd.arg("-filter_complex").arg(&filter_complex);
        }

        // Video mapping
        cmd.arg("-map").arg("0:v");

        // Audio mapping
        if audio_maps.is_empty() {
            cmd.arg("-map").arg("0:a");
        } else {
            for map in &audio_maps {
                cmd.arg("-map").arg(map);
            }
        }

        // Output codecs
        if self.video_bitrate == "copy" {
            cmd.arg("-c:v").arg("copy");
        } else {
            cmd.arg("-c:v").arg("libx264");
            cmd.arg("-preset").arg("fast");
            cmd.arg("-b:v").arg(&self.video_bitrate);
        }

        cmd.arg("-c:a").arg("aac");
        cmd.arg("-b:a").arg(&self.audio_bitrate);
        cmd.arg("-ac").arg("2");
        cmd.arg("-ar").arg("44100");

        cmd.arg(&self.output);

        if verbose {
            println!("🎬 FFmpeg command:\n{:?}", cmd.as_std());
            println!("\n📋 Filter complex:\n{}", filter_complex);
        }

        let child = cmd
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .context("Failed to spawn FFmpeg")?;

        let output = child.wait_with_output().await?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            anyhow::bail!("FFmpeg failed: {}", &stderr[..std::cmp::min(500, stderr.len())]);
        }

        if verbose {
            println!("✅ Audio mix complete: {}", self.output);
        }

        Ok(())
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();

    let spec_content = std::fs::read_to_string(&args.spec)
        .with_context(|| format!("Failed to read spec: {}", args.spec.display()))?;

    let spec: MixSpec = serde_json::from_str(&spec_content)
        .with_context(|| "Failed to parse JSON spec")?;

    if args.verbose {
        println!("🎵 Tuncay Audio Mixer v0.1.0");
        println!("📥 Input: {}", spec.video);
        if spec.music.is_some() {
            println!("🎶 Music: {}", spec.music.as_ref().unwrap());
        }
        println!("🔊 SFX events: {}", spec.sfx_events.len());
        println!("📤 Output: {}", spec.output);
    }

    spec.execute(args.verbose).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_defaults() {
        assert!((default_music_volume() - (-18.0)).abs() < 0.01);
        assert!(default_enable_ducking());
        assert!((default_sfx_volume() - (-8.0)).abs() < 0.01);
        assert!((default_sfx_mix() - 0.6).abs() < 0.01);
        assert_eq!(default_video_bitrate(), "copy");
        assert_eq!(default_audio_bitrate(), "192k");
    }

    #[test]
    fn test_build_filter_graph_no_music_no_sfx() {
        let spec = MixSpec {
            video: "test.mp4".into(),
            output: "out.mp4".into(),
            music: None,
            music_volume_db: -18.0,
            sfx_events: vec![],
            enable_ducking: false,
            video_bitrate: "copy".into(),
            audio_bitrate: "192k".into(),
        };
        let (filter, maps) = spec.build_filter_graph();
        assert!(filter.is_empty());
        assert!(maps.is_empty());
    }

    #[test]
    fn test_build_filter_graph_with_music() {
        let spec = MixSpec {
            video: "test.mp4".into(),
            output: "out.mp4".into(),
            music: Some("bgm.mp3".into()),
            music_volume_db: -18.0,
            sfx_events: vec![],
            enable_ducking: false,
            video_bitrate: "copy".into(),
            audio_bitrate: "192k".into(),
        };
        let (filter, maps) = spec.build_filter_graph();
        assert!(filter.contains("volume=-18dB[music]"));
        assert!(filter.contains("amix"));
        assert_eq!(maps.len(), 1);
        assert_eq!(maps[0], "[aout]");
    }

    #[test]
    fn test_build_filter_graph_with_sfx() {
        let spec = MixSpec {
            video: "test.mp4".into(),
            output: "out.mp4".into(),
            music: None,
            music_volume_db: -18.0,
            sfx_events: vec![SfxEvent {
                file: "boom.wav".into(),
                timestamp: 3.5,
                volume_db: -8.0,
                mix_ratio: 0.6,
            }],
            enable_ducking: false,
            video_bitrate: "copy".into(),
            audio_bitrate: "192k".into(),
        };
        let (filter, maps) = spec.build_filter_graph();
        assert!(filter.contains("adelay=3500|3500"));
        assert!(filter.contains("volume=-8dB[sfx0]"));
        assert_eq!(maps.len(), 1);
    }
}
