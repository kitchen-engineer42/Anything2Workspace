# Anything2Workspace

Knowledge management and modelling pipeline that converts various media formats into a comprehensive workspace for coding agents.

## Pipeline

```
Input Files/URLs → [Module 1] Anything2Markdown → [Module 2] Markdown2Chunks → [Module 3] Chunks2SKUs → [Module 4] SKUs2Workspace → workspace/
```

| Module | CLI | Purpose |
|--------|-----|---------|
| 1. Anything2Markdown | `anything2md` | Parse files & URLs into Markdown/JSON |
| 2. Markdown2Chunks | `md2chunks` | Split long markdown into LLM-sized chunks |
| 3. Chunks2SKUs | `chunks2skus` | Extract knowledge into Standard Knowledge Units |
| 4. SKUs2Workspace | `skus2workspace` | Assemble workspace with spec.md chatbot |

## Installation

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install package
pip install -e .

# Install Repomix (for GitHub repo parsing)
npm install -g repomix
```

## Configuration

Copy `.env.example` to `.env` and add your API keys:

```bash
cp .env.example .env
```

## Usage

### Module 1: Parse files and URLs

```bash
anything2md init                              # Create directories
anything2md run                               # Run full pipeline
anything2md parse-file ./input/document.pdf   # Parse single file
anything2md parse-url "https://example.com"   # Parse single URL
```

### Module 2: Chunk markdown

```bash
md2chunks run                    # Process all markdown from module 1
md2chunks chunk-file <file>      # Chunk single file
md2chunks estimate-tokens <file> # Show token count
```

### Module 3: Extract knowledge

```bash
chunks2skus run                      # Process all chunks
chunks2skus extract-chunk <file>     # Extract from single chunk
chunks2skus show-index               # Display SKUs summary
chunks2skus postprocess all          # Run bucketing, dedup, proofreading
```

### Module 4: Assemble workspace

```bash
skus2workspace run                        # Full pipeline (assemble + chatbot + README)
skus2workspace run --skip-chatbot         # Skip interactive chatbot
skus2workspace run -s <skus_dir> -w <dir> # Custom paths
skus2workspace assemble -s <skus_dir>     # Copy/organize SKUs only
skus2workspace chatbot -w <workspace_dir> # Run chatbot on existing workspace
```

## Project Structure

```
input/          # Place files and urls.txt here
output/         # Module 1-3 outputs (markdown, chunks, SKUs)
workspace/      # Module 4 output (self-contained workspace for coding agents)
logs/           # JSON and text logs
```

See `CLAUDE.md` for detailed project context.
