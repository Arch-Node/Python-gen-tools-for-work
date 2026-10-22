"""
Pseudo-code overview
--------------------
1. Parse three input file paths and an output HTML path.
2. Read each file using a fallback encoding strategy.
3. Normalize line endings and capture each file as a snapshot.
4. For NSC EDI files, treat each `ST ... SE` region as one student block.
5. Normalize known bookkeeping fields so report dates, control numbers, and
     segment counts do not create false differences.
6. Compare each file pair to measure similarity and changed blocks.
7. Compare student blocks by Banner ID and split students into:
     - no change
     - only in original
     - substantive differences
8. For students with differences, align repeated `SES ... NTE` subsections by
     their contained program line before rendering row-by-row differences.
9. Count lines shared by all three files and lines unique to each file.
10. Build a digestible HTML report with:
  - file summary cards
  - pairwise comparison cards
    - student summary buckets (`No Change`, `Only In Original`)
  - unique-line examples
    - student detail sections for substantive differences only
    - detailed pairwise HTML diffs
11. Write the final HTML report to disk.

Example
-------
python three_file_diff_report.py before.txt after.txt alternate.txt -o diff_report.html \
  --labels Before After Alternate
"""

from __future__ import annotations

import argparse
import difflib
import html
import re
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Sequence, Tuple


LARGE_FILE_LINE_THRESHOLD = 50_000
DIFF_BLOCK_CONTEXT_LINES = 2
MAX_RENDERED_BLOCKS = 80
MAX_RENDERED_LINES_PER_BLOCK = 60
STUDENT_DETAIL_CONTEXT_LINES = 1
MAX_RENDERED_STUDENT_DETAIL_ROWS = 160
TRAILING_DATE_PATTERN = re.compile(r"(?:\|D8\|\d{8}|\|\d{8})+$")
CONTROL_NUMBER_TOKEN = "<control-number>"
REPORT_DATE_TOKEN = "<report-date>"
REPORT_TIME_TOKEN = "<report-time>"


def read_text_guess_encoding(path: Path) -> str:
    """Read a text file using a small set of common encodings."""
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def normalize_lines(text: str) -> List[str]:
    """Normalize Windows and legacy newlines before line-based diffing."""
    return text.replace("\r\n", "\n").replace("\r", "\n").splitlines()


@dataclass(frozen=True)
class FileSnapshot:
    label: str
    path: Path
    text: str
    lines: List[str]

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size


@dataclass(frozen=True)
class PairwiseStats:
    left_label: str
    right_label: str
    equal_lines: int
    inserted_lines: int
    deleted_lines: int
    replaced_left_lines: int
    replaced_right_lines: int
    changed_blocks: int
    similarity_ratio: float
    comparison_mode: str


@dataclass(frozen=True)
class DiffBlock:
    start_index: int
    end_index: int


@dataclass(frozen=True)
class StudentDifference:
    banner_id: str
    summary: str
    statuses: dict[str, str]
    blocks: dict[str, str | None]


@dataclass(frozen=True)
class StudentBlockAnalysis:
    file_student_counts: dict[str, int]
    total_distinct_students: int
    matching_students: int
    unchanged_student_ids: List[str]
    original_only_student_ids: List[str]
    differing_students: List[StudentDifference]


@dataclass(frozen=True)
class StudentLineDifference:
    line_number: int
    values: dict[str, str]


@dataclass(frozen=True)
class StudentBlockRow:
    values: dict[str, str]
    anchor_line_number: int | None


def build_snapshot(path_text: str, label: str) -> FileSnapshot:
    """Resolve a file path and capture the text and normalized lines once."""
    path = Path(path_text).expanduser().resolve()
    text = read_text_guess_encoding(path)
    return FileSnapshot(label=label, path=path, text=text, lines=normalize_lines(text))


def use_large_file_mode(*files: FileSnapshot) -> bool:
    """Switch to a linear comparison path when inputs are too large for HtmlDiff."""
    return max(file.line_count for file in files) > LARGE_FILE_LINE_THRESHOLD


def parse_edi_text(content: str) -> Tuple[List[str], str]:
    """Parse an NSC-style EDI payload into raw segments and discover the element separator."""
    isa_start = content.find("ISA")
    if isa_start < 0:
        raise ValueError("ISA segment not found")

    content = content[isa_start:]
    elem_sep = content[3]
    content_clean = content.replace("\r", "")

    if content_clean.count("\n") > 1:
        segments = [segment.strip() for segment in content_clean.split("\n") if segment.strip()]
        return segments, elem_sep

    isa_parts = content.split(elem_sep, 16)
    if len(isa_parts) <= 16 or not isa_parts[16]:
        raise ValueError("Could not determine ISA16 / segment terminator")

    isa16_and_tail = isa_parts[16]
    seg_term = isa16_and_tail[1] if len(isa16_and_tail) > 1 else isa16_and_tail[0]
    splitter = "\n" if seg_term in {"\r", "\n"} else seg_term
    segments = [segment.strip() for segment in content_clean.split(splitter) if segment.strip()]
    return segments, elem_sep


def split_elems(seg_raw: str, elem_sep: str) -> List[str]:
    """Split one raw EDI segment into elements."""
    return seg_raw.split(elem_sep)


def join_elems(elems: Sequence[str], elem_sep: str) -> str:
    """Reassemble one parsed EDI segment."""
    return elem_sep.join(elems)


def group_transaction_sets(segments_raw: Sequence[str], elem_sep: str) -> List[List[List[str]]]:
    """Reuse NSC grouping logic where each ST..SE transaction set is one student block."""
    skip = {"ISA", "GS", "GE", "IEA"}
    txs: List[List[List[str]]] = []
    current: List[List[str]] = []
    in_tx = False

    for seg_raw in segments_raw:
        elems = split_elems(seg_raw, elem_sep)
        tag = elems[0]

        if tag in skip:
            continue

        if tag == "ST":
            if in_tx and current:
                txs.append(current)
            current = [elems]
            in_tx = True
            continue

        if not in_tx:
            current = [elems]
            in_tx = True
        else:
            current.append(elems)

        if tag == "SE":
            txs.append(current)
            current = []
            in_tx = False

    if in_tx and current:
        txs.append(current)

    return txs


def find_banner_id(tx: Sequence[Sequence[str]]) -> str | None:
    """Extract Banner ID from ENT by locating S2|93|<banner_id>."""
    for seg in tx:
        if not seg or seg[0] != "ENT":
            continue
        for index in range(1, len(seg) - 2):
            if seg[index] == "S2" and seg[index + 1] == "93":
                banner_id = seg[index + 2].strip()
                return banner_id or None
    return None


def render_transaction_set(tx: Sequence[Sequence[str]], elem_sep: str) -> str:
    """Normalize one ST..SE student block back into a comparable string block."""
    return "\n".join(join_elems(seg, elem_sep) for seg in tx)


def extract_student_blocks(snapshot: FileSnapshot) -> dict[str, str]:
    """Map Banner ID to one normalized ST..SE student block for EDI files."""
    segments_raw, elem_sep = parse_edi_text(snapshot.text)
    txs = group_transaction_sets(segments_raw, elem_sep)
    student_blocks: dict[str, str] = {}

    for tx in txs:
        banner_id = find_banner_id(tx)
        if not banner_id:
            continue

        tx_text = render_transaction_set(tx, elem_sep)
        if banner_id in student_blocks:
            student_blocks[banner_id] = student_blocks[banner_id] + "\n\n--- DUPLICATE TRANSACTION ---\n\n" + tx_text
        else:
            student_blocks[banner_id] = tx_text

    return student_blocks


def build_student_statuses(file_labels: Sequence[str], blocks_by_label: dict[str, str | None]) -> dict[str, str]:
    """Assign matching block labels so equal student blocks share the same status."""
    statuses: dict[str, str] = {}
    block_groups: dict[str, str] = {}
    next_group_number = 1

    for label in file_labels:
        block = blocks_by_label.get(label)
        if block is None:
            statuses[label] = "Missing"
            continue

        group_name = block_groups.get(block)
        if group_name is None:
            group_name = f"Block {next_group_number}"
            block_groups[block] = group_name
            next_group_number += 1
        statuses[label] = group_name

    return statuses


def join_labels_naturally(labels: Sequence[str]) -> str:
    """Join file labels into a readable English list."""
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return f"{', '.join(labels[:-1])}, and {labels[-1]}"


def summarize_student_variation(statuses: dict[str, str]) -> str:
    """Describe which files match for one student block and which are missing."""
    grouped: dict[str, List[str]] = {}
    missing: List[str] = []

    for label, status in statuses.items():
        if status == "Missing":
            missing.append(label)
            continue
        grouped.setdefault(status, []).append(label)

    summary_parts: List[str] = []
    matching_groups = [labels for labels in grouped.values() if len(labels) > 1]
    single_labels = [labels[0] for labels in grouped.values() if len(labels) == 1]

    if len(grouped) > 1 and len(single_labels) == len(grouped) and not missing:
        summary_parts.append(f"Different in {join_labels_naturally(single_labels)}")
    else:
        for labels in matching_groups:
            summary_parts.append(f"Same in {join_labels_naturally(labels)}")
        if single_labels:
            summary_parts.append(f"Different in {join_labels_naturally(single_labels)}")

    if missing:
        summary_parts.append(f"Not found in {join_labels_naturally(missing)}")

    return "; ".join(summary_parts)


def normalize_st_se_control_number(line: str) -> str:
    """Ignore ST/SE bookkeeping fields when comparing student blocks."""
    elems = line.split("|")
    if elems and elems[0] == "ST" and len(elems) > 2:
        elems[2] = CONTROL_NUMBER_TOKEN
    if elems and elems[0] == "SE":
        if len(elems) > 1:
            elems[1] = "<segment-count>"
        if len(elems) > 2:
            elems[2] = CONTROL_NUMBER_TOKEN
    return "|".join(elems)


def normalize_report_runtime_fields(line: str) -> str:
    """Ignore known BGN/SES values that vary based on when the report was run."""
    elems = line.split("|")
    if not elems:
        return line

    if elems[0] == "BGN":
        if len(elems) > 2:
            elems[2] = CONTROL_NUMBER_TOKEN
        if len(elems) > 3:
            elems[3] = REPORT_DATE_TOKEN
        if len(elems) > 4:
            elems[4] = REPORT_TIME_TOKEN
    elif elems[0] == "SES" and len(elems) > 1:
        elems[1] = REPORT_DATE_TOKEN
    elif elems[0] == "ENR" and len(elems) > 1 and elems[1] == "UN":
        if len(elems) > 0 and re.fullmatch(r"\d{8}", elems[-1] or ""):
            elems[-1] = REPORT_DATE_TOKEN

    return "|".join(elems)


def normalize_trailing_dates(line: str) -> str:
    """Remove trailing date tokens so date-only differences can be ignored."""
    return TRAILING_DATE_PATTERN.sub("", line).rstrip("|")


def normalize_comparison_line(line: str) -> str:
    """Normalize a line for comparison-only logic.

    This ignores known non-substantive differences:
    - ST/SE control numbers, which vary by file position
    - BGN runtime date/time fields
    - SES report date fields
    - trailing end-of-line dates
    """
    normalized_line = normalize_st_se_control_number(line)
    normalized_line = normalize_report_runtime_fields(normalized_line)
    return normalize_trailing_dates(normalized_line)


def normalize_student_block(block: str | None) -> str | None:
    """Normalize an entire student block for equivalence checks across files."""
    if block is None:
        return None
    return "\n".join(normalize_comparison_line(line) for line in block.splitlines())


