use std::process::Command;
use anyhow::{Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Debug, Serialize, Deserialize)]
pub struct VideoInfo {
    pub format: FormatInfo,
    pub streams: Vec<StreamInfo>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct FormatInfo {
    pub filename: String,
    pub format_name: String,
    pub duration: f64,
    pub size: u64,
    pub bit_rate: u64,
    pub nb_streams: u32,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct StreamInfo {
    pub index: u32,
    pub codec_name: String,
    pub codec_type: String,
    pub width: Option<u32>,
    pub height: Option<u32>,
    pub r_frame_rate: Option<String>,
    pub sample_rate: Option<String>,
    pub channels: Option<u32>,
}

pub async fn probe_video(input: &str, format: Option<&str>) -> Result<String> {
    let output = Command::new("ffprobe")
        .args([
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            input,
        ])
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("ffprobe failed: {}", stderr);
    }

    let raw: Value = serde_json::from_slice(&output.stdout)?;
    let info: VideoInfo = serde_json::from_value(raw.clone())?;

    match format {
        Some("summary") => {
            let fmt = &info.format;
            let video_stream = info.streams.iter().find(|s| s.codec_type == "video");
            let audio_stream = info.streams.iter().find(|s| s.codec_type == "audio");

            let summary = json!({
                "success": true,
                "input": fmt.filename,
                "format": fmt.format_name,
                "duration_sec": fmt.duration,
                "size_bytes": fmt.size,
                "bitrate_bps": fmt.bit_rate,
                "video": video_stream.map(|s| json!({
                    "codec": s.codec_name,
                    "width": s.width,
                    "height": s.height,
                    "fps": s.r_frame_rate,
                })),
                "audio": audio_stream.map(|s| json!({
                    "codec": s.codec_name,
                    "sample_rate": s.sample_rate,
                    "channels": s.channels,
                })),
            });
            Ok(serde_json::to_string_pretty(&summary)?)
        }
        _ => {
            let mut result = json!({
                "success": true,
            });
            if let Value::Object(map) = raw {
                for (k, v) in map {
                    result[k] = v;
                }
            }
            Ok(serde_json::to_string_pretty(&result)?)
        }
    }
}
