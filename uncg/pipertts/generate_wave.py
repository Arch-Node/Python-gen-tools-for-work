from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


DEFAULT_TEXT_FILE = Path("uncg/pipertts/narration_test.txt")
DEFAULT_OUTPUT_WAV = Path("uncg/pipertts/output.wav")
DEFAULT_PIPER_EXE = Path(
    "C:/Users/mrchartier/AppData/Local/Python/pythoncore-3.14-64/Scripts/piper.exe"
)
DEFAULT_VOICE_MODEL = Path("C:/software/pipertts/models/en_US-lessac-medium.onnx")
DEFAULT_LENGTH_SCALE = 1.15


def generate_wav(
    text_file: Path,
    output_wav: Path,
    piper_exe: Path,
    voice_model: Path,
    length_scale: float = DEFAULT_LENGTH_SCALE,
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
    if length_scale <= 0:
        raise ValueError("length_scale must be greater than 0.")

    output_wav.parent.mkdir(parents=True, exist_ok=True)

    process = subprocess.run(
        [
            str(piper_exe),
            "--model",
            str(voice_model),
            "--text",
            narration,
            "--output_file",
            str(output_wav),
            "--length_scale",
            str(length_scale),
        ],
        capture_output=True,
        text=True,
    )

    if process.returncode != 0:
        stderr_text = process.stderr.strip() or "No stderr output."
        raise RuntimeError(f"Piper failed with code {process.returncode}: {stderr_text}")

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
    )

    print(f"Audio generated successfully: {wav_path}")


if __name__ == "__main__":
    main()