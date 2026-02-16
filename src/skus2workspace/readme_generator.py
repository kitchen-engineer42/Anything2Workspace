"""Step 3: Generate README.md for the workspace."""

from pathlib import Path

import structlog

from skus2workspace.schemas.workspace import WorkspaceManifest

logger = structlog.get_logger(__name__)

README_TEMPLATE = """# Workspace

## Quick Start

1. **Read `spec.md`** — what to build
2. **Use `mapping.md`** — navigate SKUs by feature
3. **Check `eureka.md`** — creative ideas and cross-cutting insights

## Structure

```
workspace/
├── spec.md                      # App specification
├── mapping.md                   # SKU router — find the right knowledge
├── eureka.md                    # Creative insights and feature ideas
├── workspace_manifest.json      # Assembly metadata
├── chat_log.json                # Chatbot conversation log
└── skus/
    ├── factual/                 # Facts, definitions, data (header.md + content)
    ├── procedural/              # Skills and workflows (header.md + SKILL.md)
    ├── relational/              # Label tree + glossary
    ├── postprocessing/          # Bucketing, dedup, confidence reports
    └── skus_index.json          # Master index of all SKUs
```

## SKU Types

| Type | Description | Files |
|------|-------------|-------|
| **Factual** | Facts, definitions, data points, statistics | `header.md` + `content.md` or `content.json` |
| **Procedural** | Workflows, skills, step-by-step processes | `header.md` + `SKILL.md` |
| **Relational** | Category hierarchy and glossary | `label_tree.json` + `glossary.json` |

## Stats

{stats_section}

## How to Use

1. Start with `spec.md` to understand what the app should do
2. Use `mapping.md` to find relevant SKUs for each feature
3. Read SKU `header.md` files for quick summaries before loading full content
4. Reference `eureka.md` for creative ideas that connect multiple knowledge areas
"""


class ReadmeGenerator:
    """Generates README.md for the assembled workspace."""

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = Path(workspace_dir).resolve()

    def write(self, manifest: WorkspaceManifest) -> None:
        """
        Generate and write README.md.

        Args:
            manifest: WorkspaceManifest with counts and status.
        """
        stats_lines = []
        stats_lines.append(f"- **Factual SKUs**: {manifest.factual_count}")
        stats_lines.append(f"- **Procedural SKUs**: {manifest.procedural_count}")
        stats_lines.append(f"- **Relational knowledge**: {'Yes' if manifest.has_relational else 'No'}")
        stats_lines.append(f"- **Total files copied**: {manifest.total_files_copied}")

        stats_section = "\n".join(stats_lines)
        content = README_TEMPLATE.format(stats_section=stats_section)

        readme_path = self.workspace_dir / "README.md"
        readme_path.write_text(content, encoding="utf-8")

        manifest.has_readme = True
        logger.info("Generated README.md", path=str(readme_path))
