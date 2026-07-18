use std::process::Command;
use anyhow::{Result, bail};
use serde_json::json;

pub struct ClipArgs {
    pub input: String,
    pub output: String,
    pub start: f64,
    pub duration: f64,
    pub vcodec: String,
    pub acodec: String,
    pub user_agent: Option<String>,
    pub referer: Option<String>,
    pub extra_args: Option<Vec<String>>,
}

pub async fn extract_clip(args: &ClipArgs) -> Result<String> {
    let mut cmd = Command::new("ffmpeg");
    cmd.arg("-y");

    cmd.args(["-ss", &args.start.to_string()]);

    if args.input.starts_with("http") {
        if let Some(ua) = &args.user_agent {
            cmd.args(["-user_agent", ua]);
        }
        if let Some(ref_) = &args.referer {
            cmd.args(["-headers", &format!("Referer: {}\r\n", ref_)]);
        }
    }

    cmd.args(["-i", &args.input]);
    cmd.args(["-t", &args.duration.to_string()]);

    if args.vcodec == "copy" && args.acodec == "copy" {
        cmd.args(["-c:v", "copy", "-c:a", "copy"]);
    } else {
        cmd.args(["-c:v", &args.vcodec, "-c:a", &args.acodec]);
    }

    if let Some(extra) = &args.extra_args {
        for arg in extra {
            cmd.arg(arg);
        }
    }

    cmd.args(["-movflags", "+faststart"]);
    cmd.arg(&args.output);

    let output = cmd.output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let error_hint = parse_ffmpeg_error(&stderr);
        bail!("FFmpeg clip extraction failed: {}", error_hint);
    }

    let metadata = std::fs::metadata(&args.output)?;
    let result = json!({
        "success": true,
        "output": args.output,
        "size_bytes": metadata.len(),
        "start_sec": args.start,
        "duration_sec": args.duration,
    });

    Ok(serde_json::to_string_pretty(&result)?)
}

fn parse_ffmpeg_error(stderr: &str) -> String {
    if stderr.contains("403") || stderr.contains("Forbidden") {
        return "HTTP 403 Forbidden — possible Cloudflare block, update User-Agent/impersonate".into();
    }
    if stderr.contains("410") || stderr.contains("Gone") {
        return "HTTP 410 Gone — VOD no longer available".into();
    }
    if stderr.contains("Invalid data") {
        return "Invalid input data — file may be corrupted or incomplete".into();
    }

    let lines: Vec<&str> = stderr.lines().rev().take(3).collect();
    lines.join(" | ")
}
