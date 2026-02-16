# Module 2: Markdown2Chunks - Implementation Plan

## Overview
Smart chunking module that processes markdown files too long for LLMs by splitting them into manageable chunks while preserving context and minimizing information loss.

## Core Concepts

### Primary Method: "Peeling Onion"
For well-structured markdown with headers, chunk hierarchically by header levels (H1 → H2 → H3...). Only split when a section exceeds max token length.

### Fallback Method: "Driving Wedges" + "Rolling Context Window"
For plain text or oversized sections:
1. **Driving Wedges**: LLM reads content and outputs K nearest tokens around suggested cut points. Script uses Levenshtein distance to locate exact positions.
2. **Rolling Context Window**: Slide through long documents, processing one max-length window at a time, starting each new window from the last cut point.

## Project Structure
```
src/markdown2chunks/
├── __init__.py
├── cli.py                    # CLI entry point (md2chunks)
├── config.py                 # Pydantic settings (extends module 1)
├── pipeline.py               # Main orchestration
├── router.py                 # Route markdown vs JSON (pass-through)
├── chunkers/
│   ├── __init__.py
│   ├── base.py               # Abstract base chunker
│   ├── header_chunker.py     # "Peeling onion" - markdown header based
│   └── llm_chunker.py        # "Driving Wedges" - LLM-based fallback
├── utils/
│   ├── __init__.py
│   ├── token_estimator.py    # Token counting (tiktoken)
│   ├── levenshtein.py        # Fuzzy matching for cut point location
│   └── markdown_utils.py     # Header parsing, section extraction
└── schemas/
    ├── __init__.py
    ├── chunk.py              # Chunk and ChunkMetadata models
    └── index.py              # ChunksIndex model
```

## Key Configuration (.env additions)
```bash
# Module 2: Chunking
MAX_TOKEN_LENGTH=100000       # Max tokens per chunk
K_NEAREST_TOKENS=50           # Tokens around cut point for LLM output
MIN_CHUNK_SIZE=1000           # Don't create chunks smaller than this (chars)

# LLM Models (SiliconFlow)
CHUNKING_MODEL=Pro/zai-org/GLM-4.7      # For chunking decisions
COMPLEX_MODEL=Pro/zai-org/GLM-5          # Reserved for complex tasks
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
```

## Schemas

### Chunk (chunk.py)
```python
class ChunkMetadata(BaseModel):
    title: str                    # Section title or LLM-generated summary
    chunk_index: int              # Position in sequence (0-indexed)
    total_chunks: int             # Total chunks from source file
    character_count: int
    estimated_tokens: int
    source_file: str              # Original filename
    source_path: Path             # Full path to source
    header_level: int | None      # H1=1, H2=2, etc. None for LLM chunks
    chunking_method: str          # "header" or "llm"

class Chunk(BaseModel):
    content: str
    metadata: ChunkMetadata
```

### ChunksIndex (index.py)
```python
class ChunkEntry(BaseModel):
    chunk_id: str                 # e.g., "source_filename_chunk_001"
    file_path: str                # Path to chunk file
    title: str
    estimated_tokens: int
    source_file: str

class ChunksIndex(BaseModel):
    created_at: datetime
    total_chunks: int
    total_tokens: int
    source_files: list[str]
    chunks: list[ChunkEntry]
```

## Routing Logic (router.py)
| Input | Extension | Action |
|-------|-----------|--------|
| Markdown | .md | Process through chunkers |
| JSON | .json | Pass-through to output (no chunking) |

## Chunking Algorithm

### Step 1: Initial Assessment
```
1. Read file content
2. Estimate total tokens
3. If tokens <= MAX_TOKEN_LENGTH:
   - Output as single chunk
   - Done
```

### Step 2: Header-Based Chunking ("Peeling Onion")
```
1. Parse markdown headers (H1, H2, H3...)
2. Build section tree with token counts
3. For each top-level section:
   a. If section tokens <= MAX_TOKEN_LENGTH:
      - Output as chunk
   b. Else:
      - Recursively split by next header level
      - If no sub-headers or still too large:
        - Fall back to LLM chunking
```

