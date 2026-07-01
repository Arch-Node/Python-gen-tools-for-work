from __future__ import annotations

import argparse
import re
from pathlib import Path


def _normalize_inline(text: str) -> str:
	"""Convert inline markdown to plain speech-friendly text."""
	# Convert links and images to display text only.
	text = re.sub(r"!\[([^\]]*)\]\([^\)]*\)", r"\1", text)
	text = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", text)

	# Remove inline code markers and markdown emphasis markers.
	text = text.replace("`", "")
	text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
	text = re.sub(r"\*([^*]+)\*", r"\1", text)
	text = re.sub(r"__([^_]+)__", r"\1", text)
	text = re.sub(r"_([^_]+)_", r"\1", text)
	text = re.sub(r"~~([^~]+)~~", r"\1", text)

	# Remove escaped markdown punctuation used in source docs.
	text = re.sub(r"\\([#*_`>\-])", r"\1", text)

	# Remove raw HTML tags and normalize whitespace.
	text = re.sub(r"<[^>]+>", " ", text)
	text = re.sub(r"\s+", " ", text).strip()
	return text


def _ensure_sentence(text: str) -> str:
	if not text:
		return ""
	if text[-1] in ".!?:":
		return text
	return f"{text}."


def markdown_to_script(markdown: str, include_code_blocks: bool = False) -> str:
	"""Convert markdown content into narration-ready plain text."""
	output_lines: list[str] = []
	in_code_block = False

	for raw_line in markdown.splitlines():
		line = raw_line.rstrip()

		# Toggle fenced code block state.
		if line.lstrip().startswith("```"):
			in_code_block = not in_code_block
			if include_code_blocks:
				output_lines.append("Code block.")
			continue

		if in_code_block:
			if include_code_blocks:
				code_line = _normalize_inline(line)
				if code_line:
					output_lines.append(_ensure_sentence(code_line))
			continue

		stripped = line.strip()
		# Some markdown exporters escape control markers (for example: \# Heading).
		structure_line = re.sub(r"^\\([#>\-+*])", r"\1", stripped)
		if not stripped:
			output_lines.append("")
			continue

		# Horizontal rule.
		if re.fullmatch(r"[-*_]{3,}", structure_line):
			output_lines.append("")
			continue

		# Headers.
		header_match = re.match(r"^(#{1,6})\s+(.*)$", structure_line)
		if header_match:
			heading = _normalize_inline(header_match.group(2))
			if heading:
				output_lines.append("")
				output_lines.append(_ensure_sentence(heading))
				output_lines.append("")
			continue

		# Block quote.
		if structure_line.startswith(">"):
			quoted = _normalize_inline(structure_line.lstrip("> "))
			if quoted:
				output_lines.append(_ensure_sentence(quoted))
			continue

		# Unordered list.
		bullet_match = re.match(r"^[-*+]\s+(.*)$", structure_line)
		if bullet_match:
			item = _normalize_inline(bullet_match.group(1))
			if item:
				output_lines.append(_ensure_sentence(item))
			continue

		# Ordered list.
		ordered_match = re.match(r"^(\d+)\.\s+(.*)$", structure_line)
		if ordered_match:
			number = ordered_match.group(1)
			item = _normalize_inline(ordered_match.group(2))
			if item:
				output_lines.append(_ensure_sentence(f"Step {number}: {item}"))
			continue

		# Table formatting and alignment rows.
		if structure_line.startswith("|") and structure_line.endswith("|"):
			cells = [
				_normalize_inline(cell)
				for cell in structure_line.strip("|").split("|")
			]
			cells = [cell for cell in cells if cell]
			if cells and not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
				output_lines.append(_ensure_sentence(". ".join(cells)))
			continue

		# Fallback paragraph line.
		plain_line = _normalize_inline(structure_line)
		if plain_line:
			output_lines.append(_ensure_sentence(plain_line))

	# Remove duplicate blank lines for cleaner narration flow.
	cleaned_lines: list[str] = []
	previous_blank = False
	for line in output_lines:
		is_blank = not line.strip()
		if is_blank and previous_blank:
			continue
		cleaned_lines.append(line)
		previous_blank = is_blank

	return "\n".join(cleaned_lines).strip() + "\n"


def _build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description="Convert a Markdown file into narration-ready script text."
	)
	parser.add_argument("input", type=Path, help="Path to the input Markdown file.")
	parser.add_argument(
		"-o",
		"--output",
		type=Path,
		help="Output text path. Defaults to <input_stem>_script.txt in the same folder.",
	)
	parser.add_argument(
		"--include-code-blocks",
		action="store_true",
		help="Include fenced code blocks in output narration.",
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

	input_path: Path = args.input
	if not input_path.exists():
		raise FileNotFoundError(f"Input file not found: {input_path}")

	if input_path.suffix.lower() not in {".md", ".markdown"}:
		raise ValueError("Input must be a Markdown file with .md or .markdown extension.")

	output_path: Path = args.output or input_path.with_name(f"{input_path.stem}_script.txt")
	if output_path.exists() and not args.overwrite:
		raise FileExistsError(
			f"Output file already exists: {output_path}. Use --overwrite to replace it."
		)

	markdown_text = input_path.read_text(encoding="utf-8")
	script_text = markdown_to_script(markdown_text, include_code_blocks=args.include_code_blocks)
	output_path.write_text(script_text, encoding="utf-8")

	print(f"Script generated: {output_path.resolve()}")
	print(f"Characters: {len(script_text)}")


if __name__ == "__main__":
	main()
