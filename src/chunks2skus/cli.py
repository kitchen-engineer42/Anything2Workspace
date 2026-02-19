"""CLI entry point for chunks2skus module."""

from pathlib import Path

import click

from chunks2skus.config import settings
from chunks2skus.pipeline import ExtractionPipeline
from chunks2skus.postprocessors.pipeline import PostprocessingPipeline
from chunks2skus.utils.logging_setup import setup_logging


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
def main(verbose: bool):
    """Chunks2SKUs - Knowledge extraction from chunks."""
    if verbose:
        settings.log_level = "DEBUG"
    setup_logging()


@main.command()
@click.option(
    "--chunks-dir",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Directory with chunks (default: output/chunks/)",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    help="Output directory for SKUs (default: output/skus/)",
)
def run(chunks_dir: Path | None, output_dir: Path | None):
    """Extract SKUs from all chunks."""
    pipeline = ExtractionPipeline(
        chunks_dir=chunks_dir,
        output_dir=output_dir,
    )

    index = pipeline.run()

    zh = settings.language == "zh"
    click.echo(f"\n{'提取完成！' if zh else 'Extraction complete!'}")
    click.echo(f"  {'SKU总数' if zh else 'Total SKUs'}: {index.total_skus}")
    click.echo(f"  {'总字符数' if zh else 'Total characters'}: {index.total_characters:,}")
    click.echo(f"  {'已处理片段数' if zh else 'Chunks processed'}: {len(index.chunks_processed)}")
    click.echo(f"\n{'按类型统计：' if zh else 'By type:'}")
    click.echo(f"  {'事实型' if zh else 'Factual'}: {index.factual_count}")
    click.echo(f"  {'关系型' if zh else 'Relational'}: {index.relational_count}")
    click.echo(f"  {'程序型' if zh else 'Procedural'}: {index.procedural_count}")
    click.echo(f"  {'元知识' if zh else 'Meta'}: {index.meta_count}")
    click.echo(f"\n  {'输出目录' if zh else 'Output'}: {pipeline.output_dir}")


@main.command("extract-chunk")
@click.argument("chunk_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    help="Output directory for SKUs",
)
def extract_chunk(chunk_path: Path, output_dir: Path | None):
    """Extract SKUs from a single chunk file."""
    if chunk_path.suffix.lower() != ".md":
        click.echo(f"Error: Expected markdown file, got {chunk_path.suffix}", err=True)
        raise SystemExit(1)

    pipeline = ExtractionPipeline(output_dir=output_dir)
    skus = pipeline.extract_single_chunk(chunk_path)

    click.echo(f"\nExtracted {len(skus)} SKUs from {chunk_path.name}:")
    for sku in skus:
        click.echo(
            f"  [{sku.get('classification', 'unknown')}] "
            f"{sku.get('name', 'unknown')}: {sku.get('description', '')[:50]}..."
        )

    click.echo(f"\n  Output: {pipeline.output_dir}")


@main.command("show-index")
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(exists=True, path_type=Path),
    help="SKUs output directory",
)
def show_index(output_dir: Path | None):
    """Display the SKUs index summary."""
    pipeline = ExtractionPipeline(output_dir=output_dir)
    click.echo(pipeline.show_index_summary())


@main.command("init")
def init():
    """Initialize output directories for SKU extraction."""
    settings.skus_output_dir.mkdir(parents=True, exist_ok=True)
    settings.factual_dir.mkdir(parents=True, exist_ok=True)
    settings.relational_dir.mkdir(parents=True, exist_ok=True)
    settings.procedural_dir.mkdir(parents=True, exist_ok=True)
    settings.meta_dir.mkdir(parents=True, exist_ok=True)

    click.echo("Created directories:")
    click.echo(f"  {settings.skus_output_dir}")
    click.echo(f"  {settings.factual_dir}")
    click.echo(f"  {settings.relational_dir}")
    click.echo(f"  {settings.procedural_dir}")
    click.echo(f"  {settings.meta_dir}")