def build_student_line_differences(blocks: dict[str, str | None], file_labels: Sequence[str]) -> List[StudentLineDifference]:
    """Return line-level differences after removing trailing date-only changes."""
    line_lists = {
        label: (blocks.get(label) or "").splitlines()
        for label in file_labels
    }
    max_len = max((len(lines) for lines in line_lists.values()), default=0)
    differences: List[StudentLineDifference] = []

    for index in range(max_len):
        rendered_values = {
            label: (line_lists[label][index] if index < len(line_lists[label]) else "")
            for label in file_labels
        }
        normalized_values = {
            label: normalize_comparison_line(value)
            for label, value in rendered_values.items()
        }
        if len(set(normalized_values.values())) <= 1:
            continue
        differences.append(StudentLineDifference(line_number=index + 1, values=rendered_values))

    return differences


def line_tag(line: str) -> str:
    """Return the segment tag at the start of an EDI line."""
    return line.split("|", 1)[0] if line else ""


def find_next_tag(tags: Sequence[str], start_index: int, target_tag: str) -> int | None:
    """Find the next occurrence of a segment tag from a given position."""
    for index in range(start_index, len(tags)):
        if tags[index] == target_tag:
            return index
    return None


def find_next_matching_line(
    normalized_lines: Sequence[str],
    tags: Sequence[str],
    start_index: int,
    target_line: str,
    target_tag: str,
) -> int | None:
    """Find the next line with both the same tag and the same normalized content."""
    for index in range(start_index, len(normalized_lines)):
        if tags[index] == target_tag and normalized_lines[index] == target_line:
            return index
    return None


def find_next_matching_value(values: Sequence[str], start_index: int, target_value: str) -> int | None:
    """Find the next matching value in a normalized sequence."""
    for index in range(start_index, len(values)):
        if values[index] == target_value:
            return index
    return None


def is_detail_section_start(line: str) -> bool:
    """Return whether a line starts a repeated detail section to compare as a unit."""
    return line_tag(line) == "SES" and len(line.split("|")) > 2


def is_summary_ses_line(line: str) -> bool:
    """Return whether a line is the summary SES line for the whole student block."""
    return line_tag(line) == "SES" and len(line.split("|")) <= 2


def is_prefix_program_line(line: str) -> bool:
    """Return whether a line is a summary-level FOS|M major row."""
    elems = line.split("|")
    return len(elems) > 4 and elems[0] == "FOS" and elems[1] == "M"


def split_student_block_sections(
    lines: Sequence[str],
) -> Tuple[List[Tuple[int, str]], List[List[Tuple[int, str]]], List[Tuple[int, str]]]:
    """Split a student block into prefix, repeated detail sections, and suffix.

    Each repeated detail section starts at a detailed `SES` line and continues
    until the next detailed `SES` or the transaction-set trailer `SE`.
    """
    prefix: List[Tuple[int, str]] = []
    sections: List[List[Tuple[int, str]]] = []
    suffix: List[Tuple[int, str]] = []
    current_section: List[Tuple[int, str]] = []
    pending_section_prefix: List[Tuple[int, str]] = []
    seen_first_section = False
    inside_transaction = False
    seen_summary_ses = False

    for line_number, line in enumerate(lines, start=1):
        entry = (line_number, line)
        tag = line_tag(line)

        if tag == "ST":
            inside_transaction = True
            prefix.append(entry)
            continue

        if not inside_transaction:
            prefix.append(entry)
            continue

        if is_detail_section_start(line):
            if current_section:
                sections.append(current_section)
            current_section = [*pending_section_prefix, entry]
            pending_section_prefix = []
            seen_first_section = True
            continue

        if tag == "SE":
            if current_section:
                sections.append(current_section)
                current_section = []
            elif pending_section_prefix:
                suffix.extend(pending_section_prefix)
                pending_section_prefix = []
            suffix.append(entry)
            inside_transaction = False
            continue

        if is_summary_ses_line(line) and not seen_first_section:
            seen_summary_ses = True
            prefix.append(entry)
            continue

        if not seen_first_section:
            if seen_summary_ses:
                if is_prefix_program_line(line):
                    prefix.append(entry)
                    continue
                pending_section_prefix.append(entry)
                continue
            prefix.append(entry)
            continue

        if current_section:
            current_section.append(entry)
        else:
            suffix.append(entry)

    if current_section:
        sections.append(current_section)
    elif pending_section_prefix:
        suffix.extend(pending_section_prefix)

    return prefix, sections, suffix


def normalize_section_entries(entries: Sequence[Tuple[int, str]]) -> str:
    """Normalize a detail section into one comparable value."""
    return "\n".join(normalize_comparison_line(line) for _, line in entries)


def build_prefix_program_name_map(entries: Sequence[Tuple[int, str]]) -> dict[str, str]:
    """Map summary FOS codes to their descriptive program names within one student block."""
    program_names: dict[str, str] = {}
    for _, line in entries:
        elems = line.split("|")
        if len(elems) > 4 and elems[0] == "FOS" and elems[1] == "M":
            program_code = elems[3].strip()
            program_name = elems[4].strip()
            if program_code and program_name:
                program_names[program_code] = program_name
    return program_names


def prefix_alignment_key(line: str) -> str:
    """Return a semantic alignment key for non-section lines in the student prefix."""
    elems = line.split("|")
    if len(elems) > 4 and elems[0] == "FOS" and elems[1] == "M":
        return f"FOSM|{elems[4].strip().casefold()}"
    return normalize_comparison_line(line)


def section_alignment_key(entries: Sequence[Tuple[int, str]]) -> str:
    """Return the best key for aligning a repeated SES..NTE section.

    Prefer the detailed program line so major/program changes match the
    correct subsection even when a new subsection was inserted ahead of it.
    """
    for _, line in entries:
        elems = line.split("|")
        if len(elems) > 3 and elems[0] == "FOS" and elems[1] == "P":
            return normalize_comparison_line(line)

    for _, line in entries:
        if line_tag(line) == "FOS":
            return normalize_comparison_line(line)

    return normalize_section_entries(entries)


def section_program_key(entries: Sequence[Tuple[int, str]], program_names_by_code: dict[str, str]) -> str:
    """Return a stable dataset key for a repeated detail section.

    Prefer the descriptive program name from the summary `FOS|M|...` lines.
    This keeps sections aligned when the `FOS|P` CIPC code changed but the
    program name still identifies the same academic program.
    """
    for _, line in entries:
        elems = line.split("|")
        if len(elems) > 3 and elems[0] == "FOS" and elems[1] == "P":
            program_code = elems[3].strip()
            program_name = program_names_by_code.get(program_code)
            if program_name:
                return f"NAME|{program_name.casefold()}"
            if program_code:
                return f"P|{program_code}"

    for _, line in entries:
        elems = line.split("|")
        if len(elems) > 3 and elems[0] == "FOS":
            return f"{elems[1]}|{elems[3]}"

    return section_alignment_key(entries)


def section_identity(entries: Sequence[Tuple[int, str]], program_names_by_code: dict[str, str]) -> Tuple[str | None, str | None]:
    """Extract comparable identifiers for a repeated detail section.

    Match by exact FOS|P program code when possible. If the program code changed,
    fall back to the descriptive program name from the summary FOS|M rows.
    """
    for _, line in entries:
        elems = line.split("|")
        if len(elems) > 3 and elems[0] == "FOS" and elems[1] == "P":
            program_code = elems[3].strip() or None
            program_name = program_names_by_code.get(program_code or "")
            return program_code, program_name.casefold() if program_name else None
    return None, None


def find_matching_section_index(
    target_identity: Tuple[str | None, str | None],
    candidate_identities: Sequence[Tuple[str | None, str | None]],
    used_indices: set[int],
) -> int | None:
    """Find the best unmatched section by code first, then by program name."""
    target_code, target_name = target_identity

    if target_code:
        for index, (candidate_code, _) in enumerate(candidate_identities):
            if index not in used_indices and candidate_code == target_code:
                return index

    if target_name:
        for index, (_, candidate_name) in enumerate(candidate_identities):
            if index not in used_indices and candidate_name == target_name:
                return index

    return None


def build_section_index_map(section_keys: Sequence[str]) -> dict[str, deque[int]]:
    """Map each section key to the source indices where it occurs."""
    index_map: dict[str, deque[int]] = {}
    for index, key in enumerate(section_keys):
        index_map.setdefault(key, deque()).append(index)
    return index_map


def pop_matching_section(section_map: dict[str, deque[int]], section_key: str) -> int | None:
    """Pop the next remaining section index for a given key."""
    indices = section_map.get(section_key)
    if not indices:
        return None
    match_index = indices.popleft()
    if not indices:
        del section_map[section_key]
    return match_index


def build_exact_alignment(source_values: Sequence[str], anchor_values: Sequence[str]) -> List[Tuple[int | None, int | None]]:
    """Align two normalized sequences by exact content with lookahead for inserted sections."""
    aligned_pairs: List[Tuple[int | None, int | None]] = []
    source_index = 0
    anchor_index = 0

    while source_index < len(source_values) or anchor_index < len(anchor_values):
        if source_index >= len(source_values):
            aligned_pairs.append((None, anchor_index))
            anchor_index += 1
            continue

        if anchor_index >= len(anchor_values):
            aligned_pairs.append((source_index, None))
            source_index += 1
            continue

        if source_values[source_index] == anchor_values[anchor_index]:
            aligned_pairs.append((source_index, anchor_index))
            source_index += 1
            anchor_index += 1
            continue

        next_anchor_match = find_next_matching_value(anchor_values, anchor_index + 1, source_values[source_index])
        next_source_match = find_next_matching_value(source_values, source_index + 1, anchor_values[anchor_index])

        if next_anchor_match is None and next_source_match is None:
            aligned_pairs.append((source_index, anchor_index))
            source_index += 1
            anchor_index += 1
            continue

        if next_anchor_match is not None and (
            next_source_match is None or next_anchor_match - anchor_index <= next_source_match - source_index
        ):
            aligned_pairs.append((None, anchor_index))
            anchor_index += 1
            continue

        aligned_pairs.append((source_index, None))
        source_index += 1

    return aligned_pairs


def build_keyed_alignment(
    source_lines: Sequence[str],
    anchor_lines: Sequence[str],
    key_function,
) -> List[Tuple[int | None, int | None]]:
    """Align two sequences using a derived semantic key while preserving order."""
    source_keys = [key_function(line) for line in source_lines]
    anchor_keys = [key_function(line) for line in anchor_lines]
    return build_exact_alignment(source_keys, anchor_keys)


def section_entry_alignment_key(line: str) -> str:
    """Return a semantic alignment key for lines within one SES..NTE section."""
    elems = line.split("|")
    if len(elems) > 1 and elems[0] == "FOS":
        return f"FOS|{elems[1]}"
    return normalize_comparison_line(line)


