use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::process::Command;
use anyhow::{Result, bail};
use sha2::{Sha256, Digest};
use serde_json::json;

pub struct ValidateArgs {
    pub input: String,
    pub min_duration: Option<f64>,
    pub max_duration: Option<f64>,
}

pub async fn validate_video(args: &ValidateArgs) -> Result<String> {
    let path = Path::new(&args.input);
    if !path.exists() {
        bail!("File not found: {}", args.input);
    }

    let file_size = std::fs::metadata(path)?.len();
    if file_size == 0 {
        bail!("File is empty: {}", args.input);
    }

    let output = Command::new("ffprobe")
        .args([
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            &args.input,
        ])
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("ffprobe validation failed: {}", stderr);
    }

    let raw: serde_json::Value = serde_json::from_slice(&output.stdout)?;
    let format = raw.get("format").cloned().unwrap_or_default();

    let format_name = format.get("format_name")
        .and_then(|v| v.as_str()).unwrap_or("");
    let duration = format.get("duration")
        .and_then(|v| v.as_f64()).unwrap_or(0.0);
    let nb_streams = format.get("nb_streams")
        .and_then(|v| v.as_u64()).unwrap_or(0);

    let has_video = raw.get("streams")
        .and_then(|v| v.as_array())
        .map(|streams| streams.iter().any(|s| {
            s.get("codec_type").and_then(|v| v.as_str()) == Some("video")
        }))
        .unwrap_or(false);

    let has_audio = raw.get("streams")
        .and_then(|v| v.as_array())
        .map(|streams| streams.iter().any(|s| {
            s.get("codec_type").and_then(|v| v.as_str()) == Some("audio")
        }))
        .unwrap_or(false);

    let mut errors: Vec<String> = Vec::new();

    if !format_name.contains("mp4") {
        errors.push(format!("Not an MP4 file (format: {})", format_name));
    }
    if duration <= 0.0 {
        errors.push("Invalid duration (0 or negative)".into());
    }
    if nb_streams == 0 {
        errors.push("No streams found".into());
    }
    if !has_video {
        errors.push("No video stream".into());
    }
    if let Some(min_d) = args.min_duration {
        if duration < min_d {
            errors.push(format!("Duration {}s is below minimum {}s", duration, min_d));
        }
    }
    if let Some(max_d) = args.max_duration {
        if duration > max_d {
            errors.push(format!("Duration {}s exceeds maximum {}s", duration, max_d));
        }
    }

    let valid = errors.is_empty();

    let result = json!({
        "success": true,
        "valid": valid,
        "file": args.input,
        "size_bytes": file_size,
        "duration_sec": duration,
        "format": format_name,
        "nb_streams": nb_streams,
        "has_video": has_video,
        "has_audio": has_audio,
        "errors": errors,
    });

    Ok(serde_json::to_string_pretty(&result)?)
}

pub async fn compute_checksum(input: &str, algorithm: &str) -> Result<String> {
    let path = Path::new(input);
    if !path.exists() {
        bail!("File not found: {}", input);
    }

    let mut file = File::open(path)?;

    match algorithm {
        "sha256" => {
            let mut hasher = Sha256::new();
            let mut buffer = [0u8; 8192];
            loop {
                let bytes_read = file.read(&mut buffer)?;
                if bytes_read == 0 { break; }
                hasher.update(&buffer[..bytes_read]);
            }
            let hash = hex::encode(hasher.finalize());
            let result = json!({
                "success": true,
                "algorithm": "sha256",
                "hash": hash,
                "file": input,
                "size_bytes": std::fs::metadata(path)?.len(),
            });
            Ok(serde_json::to_string_pretty(&result)?)
        }
        "md5" => {
            use md5::Md5;
            use digest::Digest as _;
            let mut hasher = Md5::new();
            let mut buffer = [0u8; 8192];
            loop {
                let bytes_read = file.read(&mut buffer)?;
                if bytes_read == 0 { break; }
                hasher.update(&buffer[..bytes_read]);
            }
            let hash = hex::encode(hasher.finalize());
            let result = json!({
                "success": true,
                "algorithm": "md5",
                "hash": hash,
                "file": input,
                "size_bytes": std::fs::metadata(path)?.len(),
            });
            Ok(serde_json::to_string_pretty(&result)?)
        }
        _ => bail!("Unsupported algorithm: {} (use sha256 or md5)", algorithm),
    }
}