@main.group()
def postprocess():
    """Postprocess SKUs: bucketing, dedup, proofreading."""
    pass


@postprocess.command("all")
@click.option(
    "--skus-dir",
    "-s",
    type=click.Path(exists=True, path_type=Path),
    help="SKUs directory (default: output/skus/)",
)
@click.option(
    "--chunks-dir",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Chunks directory for source lookup (default: output/chunks/)",
)
def postprocess_all(skus_dir: Path | None, chunks_dir: Path | None):
    """Run all 3 postprocessing steps sequentially."""
    pipeline = PostprocessingPipeline(skus_dir=skus_dir, chunks_dir=chunks_dir)
    results = pipeline.run_all()

    bucketing = results["bucketing"]
    dedup = results["dedup"]
    proof = results["proofreading"]

    zh = settings.language == "zh"
    click.echo(f"\n{'后处理完成！' if zh else 'Postprocessing complete!'}")
    click.echo(
        f"\n  {'分桶' if zh else 'Bucketing'}: "
        f"{bucketing.total_buckets} {'个桶，来自' if zh else 'buckets from'} "
        f"{bucketing.total_skus} {'个SKU' if zh else 'SKUs'}"
    )
    click.echo(
        f"  {'去重' if zh else 'Dedup'}: "
        f"{dedup.pairs_flagged} {'对标记' if zh else 'pairs flagged'}, "
        f"{dedup.total_deleted} {'已删除' if zh else 'deleted'}, "
        f"{dedup.total_kept} {'已保留' if zh else 'kept'}"
    )
    click.echo(
        f"  {'校对' if zh else 'Proofreading'}: "
        f"{proof.total_scored} {'已评分' if zh else 'scored'}, "
        f"{'平均置信度' if zh else 'avg confidence'} {proof.average_confidence:.3f}"
    )


@postprocess.command("bucket")
@click.option(
    "--skus-dir",
    "-s",
    type=click.Path(exists=True, path_type=Path),
    help="SKUs directory",
)
def postprocess_bucket(skus_dir: Path | None):
    """Run bucketing step only."""
    pipeline = PostprocessingPipeline(skus_dir=skus_dir)
    result = pipeline.run_bucket()
    click.echo(
        f"\nBucketing complete: {result.total_buckets} buckets "
        f"from {result.total_skus} SKUs"
    )
    click.echo(f"  Factual buckets: {len(result.factual_buckets)}")
    click.echo(f"  Procedural buckets: {len(result.procedural_buckets)}")


@postprocess.command("dedup")
@click.option(
    "--skus-dir",
    "-s",
    type=click.Path(exists=True, path_type=Path),
    help="SKUs directory",
)
def postprocess_dedup(skus_dir: Path | None):
    """Run dedup step only (requires bucketing_result.json)."""
    pipeline = PostprocessingPipeline(skus_dir=skus_dir)
    result = pipeline.run_dedup()
    click.echo(f"\nDedup complete!")
    click.echo(f"  Buckets scanned: {result.buckets_scanned}")
    click.echo(f"  Pairs flagged: {result.pairs_flagged}")
    click.echo(f"  Deleted: {result.total_deleted}")
    click.echo(f"  Rewritten: {result.total_rewritten}")
    click.echo(f"  Merged: {result.total_merged}")
    click.echo(f"  Kept: {result.total_kept}")


@postprocess.command("proof")
@click.option(
    "--skus-dir",
    "-s",
    type=click.Path(exists=True, path_type=Path),
    help="SKUs directory",
)
@click.option(
    "--chunks-dir",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Chunks directory for source lookup",
)
def postprocess_proof(skus_dir: Path | None, chunks_dir: Path | None):
    """Run proofreading step only."""
    pipeline = PostprocessingPipeline(skus_dir=skus_dir, chunks_dir=chunks_dir)
    result = pipeline.run_proof()
    click.echo(f"\nProofreading complete!")
    click.echo(f"  SKUs scored: {result.total_scored}")
    click.echo(f"  Average confidence: {result.average_confidence:.3f}")


if __name__ == "__main__":
    main()
