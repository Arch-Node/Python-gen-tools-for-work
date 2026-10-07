from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

from md_2_script import markdown_to_script
from generate_wave import (
    DEFAULT_LENGTH_SCALE,
    DEFAULT_PIPER_EXE,
    DEFAULT_VOICE_MODEL,
    generate_wav,
)
from pdf_to_script import pdf_to_script
from wav_to_mp3 import FFMPEG_DOWNLOAD_URL, convert_wav_to_mp3


def _clean_path_input(raw: str) -> str:
    value = raw.strip()
    # Support pasted paths wrapped in single or double quotes.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    return value


def _ask_path(prompt: str, default: Path | None = None) -> Path:
    suffix = f" [{default}]" if default else ""
    raw = _clean_path_input(input(f"{prompt}{suffix}: "))
    if not raw and default:
        return Path(default)
    if not raw:
        raise ValueError("A value is required.")
    return Path(raw)


def _piper_downloader_python(piper_exe: Path) -> Path:
    candidates = [
        Path(sys.executable),
        piper_exe.parent.parent / "python.exe",
    ]
    checked: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in checked or not candidate.is_file():
            continue
        checked.add(candidate)
        check = subprocess.run(
            [str(candidate), "-c", "import piper.download_voices"],
            capture_output=True,
            text=True,
        )
        if check.returncode == 0:
            return candidate

    raise RuntimeError(
        "Could not find Python with Piper installed. Install piper-tts in the "
        "active environment or beside the configured Piper executable."
    )


def _choose_voice_model(piper_exe: Path) -> Path:
    default_voice = DEFAULT_VOICE_MODEL.stem.rsplit("-", 1)[0]
    available_qualities = {
        "en_GB-cori": ("medium", "high"),
    }.get(default_voice)
    if not available_qualities:
        raise RuntimeError(f"No quality options are configured for {default_voice}.")

    default_quality = DEFAULT_VOICE_MODEL.stem.rsplit("-", 1)[1]
    choices = "/".join(available_qualities)
    while True:
        selected = input(f"Voice quality ({choices}) [{default_quality}]: ").strip().lower()
        quality = selected or default_quality
        if quality in available_qualities:
            break
        print(f"Choose one of the available qualities: {choices}.")

    model_path = DEFAULT_VOICE_MODEL.with_name(f"{default_voice}-{quality}.onnx")
    config_path = model_path.with_suffix(model_path.suffix + ".json")
    if not model_path.is_file() or not config_path.is_file():
        downloader_python = _piper_downloader_python(piper_exe)
        voice_name = f"{default_voice}-{quality}"
        print(f"Downloading Piper voice: {voice_name}")
        process = subprocess.run(
            [
                str(downloader_python),
                "-m",
                "piper.download_voices",
                voice_name,
                "--download-dir",
                str(model_path.parent),
            ],
            capture_output=True,
            text=True,
        )
        if process.stdout.strip():
            print(process.stdout.strip())
        if process.returncode != 0:
            details = process.stderr.strip() or "No error details were returned."
            raise RuntimeError(f"Piper voice download failed: {details}")
        if not model_path.is_file() or not config_path.is_file():
            raise RuntimeError(f"Voice download did not create model and config for {voice_name}.")

    return model_path


def _run_md_to_txt() -> Path:
    md_path = _ask_path("Markdown input")
    txt_default = md_path.with_name(f"{md_path.stem}_script.txt")
    txt_path = _ask_path("Text output", txt_default)

    markdown = md_path.read_text(encoding="utf-8")
    script = markdown_to_script(markdown)
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text(script, encoding="utf-8")
    print(f"Created script text: {txt_path.resolve()}")
    return txt_path


def _run_pdf_to_txt() -> Path:
    pdf_path = _ask_path("PDF input")
    txt_default = pdf_path.with_name(f"{pdf_path.stem}_script.txt")
    txt_path = _ask_path("Text output", txt_default)

    created = pdf_to_script(
        input_pdf=pdf_path,
        output_text=txt_path,
        pause_between_items=True,
        overwrite=True,
    )
    print(f"Created script text: {created}")
    return Path(created)


