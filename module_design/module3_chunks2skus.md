# Module 3: Chunks2SKUs - Implementation Plan

## Overview
Knowledge extraction module that processes chunks from Module 2 and extracts 4 types of Standard Knowledge Units (SKUs).

## Key Design Decisions

| Decision | Choice |
|----------|--------|
| Agent processing | Sequential: Factual → Relational → Procedural → Meta |
| Cross-chunk context | Factual/Procedural: isolated; Relational/Meta: read-and-update |
| SKU organization | By type: `output/skus/{factual,relational,procedural,meta}/` |
| LLM model | GLM-5 (`Pro/zai-org/GLM-5`) |
| Skill format | Match Claude Code skill-creator format |
| Relational output | Separate `label_tree.json` + `glossary.json` |
| SKU header | Minimal metadata (name, classification, char count, source, description) |
| eureka.md format | Append-only bullet list |

## Output Structure

```
output/skus/
├── factual/
│   ├── sku_001/
│   │   ├── header.md          # Minimal metadata
│   │   └── content.md         # or content.json for dataframes
│   └── ...
├── relational/
│   ├── header.md              # Describes the relational knowledge base
│   ├── label_tree.json        # Multi-level label hierarchy (incremental)
│   └── glossary.json          # Term definitions (incremental)
├── procedural/
│   ├── skill_001/
│   │   ├── SKILL.md           # Claude skill format with YAML frontmatter
│   │   ├── header.md          # SKU metadata
│   │   ├── scripts/           # Optional executable code
│   │   └── references/        # Optional documentation
│   └── ...
└── meta/
    ├── header.md
    ├── mapping.md             # Router to all SKUs (incremental)
    └── eureka.md              # Ideas/insights (append-only bullets)
```

## Project Structure

```
src/chunks2skus/
├── __init__.py
├── config.py                  # Pydantic settings
├── pipeline.py                # Main orchestration
├── router.py                  # Routes chunks to extractors
├── cli.py                     # Click CLI (chunks2skus)
├── extractors/
│   ├── __init__.py
│   ├── base.py                # Abstract BaseExtractor
│   ├── factual_extractor.py   # Isolated processing → new SKUs
│   ├── relational_extractor.py # Read-and-update → label_tree + glossary
│   ├── procedural_extractor.py # Isolated processing → skill folders
│   └── meta_extractor.py      # Read-and-update → mapping.md + eureka.md
├── schemas/
│   ├── __init__.py
│   ├── sku.py                 # SKU, SKUHeader, SKUType, LabelTree, Glossary
│   └── index.py               # SKUsIndex for tracking
└── utils/
    ├── __init__.py
    ├── logging_setup.py       # Dual-format logging (JSON + text)
    └── llm_client.py          # OpenAI client wrapper for GLM-5
```

## Schemas

### SKUHeader (header.md content)
```python
class SKUHeader(BaseModel):
    name: str                      # SKU name
    classification: SKUType        # factual/relational/procedural/meta
    character_count: int
    source_chunk: str              # e.g., "document_chunk_003"
    description: str               # One-line description
```

### LabelTree (relational/label_tree.json)
```python
class LabelNode(BaseModel):
    name: str
    children: list["LabelNode"] = []

class LabelTree(BaseModel):
    roots: list[LabelNode] = []
```

### Glossary (relational/glossary.json)
```python
class GlossaryEntry(BaseModel):
    term: str
    definition: str
    labels: list[str] = []
    source_chunk: str
    related_terms: list[str] = []

class Glossary(BaseModel):
    entries: list[GlossaryEntry] = []
```

## Agent Processing Flow

```
For each chunk in chunks_index.json (ordered by chunk_id):

    1. FACTUAL EXTRACTOR (isolated)
       - Input: chunk content
       - Output: 0-N new SKU folders in factual/
       - Each SKU: header.md + content.md or content.json

    2. RELATIONAL EXTRACTOR (read-and-update)
       - Input: chunk content + existing label_tree.json + glossary.json
       - Output: Updated label_tree.json, glossary.json

    3. PROCEDURAL EXTRACTOR (isolated)
       - Input: chunk content
       - Output: 0-N new skill folders in procedural/
       - Each skill: SKILL.md (Claude format) + optional scripts/references/

    4. META EXTRACTOR (read-and-update)
       - Input: chunk content + all current SKU paths + existing mapping.md + eureka.md
       - Output: Updated mapping.md, appended eureka.md bullets
```

## Postprocessing (Section 3.4)

After extraction, three postprocessing steps refine SKU quality.

### Step 1: Bucketing

Group factual and procedural SKUs by similarity into buckets (≤100K tokens each).

