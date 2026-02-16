"""CLI entry point for markdown2chunks module."""

from pathlib import Path

import click
import structlog

from .config import settings
from .pipeline import ChunkingPipeline
from .utils.logging_setup import setup_logging
from .utils.token_estimator import estimate_tokens


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
def main(verbose: bool):
    """Markdown2Chunks - Smart chunking for long markdown files."""
    if verbose:
        settings.log_level = "DEBUG"
    setup_logging()


@main.command()
@click.option(
    "--input-dir",
    "-i",
    type=click.Path(exists=True, path_type=Path),
    help="Input directory (default: output/ from module 1)",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    help="Output directory for chunks",
)
def run(input_dir: Path | None, output_dir: Path | None):
    """Process all markdown files from module 1 output."""
    logger = structlog.get_logger(__name__)

    pipeline = ChunkingPipeline(
        input_dir=input_dir,
        output_dir=output_dir,
    )

    index = pipeline.run()

    click.echo(f"\nChunking complete!")
    click.echo(f"  Total chunks: {index.total_chunks}")
    click.echo(f"  Total tokens: {index.total_tokens:,}")
    click.echo(f"  Source files: {len(index.source_files)}")
    click.echo(f"  Output: {pipeline.output_dir}")


@main.command("chunk-file")
@click.argument("file_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    help="Output directory for chunks",
)
def chunk_file(file_path: Path, output_dir: Path | None):
    """Chunk a single markdown file."""
    logger = structlog.get_logger(__name__)

    if file_path.suffix.lower() != ".md":
        click.echo(f"Error: Expected markdown file, got {file_path.suffix}", err=True)
        raise SystemExit(1)

    output_dir = output_dir or Path("./chunks")
    output_dir.mkdir(parents=True, exist_ok=True)

    pipeline = ChunkingPipeline(output_dir=output_dir)
    chunks = pipeline.chunk_single_file(file_path)

    # Write chunks
    for chunk in chunks:
        stem = file_path.stem
        chunk_id = f"{stem}_chunk_{chunk.metadata.chunk_index + 1:03d}"
        chunk_filename = f"{chunk_id}.md"
        chunk_path = output_dir / chunk_filename

        chunk_path.write_text(
            chunk.to_markdown_with_frontmatter(),
            encoding="utf-8",
        )
        click.echo(f"  Created: {chunk_filename} ({chunk.metadata.estimated_tokens:,} tokens)")

    click.echo(f"\nCreated {len(chunks)} chunks in {output_dir}")


@main.command("estimate-tokens")
@click.argument("file_path", type=click.Path(exists=True, path_type=Path))
def estimate_tokens_cmd(file_path: Path):
    """Show estimated token count for a file."""
    content = file_path.read_text(encoding="utf-8")
    tokens = estimate_tokens(content)
    chars = len(content)

    click.echo(f"File: {file_path.name}")
    click.echo(f"  Characters: {chars:,}")
    click.echo(f"  Tokens: {tokens:,}")
    click.echo(f"  Ratio: {chars / tokens:.1f} chars/token")
    click.echo(f"  Max allowed: {settings.max_token_length:,} tokens")

    if tokens > settings.max_token_length:
        click.echo(f"  Status: EXCEEDS LIMIT (needs chunking)")
    else:
        click.echo(f"  Status: Within limit (single chunk)")


if __name__ == "__main__":
    main()
