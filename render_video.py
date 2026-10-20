
import os
import re
import sys
import shutil
import subprocess
from pathlib import Path


# --------------------------------------------------
# PROJECT PATHS
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
CLIPS_DIR = BASE_DIR / "clips"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SCRIPT_FILE = UPLOAD_DIR / "current_script.txt"


# --------------------------------------------------
# FIND FFMPEG AND FFPROBE
# Works on Windows and Render Linux
# --------------------------------------------------

def find_executable(name, windows_path):
    executable = shutil.which(name)

    if executable:
        return executable

    if os.name == "nt" and Path(windows_path).exists():
        return windows_path

    raise FileNotFoundError(
        f"{name} was not found. Check your FFmpeg installation."
    )


FFMPEG = find_executable(
    "ffmpeg",
    r"D:\ffmpeg\bin\ffmpeg.exe"
)

FFPROBE = find_executable(
    "ffprobe",
    r"D:\ffmpeg\bin\ffprobe.exe"
)


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def run_command(command):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr[-5000:]
            or result.stdout[-5000:]
            or "FFmpeg command failed."
        )

    return result


def get_duration(file_path):
    result = run_command([
        FFPROBE,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ])

    duration = float(result.stdout.strip())

    if duration <= 0:
        raise ValueError("The audio duration is invalid.")

    return duration


def split_sentences(script):
    """Split narration into individual caption sentences."""
    script = re.sub(r"\s+", " ", script).strip()

    if not script:
        raise ValueError("The narration script is empty.")

    sentences = re.split(r"(?<=[.!?])\s+", script)

    return [sentence.strip() for sentence in sentences if sentence.strip()]


def srt_timestamp(seconds):
    """Convert seconds into an SRT timestamp."""
    milliseconds = round(seconds * 1000)

    hours = milliseconds // 3600000
    milliseconds %= 3600000

    minutes = milliseconds // 60000
    milliseconds %= 60000

    secs = milliseconds // 1000
    milliseconds %= 1000

    return (
        f"{hours:02}:{minutes:02}:{secs:02},"
        f"{milliseconds:03}"
    )


def create_captions(script, duration, srt_path):
    """Create bottom subtitles, timed sentence by sentence."""
    sentences = split_sentences(script)

    # Allocate time according to sentence word count.
    word_counts = [max(1, len(s.split())) for s in sentences]
    total_words = sum(word_counts)

    current_time = 0.0
    subtitle_entries = []

    for index, sentence in enumerate(sentences):
        start = current_time

        if index == len(sentences) - 1:
            end = duration
        else:
            sentence_duration = (
                duration * word_counts[index] / total_words
            )
            end = current_time + sentence_duration

        if end <= start:
            end = min(duration, start + 0.1)

        subtitle_entries.append(
            f"{index + 1}\n"
            f"{srt_timestamp(start)} --> {srt_timestamp(end)}\n"
            f"{sentence}\n"
        )

        current_time = end

    srt_path.write_text(
        "\n".join(subtitle_entries),
        encoding="utf-8"
    )


def escape_filter_path(path):
    """Escape a file path for FFmpeg's subtitles filter."""
    value = str(path.resolve()).replace("\\", "/")
    value = value.replace(":", r"\:")
    value = value.replace("'", r"\'")
    value = value.replace(",", r"\,")
    value = value.replace("[", r"\[")
    value = value.replace("]", r"\]")
    return value


# --------------------------------------------------
# MAIN VIDEO RENDERER
# --------------------------------------------------

def render_video(audio_path, output_path, aspect_ratio="16:9"):
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

    # Support landscape, portrait and square video.
    if aspect_ratio == "9:16":
        width, height = 720, 1280
    elif aspect_ratio == "1:1":
        width, height = 720, 720
    else:
        width, height = 1280, 720

    # Find B-roll clips.
    supported_extensions = {
        ".mp4", ".mov", ".mkv", ".webm"
    }

    clips = sorted(
        clip for clip in CLIPS_DIR.iterdir()
        if clip.is_file()
        and clip.suffix.lower() in supported_extensions
    ) if CLIPS_DIR.exists() else []

    if not clips:
        raise FileNotFoundError(
            f"No B-roll clips found in {CLIPS_DIR}"
        )

    audio_duration = get_duration(audio_path)

    # Read the script saved by main.py.
    if not SCRIPT_FILE.exists():
        raise FileNotFoundError(
            f"Narration script not found: {SCRIPT_FILE}"
        )

    script = SCRIPT_FILE.read_text(encoding="utf-8").strip()

    # Generate sentence-by-sentence subtitle file.
    srt_path = OUTPUT_DIR / "captions.srt"

    create_captions(
        script,
        audio_duration,
        srt_path
    )

    # Split the video duration across the available clips.
    segment_duration = audio_duration / len(clips)

    command = [FFMPEG, "-y"]
    filter_parts = []

    # Loop each B-roll clip if necessary.
    for clip in clips:
        command.extend([
            "-stream_loop", "-1",
            "-i", str(clip)
        ])

    # Add narration audio as the final input.
    command.extend(["-i", str(audio_path)])
    audio_index = len(clips)

    # Prepare each B-roll segment.
    for index in range(len(clips)):
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

    # Join all B-roll segments.
    video_inputs = "".join(
        f"[v{index}]" for index in range(len(clips))
    )

    filter_parts.append(
        f"{video_inputs}"
        f"concat=n={len(clips)}:v=1:a=0,"
        f"trim=duration={audio_duration},"
        f"setpts=PTS-STARTPTS"
        f"[joined]"
    )

    # Burn white captions into the video.
    subtitle_path = escape_filter_path(srt_path)

    filter_parts.append(
        f"[joined]"
        f"subtitles=filename='{subtitle_path}':"
        f"force_style='FontName=DejaVu Sans,"
        f"FontSize=24,"
        f"PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H80000000,"
        f"BorderStyle=1,"
        f"Outline=2,"
        f"Shadow=1,"
        f"Alignment=2,"
        f"MarginV=35'"
        f"[video]"
    )

    # Keep the original generated narration.
    filter_parts.append(
        f"[{audio_index}:a]"
        f"atrim=duration={audio_duration},"
        f"asetpts=PTS-STARTPTS"
        f"[audio]"
    )

    command.extend([
        "-filter_complex", ";".join(filter_parts),
        "-map", "[video]",
        "-map", "[audio]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-t", str(audio_duration),
        "-movflags", "+faststart",
        str(output_path)
    ])

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    run_command(command)

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("The output video was not created correctly.")

    return output_path


# --------------------------------------------------
# COMMAND-LINE ENTRY POINT
# Compatible with main.py
# --------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print(
            "Usage: python render_video.py "
            "<audio_path> <output_path> [16:9|9:16|1:1]"
        )
        sys.exit(1)

    audio_path = sys.argv[1]
    output_path = sys.argv[2]
    aspect_ratio = sys.argv[3] if len(sys.argv) > 3 else "16:9"

    try:
        result = render_video(
            audio_path,
            output_path,
            aspect_ratio
        )

        print(f"Video created successfully: {result}")

    except Exception as error:
        print(
            f"Video generation failed: {error}",
            file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
