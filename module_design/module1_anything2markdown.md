# Module 1: Anything2Markdown - Implementation Plan

## Overview
Universal file/URL parser that routes inputs to appropriate parsers, outputting Markdown or JSON.

## Project Structure
```
Anything2Workspace/
├── .env.example
├── pyproject.toml
├── CLAUDE.md
├── input/
│   └── urls.txt          # One URL per line, auto-detect type
├── output/               # Flat structure, paths encoded in filenames
├── logs/
│   ├── json/
│   └── text/
└── src/anything2markdown/
    ├── __init__.py
    ├── cli.py            # CLI entry point (anything2md)
    ├── config.py         # Pydantic settings from .env
    ├── router.py         # Front desk routing logic
    ├── pipeline.py       # Main orchestration
    ├── parsers/
    │   ├── base.py
    │   ├── markitdown_parser.py   # PDF, PPT, DOC, media
    │   ├── mineru_parser.py       # Complex/scanned PDFs (API)
    │   └── tabular_parser.py      # xlsx/csv → JSON
    ├── url_parsers/
    │   ├── base.py
    │   ├── firecrawl_parser.py    # Multi-page websites
    │   ├── youtube_parser.py      # YouTube transcripts
    │   └── repomix_parser.py      # Git repos
    ├── utils/
    │   ├── logging_setup.py       # Dual JSON+text logging
    │   ├── file_utils.py
    │   └── retry.py               # Retry once then skip
    └── schemas/
        └── result.py              # ParseResult schema
```

## Key Configuration (.env)
```bash
INPUT_DIR=./input
OUTPUT_DIR=./output
LOG_DIR=./logs
SILICONFLOW_API_KEY=
MINERU_API_KEY=
FIRECRAWL_API_KEY=
MAX_PDF_SIZE_MB=10
MIN_VALID_CHARS=500
RETRY_COUNT=1
LOG_FORMAT=both
```

## Routing Logic (router.py)
| Input Type | Condition | Parser |
|------------|-----------|--------|
| PDF | Normal, <10MB | MarkItDown |
| PDF | >10MB or <500 valid chars | MinerU API (fallback) |
| PPT, DOC, MP3, MP4, images | By extension | MarkItDown |
| xlsx, csv | By extension | TabularParser → JSON |
| YouTube URL | Pattern match | YouTubeParser |
| GitHub repo URL | Pattern match | RepomixParser |
| Other URLs | Default | FireCrawl |

## Implementation Phases

### Phase 1: Core Infrastructure
- [ ] Create pyproject.toml with dependencies
- [ ] Implement config.py (Pydantic Settings)
- [ ] Implement utils/logging_setup.py (structlog, dual format)
- [ ] Implement utils/file_utils.py (walk_directory, read_url_list)
- [ ] Implement utils/retry.py (decorator with retry once then skip)
- [ ] Create schemas/result.py (ParseResult Pydantic model)
- [ ] Create .env.example

### Phase 2: File Parsers
- [ ] Implement parsers/base.py (abstract class)
- [ ] Implement parsers/markitdown_parser.py
- [ ] Implement parsers/tabular_parser.py (pandas → JSON)
- [ ] Implement parsers/mineru_parser.py (API integration)

### Phase 3: URL Parsers
- [ ] Implement url_parsers/base.py
- [ ] Implement url_parsers/youtube_parser.py (youtube-transcript-api)
- [ ] Implement url_parsers/firecrawl_parser.py
- [ ] Implement url_parsers/repomix_parser.py (subprocess)

### Phase 4: Orchestration
- [ ] Implement router.py (front desk routing)
- [ ] Implement pipeline.py (main orchestration)
- [ ] Implement cli.py (Click CLI)

### Phase 5: Documentation
- [ ] Create CLAUDE.md with project context

## Dependencies (pyproject.toml)
```
markitdown[all]>=0.1.0
firecrawl-py>=1.0.0
youtube-transcript-api>=0.6.0
pandas>=2.0.0
openpyxl>=3.1.0
httpx>=0.27.0
click>=8.1.0
python-dotenv>=1.0.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
structlog>=24.0.0
```

**External**: `npm install -g repomix`

## CLI Commands
```bash
anything2md init          # Create directories and urls.txt
anything2md run           # Run full pipeline
anything2md run -v        # Verbose mode
anything2md parse-file X  # Parse single file
anything2md parse-url X   # Parse single URL
```

## Verification
1. Run `anything2md init` to create directories
2. Place test files in `./input/` (PDF, DOCX, XLSX, etc.)
3. Add test URLs to `./input/urls.txt`
4. Run `anything2md run -v`
5. Check `./output/` for parsed files
6. Check `./logs/` for JSON and text logs
7. Verify file naming: `folder1_folder2_filename.md`
