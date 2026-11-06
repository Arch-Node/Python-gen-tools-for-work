import argparse
from html import escape, unescape
import re
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup, Comment, Doctype, Tag
from bs4.element import NavigableString


class HtmlMarkdownConverter:
    def convert(self, html_content):
        soup = BeautifulSoup(html_content, "html.parser")
        markdown = self._render_children(soup)
        markdown = self._clean_output(markdown)
        return self._clean_output(self._filter_unreferenced_anchors(markdown))

    def _render(self, node):
        rendered = self._render_node(node)
        return self._add_anchor(node, rendered)

    def _render_node(self, node):
        if isinstance(node, (Comment, Doctype)):
            return ""
        if isinstance(node, NavigableString):
            return self._render_text(str(node))
        if not isinstance(node, Tag):
            return ""

        name = node.name.lower()
        if name in {"head", "script", "style", "title"}:
            return ""
        if name == "pre":
            return self._fenced_code(node.get_text())
        if name == "table":
            return self._render_table(node)
        if name in {"ul", "ol"}:
            content = self._render_list(node)
            return f"\n\n{content}\n\n" if content else ""
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(name[1])
            text = self._render_inline_children(node).strip()
            return f"\n\n{'#' * level} {text}\n\n" if text else ""
        if name == "p":
            text = self._render_inline_children(node).strip()
            return f"\n\n{text}\n\n" if text else ""
        if name == "br":
            return "  \n"
        if name == "hr":
            return "\n\n---\n\n"
        if name == "blockquote":
            text = self._render_children(node).strip()
            quoted = "\n".join(f"> {line}" for line in text.splitlines())
            return f"\n\n{quoted}\n\n" if quoted else ""

        if name in {"strong", "b"}:
            text = self._render_inline_children(node).strip()
            return f"**{text}**" if text else ""
        if name in {"em", "i"}:
            text = self._render_inline_children(node).strip()
            return f"*{text}*" if text else ""
        if name == "code" or (
            name == "span" and self._has_class(node, "filepath")
        ):
            return self._code_span(node.get_text())
        if name == "a":
            text = self._render_inline_children(node).strip()
            href = node.get("href")
            if not text:
                return ""
            if not href:
                return text
            destination = str(href).replace("(", r"\(").replace(")", r"\)")
            return f"[{text}]({destination})"
        if name == "img":
            return self._render_image(node)
        if name == "div" and self._has_class(node, "p"):
            return self._render_paragraph_div(node)

        content = self._render_children(node)
        if name in {
            "address", "article", "aside", "body", "div", "footer", "header",
            "main", "nav", "section",
        }:
            content = content.strip()
            return f"\n\n{content}\n\n" if content else ""
        return content

    def _render_children(self, node):
        return "".join(self._render(child) for child in node.children)

    def _render_paragraph_div(self, node):
        blocks = []
        inline_children = []

        for child in node.children:
            is_block = (
                isinstance(child, Tag)
                and child.name.lower() in {"ol", "pre", "table", "ul"}
            )
            if not is_block:
                inline_children.append(child)
                continue

            inline_text = "".join(
                self._render_inline(item) for item in inline_children
            ).strip()
            if inline_text:
                blocks.append(inline_text)
            inline_children.clear()

            rendered_block = self._render(child).strip()
            if rendered_block:
                blocks.append(rendered_block)

        inline_text = "".join(
            self._render_inline(item) for item in inline_children
        ).strip()
        if inline_text:
            blocks.append(inline_text)

        content = "\n\n".join(blocks)
        return f"\n\n{content}\n\n" if content else ""

    def _render_inline(self, node):
        rendered = self._render_inline_node(node)
        return self._add_anchor(node, rendered)

    def _render_inline_node(self, node):
        if isinstance(node, (Comment, Doctype)):
            return ""
        if isinstance(node, NavigableString):
            return self._render_text(str(node))
        if not isinstance(node, Tag):
            return ""

        name = node.name.lower()
        if name in {"code", "pre"} or (
            name == "span" and self._has_class(node, "filepath")
        ):
            return self._code_span(node.get_text())
        if name in {"strong", "b"}:
            text = self._render_inline_children(node).strip()
            return f"**{text}**" if text else ""
        if name in {"em", "i"}:
            text = self._render_inline_children(node).strip()
            return f"*{text}*" if text else ""
        if name == "a":
            text = self._render_inline_children(node).strip()
            href = node.get("href")
            if not text:
                return ""
            if not href:
                return text
            destination = str(href).replace("(", r"\(").replace(")", r"\)")
            return f"[{text}]({destination})"
        if name == "img":
            return self._render_image(node)
        if name == "br":
            return " "
        return self._render_inline_children(node)

    def _render_inline_children(self, node):
        return "".join(self._render_inline(child) for child in node.children)

    @staticmethod
    def _add_anchor(node, rendered):
        if not isinstance(node, Tag) or node.find_parent("table") is not None:
            return rendered
        anchor_id = node.get("id")
        if not anchor_id:
            return rendered
        anchor = f'<a id="{escape(str(anchor_id), quote=True)}"></a>'
        return f"{anchor}{rendered}" if rendered.strip() else anchor

    @staticmethod
    def _render_image(node):
        alt = str(node.get("alt", ""))
        source = str(node.get("src", ""))
        if source.lower().startswith("data:"):
            return alt
        return f"![{alt}]({source})" if alt or source else ""

    def _render_list(self, list_tag, depth=0):
        ordered = list_tag.name.lower() == "ol"
        number = int(list_tag.get("start", 1))
        lines = []

        for item in list_tag.find_all("li", recursive=False):
            marker = f"{number}. " if ordered else "- "
            lines.extend(self._render_list_item(item, marker, depth))
            number += 1

        return "\n".join(lines)

    def _render_list_item(self, item, marker, depth):
        lines = []
        inline_children = []

        def flush_inline():
            text = " ".join(
                part for part in (
                    self._render_inline(child).strip() for child in inline_children
                ) if part
            )
            if text:
                prefix = "  " * depth + (marker if not lines else "   ")
                lines.append(prefix + text)
            inline_children.clear()

        for child in item.children:
            if isinstance(child, Tag) and child.name.lower() in {"ul", "ol"}:
                flush_inline()
                if lines and lines[-1]:
                    lines.append("")
                lines.extend(self._render_list(child, depth + 1).splitlines())
                lines.append("")
            elif self._is_list_block(child):
                flush_inline()
                if lines and lines[-1]:
                    lines.append("")
                lines.extend(self._render_list_block(child, depth + 1))
                lines.append("")
            else:
                inline_children.append(child)

        flush_inline()
        return lines or [f"{'  ' * depth}{marker.rstrip()}"]

    @staticmethod
    def _is_list_block(node):
        if not isinstance(node, Tag):
            return False
        if node.name.lower() in {"ol", "pre", "table", "ul"}:
            return True
        return node.name.lower() in {"div", "p"} and node.find(
            ["ol", "pre", "table", "ul"]
        ) is not None

    def _render_list_block(self, node, depth):
        name = node.name.lower()
        if name in {"ol", "ul"}:
            return self._render_list(node, depth).splitlines()

        content_indent = "  " * max(0, depth - 1) + ("   " if depth else "")
        if name in {"pre", "table"}:
            rendered = self._render(node).strip()
            return [content_indent + line if line else "" for line in rendered.splitlines()]

        lines = []
        inline_children = []

        def flush_inline():
            text = " ".join(
                part for part in (
                    self._render_inline(child).strip() for child in inline_children
                ) if part
            )
            if text:
                lines.append(content_indent + text)
            inline_children.clear()

        def append_block(block_lines):
            if lines and lines[-1]:
                lines.append("")
            lines.extend(block_lines)
            if block_lines and block_lines[-1]:
                lines.append("")

        for child in node.children:
            if isinstance(child, Tag) and child.name.lower() in {"ol", "ul"}:
                flush_inline()
                append_block(self._render_list(child, depth + 1).splitlines())
            elif self._is_list_block(child):
                flush_inline()
                append_block(self._render_list_block(child, depth))
            else:
                inline_children.append(child)

        flush_inline()
        return lines

    def _render_table_cell(self, cell):
        parts = []
        inline_children = []

        def flush_inline():
            rendered = "".join(
                self._render_inline(child) for child in inline_children
            ).strip()
            if rendered:
                parts.append(re.sub(r"\s+", " ", rendered))
            inline_children.clear()

        for child in cell.children:
            if isinstance(child, Tag) and child.name.lower() in {"ol", "ul"}:
                flush_inline()
                list_lines = self._render_list(child).splitlines()
                formatted_lines = []
                for line in list_lines:
                    indentation = len(line) - len(line.lstrip(" "))
                    formatted_lines.append("&nbsp;" * indentation + line.lstrip())
                if formatted_lines:
                    parts.append("<br>".join(formatted_lines))
            elif (
                isinstance(child, Tag)
                and child.name.lower() in {"div", "p"}
                and child.find(["ol", "ul"])
            ):
                flush_inline()
                rendered = self._render_table_cell(child)
                if rendered:
                    parts.append(rendered)
            else:
                inline_children.append(child)

        flush_inline()
        return "<br>".join(parts)

    def _render_table(self, table):
        rows = [
            row for row in table.find_all("tr")
            if row.find_parent("table") is table
        ]
        if not rows:
            return ""
        if any(row.find("pre") for row in rows):
            header_cells = rows[0].find_all(["th", "td"], recursive=False)
            if header_cells and all(cell.name == "th" for cell in header_cells):
                headers = [self._render_table_cell(cell) for cell in header_cells]
                return self._render_code_table(rows[1:], headers)

        grid = []
        for row_index, row in enumerate(rows):
            while len(grid) <= row_index:
                grid.append([])
            column_index = 0
            cells = row.find_all(["th", "td"], recursive=False)
            for cell in cells:
                while column_index < len(grid[row_index]) and grid[row_index][column_index] is not None:
                    column_index += 1

                text = self._render_table_cell(cell)
                text = text.replace("|", "&#124;")
                row_span = self._span_value(cell.get("rowspan"))
                column_span = self._span_value(cell.get("colspan"))

                for target_row in range(row_index, row_index + row_span):
                    while len(grid) <= target_row:
                        grid.append([])
                    while len(grid[target_row]) < column_index + column_span:
                        grid[target_row].append(None)
                    for target_column in range(column_index, column_index + column_span):
                        is_origin = target_row == row_index and target_column == column_index
                        grid[target_row][target_column] = text if is_origin else ""

                column_index += column_span

        column_count = max((len(row) for row in grid), default=0)
        if not column_count:
            return ""

        normalized_rows = [
            [(cell or "") for cell in row] + [""] * (column_count - len(row))
            for row in grid
        ]
        table_lines = [self._table_row(normalized_rows[0])]
        table_lines.append(self._table_row(["---"] * column_count))
        table_lines.extend(self._table_row(row) for row in normalized_rows[1:])
        return "\n\n" + "\n".join(table_lines) + "\n\n"

    def _render_code_table(self, rows, headers):
        records = []
        for row_number, row in enumerate(rows, start=1):
            cells = row.find_all(["th", "td"], recursive=False)
            if not cells:
                continue

            values = []
            code_blocks = []
            for column_index, cell in enumerate(cells):
                label = headers[column_index] if column_index < len(headers) else f"Column {column_index + 1}"
                inline_parts = []
                for child in cell.children:
                    if isinstance(child, Tag) and child.name.lower() == "pre":
                        code_blocks.append((label, self._fenced_code(child.get_text()).strip()))
                    else:
                        rendered = self._render_inline(child).strip()
                        if rendered:
                            inline_parts.append(rendered)
                value = " ".join(inline_parts)
                if value:
                    values.append((label, value))

            if not values and not code_blocks:
                continue

            title = values[0][1] if values else f"Record {row_number}"
            record = [f"### {title}"]
            record.extend(f"**{label}:** {value}" for label, value in values[1:])
            for label, code in code_blocks:
                record.extend((f"**{label}:**", "", code))
            records.append("\n\n".join(record))

        return "\n\n" + "\n\n".join(records) + "\n\n" if records else ""

    @staticmethod
    def _span_value(value):
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _has_class(node, class_name):
        classes = node.get("class")
        if isinstance(classes, list):
            return class_name in classes
        return class_name in str(classes or "").split()

    @staticmethod
    def _table_row(cells):
        return "| " + " | ".join(cells) + " |"

    @staticmethod
    def _render_text(text):
        if not text.strip():
            return " "
        text = re.sub(r"\s+", " ", text)
        return text.replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def _code_span(text):
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return "``"
        delimiter = "`" * (max((len(match) for match in re.findall(r"`+", text)), default=0) + 1)
        padding = " " if text.startswith("`") or text.endswith("`") else ""
        return f"{delimiter}{padding}{text}{padding}{delimiter}"

    @staticmethod
    def _fenced_code(text):
        text = text.strip("\n")
        fence_size = max(
            3,
            max((len(match) for match in re.findall(r"`+", text)), default=0) + 1,
        )
        fence = "`" * fence_size
        return f"\n\n{fence}\n{text}\n{fence}\n\n"

    @staticmethod
    def _filter_unreferenced_anchors(markdown):
        referenced_ids = {
            unquote(anchor_id)
            for anchor_id in re.findall(r"\]\(#([^)]+)\)", markdown)
        }
        return re.sub(
            r'<a id="([^"]+)"></a>',
            lambda match: (
                match.group(0)
                if unquote(unescape(match.group(1))) in referenced_ids
                else ""
            ),
            markdown,
        )

    @staticmethod
    def _clean_output(markdown):
        lines = []
        in_code = False
        fence_character = ""
        fence_size = 0
        blank_pending = False

        for line in markdown.splitlines():
            line = line.rstrip()
            if not in_code:
                line = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", line)
            fence_match = re.match(r"^\s*(`{3,}|~{3,})", line)

            if in_code:
                lines.append(line)
                if (
                    fence_match
                    and fence_match.group(1)[0] == fence_character
                    and len(fence_match.group(1)) >= fence_size
                ):
                    in_code = False
                continue

            if not line.strip():
                blank_pending = bool(lines)
                continue

            if blank_pending and lines and lines[-1] != "":
                lines.append("")
            blank_pending = False
            lines.append(line)

            if fence_match:
                in_code = True
                fence_character = fence_match.group(1)[0]
                fence_size = len(fence_match.group(1))

        return "\n".join(lines).strip() + "\n"