def build_anchor_alignment(source_lines: Sequence[str], anchor_lines: Sequence[str]) -> List[Tuple[int | None, int | None]]:
    """Align one file's lines to the anchor file, preferring matching segment tags."""
    normalized_source = [normalize_comparison_line(line) for line in source_lines]
    normalized_anchor = [normalize_comparison_line(line) for line in anchor_lines]
    source_tags = [line_tag(line) for line in source_lines]
    anchor_tags = [line_tag(line) for line in anchor_lines]
    aligned_pairs: List[Tuple[int | None, int | None]] = []

    source_index = 0
    anchor_index = 0

    while source_index < len(source_lines) or anchor_index < len(anchor_lines):
        if source_index >= len(source_lines):
            aligned_pairs.append((None, anchor_index))
            anchor_index += 1
            continue

        if anchor_index >= len(anchor_lines):
            aligned_pairs.append((source_index, None))
            source_index += 1
            continue

        if normalized_source[source_index] == normalized_anchor[anchor_index]:
            aligned_pairs.append((source_index, anchor_index))
            source_index += 1
            anchor_index += 1
            continue

        next_exact_anchor_match = find_next_matching_line(
            normalized_anchor,
            anchor_tags,
            anchor_index + 1,
            normalized_source[source_index],
            source_tags[source_index],
        )
        next_exact_source_match = find_next_matching_line(
            normalized_source,
            source_tags,
            source_index + 1,
            normalized_anchor[anchor_index],
            anchor_tags[anchor_index],
        )

        if next_exact_anchor_match is not None or next_exact_source_match is not None:
            if next_exact_anchor_match is not None and (
                next_exact_source_match is None
                or next_exact_anchor_match - anchor_index <= next_exact_source_match - source_index
            ):
                aligned_pairs.append((None, anchor_index))
                anchor_index += 1
                continue

            aligned_pairs.append((source_index, None))
            source_index += 1
            continue

        if source_tags[source_index] == anchor_tags[anchor_index]:
            aligned_pairs.append((source_index, anchor_index))
            source_index += 1
            anchor_index += 1
            continue

        next_anchor_match = find_next_tag(anchor_tags, anchor_index + 1, source_tags[source_index])
        next_source_match = find_next_tag(source_tags, source_index + 1, anchor_tags[anchor_index])

        if next_anchor_match is None and next_source_match is None:
            if source_tags[source_index] == anchor_tags[anchor_index]:
                aligned_pairs.append((source_index, anchor_index))
                source_index += 1
                anchor_index += 1
                continue

            aligned_pairs.append((source_index, None))
            source_index += 1
            continue

        if next_anchor_match is not None and (next_source_match is None or next_anchor_match - anchor_index <= next_source_match - source_index):
            aligned_pairs.append((None, anchor_index))
            anchor_index += 1
            continue

        aligned_pairs.append((source_index, None))
        source_index += 1

    return aligned_pairs


def merge_anchor_alignments(
    left_pairs: Sequence[Tuple[int | None, int | None]],
    right_pairs: Sequence[Tuple[int | None, int | None]],
    left_lines: Sequence[str] | None = None,
    right_lines: Sequence[str] | None = None,
    key_function: Callable[[str], str] = normalize_comparison_line,
) -> List[Tuple[int | None, int | None, int | None]]:
    """Merge two alignments that both target the same anchor sequence."""
    merged_rows: List[Tuple[int | None, int | None, int | None]] = []
    left_cursor = 0
    right_cursor = 0

    while left_cursor < len(left_pairs) or right_cursor < len(right_pairs):
        next_left_anchor = left_pairs[left_cursor][1] if left_cursor < len(left_pairs) else None
        next_right_anchor = right_pairs[right_cursor][1] if right_cursor < len(right_pairs) else None

        if (
            next_left_anchor is None
            and next_right_anchor is None
            and left_cursor < len(left_pairs)
            and right_cursor < len(right_pairs)
            and left_pairs[left_cursor][0] is not None
            and right_pairs[right_cursor][0] is not None
            and left_lines is not None
            and right_lines is not None
            and key_function(left_lines[left_pairs[left_cursor][0]])
            == key_function(right_lines[right_pairs[right_cursor][0]])
        ):
            merged_rows.append((left_pairs[left_cursor][0], None, right_pairs[right_cursor][0]))
            left_cursor += 1
            right_cursor += 1
            continue

        if next_left_anchor is None and left_cursor < len(left_pairs):
            merged_rows.append((left_pairs[left_cursor][0], None, None))
            left_cursor += 1
            continue

        if next_right_anchor is None and right_cursor < len(right_pairs):
            merged_rows.append((None, None, right_pairs[right_cursor][0]))
            right_cursor += 1
            continue

        anchor_candidates = [anchor for anchor in (next_left_anchor, next_right_anchor) if anchor is not None]
        anchor_index = min(anchor_candidates) if anchor_candidates else None
        left_source_index = None
        right_source_index = None

        if left_cursor < len(left_pairs) and left_pairs[left_cursor][1] == anchor_index:
            left_source_index = left_pairs[left_cursor][0]
            left_cursor += 1

        if right_cursor < len(right_pairs) and right_pairs[right_cursor][1] == anchor_index:
            right_source_index = right_pairs[right_cursor][0]
            right_cursor += 1

        merged_rows.append((left_source_index, anchor_index, right_source_index))

    return merged_rows


def analyze_student_blocks(files: Sequence[FileSnapshot]) -> StudentBlockAnalysis | None:
    """Compare NSC ST..SE student blocks across the three files when possible."""
    student_blocks_by_label: dict[str, dict[str, str]] = {}
    for snapshot in files:
        try:
            student_blocks = extract_student_blocks(snapshot)
        except ValueError:
            return None
        if not student_blocks:
            return None
        student_blocks_by_label[snapshot.label] = student_blocks

    file_labels = [snapshot.label for snapshot in files]
    original_label = file_labels[0]
    all_banner_ids = sorted(set().union(*(blocks.keys() for blocks in student_blocks_by_label.values())))
    differing_students: List[StudentDifference] = []
    matching_students = 0
    unchanged_student_ids: List[str] = []
    original_only_student_ids: List[str] = []

    for banner_id in all_banner_ids:
        blocks_by_label = {
            label: student_blocks_by_label[label].get(banner_id)
            for label in file_labels
        }
        normalized_blocks_by_label = {
            label: normalize_student_block(block)
            for label, block in blocks_by_label.items()
        }
        present_blocks = [block for block in normalized_blocks_by_label.values() if block is not None]

        if (
            blocks_by_label.get(original_label) is not None
            and all(blocks_by_label.get(label) is None for label in file_labels[1:])
        ):
            original_only_student_ids.append(banner_id)
            continue

        if len(present_blocks) == len(file_labels) and len(set(present_blocks)) == 1:
            matching_students += 1
            unchanged_student_ids.append(banner_id)
            continue

        statuses = build_student_statuses(file_labels, normalized_blocks_by_label)
        differing_students.append(
            StudentDifference(
                banner_id=banner_id,
                summary=summarize_student_variation(statuses),
                statuses=statuses,
                blocks=blocks_by_label,
            )
        )

    return StudentBlockAnalysis(
        file_student_counts={label: len(blocks) for label, blocks in student_blocks_by_label.items()},
        total_distinct_students=len(all_banner_ids),
        matching_students=matching_students,
        unchanged_student_ids=unchanged_student_ids,
        original_only_student_ids=original_only_student_ids,
        differing_students=differing_students,
    )


def compare_pair_by_position(left: FileSnapshot, right: FileSnapshot) -> PairwiseStats:
    """Compare files by line position to stay responsive on very large inputs."""
    max_len = max(left.line_count, right.line_count)
    if max_len == 0:
        return PairwiseStats(
            left_label=left.label,
            right_label=right.label,
            equal_lines=0,
            inserted_lines=0,
            deleted_lines=0,
            replaced_left_lines=0,
            replaced_right_lines=0,
            changed_blocks=0,
            similarity_ratio=1.0,
            comparison_mode="large-file",
        )

    equal_lines = 0
    inserted_lines = 0
    deleted_lines = 0
    replaced_left_lines = 0
    replaced_right_lines = 0
    changed_blocks = 0
    in_change_block = False

    for index in range(max_len):
        left_line = left.lines[index] if index < left.line_count else None
        right_line = right.lines[index] if index < right.line_count else None

        if left_line == right_line:
            equal_lines += 1
            in_change_block = False
            continue

        if not in_change_block:
            changed_blocks += 1
            in_change_block = True

        if left_line is None:
            inserted_lines += 1
        elif right_line is None:
            deleted_lines += 1
        else:
            replaced_left_lines += 1
            replaced_right_lines += 1

    return PairwiseStats(
        left_label=left.label,
        right_label=right.label,
        equal_lines=equal_lines,
        inserted_lines=inserted_lines,
        deleted_lines=deleted_lines,
        replaced_left_lines=replaced_left_lines,
        replaced_right_lines=replaced_right_lines,
        changed_blocks=changed_blocks,
        similarity_ratio=equal_lines / max_len,
        comparison_mode="large-file",
    )


def compare_pair(left: FileSnapshot, right: FileSnapshot) -> PairwiseStats:
    """Summarize how two files differ using line-based diff opcodes."""
    if use_large_file_mode(left, right):
        return compare_pair_by_position(left, right)

    matcher = difflib.SequenceMatcher(a=left.lines, b=right.lines)
    equal_lines = 0
    inserted_lines = 0
    deleted_lines = 0
    replaced_left_lines = 0
    replaced_right_lines = 0
    changed_blocks = 0

    # SequenceMatcher emits coarse change blocks; we convert those blocks into
    # counts that are easier to summarize in the HTML dashboard.
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if tag == "equal":
            equal_lines += left_end - left_start
            continue

        changed_blocks += 1
        if tag == "insert":
            inserted_lines += right_end - right_start
        elif tag == "delete":
            deleted_lines += left_end - left_start
        elif tag == "replace":
            replaced_left_lines += left_end - left_start
            replaced_right_lines += right_end - right_start

    return PairwiseStats(
        left_label=left.label,
        right_label=right.label,
        equal_lines=equal_lines,
        inserted_lines=inserted_lines,
        deleted_lines=deleted_lines,
        replaced_left_lines=replaced_left_lines,
        replaced_right_lines=replaced_right_lines,
        changed_blocks=changed_blocks,
        similarity_ratio=matcher.ratio(),
        comparison_mode="sequence-matcher",
    )


def content_counters(files: Sequence[FileSnapshot]) -> List[Counter[str]]:
    """Count repeated line occurrences in each file independently."""
    return [Counter(snapshot.lines) for snapshot in files]


def build_other_line_set(counters: Sequence[Counter[str]], current_index: int) -> set[str]:
    """Collect every distinct line found outside the current file."""
    other_keys: set[str] = set()
    for other_index, counter in enumerate(counters):
        if other_index == current_index:
            continue
        other_keys.update(counter.keys())
    return other_keys


def first_unique_lines(snapshot: FileSnapshot, other_keys: set[str], limit: int) -> List[str]:
    """Return the first few lines that appear only in the current file."""
    unique_lines: List[str] = []
    seen: set[str] = set()
    for line in snapshot.lines:
        if line in seen or line in other_keys:
            continue
        unique_lines.append(line)
        seen.add(line)
        if len(unique_lines) >= limit:
            break
    return unique_lines


def count_shared_line_occurrences(files: Sequence[FileSnapshot]) -> Tuple[int, int, int, int]:
    """Count shared occurrences plus per-file occurrences not matched by the others."""
    counters = content_counters(files)
    shared_all = 0
    unique_counts = [0, 0, 0]

    all_lines = set().union(*(counter.keys() for counter in counters))
    for line in all_lines:
        counts = [counter.get(line, 0) for counter in counters]
        shared_all += min(counts)
        for index in range(3):
            # Treat a line as unique only when its extra occurrences in one file
            # exceed the maximum occurrence count seen in the other two files.
            unique_counts[index] += max(counts[index] - max(counts[(index + 1) % 3], counts[(index + 2) % 3]), 0)

    return shared_all, unique_counts[0], unique_counts[1], unique_counts[2]


def triage_examples(files: Sequence[FileSnapshot], limit: int) -> List[Tuple[str, List[str]]]:
    """Build small sample lists to show file-specific lines in the report."""
    counters = content_counters(files)
    results: List[Tuple[str, List[str]]] = []
    for index, snapshot in enumerate(files):
        other_keys = build_other_line_set(counters, index)
        results.append((snapshot.label, first_unique_lines(snapshot, other_keys, limit)))
    return results


def format_percent(value: float) -> str:
    """Render a ratio as a human-readable percent string."""
    return f"{value * 100:.1f}%"


def as_html(value: object) -> str:
    """Escape content before interpolating it into HTML."""
    return html.escape(str(value), quote=True)