def _run_txt_to_wav(default_txt: Path | None = None) -> Path:
    txt_path = _ask_path("Text input", default_txt)
    wav_default = txt_path.with_suffix(".wav")
    wav_path = _ask_path("WAV output", wav_default)

    piper_exe = _ask_path("Piper executable", DEFAULT_PIPER_EXE)
    voice_model = _choose_voice_model(piper_exe)
    length_scale_raw = input(
        f"Speech slowdown / length scale [{DEFAULT_LENGTH_SCALE}]: "
    ).strip()
    length_scale = float(length_scale_raw) if length_scale_raw else DEFAULT_LENGTH_SCALE

    created = generate_wav(
        text_file=txt_path,
        output_wav=wav_path,
        piper_exe=piper_exe,
        voice_model=voice_model,
        length_scale=length_scale,
    )
    print(f"Created WAV: {created}")
    return Path(created)


def _run_wav_to_mp3(default_wav: Path | None = None) -> Path:
    wav_path = _ask_path("WAV input", default_wav)
    mp3_default = wav_path.with_suffix(".mp3")
    mp3_path = _ask_path("MP3 output", mp3_default)

    bitrate = input("MP3 bitrate [128k]: ").strip() or "128k"
    ffmpeg_bin = _clean_path_input(input("ffmpeg executable [ffmpeg]: ")) or "ffmpeg"

    created = convert_wav_to_mp3(
        input_wav=wav_path,
        output_mp3=mp3_path,
        ffmpeg_bin=ffmpeg_bin,
        bitrate=bitrate,
        overwrite=True,
    )
    print(f"Created MP3: {created}")
    return Path(created)


def _run_install_ffmpeg() -> None:
    if platform.system().lower() != "windows":
        print("FFmpeg installer script is currently set up for Windows only.")
        print(f"Download FFmpeg here: {FFMPEG_DOWNLOAD_URL}")
        return

    script_path = Path(__file__).with_name("install_ffmpeg.ps1")
    if not script_path.exists():
        print(f"Installer script not found: {script_path}")
        return

    print("Running FFmpeg installer script...")
    process = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-OpenNewTerminal",
        ],
        capture_output=True,
        text=True,
    )

    if process.stdout.strip():
        print(process.stdout.strip())
    if process.returncode != 0:
        if process.stderr.strip():
            print(process.stderr.strip())
        raise RuntimeError("FFmpeg install script failed.")

    # Keep this Python process in sync so option 3 works immediately.
    installed_bin = Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg" / "bin"
    if installed_bin.exists() and str(installed_bin) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{installed_bin};{os.environ.get('PATH', '')}"

    print("FFmpeg install script completed.")


def _run_full_pipeline() -> None:
    txt_path = _run_md_to_txt()
    wav_path = _run_txt_to_wav(default_txt=txt_path)
    _run_wav_to_mp3(default_wav=wav_path)


def _run_pdf_full_pipeline() -> None:
    txt_path = _run_pdf_to_txt()
    wav_path = _run_txt_to_wav(default_txt=txt_path)
    _run_wav_to_mp3(default_wav=wav_path)


def main() -> None:
    options = {
        "1": ("Markdown -> Script text", _run_md_to_txt),
        "2": ("Script text -> WAV", _run_txt_to_wav),
        "3": ("WAV -> MP3", _run_wav_to_mp3),
        "4": ("Run full pipeline (Markdown)", _run_full_pipeline),
        "5": ("Install/Update FFmpeg (Windows)", _run_install_ffmpeg),
        "6": ("PDF -> Script text", _run_pdf_to_txt),
        "7": ("Run full pipeline (PDF)", _run_pdf_full_pipeline),
        "q": ("Quit", None),
    }

    while True:
        print("\nMD/TTS Pipeline Menu")
        for key, (label, _) in options.items():
            print(f"  {key}. {label}")

        try:
            choice = input("Select option: ").strip().lower()
        except EOFError:
            print("Done.")
            return
        if choice == "q":
            print("Done.")
            return

        if choice not in options:
            print("Invalid option.")
            continue

        _, handler = options[choice]
        try:
            if handler:
                handler()
        except Exception as exc:
            print(f"Error: {exc}")
            if "ffmpeg was not found" in str(exc).lower():
                print(f"Download FFmpeg: {FFMPEG_DOWNLOAD_URL}")
                print(
                    "Or run menu option 5 to download and install FFmpeg and update PATH."
                )


if __name__ == "__main__":
    main()