**Algorithm**:
1. Load all factual/procedural SKUs from `skus_index.json`
2. Estimate tokens for each SKU (tiktoken cl100k_base)
3. Assign label paths from `label_tree.json` by matching SKU names/descriptions layer-by-layer
4. Compute pairwise similarity matrix (N×N) from 3 aspects:
   - **Literal (w=0.2)**: TF-IDF cosine similarity (sklearn)
   - **Label (w=0.3)**: Jaccard similarity on label paths
   - **Vector (w=0.5)**: bge-m3 embedding cosine similarity
5. Recursive split via agglomerative clustering (scipy, average linkage, cut into 2)
6. Save `postprocessing/bucketing_result.json`

**Fallbacks**: Embedding API fails → literal 0.4 + label 0.6. Label tree missing → literal 0.3 + vector 0.7. Embedding batch limit → auto-batches at 64 per request.

### Step 2: Dedup/Contradiction (Two-Tier)

**Tier 1 — Quick Scan (cheap model)**:
- Compare headers only (name + description) within each bucket
- Model: `Qwen/Qwen3-VL-235B-A22B-Instruct` (temp 0.2)
- Large buckets scanned in sub-batches of 80 headers
- Returns flagged pairs; false positives are cheap

**Tier 2 — Deep Read (GLM-5, flagged pairs only)**:
- Load full content of both SKUs
- Judgment prompt (temp 0.3): "when in doubt, KEEP both"
- Actions: `keep` / `delete` / `rewrite` / `merge`
- Applies actions: deletes folders, removes from index, cleans mapping.md references

**Safety**: All SKU IDs from LLM validated against bucket; single-SKU buckets skipped.

### Step 3: Proofreading/Confidence (Bipolar Design)

Per-SKU confidence scoring with bipolar source/web evaluation:

**Step A — Source Integrity Check (penalty only)**:
- Compare SKU against its original source chunk
- Faithful extraction → no penalty (move on)
- Distortion/hallucination → hard penalty (0.2-0.5)
- Source unavailable → skip

**Step B — External Verification (the real confidence signal)**:
- Web search via Jina `s.jina.ai` (5 results per query)
- Score 0.0-1.0 based on external corroboration

**Final score** = `web_confidence - source_penalty` (clamped 0.0-1.0)

**Scoring guide**:
- 0.8-1.0: Multiple web sources corroborate
- 0.6-0.8: Some corroboration, minor gaps
- 0.4-0.6: Ambiguous — neither confirmed nor denied
- 0.2-0.4: Weak — little external support
- 0.0-0.2: Contradicted by web sources

**Resilience**: Jina down → web_confidence=0.5 (neutral); source chunk missing → no penalty; resumable (skips already-scored SKUs).

### Postprocessing Output

```
output/skus/postprocessing/
├── bucketing_result.json       # Bucket assignments + similarity metadata
├── dedup_report.json           # Actions taken (delete/rewrite/merge/keep)
└── confidence_report.json      # Per-SKU confidence scores + web references
```

Plus modifications to existing files:
- `factual/sku_NNN/header.md` — gains `- **Confidence**: 0.85` line
- `skus_index.json` — entries gain `confidence` field, some entries removed by dedup

---

## Project Structure

```
src/chunks2skus/
├── __init__.py
├── config.py                  # Pydantic settings
├── pipeline.py                # Main orchestration
├── router.py                  # Routes chunks to extractors
├── cli.py                     # Click CLI (chunks2skus)
├── extractors/
│   ├── __init__.py
│   ├── base.py                # Abstract BaseExtractor
│   ├── factual_extractor.py   # Isolated processing → new SKUs
│   ├── relational_extractor.py # Read-and-update → label_tree + glossary
│   ├── procedural_extractor.py # Isolated processing → skill folders
│   └── meta_extractor.py      # Read-and-update → mapping.md + eureka.md
├── postprocessors/
│   ├── __init__.py
│   ├── base.py                # Abstract BasePostprocessor
│   ├── bucketing.py           # Step 1: similarity + clustering
│   ├── dedup.py               # Step 2: two-tier duplicate detection
│   ├── proofreading.py        # Step 3: bipolar confidence scoring
│   └── pipeline.py            # PostprocessingPipeline orchestrator
├── schemas/
│   ├── __init__.py
│   ├── sku.py                 # SKU, SKUHeader, SKUType, LabelTree, Glossary
│   ├── index.py               # SKUsIndex for tracking
│   └── postprocessing.py      # Bucket, DedupReport, ConfidenceReport
└── utils/
    ├── __init__.py
    ├── logging_setup.py       # Dual-format logging (JSON + text)
    ├── llm_client.py          # OpenAI client wrapper for GLM-5
    ├── embedding_client.py    # SiliconFlow bge-m3 embeddings (auto-batching)
    ├── jina_client.py         # Jina s.jina.ai web search
    └── token_utils.py         # tiktoken cl100k_base wrapper
```