### Step 3: LLM-Based Chunking ("Driving Wedges")
```
1. Initialize: remaining_text = oversized_section
2. While remaining_text exceeds MAX_TOKEN_LENGTH:
   a. Load first MAX_TOKEN_LENGTH tokens
   b. Call LLM with prompt:
      "Identify 1-3 logical cut points. For each, output:
       - K tokens before the cut
       - K tokens after the cut
       - A short title for the resulting chunk"
   c. Use Levenshtein distance to locate exact cut positions
   d. Cut at first valid position
   e. Output chunk with LLM-suggested title
   f. remaining_text = text after cut (Rolling Context Window)
3. Output final chunk
```

## LLM Prompt Design

### Chunking Prompt (llm_chunker.py)
```
You are analyzing a document section to find logical break points.

CONTENT:
{content_window}

TASK:
Find 1-3 natural break points where this text could be split into separate chunks.
For each break point, provide:
1. The ~{k} tokens BEFORE the break point (exact text)
2. The ~{k} tokens AFTER the break point (exact text)
3. A short title (5-10 words) for the chunk that would END at this break

Output JSON:
{
  "cut_points": [
    {
      "tokens_before": "...exact text before cut...",
      "tokens_after": "...exact text after cut...",
      "chunk_title": "Title for preceding chunk"
    }
  ]
}

Guidelines:
- Cut at paragraph boundaries when possible
- Keep related concepts together
- Prefer cuts between major topics or ideas
- First cut_point is most recommended
```

## Output Format

### Directory Structure
```
output/
├── chunks/
│   ├── document1_chunk_001.md
│   ├── document1_chunk_002.md
│   ├── document2_chunk_001.md
│   └── ...
├── chunks_index.json          # Master index of all chunks
└── passthrough/
    └── data.json              # JSON files passed through unchanged
```

### Chunk File Format
```markdown
---
title: "Section Title"
source: "original_document.md"
chunk: 1
total: 5
tokens: 45000
method: "header"
---

[Actual chunk content here...]
```

## Implementation Phases

### Phase 1: Core Infrastructure
- [ ] Create config.py with new settings (extend module 1 pattern)
- [ ] Implement utils/token_estimator.py (tiktoken wrapper)
- [ ] Implement utils/levenshtein.py (fuzzy string matching)
- [ ] Implement utils/markdown_utils.py (header parsing)
- [ ] Create schemas/chunk.py and schemas/index.py

### Phase 2: Chunkers
- [ ] Implement chunkers/base.py (abstract class)
- [ ] Implement chunkers/header_chunker.py ("Peeling onion")
- [ ] Implement chunkers/llm_chunker.py ("Driving wedges" + LLM calls)

### Phase 3: Orchestration
- [ ] Implement router.py (markdown vs JSON routing)
- [ ] Implement pipeline.py (main orchestration)
- [ ] Implement cli.py (Click CLI)

### Phase 4: Integration
- [ ] Add logging (structlog, same pattern as module 1)
- [ ] Create ChunksIndex generation
- [ ] Wire up pass-through for JSON files

## Dependencies (additions to pyproject.toml)
```
tiktoken>=0.7.0              # Token estimation
python-Levenshtein>=0.25.0   # Fast Levenshtein distance
openai>=1.0.0                # For SiliconFlow API (OpenAI-compatible)
```

## CLI Commands
```bash
md2chunks run                 # Process all files in output/ from module 1
md2chunks run -v              # Verbose mode
md2chunks chunk-file X        # Chunk single markdown file
md2chunks estimate-tokens X   # Show token count for file
```

## Verification
1. Create a long markdown file (>100K tokens) with headers
2. Run `md2chunks chunk-file test.md -v`
3. Verify chunks are created in output/chunks/
4. Check chunks_index.json contains correct metadata
5. Verify no chunk exceeds MAX_TOKEN_LENGTH
6. Test with headerless plain text to trigger LLM fallback
7. Run `md2chunks run` on module 1 output directory

## Integration with Module 1
- Input: Reads from module 1's output directory
- Output: Writes to chunks/ subdirectory
- JSON files: Pass-through to passthrough/ subdirectory
- Shared: Reuses logging setup, config patterns from module 1
