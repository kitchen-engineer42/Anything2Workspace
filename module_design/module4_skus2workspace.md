# Module 4: SKUs2Workspace - Implementation Plan

## Overview
Workspace assembly module that copies and reorganizes SKUs from Module 3 into a self-contained workspace, runs an interactive chatbot to generate `spec.md`, and produces a README.md entry point. The result: a coding agent can read `spec.md` and start building.

## Key Design Decisions

| Decision | Choice |
|----------|--------|
| Assembly approach | `shutil.copytree` for SKU subdirectories, selective file copies for root-level files |
| Path rewriting | Regex replaces any prefix before `factual/`/`procedural/`/`relational/`/`meta/` with `skus/` |
| Chatbot context | Compressed mapping.md summary (~30K chars max) + eureka.md snippet (~5K chars) in system prompt |
| Chat model | GLM-5 (`Pro/zai-org/GLM-5`) with temperature 0.4 |
| Multi-turn LLM | New `call_llm_chat(messages)` function for full message history |
| Spec extraction | Priority: ` ```markdown ``` ` block → largest ` ``` ``` ` block → response if starts with `#` |
| Finalize trigger | User types `/confirm` or max rounds reached (default 5) |
| README generation | Template-based with stats from `WorkspaceManifest` |

## Pipeline Steps

```
Step 1: Assembly (assembler.py)
    ├── Validate skus_dir exists with meta/mapping.md
    ├── Copy factual/, procedural/, relational/ → workspace/skus/
    ├── Copy postprocessing/ → workspace/skus/postprocessing/
    ├── Copy + rewrite skus_index.json → workspace/skus/skus_index.json
    ├── Copy eureka.md → workspace/eureka.md (root)
    └── Rewrite + copy mapping.md → workspace/mapping.md (root)

Step 2: Chatbot (chatbot.py) — optional, skippable
    ├── Build compressed mapping summary for system prompt
    ├── LLM sends initial greeting (does NOT count as a round)
    ├── User message → LLM response → repeat (each user msg = 1 round)
    ├── /confirm or max rounds → finalize prompt → extract spec
    └── Save spec.md + chat_log.json

Step 3: README (readme_generator.py)
    └── Template with quick start, structure, SKU types, stats
```

## Output Structure

```
workspace/
├── README.md                    # Entry point for agents
├── spec.md                      # App specification (from chatbot)
├── mapping.md                   # SKU router (paths rewritten to skus/...)
├── eureka.md                    # Creative insights
├── workspace_manifest.json      # Assembly metadata
├── chat_log.json                # Chatbot conversation log
└── skus/
    ├── factual/sku_001..N/      # header.md + content.md/json
    ├── procedural/skill_001..N/ # header.md + SKILL.md
    ├── relational/              # label_tree.json, glossary.json
    ├── postprocessing/          # bucketing, dedup, confidence reports
    └── skus_index.json          # Master index (paths rewritten)
```

## Project Structure

```
src/skus2workspace/
├── __init__.py
├── config.py                  # Pydantic settings (workspace_dir, chatbot_model, etc.)
├── pipeline.py                # WorkspacePipeline orchestrator
├── assembler.py               # WorkspaceAssembler (copy + rewrite paths)
├── chatbot.py                 # SpecChatbot (interactive multi-turn)
├── readme_generator.py        # ReadmeGenerator (template-based)
├── cli.py                     # Click CLI (skus2workspace)
├── schemas/
│   ├── __init__.py
│   └── workspace.py           # WorkspaceManifest, ChatMessage, ChatSession
└── utils/
    ├── __init__.py
    ├── logging_setup.py       # Dual-format logging (JSON + text)
    └── llm_client.py          # call_llm() + call_llm_chat() for multi-turn
```

## Schemas

### WorkspaceManifest
```python
class WorkspaceManifest(BaseModel):
    created_at: datetime
    source_skus_dir: str
    workspace_dir: str
    factual_count: int
    procedural_count: int
    has_relational: bool
    has_mapping: bool
    has_eureka: bool
    has_spec: bool
    has_readme: bool
    total_files_copied: int
    paths_rewritten: int
```