def render_file_cards(files: Sequence[FileSnapshot]) -> str:
    """Render one summary card per input file."""
    cards = []
    for snapshot in files:
        cards.append(
            f"""
            <article class=\"stat-card\">
              <p class=\"eyebrow\">{as_html(snapshot.label)}</p>
              <h3>{as_html(snapshot.path.name)}</h3>
              <p class=\"muted\">{as_html(snapshot.path)}</p>
              <div class=\"metrics\">
                <span>{snapshot.line_count} lines</span>
                <span>{snapshot.size_bytes:,} bytes</span>
              </div>
            </article>
            """
        )
    return "".join(cards)


def render_pairwise_cards(stats_list: Sequence[PairwiseStats]) -> str:
    """Render compact metrics for each pairwise file comparison."""
    cards = []
    for stats in stats_list:
        mode_label = (
            "Detailed comparison"
            if stats.comparison_mode == "sequence-matcher"
            else "Large-file comparison"
        )
        cards.append(
            f"""
            <article class="stat-card">
              <p class="eyebrow">File comparison</p>
              <h3>{as_html(stats.left_label)} vs {as_html(stats.right_label)}</h3>
              <div class="metrics">
                <span>{mode_label}</span>
                <span>Similarity {format_percent(stats.similarity_ratio)}</span>
                <span>{stats.changed_blocks} changed blocks</span>
                <span>{stats.inserted_lines} inserted</span>
                <span>{stats.deleted_lines} deleted</span>
                <span>{stats.replaced_left_lines}/{stats.replaced_right_lines} replaced</span>
              </div>
            </article>
            """
        )
    return "".join(cards)


def substantive_student_differences(
    differences: Sequence[StudentDifference],
    file_labels: Sequence[str],
) -> List[Tuple[StudentDifference, List[StudentLineDifference], int, dict[str, int]]]:
    """Keep only students whose aligned rows contain substantive differences."""
    substantive: List[Tuple[StudentDifference, List[StudentLineDifference], int, dict[str, int]]] = []
    for student in differences:
        block_rows = build_student_block_rows(student.blocks, file_labels)
        substantive_count = count_substantive_rows(block_rows, file_labels)
        if substantive_count:
            scope_counts = {
                "scope-12": 0,
                "scope-23": 0,
                "scope-mixed": 0,
            }
            for row in block_rows:
                if not row_has_substantive_difference(row, file_labels):
                    continue
                scope = row_difference_scope(row, file_labels)
                if scope in scope_counts:
                    scope_counts[scope] += 1
            substantive.append((student, block_rows, substantive_count, scope_counts))
    return substantive


def render_student_id_list(student_ids: Sequence[str], empty_message: str) -> str:
    """Render a compact list of Banner IDs for summary-only student buckets."""
    if not student_ids:
        return f'<p class="empty">{as_html(empty_message)}</p>'
    items = "".join(f'<li><code>{as_html(student_id)}</code></li>' for student_id in student_ids)
    return f'<ul class="student-id-list">{items}</ul>'


def render_student_record_list(records: Sequence[Tuple[str, str]], empty_message: str) -> str:
    """Render a compact list of Banner IDs with a short record summary."""
    if not records:
        return f'<p class="empty">{as_html(empty_message)}</p>'
    items = "".join(
        f'<li><code>{as_html(student_id)}</code><span class="record-separator">&nbsp;&nbsp;&nbsp;</span><span class="muted">{as_html(record_summary)}</span></li>'
        for student_id, record_summary in records
    )
    return f'<ul class="student-id-list">{items}</ul>'


def build_student_block_rows(blocks: dict[str, str | None], file_labels: Sequence[str]) -> List[StudentLineDifference]:
    """Return diff-aligned rows for a student's block anchored on the original file.

    The first file keeps the display order. Repeated detailed `SES ... NTE`
    subsections are matched against that original order so changed sections
    compare side by side without reordering the original record.
    """
    original_label, second_label, third_label = file_labels
    line_lists = {
        label: (blocks.get(label) or "").splitlines()
        for label in file_labels
    }

    split_blocks = {
        label: split_student_block_sections(line_lists[label])
        for label in file_labels
    }

    original_prefix, original_sections, original_suffix = split_blocks[original_label]
    second_prefix, second_sections, second_suffix = split_blocks[second_label]
    right_prefix, right_sections, right_suffix = split_blocks[third_label]
    original_program_names = build_prefix_program_name_map(original_prefix)
    second_program_names = build_prefix_program_name_map(second_prefix)
    right_program_names = build_prefix_program_name_map(right_prefix)

    rows: List[StudentLineDifference] = []

    second_prefix_pairs = build_keyed_alignment(
        [line for _, line in second_prefix],
        [line for _, line in original_prefix],
        prefix_alignment_key,
    )
    right_prefix_pairs = build_keyed_alignment(
        [line for _, line in right_prefix],
        [line for _, line in original_prefix],
        prefix_alignment_key,
    )
    merged_prefix_rows = merge_anchor_alignments(
        second_prefix_pairs,
        right_prefix_pairs,
        [line for _, line in second_prefix],
        [line for _, line in right_prefix],
        prefix_alignment_key,
    )
    used_second_prefix_indices: set[int] = set()
    used_right_prefix_indices: set[int] = set()

    for second_index, original_index, right_index in merged_prefix_rows:
        if second_index is not None:
            used_second_prefix_indices.add(second_index)
        if right_index is not None:
            used_right_prefix_indices.add(right_index)
        rows.append(
            StudentLineDifference(
                line_number=(original_prefix[original_index][0] if original_index is not None else 0),
                values={
                    original_label: original_prefix[original_index][1] if original_index is not None else "",
                    second_label: second_prefix[second_index][1] if second_index is not None else "",
                    third_label: right_prefix[right_index][1] if right_index is not None else "",
                },
            )
        )

    remaining_second_prefix = [entry for index, entry in enumerate(second_prefix) if index not in used_second_prefix_indices]
    remaining_right_prefix = [entry for index, entry in enumerate(right_prefix) if index not in used_right_prefix_indices]
    remaining_prefix_pairs = build_keyed_alignment(
        [line for _, line in remaining_right_prefix],
        [line for _, line in remaining_second_prefix],
        prefix_alignment_key,
    )

    for right_index, second_index in remaining_prefix_pairs:
        rows.append(
            StudentLineDifference(
                line_number=0,
                values={
                    original_label: "",
                    second_label: remaining_second_prefix[second_index][1] if second_index is not None else "",
                    third_label: remaining_right_prefix[right_index][1] if right_index is not None else "",
                },
            )
        )

    second_section_identities = [section_identity(section, second_program_names) for section in second_sections]
    original_section_identities = [section_identity(section, original_program_names) for section in original_sections]
    right_section_identities = [section_identity(section, right_program_names) for section in right_sections]
    used_second_section_indices: set[int] = set()
    used_right_section_indices: set[int] = set()

    merged_section_rows: List[Tuple[int | None, int | None, int | None]] = []
    for original_section_index, original_section_identity in enumerate(original_section_identities):
        second_match_index = find_matching_section_index(
            original_section_identity,
            second_section_identities,
            used_second_section_indices,
        )
        right_match_index = find_matching_section_index(
            original_section_identity,
            right_section_identities,
            used_right_section_indices,
        )
        if second_match_index is not None:
            used_second_section_indices.add(second_match_index)
        if right_match_index is not None:
            used_right_section_indices.add(right_match_index)
        merged_section_rows.append(
            (
                second_match_index,
                original_section_index,
                right_match_index,
            )
        )

    for second_section_index, second_section_identity in enumerate(second_section_identities):
        if second_section_index not in used_second_section_indices:
            right_match_index = find_matching_section_index(
                second_section_identity,
                right_section_identities,
                used_right_section_indices,
            )
            if right_match_index is not None:
                used_right_section_indices.add(right_match_index)
            merged_section_rows.append(
                (
                    second_section_index,
                    None,
                    right_match_index,
                )
            )

    remaining_right_indices = [
        index
        for index in range(len(right_sections))
        if index not in used_right_section_indices
    ]
    for right_section_index in sorted(remaining_right_indices):
        merged_section_rows.append((None, None, right_section_index))

    for second_section_index, original_section_index, right_section_index in merged_section_rows:
        second_entries = second_sections[second_section_index] if second_section_index is not None else []
        original_entries = original_sections[original_section_index] if original_section_index is not None else []
        right_entries = right_sections[right_section_index] if right_section_index is not None else []

        if not original_entries:
            right_pairs = build_keyed_alignment(
                [line for _, line in right_entries],
                [line for _, line in second_entries],
                section_entry_alignment_key,
            )
            for right_index, second_index in right_pairs:
                rows.append(
                    StudentLineDifference(
                        line_number=0,
                        values={
                            original_label: "",
                            second_label: second_entries[second_index][1] if second_index is not None else "",
                            third_label: right_entries[right_index][1] if right_index is not None else "",
                        },
                    )
                )
            continue

        second_pairs = build_anchor_alignment([line for _, line in second_entries], [line for _, line in original_entries])
        right_pairs = build_anchor_alignment([line for _, line in right_entries], [line for _, line in original_entries])
        merged_entry_rows = merge_anchor_alignments(
            second_pairs,
            right_pairs,
            [line for _, line in second_entries],
            [line for _, line in right_entries],
            section_entry_alignment_key,
        )

        for second_index, original_index, right_index in merged_entry_rows:
            rows.append(
                StudentLineDifference(
                    line_number=(original_entries[original_index][0] if original_index is not None else 0),
                    values={
                        original_label: original_entries[original_index][1] if original_index is not None else "",
                        second_label: second_entries[second_index][1] if second_index is not None else "",
                        third_label: right_entries[right_index][1] if right_index is not None else "",
                    },
                )
            )

    second_suffix_pairs = build_anchor_alignment([line for _, line in second_suffix], [line for _, line in original_suffix])
    right_suffix_pairs = build_anchor_alignment([line for _, line in right_suffix], [line for _, line in original_suffix])
    merged_suffix_rows = merge_anchor_alignments(
        second_suffix_pairs,
        right_suffix_pairs,
        [line for _, line in second_suffix],
        [line for _, line in right_suffix],
    )
    used_second_suffix_indices: set[int] = set()
    used_right_suffix_indices: set[int] = set()

    for second_index, original_index, right_index in merged_suffix_rows:
        if second_index is not None:
            used_second_suffix_indices.add(second_index)
        if right_index is not None:
            used_right_suffix_indices.add(right_index)
        rows.append(
            StudentLineDifference(
                line_number=(original_suffix[original_index][0] if original_index is not None else 0),
                values={
                    original_label: original_suffix[original_index][1] if original_index is not None else "",
                    second_label: second_suffix[second_index][1] if second_index is not None else "",
                    third_label: right_suffix[right_index][1] if right_index is not None else "",
                },
            )
        )

    remaining_second_suffix = [entry for index, entry in enumerate(second_suffix) if index not in used_second_suffix_indices]
    remaining_right_suffix = [entry for index, entry in enumerate(right_suffix) if index not in used_right_suffix_indices]
    remaining_suffix_pairs = build_anchor_alignment(
        [line for _, line in remaining_right_suffix],
        [line for _, line in remaining_second_suffix],
    )

    for right_index, second_index in remaining_suffix_pairs:
        rows.append(
            StudentLineDifference(
                line_number=0,
                values={
                    original_label: "",
                    second_label: remaining_second_suffix[second_index][1] if second_index is not None else "",
                    third_label: remaining_right_suffix[right_index][1] if right_index is not None else "",
                },
            )
        )

    return rows


def row_has_substantive_difference(row: StudentLineDifference, file_labels: Sequence[str]) -> bool:
    """Return whether an aligned row still differs after normalization."""
    normalized_values = [normalize_comparison_line(row.values[label]) for label in file_labels]
    if not normalized_values[0] and normalized_values[1] == normalized_values[2]:
        return False
    return len(set(normalized_values)) > 1


def count_substantive_rows(rows: Sequence[StudentLineDifference], file_labels: Sequence[str]) -> int:
    """Count aligned rows that still differ after normalization."""
    return sum(1 for row in rows if row_has_substantive_difference(row, file_labels))


