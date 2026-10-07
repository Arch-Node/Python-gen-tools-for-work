Markdown and PDF Narration Pipeline.

This folder contains a local text-to-audio workflow. It converts Markdown files or text-based PDFs into narration text, synthesizes WAV audio with Piper, and can compress the result to MP3 with FFmpeg.

The document and audio synthesis stay on your computer. The pipeline may use the internet to install pypdf, download a Piper voice model, or install FFmpeg.

Requirements.

Python 3.10 or newer is recommended.

Piper TTS, including its piper executable and Python voice downloader. Install it in your Python environment with:

FFmpeg for WAV-to-MP3 conversion. On Windows, choose menu option 5 to install it.

pypdf for PDF input. The PDF converter attempts to install it automatically when first needed; alternatively, install it with python -m pip install pypdf.

PDF support extracts embedded text only. Scanned/image-only PDFs need OCR before conversion.

Quick Start.

From the repository root, start the interactive menu:

For a PDF, choose option 7 to run the complete PDF-to-MP3 workflow. For Markdown, choose option 4. The menu prompts for input and output paths; press Enter to accept a displayed default. Pasted paths may be quoted.

To install FFmpeg on Windows, choose option 5. The installer downloads a Windows build, installs it under %LOCALAPPDATA%\ffmpeg, and adds its bin directory to your user PATH. It checks for an existing install first. Open a new terminal afterward if another terminal cannot find ffmpeg.

Menu Options.

Option. Action.

1. Convert Markdown to narration text.

2. Generate WAV from narration text.

3. Convert WAV to MP3.

4. Run Markdown -> text -> WAV -> MP3.

5. Install or update FFmpeg on Windows.

6. Convert PDF to narration text.

7. Run PDF -> text -> WAV -> MP3.

q. Quit.

During WAV generation, the menu asks for a Piper executable, voice quality, and speech length scale. The configured voice is UK English Cori. Cori has Medium and High models; High is the default. If the chosen model or its configuration file is missing, the menu downloads it before synthesis. Piper does not offer a Cori Low model.

Current audio defaults are:

Length scale: 1.15. Higher values make speech slower; 1.0 is approximately the model's normal pace.

Sentence silence: 1.2 seconds.

Paragraph silence: 2.7 seconds.

The WAV generator joins each paragraph into one Piper input so sentence pauses are preserved, then inserts silence between paragraphs. Existing WAV and MP3 files are not automatically removed after conversion.

Individual Commands.

Run these from the repository root. Replace example paths with your own; quote paths containing spaces.

Convert Markdown to narration text:

Convert a text-based PDF to narration text:

Generate a WAV. The default model is Cori High; use --voice-model to select another installed model:

Convert a WAV to MP3:

Use --help with any script to see all its options. The direct MP3 command refuses to overwrite an existing output unless --overwrite is specified.

Configure for Another Computer.

The default Piper executable and voice-model directory are currently absolute paths configured for the original Windows workstation in generate_wave.py:

DEFAULTPIPEREXE.

DEFAULTVOICEMODEL.

Before using the menu on another computer, update these constants to point to that computer's Piper executable and a model directory where voice files can be downloaded. The menu uses the default model's directory for downloaded Cori quality variants. You can also provide a different Piper executable when prompted.

The FFmpeg installer is Windows-specific. On another operating system, install FFmpeg using that operating system's package manager and ensure it is on PATH.

Troubleshooting.

Piper executable or voice model not found: Check the paths in generate_wave.py or provide a valid Piper executable when prompted.

Voice download fails: Check internet access and confirm Piper is installed in the active Python environment or alongside the configured Piper executable.

PDF has no extracted text: It may be scanned; run OCR first, then convert the searchable PDF.

FFmpeg not found: Run menu option 5, open a new terminal, or pass the executable path with --ffmpeg-bin.

Output already exists: Choose another output filename or use --overwrite where supported.
