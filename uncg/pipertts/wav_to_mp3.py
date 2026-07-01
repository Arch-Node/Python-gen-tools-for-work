from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


FFMPEG_DOWNLOAD_URL = "https://ffmpeg.org/download.html#build-windows"


def resolve_ffmpeg_executable(ffmpeg_bin: str = "ffmpeg") -> str | None:
    candidate = ffmpeg_bin.strip()
    if not candidate:
        candidate = "ffmpeg"

    # Explicit path provided.
    explicit_path = Path(candidate)
    if explicit_path.exists() and explicit_path.is_file():
        return str(explicit_path)

    # Resolve by PATH.
    from_path = shutil.which(candidate)
    if from_path:
        return from_path

    # Fallback for Windows installs created by install_ffmpeg.ps1.
    if os.name == "nt" and candidate.lower() == "ffmpeg":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        fallback = Path(local_app_data) / "ffmpeg" / "bin" / "ffmpeg.exe"
        if fallback.exists() and fallback.is_file():
            return str(fallback)

    return None


def convert_wav_to_mp3(
    input_wav: Path,
    output_mp3: Path,
    ffmpeg_bin: str = "ffmpeg",
    bitrate: str = "128k",
    overwrite: bool = False,
) -> Path:
    input_wav = Path(input_wav)
    output_mp3 = Path(output_mp3)

    if not input_wav.exists():
        raise FileNotFoundError(f"Input WAV file not found: {input_wav}")

    if input_wav.suffix.lower() != ".wav":
        raise ValueError("Input must be a .wav file.")

    if output_mp3.exists() and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {output_mp3}. Use --overwrite to replace it."
        )

    ffmpeg_path = resolve_ffmpeg_executable(ffmpeg_bin)
    if not ffmpeg_path:
        raise FileNotFoundError(
            "ffmpeg was not found on PATH. Install the latest Windows build from "
            f"{FFMPEG_DOWNLOAD_URL} or pass --ffmpeg-bin with the full path."
        )

    output_mp3.parent.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg_path,
        "-y" if overwrite else "-n",
        "-i",
        str(input_wav),
        "-codec:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        str(output_mp3),
    ]

    process = subprocess.run(command, capture_output=True, text=True)
    if process.returncode != 0:
        stderr_text = process.stderr.strip() or "No stderr output."
        raise RuntimeError(f"ffmpeg failed with code {process.returncode}: {stderr_text}")

    return output_mp3.resolve()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert WAV audio to MP3 using ffmpeg.")
    parser.add_argument("input", type=Path, help="Input WAV file path.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output MP3 path. Defaults to <input_stem>.mp3 in the same folder.",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="ffmpeg executable name or full path.",
    )
    parser.add_argument(
        "--bitrate",
        default="128k",
        help="Target MP3 bitrate, e.g. 96k, 128k, 192k.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output file if it already exists.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    output_path = args.output or args.input.with_suffix(".mp3")
    mp3_path = convert_wav_to_mp3(
        input_wav=args.input,
        output_mp3=output_path,
        ffmpeg_bin=args.ffmpeg_bin,
        bitrate=args.bitrate,
        overwrite=args.overwrite,
    )

    source_size = args.input.stat().st_size
    mp3_size = mp3_path.stat().st_size
    reduction = ((source_size - mp3_size) / source_size * 100) if source_size else 0

    print(f"MP3 generated: {mp3_path}")
    print(f"WAV size: {source_size:,} bytes")
    print(f"MP3 size: {mp3_size:,} bytes")
    print(f"Size reduction: {reduction:.1f}%")


if __name__ == "__main__":
    main()
