"""Step 2: Interactive chatbot for generating spec.md."""

import re
from pathlib import Path

import click
import structlog

from skus2workspace.config import settings
from skus2workspace.schemas.workspace import ChatMessage, ChatSession
from skus2workspace.utils.llm_client import call_llm_chat

logger = structlog.get_logger(__name__)

# Max characters from mapping.md to include in compressed summary
MAPPING_SUMMARY_MAX_CHARS = 30000
# Max characters from eureka.md to include
EUREKA_SNIPPET_MAX_CHARS = 5000

SYSTEM_PROMPT_TEMPLATE = """You are a product specification assistant helping a user design an application.

You have access to a comprehensive knowledge base of Standard Knowledge Units (SKUs) organized into factual data, procedural skills, and relational knowledge. Your job is to:

1. Interview the user about their application goals, target users, and key features
2. Draft a spec.md document based on their answers
3. Iterate on the spec based on user feedback
4. Finalize the spec when the user is satisfied

AVAILABLE KNOWLEDGE BASE:
{mapping_summary}

CREATIVE IDEAS FROM KNOWLEDGE BASE:
{eureka_snippet}

RULES:
- Reference SKUs by workspace-relative paths (e.g., skus/factual/sku_012, skus/procedural/skill_005)
- When drafting the spec, wrap it in a ```markdown code block
- The user types /confirm to finalize the current spec
- Be concise in your questions — ask 2-3 focused questions at a time
- The spec should include: App name, Overview, Target users, Core features (with SKU references), Technical notes, and MVP scope"""

FINALIZE_PROMPT = """The user has confirmed the spec. Please output the FINAL, clean version of spec.md.

Output ONLY the spec content inside a ```markdown code block. No extra commentary.
Include all sections discussed. Make sure all SKU references use workspace-relative paths (skus/factual/..., skus/procedural/..., etc.)."""


def _compress_mapping(content: str) -> str:
    """
    Compress mapping.md by keeping section headers, SKU paths, and descriptions.
    Strips verbose "When to use" text to save tokens.
    """
    lines = content.split("\n")
    compressed = []

    for line in lines:
        stripped = line.strip()
        # Keep headers
        if stripped.startswith("#"):
            compressed.append(line)
        # Keep SKU path lines (### skus/factual/...)
        elif stripped.startswith("### "):
            compressed.append(line)
        # Keep description lines
        elif stripped.startswith("**Description:**"):
            compressed.append(line)
        # Skip "When to use" and blank lines between entries
        elif stripped == "---":
            compressed.append(line)

    result = "\n".join(compressed)
    if len(result) > MAPPING_SUMMARY_MAX_CHARS:
        result = result[:MAPPING_SUMMARY_MAX_CHARS] + "\n... (truncated)"
    return result


def _extract_spec(response: str) -> str:
    """
    Extract spec content from LLM response.

    Priority:
    1. ```markdown code block
    2. Largest ``` code block
    3. Full response if it starts with #
    """
    # Try ```markdown block first
    markdown_pattern = re.compile(r"```markdown\s*\n(.*?)```", re.DOTALL)
    match = markdown_pattern.search(response)
    if match:
        return match.group(1).strip()

    # Try largest ``` block
    code_blocks = re.findall(r"```(?:\w*)\s*\n(.*?)```", response, re.DOTALL)
    if code_blocks:
        return max(code_blocks, key=len).strip()

    # If response starts with #, treat as spec
    if response.strip().startswith("#"):
        return response.strip()

    return response.strip()


