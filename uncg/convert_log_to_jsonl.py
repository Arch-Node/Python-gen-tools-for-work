#!/usr/bin/env python3
"""CLI converter: plain-text log file -> JSONL output file."""

import argparse

from log_json_tools import convert_text_log_to_jsonl


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert plain text logs to JSONL events.")
    parser.add_argument("--input", required=True, help="Input plain-text log file path")
    parser.add_argument("--output", required=True, help="Output JSONL file path")
    parser.add_argument("--app", required=True, help="Application name (for example: repoprep)")
    parser.add_argument("--component", required=True, help="Component name (for example: installer)")
    parser.add_argument("--run-id", default="", help="Optional run identifier")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    converted_count = convert_text_log_to_jsonl(
        input_path=args.input,
        output_path=args.output,
        app=args.app,
        component=args.component,
        run_id=args.run_id or None,
    )

    print(f"Converted {converted_count} lines to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
