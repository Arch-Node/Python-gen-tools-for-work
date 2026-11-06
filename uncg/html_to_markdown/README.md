# HTML to Markdown Converter

Convert an HTML document or fragment to Markdown with `main.py`.

## Requirements

- Python 3
- Beautiful Soup 4

Install the Python dependency if it is not already available in your environment:

```powershell
python -m pip install beautifulsoup4
```

## Usage

Run from the repository root:

```powershell
python .\uncg\html_to_markdown\main.py "C:\path\to\input.html"
```

By default, the converter writes a Markdown file beside the input, using the same base name. For example, `guide.html` produces `guide.md`.

To choose a different output path, use `-o` or `--output`:

```powershell
python .\uncg\html_to_markdown\main.py "C:\path\to\input.html" -o "C:\path\to\converted-guide.md"
```

The input is read as UTF-8. If it does not exist, the converter reports an error.

## Release Notes

When the document contains a heading named `Central Workspace release notes`, the converter separates that section and its table-of-contents entries from the main Markdown file. It writes them to a companion file named `<output-name>_release_notes.md` beside the selected output. For example, `guide.md` produces `guide_release_notes.md`.

If the heading is not present, only the main Markdown file is written.

## Converted Content

The converter handles headings, paragraphs, nested ordered and unordered lists, tables, links, images, block quotes, and fenced code blocks. It removes document head metadata and styles. Embedded `data:` images are replaced with their alt text to avoid copying large image payloads into Markdown.