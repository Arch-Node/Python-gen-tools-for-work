#!/usr/bin/env python3

# =============================================================================
# PSEUDOCODE - HOW TO USE THIS SCRIPT
# =============================================================================
#
# PURPOSE:
#   Convert a JSON file into a searchable HTML report with:
#     1) root-level run parameters (scalar values)
#     2) expandable nested sections for dict/list content
#     3) search/filter support in the browser
#
# QUICK COMMANDS:
#   Generate report:
#     python "json_to html.py" --input /path/input.json --output /path/report.html
#
#   Generate report with custom page title:
#     python "json_to html.py" --input /path/input.json --output /path/report.html --title "UC4 Runtime Report"
#
#   Run built-in unit tests:
#     python "json_to html.py" --run-tests
#
# HIGH-LEVEL FLOW:
#   main()
#     -> parse CLI args
#     -> if --run-tests: execute _run_tests() and exit
#     -> validate --input and --output
#     -> call json_to_html(input_path, output_path, title)
#
#   json_to_html(...)
#     -> parse JSON from disk using _parse_json()
#     -> render nested JSON into HTML blocks using _render_node()
#     -> build root scalar summary rows via _build_run_parameters()
#     -> combine template + CSS + JS + rendered content via _build_page()
#     -> write final HTML report to output path
#     -> log summary counts and generation timing
#
# TEMPLATE FILES USED (in templates/):
#   - json_report_template.html  : page structure with placeholders
#   - json_report.css            : stylesheet
#   - json_report.js             : client-side search and expand/collapse logic
#
# NOTES:
#   - HTML escaping is applied before injecting values into markup.
#   - Missing template files raise clear FileNotFoundError messages.
#   - The output is static HTML, easy to attach to job artifacts.
#
# =============================================================================

import argparse
from datetime import datetime, timezone
import html
import json
import logging
import os
import time


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_DIR = os.path.join(_SCRIPT_DIR, 'templates')
_HTML_TEMPLATE_FILE = os.path.join(_TEMPLATE_DIR, 'json_report_template.html')
_CSS_TEMPLATE_FILE = os.path.join(_TEMPLATE_DIR, 'json_report.css')
_JS_TEMPLATE_FILE = os.path.join(_TEMPLATE_DIR, 'json_report.js')


def _escape_text(raw_value):
        """Escape text before HTML injection to prevent malformed markup or script injection.

        Why: This report renders runtime data that can include special characters; escaping
        guarantees safe, predictable output.
        """
        return html.escape(str(raw_value), quote=True)


def _is_json_container(candidate_value):
        """Identify container-like JSON values.

        Why: The report treats scalars and containers differently, so this helper keeps
        that branching explicit and reusable.
        """
        return isinstance(candidate_value, (dict, list))


def _parse_json(json_file_path):
        """Load a JSON document from disk with explicit path validation.

        Why: Failing fast with a clear path-based error makes UC4 troubleshooting easier
        than surfacing a generic file-open failure later in rendering.
        """
        if not json_file_path or not os.path.isfile(json_file_path):
                raise FileNotFoundError(f'JSON file not found: {json_file_path}')

        with open(json_file_path, 'r', encoding='utf-8') as json_file_handle:
                parsed_json_data = json.load(json_file_handle)
        return parsed_json_data


def _flatten_paths(json_data, current_path='root'):
    """Flatten nested JSON into leaf path/value pairs.

    Why: Flattened leaves provide stable counts and diagnostics that are useful for
    log visibility and test assertions.
    """
    flattened_leaf_rows = []
    if isinstance(json_data, dict):
        for child_key, child_value in json_data.items():
            child_path = f'{current_path}.{child_key}'
            flattened_leaf_rows.extend(_flatten_paths(child_value, child_path))
    elif isinstance(json_data, list):
        for child_index, child_value in enumerate(json_data):
            child_path = f'{current_path}[{child_index}]'
            flattened_leaf_rows.extend(_flatten_paths(child_value, child_path))
    else:
        flattened_leaf_rows.append({'path': current_path, 'value': '' if json_data is None else str(json_data)})
    return flattened_leaf_rows