class SpecChatbot:
    """Interactive chatbot that generates spec.md through conversation."""

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = Path(workspace_dir).resolve()
        self.max_rounds = settings.max_chat_rounds
        self.session = ChatSession(max_rounds=self.max_rounds)

    def run(self) -> str:
        """
        Run the interactive chatbot loop.

        Returns:
            The final spec content.
        """
        logger.info("Starting spec chatbot", max_rounds=self.max_rounds)

        # Build context
        system_prompt = self._build_system_prompt()
        self.session.messages.append(ChatMessage(role="system", content=system_prompt))

        # Get initial greeting from LLM
        messages_for_api = [{"role": m.role, "content": m.content} for m in self.session.messages]
        greeting = call_llm_chat(messages_for_api)

        if not greeting:
            click.echo("Error: Failed to get LLM response. Check your API key.")
            return ""

        self.session.messages.append(ChatMessage(role="assistant", content=greeting))
        click.echo(f"\nAssistant: {greeting}\n")

        # Chat loop
        while self.session.rounds_used < self.max_rounds:
            # Get user input
            try:
                user_input = click.prompt("You", type=str)
            except (click.Abort, EOFError, KeyboardInterrupt):
                click.echo("\nChat ended by user.")
                break

            if not user_input.strip():
                continue

            # Check for /confirm
            if user_input.strip().lower() == "/confirm":
                self.session.confirmed = True
                click.echo("\nFinalizing spec...")
                spec = self._finalize()
                if spec:
                    self.session.spec_content = spec
                    self._save_spec(spec)
                    click.echo(f"\nspec.md saved to {self.workspace_dir / 'spec.md'}")
                return spec or ""

            # Add user message and increment round
            self.session.messages.append(ChatMessage(role="user", content=user_input))
            self.session.rounds_used += 1

            remaining = self.max_rounds - self.session.rounds_used
            if remaining <= 1:
                click.echo(f"  ({remaining} round remaining — type /confirm to finalize)")

            # Get LLM response
            messages_for_api = [
                {"role": m.role, "content": m.content} for m in self.session.messages
            ]
            response = call_llm_chat(messages_for_api)

            if not response:
                click.echo("Error: Failed to get LLM response.")
                continue

            self.session.messages.append(ChatMessage(role="assistant", content=response))
            click.echo(f"\nAssistant: {response}\n")

        # Max rounds reached — auto-finalize
        if not self.session.confirmed:
            click.echo(f"\nMax rounds ({self.max_rounds}) reached. Auto-finalizing...")
            spec = self._finalize()
            if spec:
                self.session.spec_content = spec
                self._save_spec(spec)
                click.echo(f"\nspec.md saved to {self.workspace_dir / 'spec.md'}")
            return spec or ""

        return self.session.spec_content or ""

    def _build_system_prompt(self) -> str:
        """Build system prompt with compressed mapping and eureka snippet."""
        mapping_summary = ""
        eureka_snippet = ""

        mapping_path = self.workspace_dir / "mapping.md"
        if mapping_path.exists():
            content = mapping_path.read_text(encoding="utf-8")
            mapping_summary = _compress_mapping(content)
            logger.info(
                "Loaded mapping.md",
                original_chars=len(content),
                compressed_chars=len(mapping_summary),
            )

        eureka_path = self.workspace_dir / "eureka.md"
        if eureka_path.exists():
            content = eureka_path.read_text(encoding="utf-8")
            eureka_snippet = content[:EUREKA_SNIPPET_MAX_CHARS]
            if len(content) > EUREKA_SNIPPET_MAX_CHARS:
                eureka_snippet += "\n... (truncated)"
            logger.info("Loaded eureka.md", chars=len(eureka_snippet))

        return SYSTEM_PROMPT_TEMPLATE.format(
            mapping_summary=mapping_summary or "(no mapping available)",
            eureka_snippet=eureka_snippet or "(no eureka notes available)",
        )

    def _finalize(self) -> str | None:
        """Send finalize prompt and extract clean spec."""
        self.session.messages.append(ChatMessage(role="user", content=FINALIZE_PROMPT))

        messages_for_api = [
            {"role": m.role, "content": m.content} for m in self.session.messages
        ]
        response = call_llm_chat(messages_for_api)

        if not response:
            logger.error("Failed to get final spec from LLM")
            return None

        self.session.messages.append(ChatMessage(role="assistant", content=response))
        return _extract_spec(response)

    def _save_spec(self, content: str) -> None:
        """Save spec.md to workspace."""
        spec_path = self.workspace_dir / "spec.md"
        spec_path.write_text(content, encoding="utf-8")
        logger.info("Saved spec.md", path=str(spec_path), chars=len(content))

    def get_session(self) -> ChatSession:
        """Return the current chat session for logging."""
        return self.session