def compact_student_rows_for_render(
    rows: Sequence[StudentLineDifference],
    file_labels: Sequence[str],
) -> List[StudentLineDifference]:
    """Keep substantive rows plus a small context window to limit report size."""
    substantive_indices = [
        index
        for index, row in enumerate(rows)
        if row_has_substantive_difference(row, file_labels)
    ]
    if not substantive_indices:
        return []

    keep_indices: set[int] = set()
    for index in substantive_indices:
        start_index = max(0, index - STUDENT_DETAIL_CONTEXT_LINES)
        end_index = min(len(rows) - 1, index + STUDENT_DETAIL_CONTEXT_LINES)
        keep_indices.update(range(start_index, end_index + 1))

    compact_rows = [rows[index] for index in sorted(keep_indices)]
    if len(compact_rows) <= MAX_RENDERED_STUDENT_DETAIL_ROWS:
        return compact_rows

    trimmed_rows = compact_rows[:MAX_RENDERED_STUDENT_DETAIL_ROWS]
    omitted_count = len(compact_rows) - MAX_RENDERED_STUDENT_DETAIL_ROWS
    marker_text = f"[... {omitted_count} additional context rows omitted ...]"
    trimmed_rows.append(
        StudentLineDifference(
            line_number=0,
            values=dict.fromkeys(file_labels, marker_text),
        )
    )
    return trimmed_rows


def row_difference_scope(row: StudentLineDifference, file_labels: Sequence[str]) -> str:
    """Classify whether a row differs only in pair 1-2, only in pair 2-3, or both."""
    first_label, second_label, third_label = file_labels
    first_second_diff = normalize_comparison_line(row.values[first_label]) != normalize_comparison_line(row.values[second_label])
    second_third_diff = normalize_comparison_line(row.values[second_label]) != normalize_comparison_line(row.values[third_label])

    if first_second_diff and not second_third_diff:
        return "scope-12"
    if second_third_diff and not first_second_diff:
        return "scope-23"
    if first_second_diff or second_third_diff:
        return "scope-mixed"
    return "scope-none"


def extract_fos_p_program_number(line: str) -> str | None:
    """Extract the trailing program number from an FOS|P line when present."""
    elems = line.split("|")
    if len(elems) > 2 and elems[0] == "FOS" and elems[1] == "P":
        program_number = elems[-1].strip()
        return program_number or None
    return None


def extract_fos_program_code(line: str) -> str | None:
    """Extract the program code from an FOS|M or FOS|P line when present."""
    elems = line.split("|")
    if len(elems) > 3 and elems[0] == "FOS" and elems[1] in {"M", "P"}:
        program_code = elems[3].strip()
        return program_code or None
    return None


def normalize_fos_ignoring_program_code(line: str) -> str:
    """Normalize an FOS|M or FOS|P line while ignoring its program code."""
    elems = line.split("|")
    if len(elems) > 3 and elems[0] == "FOS" and elems[1] in {"M", "P"}:
        elems[3] = "<program-code>"
        line = "|".join(elems)
    return normalize_comparison_line(line)


def normalize_fos_p_ignoring_program_number(line: str) -> str:
    """Normalize an FOS|P line while ignoring its trailing program number."""
    elems = line.split("|")
    if len(elems) > 2 and elems[0] == "FOS" and elems[1] == "P":
        elems[-1] = "<program-number>"
        line = "|".join(elems)
    return normalize_comparison_line(line)


def row_is_program_number_only_change_between_first_two(
    row: StudentLineDifference,
    file_labels: Sequence[str],
) -> bool:
    """Return whether file 1 vs file 2 differs only by FOS|P trailing program number."""
    first_label, second_label, _ = file_labels
    normalized_first = normalize_comparison_line(row.values[first_label])
    normalized_second = normalize_comparison_line(row.values[second_label])
    if normalized_first == normalized_second:
        return False

    first_program_number = extract_fos_p_program_number(row.values[first_label])
    second_program_number = extract_fos_p_program_number(row.values[second_label])
    if not first_program_number or not second_program_number:
        return False
    if first_program_number == second_program_number:
        return False

    normalized_first_without_program_number = normalize_fos_p_ignoring_program_number(row.values[first_label])
    normalized_second_without_program_number = normalize_fos_p_ignoring_program_number(row.values[second_label])
    return normalized_first_without_program_number == normalized_second_without_program_number


def row_is_program_added_between_first_two(
    row: StudentLineDifference,
    file_labels: Sequence[str],
) -> bool:
    """Return whether file 2 adds an FOS program line that is missing in file 1."""
    first_label, second_label, _ = file_labels
    first_line = row.values[first_label]
    second_line = row.values[second_label]
    if normalize_comparison_line(first_line) == normalize_comparison_line(second_line):
        return False
    if first_line.strip() or not second_line.strip():
        return False

    second_elems = second_line.split("|")
    return len(second_elems) > 1 and second_elems[0] == "FOS" and second_elems[1] in {"M", "P"}


def row_program_code_change_signature_between_first_two(
    row: StudentLineDifference,
    file_labels: Sequence[str],
) -> str | None:
    """Return a logical FOS program-code change signature for file 1 vs file 2."""
    first_label, second_label, _ = file_labels
    normalized_first = normalize_comparison_line(row.values[first_label])
    normalized_second = normalize_comparison_line(row.values[second_label])
    if normalized_first == normalized_second:
        return None

    first_line = row.values[first_label]
    second_line = row.values[second_label]
    first_elems = first_line.split("|")
    second_elems = second_line.split("|")
    if (
        len(first_elems) <= 3
        or len(second_elems) <= 3
        or first_elems[0] != "FOS"
        or second_elems[0] != "FOS"
        or first_elems[1] not in {"M", "P"}
        or second_elems[1] not in {"M", "P"}
    ):
        return None

    first_program_code = extract_fos_program_code(first_line)
    second_program_code = extract_fos_program_code(second_line)
    if not first_program_code or not second_program_code or first_program_code == second_program_code:
        return None

    normalized_first_without_program_code = normalize_fos_ignoring_program_code(first_line)
    normalized_second_without_program_code = normalize_fos_ignoring_program_code(second_line)
    if normalized_first_without_program_code != normalized_second_without_program_code:
        return None

    return f"{first_program_code}->{second_program_code}"


def student_has_program_number_change(
    rows: Sequence[StudentLineDifference],
    file_labels: Sequence[str],
) -> bool:
    """Return whether aligned FOS|P rows show different program numbers across files."""
    for row in rows:
        program_numbers = {
            extract_fos_p_program_number(row.values[label])
            for label in file_labels
        }
        present_program_numbers = {
            program_number
            for program_number in program_numbers
            if program_number
        }
        if len(present_program_numbers) > 1:
            return True
    return False


def student_has_program_code_change_between_first_two(
    rows: Sequence[StudentLineDifference],
    file_labels: Sequence[str],
) -> bool:
    """Return whether file 1 vs file 2 contains any logical FOS program-code change."""
    return any(
        row_program_code_change_signature_between_first_two(row, file_labels)
        for row in rows
    )


def student_has_program_added_between_first_two(
    rows: Sequence[StudentLineDifference],
    file_labels: Sequence[str],
) -> bool:
    """Return whether file 2 introduces a new FOS program line not present in file 1."""
    return any(row_is_program_added_between_first_two(row, file_labels) for row in rows)


def student_has_only_program_number_change_between_first_two(
    rows: Sequence[StudentLineDifference],
    file_labels: Sequence[str],
) -> bool:
    """Return whether there is exactly one file 1 vs file 2 program-number-only change row."""
    qualifying_rows = [
        row
        for row in rows
        if row_is_program_number_only_change_between_first_two(row, file_labels)
    ]
    return len(qualifying_rows) == 1


def student_has_only_program_code_change_between_first_two(
    rows: Sequence[StudentLineDifference],
    file_labels: Sequence[str],
) -> bool:
    """Return whether there is exactly one logical FOS program-code change in file 1 vs file 2."""
    return program_code_change_record_between_first_two(rows, file_labels) is not None


def student_has_exclusive_program_number_change_between_first_two(
    rows: Sequence[StudentLineDifference],
    file_labels: Sequence[str],
) -> bool:
    """Return whether a student's substantive differences are only one program-number change."""
    substantive_rows = [row for row in rows if row_has_substantive_difference(row, file_labels)]
    return (
        len(substantive_rows) == 1
        and row_is_program_number_only_change_between_first_two(substantive_rows[0], file_labels)
    )


def student_has_exclusive_program_code_change_between_first_two(
    rows: Sequence[StudentLineDifference],
    file_labels: Sequence[str],
) -> bool:
    """Return whether a student's substantive differences are only one logical program-code change."""
    substantive_rows = [row for row in rows if row_has_substantive_difference(row, file_labels)]
    qualifying_signatures = {
        signature
        for row in substantive_rows
        for signature in [row_program_code_change_signature_between_first_two(row, file_labels)]
        if signature
    }
    return len(substantive_rows) in {1, 2} and len(qualifying_signatures) == 1 and all(
        row_program_code_change_signature_between_first_two(row, file_labels)
        for row in substantive_rows
    )


def student_has_exclusive_program_change_between_first_two(
    rows: Sequence[StudentLineDifference],
    file_labels: Sequence[str],
) -> bool:
    """Return whether a student belongs only in a standalone program-change bucket."""
    return (
        student_has_exclusive_program_number_change_between_first_two(rows, file_labels)
        or student_has_exclusive_program_code_change_between_first_two(rows, file_labels)
    )


def program_code_change_record_between_first_two(
    rows: Sequence[StudentLineDifference],
    file_labels: Sequence[str],
) -> Tuple[str, str] | None:
    """Return the old and new code for a single logical file 1 vs file 2 program-code change."""
    qualifying_signatures = {
        signature
        for row in rows
        for signature in [row_program_code_change_signature_between_first_two(row, file_labels)]
        if signature
    }
    qualifying_row_count = sum(
        1
        for row in rows
        if row_program_code_change_signature_between_first_two(row, file_labels)
    )
    if len(qualifying_signatures) != 1 or qualifying_row_count not in {1, 2}:
        return None
    signature = next(iter(qualifying_signatures))
    old_code, new_code = signature.split("->", 1)
    return old_code, new_code


def highlight_class_names(row: StudentLineDifference, file_labels: Sequence[str], label: str) -> str:
    """Choose highlight colors for pairwise cell differences in the student block view."""
    first_label, second_label, third_label = file_labels
    first_second_diff = normalize_comparison_line(row.values[first_label]) != normalize_comparison_line(row.values[second_label])
    second_third_diff = normalize_comparison_line(row.values[second_label]) != normalize_comparison_line(row.values[third_label])
    first_second_gap = not row.values[first_label] or not row.values[second_label]
    second_third_gap = not row.values[second_label] or not row.values[third_label]

    classes: List[str] = []
    if label in {first_label, second_label} and first_second_diff:
        classes.append("pair-12-gap" if first_second_gap else "pair-12-diff")
    if label in {second_label, third_label} and second_third_diff:
        classes.append("pair-23-gap" if second_third_gap else "pair-23-diff")
    return " ".join(classes)


def status_css_class(status: str) -> str:
    """Map a student block status label to a CSS class."""
    if status == "Missing":
        return "status-missing"
    suffix = status.split()[-1]
    if suffix.isdigit():
        return f"status-group-{suffix}"
    return "status-generic"


def render_student_difference_rows(differences: Sequence[StudentDifference], file_labels: Sequence[str]) -> str:
    """Render one table row per student whose blocks differ across files."""
    rows = []
    for student in differences:
        status_cells = "".join(
            f'<td><span class="status-chip {status_css_class(student.statuses[label])}">{as_html(student.statuses[label])}</span></td>'
            for label in file_labels
        )
        rows.append(
            f"""
            <tr class="student-row" data-search="{as_html(student.banner_id)} {as_html(student.summary)}">
              <td>{as_html(student.banner_id)}</td>
              <td>{as_html(student.summary)}</td>
              {status_cells}
            </tr>
            """
        )
    return "".join(rows)


