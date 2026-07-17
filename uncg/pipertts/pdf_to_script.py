from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def _ensure_sentence(text: str) -> str:
    if not text:
        return ""
    if text[-1] in ".!?:":
        return text
    return f"{text}."


def _normalize_line(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def _ensure_pypdf_available(auto_install_pypdf: bool = True) -> None:
    try:
        import pypdf  # noqa: F401
    except ImportError as exc:
        if not auto_install_pypdf:
            raise RuntimeError(
                "Missing dependency: pypdf. Install with: pip install pypdf"
            ) from exc

        install_cmd = [sys.executable, "-m", "pip", "install", "pypdf"]
        process = subprocess.run(install_cmd, capture_output=True, text=True)
        if process.returncode != 0:
            stderr_text = process.stderr.strip() or "No stderr output."
            raise RuntimeError(
                "Missing dependency: pypdf. Automatic install failed. "
                f"Command: {' '.join(install_cmd)}. Error: {stderr_text}"
            ) from exc

        try:
            import pypdf  # noqa: F401
        except ImportError as second_exc:
            raise RuntimeError(
                "pypdf install command completed but package is still unavailable."
            ) from second_exc


def _extract_pdf_text(input_pdf: Path, auto_install_pypdf: bool = True) -> str:
    _ensure_pypdf_available(auto_install_pypdf=auto_install_pypdf)

    from pypdf import PdfReader

    reader = PdfReader(str(input_pdf))
    page_texts: list[str] = []
    for page in reader.pages:
        extracted = page.extract_text() or ""
        cleaned = extracted.replace("\r\n", "\n").replace("\r", "\n")
        page_texts.append(cleaned)

    return "\n\n".join(page_texts)


def pdf_text_to_script(raw_text: str, pause_between_items: bool = True) -> str:
    lines = raw_text.splitlines()
    output_lines: list[str] = []

    for line in lines:
        stripped = _normalize_line(line)
        if not stripped:
            output_lines.append("")
            continue

        # Handle bullet and numbered lines from extracted text.
        bullet = re.match(r"^[-*•]\s+(.*)$", stripped)
        if bullet:
            output_lines.append(_ensure_sentence(bullet.group(1)))
            if pause_between_items:
                output_lines.append("")
            continue

        numbered = re.match(r"^(\d+)[\.)]\s+(.*)$", stripped)
        if numbered:
            output_lines.append(_ensure_sentence(f"Step {numbered.group(1)}: {numbered.group(2)}"))
            if pause_between_items:
                output_lines.append("")
            continue

        output_lines.append(_ensure_sentence(stripped))

    cleaned_lines: list[str] = []
    previous_blank = False
    for line in output_lines:
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        cleaned_lines.append(line)
        previous_blank = is_blank

    script = "\n".join(cleaned_lines).strip()
    if not script:
        raise ValueError(
            "No extractable text found in PDF. If this is a scanned PDF, OCR is required first."
        )
    return script + "\n"


def pdf_to_script(
    input_pdf: Path,
    output_text: Path,
    pause_between_items: bool = True,
    auto_install_pypdf: bool = True,
    overwrite: bool = False,
) -> Path:
    input_pdf = Path(input_pdf)
    output_text = Path(output_text)

    if not input_pdf.exists():
        raise FileNotFoundError(f"Input file not found: {input_pdf}")
    if input_pdf.suffix.lower() != ".pdf":
        raise ValueError("Input must be a .pdf file.")
    if output_text.exists() and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {output_text}. Use --overwrite to replace it."
        )

    raw_text = _extract_pdf_text(
        input_pdf,
        auto_install_pypdf=auto_install_pypdf,
    )
    script_text = pdf_text_to_script(raw_text, pause_between_items=pause_between_items)

    output_text.parent.mkdir(parents=True, exist_ok=True)
    output_text.write_text(script_text, encoding="utf-8")
    return output_text.resolve()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a text-based PDF file to narration-ready script text."
    )
    parser.add_argument("input", type=Path, help="Path to the input PDF file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output text path. Defaults to <input_stem>_script.txt in the same folder.",
    )
    parser.add_argument(
        "--no-item-pauses",
        action="store_true",
        help="Disable extra pause spacing between bullet/numbered items.",
    )
    parser.add_argument(
        "--no-auto-install-pypdf",
        action="store_true",
        help="Disable automatic pypdf installation when missing.",
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

    output_path = args.output or args.input.with_name(f"{args.input.stem}_script.txt")
    created = pdf_to_script(
        input_pdf=args.input,
        output_text=output_path,
        pause_between_items=not args.no_item_pauses,
        auto_install_pypdf=not args.no_auto_install_pypdf,
        overwrite=args.overwrite,
    )
    print(f"Script generated: {created}")


if __name__ == "__main__":
    main()
