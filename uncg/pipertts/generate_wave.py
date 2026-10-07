from __future__ import annotations

import argparse
import math
import re
import subprocess
import tempfile
import wave
from pathlib import Path


DEFAULT_TEXT_FILE = Path("uncg/pipertts/narration_test.txt")
DEFAULT_OUTPUT_WAV = Path("uncg/pipertts/output.wav")
DEFAULT_PIPER_EXE = Path(
    "C:/Users/mrchartier/AppData/Local/Python/pythoncore-3.14-64/Scripts/piper.exe"
)
DEFAULT_VOICE_MODEL = Path("C:/software/pipertts/models/en_GB-cori-high.onnx")
DEFAULT_LENGTH_SCALE = 1.15
DEFAULT_SENTENCE_SILENCE = 1.2
DEFAULT_PARAGRAPH_SILENCE = 2.7


def generate_wav(
    text_file: Path,
    output_wav: Path,
    piper_exe: Path,
    voice_model: Path,
    length_scale: float = DEFAULT_LENGTH_SCALE,
    sentence_silence: float = DEFAULT_SENTENCE_SILENCE,
    paragraph_silence: float = DEFAULT_PARAGRAPH_SILENCE,
) -> Path:
    text_file = Path(text_file)
    output_wav = Path(output_wav)
    piper_exe = Path(piper_exe)
    voice_model = Path(voice_model)

    if not text_file.exists():
        raise FileNotFoundError(f"Input text file not found: {text_file}")
    if not piper_exe.exists():
        raise FileNotFoundError(f"Piper executable not found: {piper_exe}")
    if not voice_model.exists():
        raise FileNotFoundError(f"Voice model file not found: {voice_model}")

    narration = text_file.read_text(encoding="utf-8").strip()
    if not narration:
        raise ValueError("Input text file is empty.")
    if not math.isfinite(length_scale) or length_scale <= 0:
        raise ValueError("length_scale must be greater than 0.")
    if any(not math.isfinite(value) or value < 0 for value in (sentence_silence, paragraph_silence)):
        raise ValueError("Pause durations must be finite, non-negative seconds.")

    output_wav.parent.mkdir(parents=True, exist_ok=True)

    paragraphs = re.split(r"\n\s*\n", narration)
    with tempfile.TemporaryDirectory() as temp_dir:
        combined_path = Path(temp_dir) / "combined.wav"
        with wave.open(str(combined_path), "wb") as combined:
            audio_format = None
            for index, paragraph in enumerate(paragraphs):
                text_path = Path(temp_dir) / "paragraph.txt"
                chunk_path = Path(temp_dir) / "paragraph.wav"
                text_path.write_text(" ".join(paragraph.split()), encoding="utf-8")
                process = subprocess.run(
                    [
                        str(piper_exe),
                        "--model", str(voice_model),
                        "--input-file", str(text_path),
                        "--output-file", str(chunk_path),
                        "--length-scale", str(length_scale),
                        "--sentence-silence", str(sentence_silence),
                    ],
                    capture_output=True,
                    text=True,
                )
                if process.returncode != 0:
                    stderr_text = process.stderr.strip() or "No stderr output."
                    raise RuntimeError(f"Piper failed with code {process.returncode}: {stderr_text}")
                with wave.open(str(chunk_path), "rb") as chunk:
                    chunk_format = (chunk.getnchannels(), chunk.getsampwidth(), chunk.getframerate())
                    if audio_format is None:
                        audio_format = chunk_format
                        combined.setnchannels(chunk_format[0])
                        combined.setsampwidth(chunk_format[1])
                        combined.setframerate(chunk_format[2])
                    elif chunk_format != audio_format:
                        raise RuntimeError("Piper produced incompatible WAV formats between paragraphs.")
                    if index:
                        silent_frames = round(paragraph_silence * chunk_format[2])
                        silent_sample = b"\x80" if chunk_format[1] == 1 else b"\x00" * chunk_format[1]
                        combined.writeframes(silent_sample * chunk_format[0] * silent_frames)
                    combined.writeframes(chunk.readframes(chunk.getnframes()))
        output_wav.write_bytes(combined_path.read_bytes())

    return output_wav.resolve()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a WAV file from narration text using Piper."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_TEXT_FILE,
        help="Input text file path.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_WAV,
        help="Output WAV path.",
    )
    parser.add_argument(
        "--piper-exe",
        type=Path,
        default=DEFAULT_PIPER_EXE,
        help="Path to piper executable.",
    )
    parser.add_argument(
        "--voice-model",
        type=Path,
        default=DEFAULT_VOICE_MODEL,
        help="Path to Piper ONNX voice model.",
    )
    parser.add_argument(
        "--length-scale",
        type=float,
        default=DEFAULT_LENGTH_SCALE,
        help="Speech speed scale for Piper (higher is slower). Default is slightly slower.",
    )
    parser.add_argument(
        "--sentence-silence", type=float, default=DEFAULT_SENTENCE_SILENCE,
        help="Seconds of added silence after each sentence (default: 1.2).",
    )
    parser.add_argument(
        "--paragraph-silence", type=float, default=DEFAULT_PARAGRAPH_SILENCE,
        help="Seconds of added silence between paragraphs/headings (default: 2.7).",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    wav_path = generate_wav(
        text_file=args.input,
        output_wav=args.output,
        piper_exe=args.piper_exe,
        voice_model=args.voice_model,
        length_scale=args.length_scale,
        sentence_silence=args.sentence_silence,
        paragraph_silence=args.paragraph_silence,
    )

    print(f"Audio generated successfully: {wav_path}")


if __name__ == "__main__":
    main()