def render_student_detail_rows(
    line_differences: Sequence[StudentLineDifference],
    file_labels: Sequence[str],
) -> str:
    """Render rows for a student's full block with pairwise highlight colors."""
    rows = []
    for diff in line_differences:
        row_scope_class = row_difference_scope(diff, file_labels)
        value_cells = "".join(
            f'<td class="{highlight_class_names(diff, file_labels, label)}"><code>{as_html(diff.values[label] or "[missing line]")}</code></td>'
            for label in file_labels
        )
        rows.append(
            f"""
            <tr class="{row_scope_class}">
                            <td class="line-no {row_scope_class}">{diff.line_number if diff.line_number > 0 else ''}</td>
              {value_cells}
            </tr>
            """
        )
    return "".join(rows)


def missing_header_dtp007_reason(blocks: dict[str, str | None], file_labels: Sequence[str]) -> str | None:
    """Identify current-file insertion candidates without treating all absent dates as errors."""
    current = blocks.get(file_labels[2])
    previous = blocks.get(file_labels[1]) or blocks.get(file_labels[0])
    if not current or not previous:
        return None

    def header(block: str) -> List[List[str]]:
        records = []
        for line in block.splitlines():
            elements = line.split("|")
            if elements[0] == "ENT":
                break
            records.append(elements)
        return records

    if sum(line.startswith("ST|") for line in current.splitlines()) != 1:
        return None
    if sum(line.startswith("ST|") for line in previous.splitlines()) != 1:
        return None
    current_header, previous_header = header(current), header(previous)

    def has_date(records: Sequence[Sequence[str]]) -> bool:
        return any(len(record) > 1 and record[0] == "DTP" and record[1].strip().lstrip("0") == "7" for record in records)

    if has_date(current_header):
        return None
    if has_date(previous_header):
        return "Header DTP 007 was present in the prior file and is absent from the current file"

    def status(records: Sequence[Sequence[str]]) -> str | None:
        enrollments = [record for record in records if len(record) > 1 and record[0] == "ENR"]
        primary = next(
            (record for record in enrollments if len(record) > 2 and record[2] == "UN"),
            enrollments[0] if enrollments else None,
        )
        return primary[1] if primary else None

    ranks = {"EB6": 4, "EBO": 3, "EB7": 2, "EB8": 1, "EB3": 0}
    before, after = status(previous_header), status(current_header)
    if before in ranks and after in ranks and ranks[after] < ranks[before]:
        return f"University enrollment status decreased {before} -> {after} without a current header DTP 007"
    return None


def render_student_detail_sections(
    differences: Sequence[StudentDifference],
    file_labels: Sequence[str],
    compact_student_details: bool = False,
    exclude_program_change_only: bool = True,
) -> str:
    """Render expandable three-column detail blocks for substantive student differences."""
    substantive = substantive_student_differences(differences, file_labels)
    if exclude_program_change_only:
        substantive = [
            item
            for item in substantive
            if not student_has_exclusive_program_change_between_first_two(item[1], file_labels)
        ]
    if not substantive:
        return '<p class="empty">No students had detail-card differences beyond the standalone program-change buckets and trailing end-of-line date changes.</p>'

    sections = []
    header_cells = "".join(f"<th>{as_html(label)}</th>" for label in file_labels)
    first_label, second_label, third_label = file_labels
    for student, block_rows, substantive_count, scope_counts in substantive:
        rendered_rows = compact_student_rows_for_render(block_rows, file_labels) if compact_student_details else block_rows
        scope_parts: List[str] = []
        has_program_number_change = student_has_program_number_change(block_rows, file_labels)
        program_code_record = program_code_change_record_between_first_two(block_rows, file_labels)
        has_program_code_change = program_code_record is not None
        has_program_added = student_has_program_added_between_first_two(block_rows, file_labels)
        missing_date_reason = missing_header_dtp007_reason(student.blocks, file_labels)
        has_both_pairs = bool(scope_counts["scope-12"] and scope_counts["scope-23"])
        if has_both_pairs:
            scope_parts.append(f'<span class="meta-scope-mixed">Changes involve all three files: {substantive_count}</span>')
        elif scope_counts["scope-12"]:
            scope_parts.append(
                f'<span class="meta-scope-12">Differences between {as_html(first_label)} and {as_html(second_label)}: {scope_counts["scope-12"]}</span>'
            )
        elif scope_counts["scope-23"]:
            scope_parts.append(
                f'<span class="meta-scope-23">Differences between {as_html(second_label)} and {as_html(third_label)}: {scope_counts["scope-23"]}</span>'
            )
        elif scope_counts["scope-mixed"]:
            scope_parts.append(f'<span class="meta-scope-mixed">Changes involve all three files: {scope_counts["scope-mixed"]}</span>')
        if not scope_parts:
            scope_parts.append(f'<span class="meta-scope-mixed">Changed lines: {substantive_count}</span>')
        if has_program_number_change:
            scope_parts.append('<span class="meta-program-number">Program number change</span>')
        if has_program_code_change:
            scope_parts.append(
                f'<span class="meta-program-code">Program code change {as_html(program_code_record[0])} -&gt; {as_html(program_code_record[1])}</span>'
            )
        if has_program_added:
            scope_parts.append('<span class="meta-program-added">Program added</span>')
        if missing_date_reason:
            scope_parts.append(
                f'<span class="meta-missing-dtp007" title="{as_html(missing_date_reason)}">Possible 201 Error</span>'
            )
        scope_summary = " ".join(scope_parts)
        search_terms: List[str] = []
        if has_program_number_change:
            search_terms.append("program number change")
        if has_program_code_change:
            search_terms.append("program code change")
        if has_program_added:
            search_terms.append("program added")
        if missing_date_reason:
            search_terms.append("possible 201 error missing dtp 007 dtp 07 insertion candidate status start date")
        search_suffix = f" {' '.join(search_terms)}" if search_terms else ""
        sections.append(
            f"""
            <details class="student-card student-filter-item" data-search="{as_html(student.banner_id)} {as_html(student.summary)}{as_html(search_suffix)}">
                <summary>
                    <span class="student-title">Banner ID {as_html(student.banner_id)}</span>
                    <span class="student-meta">{scope_summary}</span>
                </summary>
                <div class="student-body">
                    <table class="listing-table">
                        <thead>
                            <tr>
                                <th>Line</th>
                                {header_cells}
                            </tr>
                        </thead>
                        <tbody>{render_student_detail_rows(rendered_rows, file_labels)}</tbody>
                    </table>
                </div>
            </details>
            """
        )
    return "".join(sections)


def render_student_block_section(
    analysis: StudentBlockAnalysis,
    file_labels: Sequence[str],
    compact_student_details: bool = False,
) -> str:
    """Render the student comparison summary and substantive detail sections."""
    file_count_pills = "".join(
        f'<span>{as_html(label)}: {analysis.file_student_counts.get(label, 0):,} students</span>'
        for label in file_labels
    )
    differing_count = len(analysis.differing_students)

    detail_sections = render_student_detail_sections(
        analysis.differing_students,
        file_labels,
        compact_student_details=compact_student_details,
        exclude_program_change_only=True,
    )
    unchanged_students_html = render_student_id_list(
        analysis.unchanged_student_ids,
        "No unchanged students were found.",
    )
    original_only_students_html = render_student_id_list(
        analysis.original_only_student_ids,
        f'No students were found only in {file_labels[0]}.',
    )
    unchanged_count = len(analysis.unchanged_student_ids)
    original_only_count = len(analysis.original_only_student_ids)
    substantive = substantive_student_differences(analysis.differing_students, file_labels)
    program_code_only_students = [
        student
        for student, block_rows, _, _ in substantive
        if student_has_exclusive_program_code_change_between_first_two(block_rows, file_labels)
    ]
    program_code_only_html = render_student_detail_sections(
        program_code_only_students,
        file_labels,
        compact_student_details=compact_student_details,
        exclude_program_change_only=False,
    )
    program_code_only_count = len(program_code_only_students)
    missing_date_ids = [
        student.banner_id for student in analysis.differing_students
        if missing_header_dtp007_reason(student.blocks, file_labels)
    ]
    missing_date_ids_html = render_student_id_list(missing_date_ids, "No possible 201 errors found.")

    return f"""
    <section>
        <h2 class="section-heading">Student Block Comparison</h2>
        <div class="grid cols-3">
            <article class="stat-card">
                <p class="eyebrow">Student blocks</p>
                <h3>{analysis.total_distinct_students:,} distinct students</h3>
                <div class="metrics">{file_count_pills}</div>
            </article>
            <article class="stat-card">
                <p class="eyebrow">Exact matches</p>
                <h3>{analysis.matching_students:,} students</h3>
                <p class="muted">Student transaction blocks are identical in all three files.</p>
            </article>
            <article class="stat-card">
                <p class="eyebrow">Differences</p>
                <h3>{differing_count:,} students</h3>
                <p class="muted">These students have differences you can review below.</p>
            </article>
        </div>
        <details class="bucket-card">
            <summary>
                <span>No Change</span>
                <span class="bucket-count">{unchanged_count:,}</span>
            </summary>
            <p class="muted">These students match across all three files.</p>
            {unchanged_students_html}
        </details>
        <details class="bucket-card">
            <summary>
                <span>Only In {as_html(file_labels[0])}</span>
                <span class="bucket-count">{original_only_count:,}</span>
            </summary>
            <p class="muted">These students appear only in {as_html(file_labels[0])}.</p>
            {original_only_students_html}
        </details>
        <details class="bucket-card">
            <summary>
                <span>Only Program Code Change In {as_html(file_labels[0])} vs {as_html(file_labels[1])}</span>
                <span class="bucket-count">{program_code_only_count:,}</span>
            </summary>
            <p class="muted">These students include a logical FOS program code change between {as_html(file_labels[0])} and {as_html(file_labels[1])}. Open a card to inspect the full record and code change summary.</p>
            {program_code_only_html}
        </details>
        <details class="bucket-card">
            <summary>
                <span>Possible 201 Error In {as_html(file_labels[2])}</span>
                <span class="bucket-count">{len(missing_date_ids):,}</span>
            </summary>
            {missing_date_ids_html}
        </details>
        <div class="section-panel">
            <h3>Student Record Details</h3>
            <p class="muted">Use the search box to find a student by Banner ID or summary. Open a student to see line-by-line differences across the three files.</p>
            <div class="color-legend">
                <span class="legend-item legend-12">Difference between {as_html(file_labels[0])} and {as_html(file_labels[1])}</span>
                <span class="legend-item legend-23">Difference between {as_html(file_labels[1])} and {as_html(file_labels[2])}</span>
                <span class="legend-item legend-mixed">Differences involve all three files</span>
                <span class="legend-item legend-program-number">Program number change</span>
                <span class="legend-item legend-program-code">Program code change</span>
                <span class="legend-item legend-program-added">Program added</span>
                <span class="legend-item legend-missing-dtp007">Possible 201 Error</span>
            </div>
            <div class="controls">
                <input id="studentBlockFilter" type="text" placeholder="Search by Banner ID or summary" oninput="filterStudentRows()" />
            </div>
            {detail_sections}
        </div>
    </section>
    """


def render_unique_examples(example_groups: Iterable[Tuple[str, List[str]]]) -> str:
    """Render file-specific example lines to make the summary more digestible."""
    sections = []
    for label, lines in example_groups:
        if lines:
            items = "".join(f"<li><code>{as_html(line or '[blank line]')}</code></li>" for line in lines)
        else:
            items = '<li class="muted">No fully unique lines found.</li>'
        sections.append(
            f"""
            <article class=\"section-panel\">
              <h3>{as_html(label)}</h3>
              <ul class=\"example-list\">{items}</ul>
            </article>
            """
        )
    return "".join(sections)