### ChatSession
```python
class ChatMessage(BaseModel):
    role: str       # system, assistant, user
    content: str

class ChatSession(BaseModel):
    started_at: datetime
    messages: list[ChatMessage]
    rounds_used: int
    max_rounds: int
    confirmed: bool
    spec_content: Optional[str]
```

## Path Rewriting

Paths in `mapping.md` and `skus_index.json` reference original extraction locations:
```
test_data/basel_skus/factual/sku_001
output/skus/procedural/skill_003
```

The assembler rewrites any prefix before `factual/`/`procedural/`/`relational/`/`meta/` with `skus/`:
```
skus/factual/sku_001
skus/procedural/skill_003
```

**Regex**: Matches word/path characters up to the known subdirectory boundary, handles both mid-text paths and end-of-line paths.

## Chatbot Context Management

`mapping.md` can be 127KB (~35K tokens). To fit in the system prompt:

1. **Compress**: Keep `##` section headers + `### skus/...` path lines + `**Description:**` lines. Strip verbose "When to use" text.
2. **Cap**: Truncate compressed summary at 30K chars.
3. **Eureka**: Include first ~5K chars of `eureka.md` for creative inspiration.
4. **Send once**: System prompt sent once and carried through the conversation.

### System Prompt Structure
```
You are a product specification assistant...
AVAILABLE KNOWLEDGE BASE: {compressed mapping}
CREATIVE IDEAS: {eureka snippet}
RULES: Reference SKUs by workspace-relative paths (skus/factual/sku_012)
       Wrap spec in ```markdown code block
       User types /confirm to finalize
```

### Chat Loop
1. LLM sends initial greeting (asks about app goals) — NOT a round
2. User types input → LLM responds → repeat (each user msg = 1 round)
3. `/confirm` → finalize prompt → extract spec → save
4. Max rounds → auto-finalize with current draft

## Configuration (.env)

```bash
# Module 4: Workspace Assembly
WORKSPACE_DIR=./workspace
CHATBOT_MODEL=Pro/zai-org/GLM-5
MAX_CHAT_ROUNDS=5
CHATBOT_TEMPERATURE=0.4
CHATBOT_MAX_TOKENS=8000

# Inherited from previous modules
SILICONFLOW_API_KEY=...
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
LOG_LEVEL=INFO
LOG_FORMAT=both
```

## CLI Commands

```bash
# Full pipeline
skus2workspace run                                    # Assemble + chatbot + README
skus2workspace run -v                                 # Verbose
skus2workspace run --skip-chatbot                     # No interactive chatbot
skus2workspace run -s <skus_dir> -w <workspace_dir>   # Custom paths

# Individual steps
skus2workspace assemble -s <skus_dir> -w <workspace_dir>  # Copy only
skus2workspace chatbot -w <workspace_dir>                  # Chatbot only (workspace must exist)
skus2workspace init                                        # Create workspace dir
```

## Verification

1. `skus2workspace assemble -s test_data/basel_skus -w workspace/`
   - Verify `workspace/skus/` has `factual/`, `procedural/`, `relational/`, `postprocessing/`, `skus_index.json`
   - Verify `workspace/mapping.md` paths are `skus/factual/...` (not `test_data/...`)
   - Verify `workspace/skus/skus_index.json` entries have rewritten paths
   - Verify `workspace/eureka.md` exists

2. `skus2workspace chatbot -w workspace/`
   - Verify interactive loop works, LLM responds
   - Type `/confirm` to finalize
   - Verify `workspace/spec.md` and `workspace/chat_log.json` created

3. `skus2workspace run -s test_data/basel_skus --skip-chatbot`
   - Verify full pipeline: `README.md` + `workspace_manifest.json` + all SKUs
   - Verify `workspace_manifest.json` has correct counts

4. `skus2workspace run -s test_data/basel_skus`
   - Full pipeline with chatbot interaction

## Performance

### Test: Basel Framework (420 SKUs)

| Metric | Value |
|--------|-------|
| Factual SKUs copied | 300 |
| Procedural skills copied | 82 |
| Total files copied | 775 |
| Paths rewritten | 803 |
| Assembly time | <1 second |