## Schemas

### SKUHeader (header.md content)
```python
class SKUHeader(BaseModel):
    name: str                      # SKU name
    classification: SKUType        # factual/relational/procedural/meta
    character_count: int
    source_chunk: str              # e.g., "document_chunk_003"
    description: str               # One-line description
    confidence: Optional[float]    # 0.0-1.0, set by proofreading
```

### LabelTree (relational/label_tree.json)
```python
class LabelNode(BaseModel):
    name: str
    children: list["LabelNode"] = []

class LabelTree(BaseModel):
    roots: list[LabelNode] = []
```

### Glossary (relational/glossary.json)
```python
class GlossaryEntry(BaseModel):
    term: str
    definition: str
    labels: list[str] = []
    source_chunk: str
    related_terms: list[str] = []

class Glossary(BaseModel):
    entries: list[GlossaryEntry] = []
```

## Output Structure

```
output/skus/
├── factual/
│   ├── sku_001/
│   │   ├── header.md          # Minimal metadata (+ confidence after proofread)
│   │   └── content.md         # or content.json for dataframes
│   └── ...
├── relational/
│   ├── header.md              # Describes the relational knowledge base
│   ├── label_tree.json        # Multi-level label hierarchy (incremental)
│   └── glossary.json          # Term definitions (incremental)
├── procedural/
│   ├── skill_001/
│   │   ├── SKILL.md           # Claude skill format with YAML frontmatter
│   │   ├── header.md          # SKU metadata
│   │   ├── scripts/           # Optional executable code
│   │   └── references/        # Optional documentation
│   └── ...
├── meta/
│   ├── header.md
│   ├── mapping.md             # Router to all SKUs (incremental)
│   └── eureka.md              # Ideas/insights (append-only bullets)
├── postprocessing/
│   ├── bucketing_result.json
│   ├── dedup_report.json
│   └── confidence_report.json
└── skus_index.json
```

## Configuration (.env)

```bash
# Module 3: Knowledge Extraction
EXTRACTION_MODEL=Pro/zai-org/GLM-5
SKUS_OUTPUT_DIR=./output/skus

# Postprocessing: Bucketing
MAX_BUCKET_TOKENS=100000
EMBEDDING_MODEL=Pro/BAAI/bge-m3
SIMILARITY_WEIGHT_LITERAL=0.2
SIMILARITY_WEIGHT_LABEL=0.3
SIMILARITY_WEIGHT_VECTOR=0.5

# Postprocessing: Dedup
DEDUP_SCAN_MODEL=Qwen/Qwen3-VL-235B-A22B-Instruct

# Postprocessing: Proofreading
JINA_API_KEY=...

# Inherited from previous modules
SILICONFLOW_API_KEY=...
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
LOG_LEVEL=INFO
LOG_FORMAT=both
```

## CLI Commands

```bash
# Extraction
chunks2skus run                    # Process all chunks from Module 2
chunks2skus run -v                 # Verbose mode
chunks2skus extract-chunk <path>   # Process single chunk (all 4 agents)
chunks2skus show-index             # Display SKUs index summary
chunks2skus init                   # Create output directories

# Postprocessing
chunks2skus postprocess all -s <skus_dir> -c <chunks_dir>   # All 3 steps
chunks2skus postprocess bucket -s <skus_dir>                 # Bucketing only
chunks2skus postprocess dedup -s <skus_dir>                  # Dedup only
chunks2skus postprocess proof -s <skus_dir> -c <chunks_dir>  # Proofreading only
```

## Verification

### Extraction
1. Place test chunks in `output/chunks/`
2. Run `chunks2skus run -v`
3. Verify output structure matches Output Structure above
4. Check logs in `logs/json/` and `logs/text/`
5. Run `chunks2skus show-index` to verify tracking

### Postprocessing
1. `chunks2skus postprocess bucket -s test_data/basel_skus` — verify bucketing_result.json has reasonable bucket sizes
2. `chunks2skus postprocess dedup -s test_data/basel_skus` — verify dedup_report.json, check deleted SKUs removed from disk + index
3. `chunks2skus postprocess proof -s test_data/basel_skus -c test_data/basel_chunks` — verify confidence scores in headers
4. `chunks2skus postprocess all -s test_data/basel_skus -c test_data/basel_chunks` — full pipeline
