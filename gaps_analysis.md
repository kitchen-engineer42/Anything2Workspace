 Anything2Workspace — Systematic Gap Analysis                                                                                        
                                                                                                                                     
 Context                                                                                                                             
                                                                                                                                     
 All 4 modules are implemented, stress-tested on a 2000-page Basel Framework PDF (300 factual SKUs, 82 procedural skills, relational 
  knowledge, meta knowledge), packaged in Docker, and pushed to GitHub. This analysis reviews the project from a knowledge           
 management / NLP algorithm perspective to identify what's systematically missing.                                                   
                                                                                                                                     
 ---                                                                                                                                 
 Severity Summary                                                                                                                    

 ┌──────────┬───────┬──────────────────────────────────────────────────────────────────────┐
 │ Severity │ Count │                                Theme                                 │
 ├──────────┼───────┼──────────────────────────────────────────────────────────────────────┤
 │ CRITICAL │ 5     │ Implementation bugs that silently lose data or produce wrong results │
 ├──────────┼───────┼──────────────────────────────────────────────────────────────────────┤
 │ HIGH     │ 9     │ Missing capabilities that significantly degrade knowledge quality    │
 ├──────────┼───────┼──────────────────────────────────────────────────────────────────────┤
 │ MEDIUM   │ 10    │ Design gaps that limit scalability, navigability, or robustness      │
 ├──────────┼───────┼──────────────────────────────────────────────────────────────────────┤
 │ LOW      │ 8     │ Nice-to-have capabilities for future roadmap                         │
 └──────────┴───────┴──────────────────────────────────────────────────────────────────────┘

 ---
 CRITICAL — Implementation Bugs (fix before next production run)

 C1. Dedup rewrite action is a no-op

 File: src/chunks2skus/postprocessors/dedup.py lines 302-305
 The Tier 2 LLM generates new_content for rewrites, but _apply_action only logs "Rewrite flagged (manual review)" and discards the
 content. SKUs flagged for rewriting remain unchanged.

 C2. Dedup merge deletes but doesn't write merged content

 File: src/chunks2skus/postprocessors/dedup.py lines 307-311
 The merge action deletes one SKU but never writes the LLM's merged_content to the surviving SKU. The unique information from the
 deleted SKU is lost.

 C3. Label assignment uses naive substring match

 File: src/chunks2skus/postprocessors/bucketing.py lines 246-257
 _assign_labels uses label.lower() in text — so "risk" matches "asterisk". In the Basel test, all label_paths came back empty,
 meaning the label similarity channel (weight 0.3) contributed zero signal to bucketing.

 C4. Glossary overwrites definitions and loses multi-source provenance

 File: src/chunks2skus/schemas/sku.py lines 143-158
 Glossary.add_or_update() overwrites definition with the latest chunk's version (relying on LLM to merge, which is fragile).
 source_chunk retains only the first chunk — a term enriched across chunks 1, 5, 12 shows only chunk 1.

 C5. Zero automated tests

 No test_*.py files exist anywhere. The label substring bug, the dedup no-ops, and the glossary data loss would all be caught by
 trivial unit tests. No golden-set evaluation, no accuracy metrics, no regression safety net.

 ---
 HIGH — Significant Knowledge Quality Gaps

 H1. No structured output enforcement for LLM calls

 File: src/chunks2skus/utils/llm_client.py
 All LLM calls use text-only "Output ONLY valid JSON" instruction. No response_format={"type": "json_object"}. Parse failures cause
 chunks to be silently skipped with no retry — permanent data loss.

 H2. No retry on LLM parse failures

 File: all extractors (factual_extractor.py, etc.)
 When parse_json_response returns None, the extractor returns [] and moves on. No retry, no error prompt append, no fallback.

 H3. Relational schema cannot represent typed relationships

 Files: src/chunks2skus/schemas/sku.py, src/chunks2skus/extractors/relational_extractor.py
 The extraction prompt asks for "A causes B, X is part of Y" but LabelTree only holds tree hierarchy and Glossary.related_terms is
 list[str] with no relationship qualifier. Rich relational knowledge is extracted by the LLM and immediately lost at the schema
 boundary.

 H4. No entity resolution or canonical form normalization

 "G-SIB" and "Global Systemically Important Banks" produce separate glossary entries and separate SKUs. No alias tracking, no fuzzy
 matching, no canonical forms. Knowledge fragments across surface form variants.

 H5. No cross-SKU linking

 SKUHeader has no related_skus, depends_on, or contradicts fields. Each SKU is an island. A coding agent cannot navigate from a
 definition SKU to the procedure that uses it.

 H6. No contradiction detection

 Two factual SKUs can state contradictory things about the same entity with zero flagging. Dedup Tier 2 mentions "contradictory" but
  the action vocabulary (keep/delete/rewrite/merge) has no explicit contradiction handling.

 H7. ParseResult not persisted to disk

 File: src/anything2markdown/pipeline.py
 Module 1's ParseResult objects (parser used, timing, JIT metadata) are ephemeral in memory. No parse_results_index.json. The
 provenance chain breaks at the Module 1 → Module 2 boundary.

 H8. eureka.md doesn't follow its own prompt rules

 File: src/chunks2skus/extractors/meta_extractor.py
 Prompt says "organize by THEME, max 20 bullets." Actual output: 21 per-chunk sections, 63 bullets. No few-shot examples in any
 prompt across the project.

 H9. mapping.md grows unbounded

 Basel test: 124KB for 300 SKUs. This is passed into the LLM prompt for every chunk, consuming context window. Will not scale to
 1000+ SKU corpora.

 ---
 MEDIUM — Design Gaps Limiting Scalability & Robustness

 M1. TF-IDF computed on descriptions only (often <30 words), not content

 M2. No embedding caching — every bucketing run recomputes all embeddings

 M3. Dedup only within buckets, not cross-bucket

 M4. No chunk overlap/context windows — clean cuts lose boundary context

 M5. No temporal reasoning — no valid_from/as_of_date on SKUs

 M6. No extraction-time confidence (only post-hoc via web search)

 M7. Forward-only pipeline with no quality feedback loops between modules

 M8. No incremental/delta processing for Modules 1 and 2

 M9. No end-to-end pipeline orchestrator (anything2workspace run)

 M10. No document metadata extraction (author, date, title from PDF/PPTX fields)

 ---
 LOW — Future Roadmap

 L1. No coreference resolution (pronouns → entity names)

 L2. No cross-reference detection in chunks ("see Section 3.2" → dangling)

 L3. No special handling for tables/code blocks as atomic units in chunking

 L4. No citation/bibliography extraction for academic documents

 L5. No graph data structure (only tree + flat glossary, no cycles/cross-links)

 L6. No ontology alignment with external vocabularies (WordNet, Wikidata)

 L7. No edge weighting on relationships

 L8. No schema versioning on persisted JSON artifacts

 ---
 Prioritized Implementation Roadmap

 Phase 1: Bug Fixes (immediate)

 Fix C1-C4 — these are code-level bugs that produce silent data loss or wrong results.
 - Implement dedup rewrite and merge actions properly
 - Replace label substring match with word-boundary regex or embedding-based matching
 - Change GlossaryEntry.source_chunk: str → source_chunks: list[str], accumulate on update

 Phase 2: Reliability (short-term)

 Address H1, H2, H5, C5 — make the pipeline robust and testable.
 - Add response_format to LLM calls + retry with error feedback on parse failures
 - Add basic unit tests for pure functions (glossary merge, label assignment, JSON parsing, path rewriting)
 - Add few-shot examples to extraction prompts (addresses H8)

 Phase 3: Knowledge Quality (medium-term)

 Address H3, H4, H5, H6, H9 — upgrade the knowledge representation.
 - Add Relationship model with typed predicates (is-a, has-a, causes, etc.) to relational schema
 - Add aliases: list[str] to glossary + entity resolution post-processing pass
 - Add related_skus: list[str] to SKUHeader, populated during meta extraction
 - Add contradiction flagging to dedup
 - Implement mapping.md pagination (hierarchical sub-files or structured JSON)

 Phase 4: Pipeline Maturity (medium-term)

 Address H7, M8, M9 — make the pipeline production-ready.
 - Persist parse_results_index.json from Module 1
 - Add incremental processing (hash-based skip) to Modules 1 and 2
 - Add top-level anything2workspace run orchestrator
 - Add embedding caching

 Phase 5: Advanced NLP (long-term)

 Address M4, M5, L1, L5 — advanced knowledge management capabilities.
 - Chunk overlap with configurable token count
 - Temporal metadata on SKUs
 - Knowledge graph data structure (NetworkX → JSON serialization)
 - Coreference resolution pre-processing step

 ---
 Key Files for Each Phase

 ┌─────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │      Phase      │                                              Files to modify                                              │
 ├─────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ 1 (Bugs)        │ postprocessors/dedup.py, postprocessors/bucketing.py, schemas/sku.py                                      │
 ├─────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ 2 (Reliability) │ utils/llm_client.py, all extractors, new tests/ directory                                                 │
 ├─────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ 3 (Knowledge)   │ schemas/sku.py, extractors/relational_extractor.py, extractors/meta_extractor.py, postprocessors/dedup.py │
 ├─────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ 4 (Pipeline)    │ anything2markdown/pipeline.py, markdown2chunks/pipeline.py, new top-level CLI                             │
 ├─────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ 5 (Advanced)    │ markdown2chunks/chunkers/, schemas/sku.py, new knowledge_graph.py                                         │
 └─────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────┘