def _render_node(json_node, node_path='root', depth=0):
        """Render one JSON node (and its children) into searchable HTML blocks.

        Why: A recursive renderer keeps nested data readable in a browser while preserving
        full path context for search and diagnostics.
        """
        depth_class_name = f'depth-{depth}'
        escaped_node_path = _escape_text(node_path)

        if isinstance(json_node, dict):
                if not json_node:
                        return (
                                f'<div class="item {depth_class_name}" data-search="{escaped_node_path} empty object">'
                                f'<span class="key">{escaped_node_path}</span>: '
                                f'<span class="value empty">{{}}</span>'
                                '</div>'
                        )

                rendered_segments = [
                        f'<details class="group {depth_class_name}" data-search="{escaped_node_path}" open>',
                        f'<summary><span class="key">{escaped_node_path}</span> '
                        f'<span class="type-tag">object ({len(json_node)})</span></summary>'
                ]
                for child_key, child_value in json_node.items():
                        child_path = f'{node_path}.{child_key}'
                        rendered_segments.append(_render_node(child_value, node_path=child_path, depth=depth + 1))
                rendered_segments.append('</details>')
                return ''.join(rendered_segments)

        if isinstance(json_node, list):
                if not json_node:
                        return (
                                f'<div class="item {depth_class_name}" data-search="{escaped_node_path} empty list">'
                                f'<span class="key">{escaped_node_path}</span>: '
                                f'<span class="value empty">[]</span>'
                                '</div>'
                        )

                rendered_segments = [
                        f'<details class="group {depth_class_name}" data-search="{escaped_node_path}" open>',
                        f'<summary><span class="key">{escaped_node_path}</span> '
                        f'<span class="type-tag">list ({len(json_node)})</span></summary>'
                ]
                for child_index, child_value in enumerate(json_node):
                        child_path = f'{node_path}[{child_index}]'
                        rendered_segments.append(_render_node(child_value, node_path=child_path, depth=depth + 1))
                rendered_segments.append('</details>')
                return ''.join(rendered_segments)

        scalar_text = '' if json_node is None else str(json_node)
        search_text_blob = _escape_text(f'{node_path} {scalar_text}')
        return (
                f'<div class="item {depth_class_name}" data-search="{search_text_blob}">'
                f'<span class="key">{escaped_node_path}</span>: '
                f'<span class="value">{_escape_text(scalar_text)}</span>'
                '</div>'
        )


def _build_run_parameters(json_data):
        """Extract root-level scalar values for the run-parameter summary panel.

        Why: Operators typically want quick top-level context first before expanding
        deeply nested objects.
        """
        if not isinstance(json_data, dict):
                return []

        run_parameter_rows = []
        for top_level_key, top_level_value in json_data.items():
                if not _is_json_container(top_level_value):
                        run_parameter_rows.append({'path': f'root.{top_level_key}', 'value': '' if top_level_value is None else str(top_level_value)})
        return run_parameter_rows


def _build_page(page_title, rendered_body_html, summary_rows, source_json_file_path):
        """Assemble the final HTML page from external templates and computed content.

        Why: Keeping CSS/JS/HTML templates outside Python makes the presentation layer
        easier to maintain without touching rendering logic.
        """

        def _read_template_text(template_file_path):
                if not os.path.isfile(template_file_path):
                        raise FileNotFoundError(f'Template file not found: {template_file_path}')
                with open(template_file_path, 'r', encoding='utf-8') as template_file_handle:
                        return template_file_handle.read()

        generated_timestamp_utc = datetime.now(timezone.utc).isoformat()
        summary_rows_html = ''.join(
                '<div class="summary-row">'
                f'<span class="summary-key">{_escape_text(summary_item["path"])}</span>'
                f'<span class="summary-value">{_escape_text(summary_item["value"])}</span>'
                '</div>'
                for summary_item in summary_rows
        )
        if not summary_rows_html:
                summary_rows_html = (
                        '<div class="summary-row"><span class="summary-key">None</span>'
                        '<span class="summary-value">No root scalar values found.</span></div>'
                )

        html_template_text = _read_template_text(_HTML_TEMPLATE_FILE)
        css_template_text = _read_template_text(_CSS_TEMPLATE_FILE)
        js_template_text = _read_template_text(_JS_TEMPLATE_FILE)

        placeholder_replacements = {
                '{{TITLE}}': _escape_text(page_title),
                '{{CSS_CONTENT}}': css_template_text,
                '{{JS_CONTENT}}': js_template_text,
                '{{SOURCE_NAME}}': _escape_text(os.path.basename(source_json_file_path)),
                '{{GENERATED_AT}}': _escape_text(generated_timestamp_utc),
                '{{SUMMARY_COUNT}}': str(len(summary_rows)),
                '{{SUMMARY_HTML}}': summary_rows_html,
                '{{BODY_HTML}}': rendered_body_html,
        }

        compiled_page_html = html_template_text
        for placeholder_token, replacement_value in placeholder_replacements.items():
                compiled_page_html = compiled_page_html.replace(placeholder_token, replacement_value)

        return compiled_page_html


def find_key_index_values(json_data, target_key):
        """Collect all values for a given key across nested dict/list structures.

        Why: This utility supports quick record lookups for troubleshooting without
        requiring users to manually traverse complex JSON paths.
        """
        matching_values = []
        if isinstance(json_data, dict):
                if target_key in json_data:
                        matching_values.append(json_data[target_key])
                for child_value in json_data.values():
                        if isinstance(child_value, (dict, list)):
                                matching_values.extend(find_key_index_values(child_value, target_key))
        elif isinstance(json_data, list):
                for child_value in json_data:
                        if isinstance(child_value, (dict, list)):
                                matching_values.extend(find_key_index_values(child_value, target_key))
        return matching_values


