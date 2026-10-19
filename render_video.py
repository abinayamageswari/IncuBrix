import subprocess
import re
import sys
from pathlib import Path


# Project folders
BASE_DIR = Path(__file__).resolve().parent
CLIPS_DIR = BASE_DIR / "clips"
UPLOADS_DIR = BASE_DIR / "uploads"

# Use the output folder provided by main.py.
# If run manually, default to the original outputs folder.
DEFAULT_OUTPUT_DIR = BASE_DIR / "outputs"

OUTPUT_DIR = (
    Path(sys.argv[1]).resolve()
    if len(sys.argv) > 1
    else DEFAULT_OUTPUT_DIR
)

AUDIO_FILE = UPLOADS_DIR / "narration.wav"
SCRIPT_FILE = UPLOADS_DIR / "current_script.txt"
RATIO_FILE = UPLOADS_DIR / "current_aspect_ratio.txt"

FFMPEG = r"D:\ffmpeg\bin\ffmpeg.exe"
FFPROBE = r"D:\ffmpeg\bin\ffprobe.exe"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Read script and aspect ratio
script = SCRIPT_FILE.read_text(encoding="utf-8").strip()

ratio = (
    RATIO_FILE.read_text(encoding="utf-8").strip()
    if RATIO_FILE.exists()
    else "16:9"
)

dimensions = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080)
}

if ratio not in dimensions:
    raise ValueError(
        "Aspect ratio must be 16:9, 9:16, or 1:1"
    )

width, height = dimensions[ratio]


# Split script into sentences
sentences = [
    sentence.strip()
    for sentence in re.split(r"(?<=[.!?])\s+", script)
    if sentence.strip()
]

if not sentences:
    sentences = [script]


# Select B-roll for each sentence
def select_clip(sentence):
    text = sentence.lower()

    city_words = [
        "city", "urban", "street", "traffic",
        "building", "buildings", "skyline"
    ]

    mountain_words = [
        "mountain", "mountains", "hill", "hills",
        "peak", "peaks", "hiking", "snow"
    ]

    nature_words = [
        "nature", "forest", "forests", "tree", "trees",
        "wildlife", "river", "lake", "flower", "flowers",
        "bird", "birds", "garden"
    ]

    if any(word in text for word in city_words):
        filename = "city_small.mp4"
    elif any(word in text for word in mountain_words):
        filename = "mountains_small.mp4"
    elif any(word in text for word in nature_words):
        filename = "nature_small.mp4"
    else:
        filename = "nature_small.mp4"

    path = CLIPS_DIR / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Required B-roll clip not found: {path}"
        )

    return path


# Check required files
for file_path in [AUDIO_FILE, SCRIPT_FILE]:
    if not file_path.exists():
        raise FileNotFoundError(
            f"Missing file: {file_path}"
        )


# Get narration duration
result = subprocess.run(
    [
        FFPROBE,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(AUDIO_FILE)
    ],
    capture_output=True,
    text=True,
    check=True
)

duration = float(result.stdout.strip())

if duration <= 0:
    raise ValueError("Narration duration must be positive")


# Estimate sentence durations using character length.
# This is an estimate, not exact speech recognition.
weights = [
    max(len(sentence), 1)
    for sentence in sentences
]

total_weight = sum(weights)

durations = [
    duration * weight / total_weight
    for weight in weights
]


# Create temporary video segments inside this job's folder
temp_dir = OUTPUT_DIR / "segments"
temp_dir.mkdir(parents=True, exist_ok=True)

segment_files = []

for index, (sentence, segment_duration) in enumerate(
    zip(sentences, durations)
):
    clip = select_clip(sentence)

    segment_file = temp_dir / f"segment_{index:03d}.mp4"

    # Escape caption text for FFmpeg
    caption = (
        sentence.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )

    video_filter = (
        f"scale={width}:{height}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        "fps=30,"
        "drawtext="
        f"text='{caption}':"
        "fontcolor=white:fontsize=32:"
        "borderw=2:bordercolor=black:"
        "x=(w-text_w)/2:y=h-text_h-60,"
        "format=yuv420p"
    )

    command = [
        FFMPEG, "-y",
        "-stream_loop", "-1",
        "-i", str(clip),
        "-t", f"{segment_duration:.3f}",
        "-vf", video_filter,
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        str(segment_file)
    ]

    subprocess.run(command, check=True)

    segment_files.append(segment_file)

    print(
        f"Sentence {index + 1}: {sentence}\n"
        f"Selected B-roll: {clip.name}\n"
        f"Estimated duration: {segment_duration:.2f}s"
    )


# Create FFmpeg concat list
concat_file = temp_dir / "concat_list.txt"

with concat_file.open("w", encoding="utf-8") as file:
    for segment in segment_files:
        safe_path = segment.as_posix().replace("'", "'\\''")
        file.write(f"file '{safe_path}'\n")


# Save final video inside this job's output folder
output_file = OUTPUT_DIR / (
    f"final_video_{ratio.replace(':', 'x')}.mp4"
)


# Join video segments and add the original narration
command = [
    FFMPEG, "-y",
    "-f", "concat",
    "-safe", "0",
    "-i", str(concat_file),
    "-i", str(AUDIO_FILE),
    "-map", "0:v:0",
    "-map", "1:a:0",
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "-c:a", "aac",
    "-b:a", "192k",
    "-t", str(duration),
    "-movflags", "+faststart",
    str(output_file)
]

subprocess.run(command, check=True)

print("\nVideo generation complete!")
print(f"Aspect ratio: {ratio}")
print(f"Output video: {output_file}")