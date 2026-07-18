use std::fs;
use anyhow::{Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::json;
use tokio::task;
use indicatif::{ProgressBar, ProgressStyle};

#[derive(Debug, Deserialize, Serialize)]
struct ClipJob {
    input: String,
    output: String,
    start: f64,
    duration: f64,
    #[serde(default = "default_vcodec")]
    vcodec: String,
    #[serde(default = "default_acodec")]
    acodec: String,
}

fn default_vcodec() -> String { "copy".into() }
fn default_acodec() -> String { "copy".into() }

#[derive(Debug, Deserialize)]
struct BatchManifest {
    jobs: Vec<ClipJob>,
}

pub async fn process_batch(manifest_path: &str, output_dir: &str, max_jobs: usize) -> Result<String> {
    let manifest_content = fs::read_to_string(manifest_path)?;
    let manifest: BatchManifest = serde_json::from_str(&manifest_content)?;

    if manifest.jobs.is_empty() {
        bail!("No jobs in manifest");
    }

    fs::create_dir_all(output_dir)?;

    let total = manifest.jobs.len();
    let pb = ProgressBar::new(total as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} ({eta})")
            .unwrap()
            .progress_chars("#>-"),
    );

    let mut handles = Vec::new();
    let semaphore = std::sync::Arc::new(tokio::sync::Semaphore::new(max_jobs));

    for job in manifest.jobs {
        let permit = semaphore.clone().acquire_owned().await?;
        let pb = pb.clone();
        let handle = task::spawn(async move {
            let result = task_extract(&job);
            drop(permit);
            pb.inc(1);
            (job.output.clone(), result)
        });
        handles.push(handle);
    }

    let mut succeeded = 0;
    let mut failed = 0;
    let mut results = Vec::new();

    for handle in handles {
        let (output, result) = handle.await?;
        match result {
            Ok(size) => {
                succeeded += 1;
                results.push(json!({"file": output, "size_bytes": size, "success": true}));
            }
            Err(e) => {
                failed += 1;
                results.push(json!({"file": output, "error": format!("{}", e), "success": false}));
            }
        }
    }

    pb.finish_with_message("done");

    let summary = json!({
        "success": failed == 0,
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "output_dir": output_dir,
        "results": results,
    });

    Ok(serde_json::to_string_pretty(&summary)?)
}

fn task_extract(job: &ClipJob) -> std::result::Result<u64, String> {
    let output = std::process::Command::new("ffmpeg")
        .args([
            "-y",
            "-ss", &job.start.to_string(),
            "-i", &job.input,
            "-t", &job.duration.to_string(),
            "-c:v", &job.vcodec,
            "-c:a", &job.acodec,
            "-movflags", "+faststart",
            &job.output,
        ])
        .output()
        .map_err(|e| format!("Failed to spawn ffmpeg: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("FFmpeg error: {}", stderr.chars().take(500).collect::<String>()));
    }

    let meta = std::fs::metadata(&job.output)
        .map_err(|e| format!("Cannot read output: {}", e))?;
    Ok(meta.len())
}