def json_to_html(json_file_path, output_html_file_path, page_title='JSON Runtime Report'):
        """Convert a JSON file into a styled, searchable HTML report.

        Why: A static HTML artifact is easy to attach to job runs and share during
        incident analysis without requiring Python tooling on the viewer side.
        """
        generation_start_time = time.perf_counter()
        parsed_json_data = _parse_json(json_file_path)
        rendered_body_html = _render_node(parsed_json_data)
        summary_rows = _build_run_parameters(parsed_json_data)

        output_directory_path = os.path.dirname(os.path.abspath(output_html_file_path))
        if output_directory_path:
                os.makedirs(output_directory_path, exist_ok=True)

        compiled_page_html = _build_page(page_title, rendered_body_html, summary_rows, source_json_file_path=json_file_path)
        with open(output_html_file_path, 'w', encoding='utf-8') as output_html_file_handle:
                output_html_file_handle.write(compiled_page_html)

        flattened_leaf_count = len(_flatten_paths(parsed_json_data))
        generation_duration_ms = (time.perf_counter() - generation_start_time) * 1000
        logging.info(
                'Wrote HTML report to %s (summary_rows=%s, flattened_leaf_nodes=%s, duration_ms=%.1f)',
                output_html_file_path,
                len(summary_rows),
                flattened_leaf_count,
                generation_duration_ms,
        )


def _build_cli_parser():
        """Construct command-line arguments for conversion and local test execution.

        Why: Keeping parser setup in one place simplifies future CLI changes and keeps
        main focused on execution flow.
        """
        argument_parser = argparse.ArgumentParser(description='Convert JSON into a searchable, expandable HTML report.')
        argument_parser.add_argument('--input', dest='input_json', help='Path to input JSON file.')
        argument_parser.add_argument('--output', dest='output_html', help='Path to output HTML file.')
        argument_parser.add_argument('--title', dest='title', default='JSON Runtime Report', help='Page title for the HTML report.')
        argument_parser.add_argument('--run-tests', action='store_true', help='Run built-in unit tests and exit.')
        return argument_parser


def _run_tests():
        """Execute built-in unit tests for local verification.

        Why: Keeping fast tests in the script allows teams to validate behavior quickly
        on hosts where a separate test runner may not be configured.
        """
        import tempfile
        import unittest

        class JsonToHtmlTests(unittest.TestCase):
                def test_parse_json_file_not_found(self):
                        with self.assertRaises(FileNotFoundError):
                                _parse_json('/tmp/this_file_should_not_exist_1234.json')

                def test_find_key_index_values_handles_dict_and_list(self):
                        nested_json_data = {'a': {'id': 1}, 'b': [{'id': 2}, {'x': 7}]}
                        self.assertEqual(find_key_index_values(nested_json_data, 'id'), [1, 2])

                def test_render_escapes_html(self):
                        rendered_html = _render_node({'x': '<script>alert(1)</script>'})
                        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', rendered_html)
                        self.assertNotIn('<script>alert(1)</script>', rendered_html)

                def test_build_run_parameters_root_scalars_only(self):
                        run_parameters = _build_run_parameters({'a': 1, 'b': {'c': 2}, 'd': [1, 2], 'e': 'ok'})
                        self.assertEqual(run_parameters, [{'path': 'root.a', 'value': '1'}, {'path': 'root.e', 'value': 'ok'}])

                def test_json_to_html_writes_file(self):
                        with tempfile.TemporaryDirectory() as temporary_directory:
                                input_json_path = os.path.join(temporary_directory, 'in.json')
                                output_html_path = os.path.join(temporary_directory, 'out.html')

                                with open(input_json_path, 'w', encoding='utf-8') as input_json_handle:
                                        json.dump({'job': {'id': 100}, 'status': 'ok'}, input_json_handle)

                                json_to_html(input_json_path, output_html_path, page_title='Test Report')

                                self.assertTrue(os.path.isfile(output_html_path))
                                with open(output_html_path, 'r', encoding='utf-8') as output_html_handle:
                                        output_html = output_html_handle.read()

                                self.assertIn('Test Report', output_html)
                                self.assertIn('root.job.id', output_html)
                                self.assertIn('root.status', output_html)

                def test_flatten_paths_handles_scalar_root(self):
                        flattened_rows = _flatten_paths('hello')
                        self.assertEqual(flattened_rows, [{'path': 'root', 'value': 'hello'}])

        unit_test_suite = unittest.defaultTestLoader.loadTestsFromTestCase(JsonToHtmlTests)
        return unittest.TextTestRunner(verbosity=2).run(unit_test_suite)


def main():
    """Entry point for CLI execution.

    Why: Centralizing execution flow keeps argument validation, test execution, and
    runtime error handling explicit and easy to follow.
    """
    cli_parser = _build_cli_parser()
    parsed_arguments = cli_parser.parse_args()

    if parsed_arguments.run_tests:
        test_result = _run_tests()
        raise SystemExit(0 if test_result.wasSuccessful() else 1)

    if not parsed_arguments.input_json or not parsed_arguments.output_html:
        cli_parser.error('--input and --output are required unless --run-tests is used.')

    try:
        json_to_html(parsed_arguments.input_json, parsed_arguments.output_html, page_title=parsed_arguments.title)
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        logging.error('Failed to generate HTML report: %s', error)
        raise SystemExit(1)


if __name__ == '__main__':
        main()