def convert_html_to_markdown(html_content):
    return HtmlMarkdownConverter().convert(html_content)


def split_release_notes(markdown):
    lines = markdown.splitlines()
    release_heading = re.compile(r"^(#{1,6})\s+Central Workspace release notes\s*$")
    release_start = None
    release_match = None
    for index, line in enumerate(lines):
        candidate = release_heading.match(line)
        if candidate:
            release_start = index
            release_match = candidate
            break
    if release_start is None or release_match is None:
        return markdown, None

    heading_level = len(release_match.group(1))
    release_end = len(lines)
    for index in range(release_start + 1, len(lines)):
        match = re.match(r"^(#{1,6})\s+", lines[index])
        if match and len(match.group(1)) <= heading_level:
            release_end = index
            break

    release_content_start = release_start
    while release_content_start > 0:
        previous_line = lines[release_content_start - 1].strip()
        if not previous_line or re.fullmatch(r'<a id="[^"]+"></a>', previous_line):
            release_content_start -= 1
        else:
            break

    toc_start = None
    toc_end = None
    toc_heading = next(
        (index for index, line in enumerate(lines[:release_start])
         if line.strip().lower() == "## table of contents"),
        None,
    )
    if toc_heading is not None:
        for index in range(toc_heading + 1, release_start):
            match = re.match(
                r"^(\s*)[-*]\s+\[Central Workspace release notes\]\(",
                lines[index],
            )
            if match:
                toc_start = index
                base_indent = len(match.group(1))
                toc_end = index + 1
                while toc_end < release_start:
                    line = lines[toc_end]
                    if not line.strip():
                        toc_end += 1
                        continue
                    item = re.match(r"^(\s*)[-*]\s+", line)
                    if not item or len(item.group(1)) <= base_indent:
                        break
                    toc_end += 1
                break

    release_toc = lines[toc_start:toc_end] if toc_start is not None else []
    release_content = lines[release_content_start:release_end]
    release_markdown = HtmlMarkdownConverter._clean_output(
        "## Table Of Contents\n\n"
        + "\n".join(release_toc)
        + "\n\n"
        + "\n".join(release_content)
    )
    release_markdown = HtmlMarkdownConverter._clean_output(
        HtmlMarkdownConverter._filter_unreferenced_anchors(release_markdown)
    )

    main_lines = [
        line for index, line in enumerate(lines)
        if not (release_content_start <= index < release_end)
        and not (
            toc_start is not None and toc_end is not None
            and toc_start <= index < toc_end
        )
    ]
    main_markdown = HtmlMarkdownConverter._clean_output("\n".join(main_lines))
    main_markdown = HtmlMarkdownConverter._clean_output(
        HtmlMarkdownConverter._filter_unreferenced_anchors(main_markdown)
    )
    return main_markdown, release_markdown


def main():
    parser = argparse.ArgumentParser(description="Convert an HTML fragment to Markdown.")
    parser.add_argument("input", nargs="?", default="input.html", help="Input HTML file")
    parser.add_argument("-o", "--output", help="Output Markdown file")
    args = parser.parse_args()

    input_file = Path(args.input)
    output_file = Path(args.output) if args.output else input_file.with_suffix(".md")
    if not input_file.is_file():
        parser.error(f"input file not found: {input_file}")

    try:
        html_data = input_file.read_text(encoding="utf-8")
        markdown = convert_html_to_markdown(html_data)
        main_markdown, release_notes = split_release_notes(markdown)
        output_file.write_text(main_markdown, encoding="utf-8")
        if release_notes:
            release_notes_file = output_file.with_name(
                f"{output_file.stem}_release_notes.md"
            )
            release_notes_file.write_text(release_notes, encoding="utf-8")
    except OSError as error:
        parser.error(str(error))

    print(f"Converted '{input_file}' to '{output_file}'.")
    if release_notes:
        print(f"Release notes saved to '{release_notes_file}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
