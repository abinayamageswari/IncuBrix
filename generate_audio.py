
import sys
from pathlib import Path
import pyttsx3


def generate_audio(script):
    output_folder = Path(__file__).resolve().parent / "uploads"
    output_folder.mkdir(exist_ok=True)

    audio_file = output_folder / "narration.wav"

    engine = pyttsx3.init()
    engine.setProperty("rate", 155)
    engine.save_to_file(script, str(audio_file))
    engine.runAndWait()
    engine.stop()

    if not audio_file.exists() or audio_file.stat().st_size == 0:
        raise RuntimeError("Audio generation failed.")

    print(f"Audio created: {audio_file}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_audio.py \"Your script here\"")
        sys.exit(1)

    generate_audio(" ".join(sys.argv[1:]))