def classify_line_pair(left_line: str | None, right_line: str | None) -> str:
    """Classify a pair of lines for large-file side-by-side rendering."""
    if left_line == right_line:
        return "same"
    if left_line is None:
        return "insert"
    if right_line is None:
        return "delete"
    return "change"


def collect_raw_position_diff_blocks(left: FileSnapshot, right: FileSnapshot) -> List[DiffBlock]:
    """Collect raw contiguous mismatch regions using line-position comparison."""
    max_len = max(left.line_count, right.line_count)
    raw_blocks: List[DiffBlock] = []
    block_start: int | None = None

    for index in range(max_len):
        left_line = left.lines[index] if index < left.line_count else None
        right_line = right.lines[index] if index < right.line_count else None
        lines_differ = left_line != right_line

        if lines_differ and block_start is None:
            block_start = index
        elif not lines_differ and block_start is not None:
            raw_blocks.append(DiffBlock(block_start, index - 1))
            block_start = None

    if block_start is not None:
        raw_blocks.append(DiffBlock(block_start, max_len - 1))

    return raw_blocks


def add_context_to_diff_blocks(raw_blocks: Sequence[DiffBlock], max_len: int) -> List[DiffBlock]:
    """Expand blocks by a small context window and merge overlapping windows."""
    contextual_blocks: List[DiffBlock] = []
    for block in raw_blocks[:MAX_RENDERED_BLOCKS]:
        start_index = max(0, block.start_index - DIFF_BLOCK_CONTEXT_LINES)
        end_index = min(max_len - 1, block.end_index + DIFF_BLOCK_CONTEXT_LINES)
        if contextual_blocks and start_index <= contextual_blocks[-1].end_index + 1:
            previous = contextual_blocks[-1]
            contextual_blocks[-1] = DiffBlock(previous.start_index, max(previous.end_index, end_index))
        else:
            contextual_blocks.append(DiffBlock(start_index, end_index))
    return contextual_blocks


def build_position_diff_blocks(left: FileSnapshot, right: FileSnapshot) -> Tuple[List[DiffBlock], int]:
    """Group contiguous mismatches into bounded diff blocks for large-file rendering."""
    max_len = max(left.line_count, right.line_count)
    raw_blocks = collect_raw_position_diff_blocks(left, right)
    total_blocks = len(raw_blocks)
    return add_context_to_diff_blocks(raw_blocks, max_len), total_blocks


def render_large_diff_row(left: FileSnapshot, right: FileSnapshot, index: int) -> str:
    """Render one row in a large-file side-by-side diff table."""
    left_line = left.lines[index] if index < left.line_count else None
    right_line = right.lines[index] if index < right.line_count else None
    row_class = classify_line_pair(left_line, right_line)
    return f"""
            <tr class=\"{row_class}\">
              <td class=\"line-no\">{index + 1 if index < left.line_count else ''}</td>
              <td><code>{as_html(left_line or '')}</code></td>
              <td class=\"line-no\">{index + 1 if index < right.line_count else ''}</td>
              <td><code>{as_html(right_line or '')}</code></td>
            </tr>
            """


def render_large_diff_block(left: FileSnapshot, right: FileSnapshot, block: DiffBlock, block_number: int) -> str:
    """Render one bounded side-by-side table for a large-file diff block."""
    display_end = min(block.end_index, block.start_index + MAX_RENDERED_LINES_PER_BLOCK - 1)
    rows = [render_large_diff_row(left, right, index) for index in range(block.start_index, display_end + 1)]

    if display_end < block.end_index:
        rows.append(
            f"""
            <tr class=\"truncated\">
              <td colspan=\"4\">Showing first {MAX_RENDERED_LINES_PER_BLOCK} lines of this block. Remaining lines in block: {block.end_index - display_end}</td>
            </tr>
            """
        )

    return f"""
    <section class=\"block-card\">
      <h3>Changed block {block_number}</h3>
      <p class=\"muted\">Context window spans line positions {block.start_index + 1} to {block.end_index + 1}.</p>
      <table class=\"line-diff-table\">
        <thead>
          <tr>
            <th>{as_html(left.label)} line</th>
            <th>{as_html(left.label)} content</th>
            <th>{as_html(right.label)} line</th>
            <th>{as_html(right.label)} content</th>
          </tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>
    """


def render_large_diff_sections(left: FileSnapshot, right: FileSnapshot) -> str:
    """Render capped block-based detail sections for very large file pairs."""
    blocks, total_blocks = build_position_diff_blocks(left, right)
    if not blocks:
        return '<p class="empty">No line-level differences found.</p>'

    note = (
        f'<p class="muted">Large-file mode is active. Showing {len(blocks)} of {total_blocks} changed blocks using line-position windows.</p>'
        if total_blocks > len(blocks)
        else '<p class="muted">Large-file mode is active. Detailed sections are rendered as bounded line-position windows.</p>'
    )
    body = ''.join(render_large_diff_block(left, right, block, index) for index, block in enumerate(blocks, start=1))
    return note + body


def render_diff_sections(files: Sequence[FileSnapshot], stats_list: Sequence[PairwiseStats]) -> str:
    """Render three collapsible side-by-side HTML diff tables."""
    sections = []
    for (left, right), stats in zip(((files[0], files[1]), (files[0], files[2]), (files[1], files[2])), stats_list):
        # HtmlDiff remains useful for small inputs, but very large files need a
        # bounded renderer so report generation finishes in reasonable time.
        if stats.comparison_mode == "large-file":
            diff_table = render_large_diff_sections(left, right)
        else:
            diff_table = difflib.HtmlDiff(wrapcolumn=120).make_table(
                left.lines,
                right.lines,
                fromdesc=f"{left.label}: {left.path.name}",
                todesc=f"{right.label}: {right.path.name}",
                context=True,
                numlines=3,
            )
        sections.append(
            f"""
            <details class=\"diff-panel\">
              <summary>
                <span>{as_html(left.label)} vs {as_html(right.label)}</span>
                <span class=\"muted\">{format_percent(stats.similarity_ratio)} similar, {stats.changed_blocks} changed blocks</span>
              </summary>
              <div class=\"diff-wrap\">{diff_table}</div>
            </details>
            """
        )
    return "".join(sections)


