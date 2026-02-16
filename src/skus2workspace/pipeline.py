"""Main orchestration pipeline for workspace assembly."""

import json
from datetime import datetime
from pathlib import Path

import structlog

from skus2workspace.assembler import WorkspaceAssembler
from skus2workspace.chatbot import SpecChatbot
from skus2workspace.config import settings
from skus2workspace.readme_generator import ReadmeGenerator
from skus2workspace.schemas.workspace import WorkspaceManifest

logger = structlog.get_logger(__name__)


class WorkspacePipeline:
    """
    Main pipeline for assembling a workspace from SKUs.

    Steps:
    1. Assemble: copy/organize SKUs, rewrite paths
    2. Chatbot: interactive spec.md generation (optional)
    3. README: generate README.md
    """

    def __init__(
        self,
        skus_dir: Path | None = None,
        workspace_dir: Path | None = None,
    ):
        self.skus_dir = Path(skus_dir) if skus_dir else settings.skus_output_dir
        self.workspace_dir = Path(workspace_dir) if workspace_dir else settings.workspace_dir

    def run(self, skip_chatbot: bool = False) -> WorkspaceManifest:
        """
        Run the full workspace pipeline.

        Args:
            skip_chatbot: If True, skip the interactive chatbot step.

        Returns:
            WorkspaceManifest with assembly metadata.
        """
        start_time = datetime.now()
        logger.info(
            "Starting workspace pipeline",
            skus_dir=str(self.skus_dir),
            workspace_dir=str(self.workspace_dir),
            skip_chatbot=skip_chatbot,
        )

        # Step 1: Assemble
        manifest = self.assemble_only()

        # Step 2: Chatbot (optional)
        if not skip_chatbot:
            spec = self.chatbot_only()
            if spec:
                manifest.has_spec = True

        # Step 3: README
        readme_gen = ReadmeGenerator(self.workspace_dir)
        readme_gen.write(manifest)

        # Save manifest
        self._save_manifest(manifest)

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Workspace pipeline complete",
            total_files=manifest.total_files_copied,
            has_spec=manifest.has_spec,
            has_readme=manifest.has_readme,
            duration_seconds=f"{duration:.1f}",
        )

        return manifest

    def assemble_only(self) -> WorkspaceManifest:
        """Run only the assembly step."""
        assembler = WorkspaceAssembler(self.skus_dir, self.workspace_dir)
        return assembler.assemble()

    def chatbot_only(self) -> str:
        """
        Run only the chatbot step.
        Workspace must already exist with mapping.md.

        Returns:
            Spec content string.
        """
        chatbot = SpecChatbot(self.workspace_dir)
        spec = chatbot.run()

        # Save chat log
        session = chatbot.get_session()
        chat_log_path = self.workspace_dir / "chat_log.json"
        chat_log_path.write_text(
            session.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info(
            "Saved chat log",
            path=str(chat_log_path),
            rounds=session.rounds_used,
            confirmed=session.confirmed,
        )

        return spec

    def _save_manifest(self, manifest: WorkspaceManifest) -> None:
        """Save workspace manifest to disk."""
        manifest_path = self.workspace_dir / "workspace_manifest.json"
        manifest_path.write_text(
            manifest.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info("Saved workspace manifest", path=str(manifest_path))
