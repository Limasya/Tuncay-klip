use anyhow::Result;
use clap::{Parser, Subcommand};
use serde_json::json;

mod probe;
mod clip;
mod validate;
mod export;
mod batch;

#[derive(Parser)]
#[command(
    name = "tuncay-video-processor",
    about = "High-performance video processing toolkit",
    version,
    long_about = "Professional video processor for the Tuncay-Klip pipeline.\nHandles clip extraction, validation, probing, and platform export."
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Extract a clip from a video file or HLS stream
    Clip {
        #[arg(short, long, help = "Input video path or HLS URL")]
        input: String,

        #[arg(short, long, help = "Output file path")]
        output: String,

        #[arg(short = 'S', long, help = "Start time in seconds")]
        start: f64,

        #[arg(short = 'D', long, help = "Duration in seconds")]
        duration: f64,

        #[arg(long, default_value = "copy", help = "Video codec (copy, libx264, libx265)")]
        vcodec: String,

        #[arg(long, default_value = "copy", help = "Audio codec (copy, aac, libopus)")]
        acodec: String,

        #[arg(long, help = "Custom User-Agent for HTTP streams")]
        user_agent: Option<String>,

        #[arg(long, help = "HTTP Referer header")]
        referer: Option<String>,

        #[arg(long, help = "Additional FFmpeg arguments")]
        extra_args: Option<Vec<String>>,
    },

    /// Probe video file for metadata
    Probe {
        #[arg(short, long, help = "Input video path")]
        input: String,

        #[arg(long, help = "Output format: json (default), summary")]
        format: Option<String>,
    },

    /// Validate a video file (MP4 check, duration, codecs)
    Validate {
        #[arg(short, long, help = "Input video path")]
        input: String,

        #[arg(long, help = "Expected minimum duration in seconds")]
        min_duration: Option<f64>,

        #[arg(long, help = "Expected maximum duration in seconds")]
        max_duration: Option<f64>,
    },

    /// Export clip to platform-specific format
    Export {
        #[arg(short, long, help = "Input video path")]
        input: String,

        #[arg(short, long, help = "Output file path")]
        output: String,

        #[arg(short, long, help = "Target platform (tiktok, youtube, youtube_shorts, instagram, kick)")]
        platform: String,

        #[arg(long, help = "Custom FFmpeg filter string")]
        filter: Option<String>,
    },

    /// Process multiple clips in parallel
    Batch {
        #[arg(short, long, help = "JSON manifest file with clip definitions")]
        manifest: String,

        #[arg(short, long, help = "Output directory")]
        output_dir: String,

        #[arg(long, default_value = "4", help = "Max parallel jobs")]
        jobs: usize,
    },

    /// Compute file checksum for deduplication
    Checksum {
        #[arg(short, long, help = "Input file path")]
        input: String,

        #[arg(long, default_value = "sha256", help = "Hash algorithm (sha256, md5)")]
        algorithm: String,
    },
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    let cli = Cli::parse();

    let result = match cli.command {
        Commands::Clip { input, output, start, duration, vcodec, acodec, user_agent, referer, extra_args } => {
            clip::extract_clip(&clip::ClipArgs {
                input, output, start, duration, vcodec, acodec,
                user_agent, referer, extra_args,
            }).await
        }
        Commands::Probe { input, format } => {
            probe::probe_video(&input, format.as_deref()).await
        }
        Commands::Validate { input, min_duration, max_duration } => {
            validate::validate_video(&validate::ValidateArgs {
                input, min_duration, max_duration,
            }).await
        }
        Commands::Export { input, output, platform, filter } => {
            export::export_clip(&export::ExportArgs {
                input, output, platform, filter,
            }).await
        }
        Commands::Batch { manifest, output_dir, jobs } => {
            batch::process_batch(&manifest, &output_dir, jobs).await
        }
        Commands::Checksum { input, algorithm } => {
            validate::compute_checksum(&input, &algorithm).await
        }
    };

    match result {
        Ok(output) => {
            println!("{}", output);
            Ok(())
        }
        Err(e) => {
            let err_output = json!({
                "success": false,
                "error": format!("{}", e),
            });
            eprintln!("{}", serde_json::to_string_pretty(&err_output)?);
            std::process::exit(1);
        }
    }
}
