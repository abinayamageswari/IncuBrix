
import os
import sys
import json
import shutil
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CLIPS_DIR = BASE_DIR / "clips"
OUTPUT_DIR = BASE_DIR / "outputs"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def find_executable(name, windows_path):
    """Find FFmpeg tools on Windows or Linux."""
    executable = shutil.which(name)

    if executable:
        return executable

    if os.name == "nt" and Path(windows_path).exists():
        return windows_path

    raise FileNotFoundError(
        f"{name} was not found. Please install FFmpeg and ensure it is available."
    )


FFMPEG = find_executable(
    "ffmpeg",
    r"D:\ffmpeg\bin\ffmpeg.exe"
)

FFPROBE = find_executable(
    "ffprobe",
    r"D:\ffmpeg\bin\ffprobe.exe"
)


def get_duration(video_path):
    """Get video duration in seconds."""
    result = subprocess.run(
        [
            FFPROBE,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    return float(result.stdout.strip())


def run_command(command):
    """Run a command and report errors clearly."""
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Video processing failed:\n"
            + result.stderr[-4000:]
        )

    return result


def render_video(audio_path, output_path, aspect_ratio="16:9"):
    """
    Combine generated audio with available B-roll clips.

    audio_path: path to the generated voiceover audio.
    output_path: destination for the rendered MP4.
    aspect_ratio: '16:9' or '9:16'.
    """
    audio_path = Path(audio_path)
    output_path = Path(output_path)

    if not audio_path.is_absolute():
        audio_path = BASE_DIR / audio_path

    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path

    if not audio_path.exists():
        raise FileNotFoundError(
            f"Audio file not found: {audio_path}"
        )

    if aspect_ratio == "9:16":
        width, height = 720, 1280
    else:
        width, height = 1280, 720

    extensions = {".mp4", ".mov", ".mkv", ".webm"}

    clips = sorted(
        file for file in CLIPS_DIR.iterdir()
        if file.is_file() and file.suffix.lower() in extensions
    ) if CLIPS_DIR.exists() else []

    if not clips:
        raise FileNotFoundError(
            f"No video clips found in {CLIPS_DIR}. "
            "Add B-roll videos to the clips folder."
        )

    audio_duration = get_duration(audio_path)

    if audio_duration <= 0:
        raise ValueError("The generated audio has no valid duration.")

    # Use the available clips repeatedly until the voiceover ends.
    segment_duration = audio_duration / len(clips)

    filter_parts = []
    input_args = []

    for clip in clips:
        input_args.extend(["-i", str(clip)])

    input_args.extend(["-i", str(audio_path)])
    audio_index = len(clips)

    for index, clip in enumerate(clips):
        filter_parts.append(
            f"[{index}:v]"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"setsar=1,"
            f"fps=30,"
            f"trim=duration={segment_duration},"
            f"setpts=PTS-STARTPTS"
            f"[v{index}]"
        )

    video_inputs = "".join(
        f"[v{index}]" for index in range(len(clips))
    )

    filter_parts.append(
        f"{video_inputs}"
        f"concat=n={len(clips)}:v=1:a=0,"
        f"trim=duration={audio_duration},"
        f"setpts=PTS-STARTPTS"
        f"[video]"
    )

    filter_parts.append(
        f"[{audio_index}:a]"
        f"atrim=duration={audio_duration},"
        f"asetpts=PTS-STARTPTS"
        f"[audio]"
    )

    filter_complex = ";".join(filter_parts)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        FFMPEG,
        "-y",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", "[video]",
        "-map", "[audio]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]

    run_command(command)

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("The output video was not created correctly.")

    return output_path


def main():
    """Support command-line execution."""
    if len(sys.argv) < 3:
        print(
            "Usage: python render_video.py "
            "<audio_path> <output_path> [16:9|9:16]"
        )
        sys.exit(1)

    audio_path = sys.argv[1]
    output_path = sys.argv[2]
    aspect_ratio = sys.argv[3] if len(sys.argv) > 3 else "16:9"

    try:
        result = render_video(
            audio_path,
            output_path,
            aspect_ratio,
        )
        print(f"Video created successfully: {result}")

    except Exception as error:
        print(f"Video generation failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