def build_html_report(
    files: Sequence[FileSnapshot],
    include_detailed_diffs: bool = True,
    compact_student_details: bool = False,
) -> str:
    """Assemble the complete HTML document for the three-file comparison."""
    file_labels = [snapshot.label for snapshot in files]
    stats_list = [
        compare_pair(files[0], files[1]),
        compare_pair(files[0], files[2]),
        compare_pair(files[1], files[2]),
    ]
    shared_all, unique_1, unique_2, unique_3 = count_shared_line_occurrences(files)
    unique_examples = triage_examples(files, limit=8)
    student_analysis = analyze_student_blocks(files)
    student_block_section = (
        render_student_block_section(
            student_analysis,
            file_labels,
            compact_student_details=compact_student_details,
        )
        if student_analysis
        else ""
    )
    detailed_diffs_section = (
        render_diff_sections(files, stats_list)
        if include_detailed_diffs
        else '<p class="empty">Detailed diffs were skipped to keep this report compact. Re-run without --skip-detailed-diffs to include them.</p>'
    )

    return f"""
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Three File Diff Report</title>
  <style>
    :root {{
      --paper: #f8f4ec;
      --ink: #1f2933;
      --panel: rgba(255, 252, 247, 0.92);
      --line: #d9ccb6;
      --accent: #155e75;
      --accent-soft: #d8eef2;
      --warm: #b45309;
      --shadow: 0 10px 35px rgba(68, 54, 34, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(21, 94, 117, 0.14), transparent 28%),
        radial-gradient(circle at top right, rgba(180, 83, 9, 0.12), transparent 24%),
        linear-gradient(180deg, #f4efe4 0%, var(--paper) 48%, #f6f3ee 100%);
      font-family: Georgia, Cambria, "Times New Roman", serif;
      line-height: 1.45;
    }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 64px 40px 80px; }}
    h1, h2, h3, summary {{ font-family: "Segoe UI Semibold", "Trebuchet MS", sans-serif; }}
    h1 {{ margin: 0; font-size: clamp(2rem, 3vw, 3.2rem); line-height: 1.05; }}
    h2 {{ margin: 0 0 14px; font-size: 1.4rem; }}
    h3 {{ margin: 0 0 10px; font-size: 1.1rem; }}
    p {{ margin: 0; }}
    code {{ font-family: Consolas, "Courier New", monospace; font-size: 0.92em; }}
    .hero {{
      background: var(--panel);
      border: 1px solid rgba(217, 204, 182, 0.9);
      border-radius: 20px;
            padding: 32px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(6px);
            margin-bottom: 36px;
    }}
    .hero p {{ margin-top: 12px; max-width: 70ch; color: #4b5563; }}
        .grid {{ display: grid; gap: 20px; margin-top: 22px; }}
    .grid.cols-3 {{ grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
    .grid.cols-2 {{ grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }}
    .stat-card, .section-panel {{
      background: var(--panel);
      border: 1px solid rgba(217, 204, 182, 0.9);
      border-radius: 18px;
            padding: 22px;
      box-shadow: var(--shadow);
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.72rem;
      color: var(--warm);
      margin-bottom: 8px;
    }}
    .muted {{ color: #5f6b76; }}
    .metrics {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }}
    .metrics span {{
      background: var(--accent-soft);
      color: var(--accent);
      border-radius: 999px;
      padding: 6px 10px;
      font-family: "Segoe UI", sans-serif;
      font-size: 0.92rem;
    }}
    .section-heading {{ margin-top: 42px; margin-bottom: 18px; }}
    .kpi-strip {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 18px; }}
    .kpi {{
      background: linear-gradient(135deg, rgba(21, 94, 117, 0.08), rgba(180, 83, 9, 0.08));
      border: 1px solid rgba(217, 204, 182, 0.9);
      border-radius: 16px;
      padding: 16px;
    }}
    .kpi strong {{ display: block; font-size: 1.7rem; font-family: "Segoe UI Semibold", sans-serif; }}
    .example-list {{ margin: 0; padding-left: 18px; }}
    .example-list li {{ margin: 8px 0; }}
    .student-id-list {{ margin: 12px 0 0; padding-left: 18px; max-height: 260px; overflow: auto; }}
    .student-id-list li {{ margin: 6px 0; }}
    .record-separator {{ display: inline-block; min-width: 1.5rem; }}
    .bucket-card {{ margin: 16px 0; background: rgba(255, 255, 255, 0.72); border: 1px solid #e7dcc8; border-radius: 14px; overflow: hidden; }}
    .bucket-card summary {{ cursor: pointer; list-style: none; padding: 12px 14px; display: flex; justify-content: space-between; gap: 12px; align-items: center; background: linear-gradient(90deg, rgba(21, 94, 117, 0.08), rgba(255, 252, 247, 0)); font-family: "Segoe UI Semibold", "Trebuchet MS", sans-serif; position: relative; padding-right: 40px; }}
    .bucket-card summary::after, .student-card summary::after {{ content: "▸"; position: absolute; right: 14px; top: 50%; transform: translateY(-50%); color: #5f6b76; font-size: 1rem; transition: transform 0.15s ease; }}
    .bucket-card[open] summary::after, .student-card[open] summary::after {{ transform: translateY(-50%) rotate(90deg); }}
    .bucket-card > p, .bucket-card > ul {{ margin-left: 14px; margin-right: 14px; }}
    .bucket-card > p {{ margin-top: 10px; margin-bottom: 6px; }}
    .bucket-card .bucket-count {{ background: #e8f0ef; color: #28424a; border-radius: 999px; padding: 2px 10px; font-size: 0.88rem; }}
    .controls {{ margin: 12px 0; }}
    .controls input {{ width: min(460px, 100%); padding: 10px 12px; border-radius: 10px; border: 1px solid #d9ccb6; background: rgba(255, 255, 255, 0.92); }}
    .color-legend {{ margin: 12px 0 8px; display: flex; flex-wrap: wrap; gap: 8px; }}
    .legend-item {{ display: inline-block; padding: 3px 10px; border-radius: 999px; color: #1f2933; font-family: "Segoe UI", sans-serif; font-size: 0.86rem; border: 1px solid transparent; }}
    .legend-12 {{ background: #f7d7b5; border-color: #e8be8f; }}
    .legend-23 {{ background: #f7ec9a; border-color: #e7d972; }}
    .legend-mixed {{ background: #e7e5ff; border-color: #cfc9ff; }}
    .legend-program-number {{ background: #d9f3df; border-color: #a9d8b6; }}
    .legend-program-code {{ background: #dbeafe; border-color: #93c5fd; }}
    .legend-program-added {{ background: #fde68a; border-color: #f59e0b; }}
    .listing-table {{ width: 100%; border-collapse: collapse; background: white; margin-top: 12px; table-layout: fixed; }}
    .student-card {{ margin: 16px 0; background: rgba(255, 255, 255, 0.72); border: 1px solid #e7dcc8; border-radius: 14px; overflow: hidden; }}
    .student-card summary {{ cursor: pointer; list-style: none; padding: 14px 16px; display: flex; justify-content: space-between; gap: 12px; align-items: center; background: linear-gradient(90deg, rgba(21, 94, 117, 0.08), rgba(255, 252, 247, 0)); position: relative; padding-right: 42px; }}
    .student-title {{ font-weight: 700; }}
    .student-meta {{ color: #5f6b76; font-size: 0.95rem; }}
    .student-body {{ padding: 0 14px 14px; overflow-x: auto; }}
    .block-card {{ margin: 18px 0; padding: 18px; background: rgba(255, 255, 255, 0.65); border: 1px solid #e7dcc8; border-radius: 14px; }}
    .diff-panel {{
      background: var(--panel);
      border: 1px solid rgba(217, 204, 182, 0.9);
      border-radius: 18px;
      padding: 0;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    .diff-panel + .diff-panel {{ margin-top: 14px; }}
    .diff-panel summary {{
      cursor: pointer;
      list-style: none;
      padding: 16px 18px;
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: center;
      background: linear-gradient(90deg, rgba(21, 94, 117, 0.08), rgba(255, 252, 247, 0));
    }}
    .diff-wrap {{ overflow-x: auto; padding: 8px 10px 16px; }}
    table.diff {{ width: 100%; border-collapse: collapse; font-family: Consolas, "Courier New", monospace; font-size: 0.88rem; }}
    .line-diff-table {{ width: 100%; border-collapse: collapse; font-family: Consolas, "Courier New", monospace; font-size: 0.84rem; background: white; }}
    .diff_header {{ background: #e8f0ef; color: #28424a; }}
    td.diff_header {{ text-align: right; }}
    .diff_next {{ background: #f4ead8; }}
    .diff_add {{ background: #dff4e4; }}
    .diff_chg {{ background: #fff0b9; }}
    .diff_sub {{ background: #f8d7da; }}
    .diff td, .diff th, .line-diff-table td, .line-diff-table th, .listing-table td, .listing-table th {{ padding: 6px 8px; border: 1px solid #e7dcc8; vertical-align: top; }}
    .line-no {{ width: 44px; text-align: right; color: #6b7280; white-space: nowrap; }}
    .listing-table th:first-child, .listing-table td.line-no {{ width: 44px; }}
    .listing-table th:not(:first-child), .listing-table td:not(.line-no) {{ width: 33%; }}
    .listing-table code {{ display: block; white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word; }}
    .listing-table td.pair-12-diff {{ background: #f7d7b5; }}
    .listing-table td.pair-23-diff {{ background: #f7ec9a; }}
    .listing-table td.pair-12-gap {{ background: #fbe9d7; }}
    .listing-table td.pair-23-gap {{ background: #fbf4cf; }}
    .listing-table td.pair-12-diff.pair-23-diff {{ background: linear-gradient(90deg, #f7d7b5 0 50%, #f7ec9a 50% 100%); }}
    .listing-table td.pair-12-gap.pair-23-gap {{ background: linear-gradient(90deg, #fbe9d7 0 50%, #fbf4cf 50% 100%); }}
    .listing-table td.pair-12-diff.pair-23-gap {{ background: linear-gradient(90deg, #f7d7b5 0 50%, #fbf4cf 50% 100%); }}
    .listing-table td.pair-12-gap.pair-23-diff {{ background: linear-gradient(90deg, #fbe9d7 0 50%, #f7ec9a 50% 100%); }}
    .listing-table .line-no {{ color: #1f2933; }}
        .student-meta .meta-scope-12, .student-meta .meta-scope-23, .student-meta .meta-scope-mixed, .student-meta .meta-program-number, .student-meta .meta-program-code, .student-meta .meta-program-added, .student-meta .meta-missing-dtp007 {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 999px;
            color: #1f2933;
            font-weight: 700;
            border: 1px solid transparent;
        }}
        .student-meta .meta-scope-12 {{ background: #f7d7b5; border-color: #e8be8f; }}
        .student-meta .meta-scope-23 {{ background: #f7ec9a; border-color: #e7d972; }}
        .student-meta .meta-scope-mixed {{ background: #e7e5ff !important; border-color: #cfc9ff !important; }}
        .student-meta .meta-program-number {{ background: #d9f3df; border-color: #a9d8b6; }}
        .student-meta .meta-program-code {{ background: #dbeafe; border-color: #93c5fd; }}
        .student-meta .meta-program-added {{ background: #fde68a; border-color: #f59e0b; }}
        .student-meta .meta-missing-dtp007, .legend-missing-dtp007 {{ background: #fee2e2; border-color: #ef4444; }}
    .line-diff-table tr.same {{ background: #faf7f2; }}
    .line-diff-table tr.change {{ background: #fff0b9; }}
    .line-diff-table tr.insert {{ background: #dff4e4; }}
    .line-diff-table tr.delete {{ background: #f8d7da; }}
    .line-diff-table tr.truncated {{ background: #f4ead8; font-family: "Segoe UI", sans-serif; }}
    .status-chip {{ display: inline-block; padding: 4px 8px; border-radius: 999px; font-family: "Segoe UI", sans-serif; font-size: 0.86rem; white-space: nowrap; }}
    .status-missing {{ background: #f8d7da; color: #7f1d1d; }}
    .status-group-1 {{ background: #d8eef2; color: #155e75; }}
    .status-group-2 {{ background: #fff0b9; color: #92400e; }}
    .status-group-3 {{ background: #e7e5ff; color: #4338ca; }}
    .status-generic {{ background: #eceff3; color: #334155; }}
    @media (max-width: 720px) {{
            main {{ padding: 32px 18px 48px; }}
            .hero {{ padding: 22px; }}
      .diff-panel summary {{ align-items: flex-start; flex-direction: column; }}
    }}
  </style>
 </head>
 <body>
     <main>
            <section class="hero">
                <p class="eyebrow">Three-file comparison</p>
                <h1>Three File Diff Report</h1>
                <p>Student-level comparison across three files with normalization for runtime-only differences.</p>
            </section>

                    {student_block_section}

            <section>
                <h2 class="section-heading">Files</h2>
                <div class="grid cols-3">{render_file_cards(files)}</div>
            </section>

            <section>
                <h2 class="section-heading">Pairwise summary</h2>
                <div class="grid cols-3">{render_pairwise_cards(stats_list)}</div>
            </section>

            <section>
                <h2 class="section-heading">Unique line samples</h2>
                <div class="grid cols-3">{render_unique_examples(unique_examples)}</div>
            </section>

            <section>
                <h2 class="section-heading">Line-by-Line File Comparison</h2>
                {detailed_diffs_section}
            </section>

            <section>
                <h2 class="section-heading">Overall Content Summary</h2>
                <div class="kpi-strip">
                    <div class="kpi"><span class="eyebrow">Shared in all files</span><strong>{shared_all}</strong><span>line entries found in all three files</span></div>
                    <div class="kpi"><span class="eyebrow">Only in {as_html(files[0].label)}</span><strong>{unique_1}</strong><span>line entries found only in this file</span></div>
                    <div class="kpi"><span class="eyebrow">Only in {as_html(files[1].label)}</span><strong>{unique_2}</strong><span>line entries found only in this file</span></div>
                    <div class="kpi"><span class="eyebrow">Only in {as_html(files[2].label)}</span><strong>{unique_3}</strong><span>line entries found only in this file</span></div>
                </div>
    </section>

        </main>
    <script>
        function filterStudentRows() {{
            const input = document.getElementById('studentBlockFilter');
            if (!input) {{
                return;
            }}
            const query = input.value.toLowerCase().trim();
            document.querySelectorAll('.student-filter-item').forEach((item) => {{
                const haystack = (item.dataset.search || '').toLowerCase();
                item.style.display = !query || haystack.includes(query) ? '' : 'none';
            }});
        }}
    </script>
</body>
</html>
"""


def minify_html_document(document: str) -> str:
    """Minify HTML while preserving script/style blocks verbatim."""
    protected_blocks: List[str] = []

    def protect_block(match: re.Match[str]) -> str:
        protected_blocks.append(match.group(0))
        return f"__HTML_BLOCK_{len(protected_blocks) - 1}__"

    # Avoid rewriting whitespace-sensitive JS/CSS content.
    working = re.sub(r"(?is)<(script|style)\b.*?</\1>", protect_block, document)
    working = re.sub(r">\s+<", "><", working)
    working = re.sub(r"\n{2,}", "\n", working).strip()

    for index, block in enumerate(protected_blocks):
        working = working.replace(f"__HTML_BLOCK_{index}__", block)

    return working


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the three input files and output options."""
    parser = argparse.ArgumentParser(
        description="Compare three text files and write an HTML report with pairwise diffs.",
    )
    parser.add_argument("file_a", help="First input file path")
    parser.add_argument("file_b", help="Second input file path")
    parser.add_argument("file_c", help="Third input file path")
    parser.add_argument(
        "-o",
        "--output",
        default="three_file_diff_report.html",
        help="Output HTML path. Default: %(default)s",
    )
    parser.add_argument(
        "--labels",
        nargs=3,
        metavar=("LABEL_A", "LABEL_B", "LABEL_C"),
        help="Optional labels to use in the report instead of File A/B/C.",
    )
    parser.add_argument(
        "--skip-detailed-diffs",
        action="store_true",
        help="Skip large pairwise detailed diff tables to reduce report size.",
    )
    parser.add_argument(
        "--compact-student-details",
        action="store_true",
        help="Render only substantive student rows with small context to reduce output size.",
    )
    parser.add_argument(
        "--minify-output",
        action="store_true",
        help="Minify final HTML to reduce file size while preserving rendered output.",
    )
    return parser.parse_args()


def main() -> int:
    """Entry point: load files, build the report, and write it to disk."""
    args = parse_args()
    labels = args.labels or ["File A", "File B", "File C"]
    files = [
        build_snapshot(args.file_a, labels[0]),
        build_snapshot(args.file_b, labels[1]),
        build_snapshot(args.file_c, labels[2]),
    ]

    report_html = build_html_report(
        files,
        include_detailed_diffs=not args.skip_detailed_diffs,
        compact_student_details=args.compact_student_details,
    )
    if args.minify_output:
        report_html = minify_html_document(report_html)
    output_path = Path(args.output).expanduser().resolve()
    output_path.write_text(report_html, encoding="utf-8")
    print(f"Wrote HTML report to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())