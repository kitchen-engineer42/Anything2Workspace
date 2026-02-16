# Anything2Workspace

**Turn any document, URL, or repo into a structured workspace that coding agents can immediately build from.**

Anything2Workspace is a 4-module pipeline that ingests raw media (PDFs, slides, spreadsheets, YouTube videos, GitHub repos, websites), extracts structured knowledge, and assembles a self-contained workspace complete with a product spec — ready for an AI coding agent to pick up and start building.

```
 ┌──────────┐    ┌───────────────┐    ┌──────────────┐    ┌────────────┐    ┌──────────────┐
 │  Input    │───>│  Module 1     │───>│  Module 2    │───>│  Module 3  │───>│  Module 4    │
 │  Files &  │    │  Anything2    │    │  Markdown2   │    │  Chunks2   │    │  SKUs2       │
 │  URLs     │    │  Markdown     │    │  Chunks      │    │  SKUs      │    │  Workspace   │
 └──────────┘    └───────────────┘    └──────────────┘    └────────────┘    └──────────────┘
  PDF, PPTX,       Unified              Token-sized         Factual,          workspace/
  XLSX, YouTube,   Markdown/JSON         chunks              Relational,       ├── spec.md
  GitHub repos,                          (100K tokens)       Procedural,       ├── mapping.md
  Websites                                                   Meta SKUs         └── skus/
```

## Why?

You have a 2000-page regulation PDF. Or a GitHub repo with 500 files. Or a collection of slides, spreadsheets, and YouTube tutorials. You want an AI agent to build something from this knowledge.

**The problem**: Dumping raw files into an LLM context doesn't work — they're too large, unstructured, and full of noise.

**Anything2Workspace** solves this by:
1. **Parsing** everything into clean Markdown
2. **Chunking** oversized documents into LLM-friendly pieces
3. **Extracting** structured knowledge units (facts, skills, relationships, creative insights)
4. **Assembling** a workspace with navigable knowledge + a product spec

The output `workspace/` folder is designed so a coding agent can read `spec.md` and start building, with `mapping.md` as a router to find relevant knowledge.

## Quick Start

### Local Installation

```bash
git clone https://github.com/kitchen-engineer42/Anything2Workspace.git
cd Anything2Workspace

python -m venv .venv
source .venv/bin/activate

pip install -e .
npm install -g repomix    # for GitHub repo parsing

cp .env.example .env      # add your API keys
```

### Docker

```bash
docker compose build
docker compose run anything2workspace bash
```

### Run the Pipeline

```bash
# Place files in input/ or add URLs to input/urls.txt

anything2md run              # Step 1: Parse to Markdown
md2chunks run                # Step 2: Chunk into pieces
chunks2skus run              # Step 3: Extract knowledge
skus2workspace run           # Step 4: Assemble workspace (includes interactive chatbot)
```

Or skip the chatbot for fully automated runs:

```bash
skus2workspace run --skip-chatbot
```

## Modules

### Module 1: Anything2Markdown

Converts diverse file types and URLs into Markdown or JSON.

| Input | Parser |
|-------|--------|
| PDF | MarkItDown (normal) / MinerU API (scanned/large) |
| PPTX, DOCX, media | MarkItDown |
| XLSX, CSV | TabularParser (JSON output) |
| YouTube URL | YouTubeParser (transcript extraction) |
| GitHub repo | RepomixParser (full repo → single Markdown) |
| Other URLs | FireCrawlParser (web crawling) |

```bash
anything2md run                               # Process all inputs
anything2md parse-file ./input/document.pdf   # Single file
anything2md parse-url "https://example.com"   # Single URL
```

### Module 2: Markdown2Chunks

Splits long Markdown into token-limited chunks (default 100K tokens) using two strategies:

- **Header Chunker** — Hierarchical split by Markdown headers (H1 > H2 > H3)
- **LLM Chunker** — Fallback for unstructured text, uses LLM to find semantic cut points

```bash
md2chunks run                     # Process all Markdown from Module 1
md2chunks chunk-file <file>       # Chunk single file
md2chunks estimate-tokens <file>  # Show token count
```

### Module 3: Chunks2SKUs

Extracts 4 types of Standard Knowledge Units (SKUs) from chunks:

| Type | Description | Output |
|------|-------------|--------|
| **Factual** | Facts, definitions, data points | `sku_NNN/content.md` |
| **Relational** | Category hierarchies, glossary terms | `label_tree.json` + `glossary.json` |
| **Procedural** | Workflows, step-by-step skills | `SKILL.md` (Claude Code format) |
| **Meta** | Knowledge map + creative insights | `mapping.md` + `eureka.md` |

Includes postprocessing: similarity-based bucketing, two-tier deduplication, and web-grounded confidence scoring.

```bash
chunks2skus run                    # Extract from all chunks
chunks2skus show-index             # Display SKU summary
chunks2skus postprocess all        # Run bucketing + dedup + proofreading
```

### Module 4: SKUs2Workspace

Assembles SKUs into a self-contained workspace:

1. **Assemble** — Copies SKUs, rewrites internal paths, promotes key files to root
2. **Chatbot** — Interactive LLM conversation to generate `spec.md` from the knowledge base
3. **README** — Auto-generated entry point for agents

```bash
skus2workspace run                   # Full pipeline
skus2workspace run --skip-chatbot    # Automated (no interactive chatbot)
skus2workspace assemble              # Copy/organize only
skus2workspace chatbot -w workspace/ # Chatbot only
```

**Output workspace:**
```
workspace/
├── spec.md              # Product specification (from chatbot)
├── mapping.md           # SKU router — find knowledge by topic
├── eureka.md            # Creative insights and feature ideas
├── README.md            # Entry point for coding agents
└── skus/
    ├── factual/         # Fact-based knowledge units
    ├── procedural/      # Step-by-step skills
    ├── relational/      # Taxonomies and glossaries
    └── skus_index.json  # Master index
```

## Configuration

Copy `.env.example` to `.env` and set your API keys:

```bash
# Required
SILICONFLOW_API_KEY=       # LLM features (Modules 2-4)

# Optional (enable specific parsers)
MINERU_API_KEY=            # Scanned/large PDF parsing
FIRECRAWL_API_KEY=         # Website crawling
JINA_API_KEY=              # Web-grounded confidence scoring
```

See `.env.example` for the full list of configurable options (models, token limits, temperatures, etc.).

## Project Structure

```
src/
├── anything2markdown/     # Module 1: Universal parser
├── markdown2chunks/       # Module 2: Smart chunking
├── chunks2skus/           # Module 3: Knowledge extraction + postprocessing
└── skus2workspace/        # Module 4: Workspace assembly + chatbot
```

```
input/          # Place files and urls.txt here
output/         # Intermediate outputs (Markdown, chunks, SKUs)
workspace/      # Final output — hand this to your coding agent
logs/           # Dual-format logs (JSON + plain text)
```

## Requirements

- Python 3.10+
- Node.js 20+ (for `repomix`)
- SiliconFlow API key (for LLM features)

## License

MIT
