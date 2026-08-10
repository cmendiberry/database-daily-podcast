#!/usr/bin/env python3
"""
tts_generate.py - Generate a Database Daily episode MP3 using Kokoro TTS.

Reads a plain-text script file and writes an MP3. Voice, speed, and paths
are configurable via command-line arguments. Writes optional JSON metrics.

Usage:
    python scripts/tts_generate.py \\
        --script-file /path/to/script.txt \\
        --output /path/to/episode.mp3 \\
        [--voice af_heart] \\
        [--speed 1.0] \\
        [--lang en-us] \\
        [--model /path/to/kokoro-v1.0.onnx] \\
        [--voices-bin /path/to/voices-v1.0.bin] \\
        [--bitrate 128k] \\
        [--metrics-out /path/to/metrics.json]

Exit codes:
    0 - Success
    1 - Error (message printed to stderr)

No API keys or credentials required.
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path


def format_duration(seconds: float) -> str:
    """Format a duration in seconds as M:SS or H:MM:SS."""
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def generate(
    script_text: str,
    output_path: Path,
    model_path: Path,
    voices_path: Path,
    voice: str,
    speed: float,
    lang: str,
    bitrate: str,
) -> dict:
    """
    Run Kokoro TTS on script_text and write an MP3 to output_path.

    Returns a metrics dict with timing and audio statistics.
    Imports kokoro/soundfile/pydub inside this function so the module
    can be imported for unit tests without those packages installed.
    """
    try:
        import soundfile as sf
        from pydub import AudioSegment
        from kokoro_onnx import Kokoro
    except ImportError as exc:
        print(f"ERROR: Missing TTS dependency: {exc}", file=sys.stderr)
        print("Install with: pip install kokoro-onnx soundfile pydub", file=sys.stderr)
        sys.exit(1)

    t_wall = time.time()

    # Load model
    print(f"Loading Kokoro model from {model_path} ...", flush=True)
    t0 = time.time()
    kokoro = Kokoro(str(model_path), str(voices_path))
    t_load = time.time() - t0
    print(f"  Model loaded in {t_load:.1f}s")

    # Generate speech
    word_count = len(script_text.split())
    print(
        f"Generating TTS: voice={voice!r}, speed={speed}, lang={lang!r}, words={word_count}",
        flush=True,
    )
    t0 = time.time()
    samples, sample_rate = kokoro.create(script_text, voice=voice, speed=speed, lang=lang)
    t_tts = time.time() - t0
    print(f"  TTS done in {t_tts:.1f}s")

    # Convert to MP3 via a temporary WAV
    print(f"Converting to MP3 ({bitrate}) ...", flush=True)
    t0 = time.time()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = Path(tmp.name)
    try:
        sf.write(str(tmp_wav), samples, sample_rate)
        audio = AudioSegment.from_wav(str(tmp_wav))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        audio.export(str(output_path), format="mp3", bitrate=bitrate)
    finally:
        tmp_wav.unlink(missing_ok=True)
    t_mp3 = time.time() - t0

    duration_s = len(audio) / 1000.0
    size_bytes = output_path.stat().st_size
    t_total = time.time() - t_wall

    metrics = {
        "voice": voice,
        "speed": speed,
        "lang": lang,
        "word_count": word_count,
        "t_model_load_s": round(t_load, 1),
        "t_tts_s": round(t_tts, 1),
        "t_mp3_s": round(t_mp3, 1),
        "t_total_s": round(t_total, 1),
        "duration_s": round(duration_s, 1),
        "duration_formatted": format_duration(duration_s),
        "size_bytes": size_bytes,
        "size_kb": size_bytes // 1024,
        "sample_rate": sample_rate,
    }

    print(
        f"\nGeneration complete:\n"
        f"  Audio duration : {format_duration(duration_s)} ({duration_s:.1f}s)\n"
        f"  MP3 size       : {size_bytes // 1024} KB\n"
        f"  Total time     : {t_total:.1f}s"
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Database Daily episode MP3 using Kokoro TTS."
    )
    parser.add_argument(
        "--script-file",
        required=True,
        help="Path to plain-text file containing the episode script",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output MP3 file path",
    )
    parser.add_argument(
        "--voice",
        default="af_heart",
        help="Kokoro voice name (default: af_heart)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speech rate multiplier (default: 1.0)",
    )
    parser.add_argument(
        "--lang",
        default="en-us",
        help="BCP-47 language code (default: en-us)",
    )
    parser.add_argument(
        "--model",
        default="kokoro-v1.0.onnx",
        help="Path to kokoro-v1.0.onnx model file",
    )
    parser.add_argument(
        "--voices-bin",
        default="voices-v1.0.bin",
        help="Path to voices-v1.0.bin file",
    )
    parser.add_argument(
        "--bitrate",
        default="128k",
        help="MP3 bitrate (default: 128k)",
    )
    parser.add_argument(
        "--metrics-out",
        default=None,
        help="Optional path to write a JSON metrics file",
    )
    args = parser.parse_args()

    # Validate inputs before touching Kokoro
    script_file = Path(args.script_file)
    if not script_file.exists():
        print(f"ERROR: Script file not found: {script_file}", file=sys.stderr)
        sys.exit(1)

    script_text = script_file.read_text(encoding="utf-8").strip()
    if not script_text:
        print("ERROR: Script file is empty", file=sys.stderr)
        sys.exit(1)

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"ERROR: Kokoro model file not found: {model_path}", file=sys.stderr)
        print(
            "Download: https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0",
            file=sys.stderr,
        )
        sys.exit(1)

    voices_path = Path(args.voices_bin)
    if not voices_path.exists():
        print(f"ERROR: Voices file not found: {voices_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output)

    metrics = generate(
        script_text=script_text,
        output_path=output_path,
        model_path=model_path,
        voices_path=voices_path,
        voice=args.voice,
        speed=args.speed,
        lang=args.lang,
        bitrate=args.bitrate,
    )

    if args.metrics_out:
        metrics_path = Path(args.metrics_out)
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
        print(f"Metrics saved to {metrics_path}")


if __name__ == "__main__":
    main()
