"""CLI entry point for skus2workspace module."""

from pathlib import Path

import click

from skus2workspace.config import settings
from skus2workspace.pipeline import WorkspacePipeline
from skus2workspace.utils.logging_setup import setup_logging


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
def main(verbose: bool):
    """SKUs2Workspace - Assemble SKUs into a self-contained workspace."""
    if verbose:
        settings.log_level = "DEBUG"
    setup_logging()


@main.command()
@click.option(
    "--skus-dir",
    "-s",
    type=click.Path(exists=True, path_type=Path),
    help="Source SKUs directory (default: output/skus/)",
)
@click.option(
    "--workspace-dir",
    "-w",
    type=click.Path(path_type=Path),
    help="Target workspace directory (default: ./workspace/)",
)
@click.option(
    "--skip-chatbot",
    is_flag=True,
    help="Skip the interactive chatbot step",
)
def run(skus_dir: Path | None, workspace_dir: Path | None, skip_chatbot: bool):
    """Run the full workspace pipeline."""
    pipeline = WorkspacePipeline(
        skus_dir=skus_dir,
        workspace_dir=workspace_dir,
    )

    manifest = pipeline.run(skip_chatbot=skip_chatbot)

    click.echo(f"\nWorkspace ready!")
    click.echo(f"  Location: {pipeline.workspace_dir}")
    click.echo(f"  Factual SKUs: {manifest.factual_count}")
    click.echo(f"  Procedural SKUs: {manifest.procedural_count}")
    click.echo(f"  Relational: {'Yes' if manifest.has_relational else 'No'}")
    click.echo(f"  spec.md: {'Yes' if manifest.has_spec else 'No'}")
    click.echo(f"  README.md: {'Yes' if manifest.has_readme else 'No'}")
    click.echo(f"  Total files: {manifest.total_files_copied}")
    click.echo(f"  Paths rewritten: {manifest.paths_rewritten}")


@main.command()
@click.option(
    "--skus-dir",
    "-s",
    type=click.Path(exists=True, path_type=Path),
    help="Source SKUs directory",
)
@click.option(
    "--workspace-dir",
    "-w",
    type=click.Path(path_type=Path),
    help="Target workspace directory",
)
def assemble(skus_dir: Path | None, workspace_dir: Path | None):
    """Copy and organize SKUs into workspace (no chatbot)."""
    pipeline = WorkspacePipeline(
        skus_dir=skus_dir,
        workspace_dir=workspace_dir,
    )

    manifest = pipeline.assemble_only()

    click.echo(f"\nAssembly complete!")
    click.echo(f"  Location: {pipeline.workspace_dir}")
    click.echo(f"  Factual SKUs: {manifest.factual_count}")
    click.echo(f"  Procedural SKUs: {manifest.procedural_count}")
    click.echo(f"  Total files: {manifest.total_files_copied}")
    click.echo(f"  Paths rewritten: {manifest.paths_rewritten}")


@main.command()
@click.option(
    "--workspace-dir",
    "-w",
    type=click.Path(exists=True, path_type=Path),
    help="Workspace directory (must already exist with mapping.md)",
)
def chatbot(workspace_dir: Path | None):
    """Run the spec chatbot on an existing workspace."""
    pipeline = WorkspacePipeline(workspace_dir=workspace_dir)
    spec = pipeline.chatbot_only()

    if spec:
        click.echo(f"\nspec.md generated ({len(spec)} chars)")
        click.echo(f"  Saved to: {pipeline.workspace_dir / 'spec.md'}")
    else:
        click.echo("\nNo spec generated.")


@main.command()
def init():
    """Create the workspace directory."""
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"Created workspace directory: {settings.workspace_dir}")


if __name__ == "__main__":
    main()
