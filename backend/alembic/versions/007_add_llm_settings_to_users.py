"""add_llm_settings_to_users

Per-user LLM provider settings: provider, model, Fernet-encrypted API key,
and custom base URL. NULL everywhere = system default Groq.

Revision ID: 007
Revises: 006
Create Date: 2026-09-27 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # User: per-user LLM settings (all nullable — NULL = default Groq).
    op.add_column(
        "users",
        sa.Column(
            "llm_provider",
            sa.String(32),
            nullable=True,
            comment="LLM provider: groq | openai | anthropic | gemini | ollama",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "llm_model",
            sa.String(128),
            nullable=True,
            comment="Per-user model override",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "llm_api_key",
            sa.Text(),
            nullable=True,
            comment="Fernet-encrypted LLM API key",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "llm_base_url",
            sa.String(512),
            nullable=True,
            comment="Custom endpoint base URL (Ollama / OpenAI-compatible)",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "llm_base_url")
    op.drop_column("users", "llm_api_key")
    op.drop_column("users", "llm_model")
    op.drop_column("users", "llm_provider")
