use std::process::Command;
use anyhow::{Result, bail};
use serde_json::json;
use std::collections::HashMap;

pub struct ExportArgs {
    pub input: String,
    pub output: String,
    pub platform: String,
    pub filter: Option<String>,
}

struct PlatformSpec {
    width: u32,
    height: u32,
    max_duration: Option<f64>,
    vcodec: &'static str,
    crf: &'static str,
    extra_args: Vec<&'static str>,
}

fn get_platform_spec(platform: &str) -> Result<PlatformSpec> {
    match platform.to_lowercase().as_str() {
        "tiktok" | "youtube_shorts" | "shorts" => Ok(PlatformSpec {
            width: 1080,
            height: 1920,
            max_duration: Some(60.0),
            vcodec: "libx264",
            crf: "23",
            extra_args: vec!["-movflags", "+faststart"],
        }),
        "youtube" => Ok(PlatformSpec {
            width: 1920,
            height: 1080,
            max_duration: None,
            vcodec: "libx264",
            crf: "20",
            extra_args: vec!["-movflags", "+faststart"],
        }),
        "instagram" | "instagram_reels" | "reels" => Ok(PlatformSpec {
            width: 1080,
            height: 1920,
            max_duration: Some(90.0),
            vcodec: "libx264",
            crf: "23",
            extra_args: vec!["-movflags", "+faststart"],
        }),
        "kick" => Ok(PlatformSpec {
            width: 1920,
            height: 1080,
            max_duration: None,
            vcodec: "libx264",
            crf: "20",
            extra_args: vec!["-movflags", "+faststart"],
        }),
        _ => bail!("Unknown platform: {} (supported: tiktok, youtube, youtube_shorts, instagram, kick)", platform),
    }
}

pub async fn export_clip(args: &ExportArgs) -> Result<String> {
    let spec = get_platform_spec(&args.platform)?;

    let mut cmd = Command::new("ffmpeg");
    cmd.arg("-y");
    cmd.args(["-i", &args.input]);

    if let Some(filter) = &args.filter {
        cmd.args(["-vf", filter]);
    } else {
        let vf = format!(
            "scale={}:{}:force_original_aspect_ratio=decrease,pad={}:{}:(ow-iw)/2:(oh-ih)/2",
            spec.width, spec.height, spec.width, spec.height
        );
        cmd.args(["-vf", &vf]);
    }

    cmd.args(["-c:v", spec.vcodec, "-crf", spec.crf]);
    cmd.args(["-c:a", "aac", "-b:a", "128k"]);
    cmd.args(["-pix_fmt", "yuv420p"]);

    if let Some(max_dur) = spec.max_duration {
        cmd.args(["-t", &max_dur.to_string()]);
    }

    for arg in &spec.extra_args {
        cmd.arg(arg);
    }

    cmd.arg(&args.output);

    let output = cmd.output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("FFmpeg export failed: {}", stderr);
    }

    let metadata = std::fs::metadata(&args.output)?;

    let mut dimensions = HashMap::new();
    dimensions.insert("width", spec.width);
    dimensions.insert("height", spec.height);

    let result = json!({
        "success": true,
        "output": args.output,
        "platform": args.platform,
        "size_bytes": metadata.len(),
        "dimensions": dimensions,
        "codec": spec.vcodec,
    });

    Ok(serde_json::to_string_pretty(&result)?)
}
