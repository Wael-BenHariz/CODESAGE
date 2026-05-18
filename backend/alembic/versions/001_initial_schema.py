"""Initial schema - create all tables

Revision ID: 001
Revises:
Create Date: 2026-05-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all initial tables and indexes.

    This migration creates the complete schema for CodeSage with:
    - Users table for GitHub OAuth
    - OAuth tokens for API access
    - GitHub installations for App-level access
    - Repositories linked to installations
    - Pull requests for tracking
    - Reviews for AI/human code reviews
    - Review comments for inline feedback
    - Webhook events for audit trail

    All tables use UUID primary keys with proper indexes for common queries.
    """
    # Enable required extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"pg_trgm\"")  # For fuzzy text search

    # ============================================================
    # USERS TABLE
    # ============================================================
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("github_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("login", sa.String(255), nullable=False, unique=True),
        sa.Column("email", sa.String(512), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="GitHub OAuth users with authentication tokens",
    )

    # Indexes for users
    op.create_index("idx_users_github_id", "users", ["github_id"], unique=True)
    op.create_index("idx_users_login", "users", ["login"], unique=True)
    op.create_index("idx_users_email", "users", ["email"])
    op.create_index("idx_users_updated_at", "users", ["updated_at"])

    # ============================================================
    # OAUTH_TOKENS TABLE
    # ============================================================
    op.create_table(
        "oauth_tokens",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Encrypted OAuth tokens for GitHub API access",
    )

    # Indexes for oauth_tokens
    op.create_index("idx_oauth_tokens_user_id", "oauth_tokens", ["user_id"])

    # ============================================================
    # GITHUB_INSTALLATIONS TABLE
    # ============================================================
    op.create_table(
        "github_installations",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("account_login", sa.String(255), nullable=False),
        sa.Column("account_type", sa.String(50), nullable=False),
        sa.Column("permissions", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="GitHub App installations linking app to accounts",
    )

    # Indexes for github_installations
    op.create_index("idx_github_installations_installation_id", "github_installations", ["installation_id"], unique=True)
    op.create_index("idx_github_installations_account_login", "github_installations", ["account_login"])
    op.create_index("idx_github_installations_app_id", "github_installations", ["app_id"])

    # ============================================================
    # REPOSITORIES TABLE
    # ============================================================
    op.create_table(
        "repositories",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("installation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("github_repo_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(512), nullable=False, unique=True),
        sa.Column("private", sa.Boolean(), nullable=False, default=False),
        sa.Column("default_branch", sa.String(255), nullable=False, default="main"),
        sa.Column("webhook_id", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["installation_id"], ["github_installations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="GitHub repositories connected to CodeSage",
    )

    # Indexes for repositories
    op.create_index("idx_repositories_installation_id", "repositories", ["installation_id"])
    op.create_index("idx_repositories_github_repo_id", "repositories", ["github_repo_id"])
    op.create_index("idx_repositories_full_name", "repositories", ["full_name"], unique=True)
    op.create_index("idx_repositories_enabled", "repositories", ["enabled"])
    op.create_index("idx_repositories_updated_at", "repositories", ["updated_at"])

    # ============================================================
    # PULL_REQUESTS TABLE
    # ============================================================
    op.create_table(
        "pull_requests",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True), nullable=False),
        sa.Column("github_pr_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, default="open"),
        sa.Column("author_login", sa.String(255), nullable=False),
        sa.Column("author_avatar_url", sa.String(1024), nullable=True),
        sa.Column("base_branch", sa.String(255), nullable=False),
        sa.Column("head_branch", sa.String(255), nullable=False),
        sa.Column("base_sha", sa.String(40), nullable=False),
        sa.Column("head_sha", sa.String(40), nullable=False),
        sa.Column("additions", sa.Integer(), nullable=False, default=0),
        sa.Column("deletions", sa.Integer(), nullable=False, default=0),
        sa.Column("changed_files", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Pull requests being tracked for code review",
    )

    # Indexes for pull_requests
    op.create_index("idx_pull_requests_repository_id", "pull_requests", ["repository_id"])
    op.create_index("idx_pull_requests_state", "pull_requests", ["state"])
    op.create_index("idx_pull_requests_author_login", "pull_requests", ["author_login"])
    op.create_index("idx_pull_requests_created_at", "pull_requests", ["created_at"])
    op.create_index("idx_pull_requests_updated_at", "pull_requests", ["updated_at"])
    # Composite index for common query: repo + state
    op.create_index("idx_pull_requests_repo_state", "pull_requests", ["repository_id", "state"])
    # Partial index for open PRs
    op.execute("""
        CREATE INDEX idx_pull_requests_open
        ON pull_requests(repository_id, updated_at DESC)
        WHERE state = 'open'
    """)

    # ============================================================
    # REVIEWS TABLE
    # ============================================================
    op.create_table(
        "reviews",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("pull_request_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("gemini_model", sa.String(100), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["pull_request_id"], ["pull_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        comment="AI and human reviews for pull requests",
    )

    # Indexes for reviews
    op.create_index("idx_reviews_pull_request_id", "reviews", ["pull_request_id"])
    op.create_index("idx_reviews_user_id", "reviews", ["user_id"])
    op.create_index("idx_reviews_status", "reviews", ["status"])
    op.create_index("idx_reviews_created_at", "reviews", ["created_at"])
    # Composite index for PR + status queries
    op.create_index("idx_reviews_pr_status", "reviews", ["pull_request_id", "status"])
    # Partial index for pending reviews
    op.execute("""
        CREATE INDEX idx_reviews_pending
        ON reviews(created_at ASC)
        WHERE status = 'pending'
    """)

    # ============================================================
    # REVIEW_COMMENTS TABLE
    # ============================================================
    op.create_table(
        "review_comments",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("review_id", UUID(as_uuid=True), nullable=False),
        sa.Column("pull_request_id", UUID(as_uuid=True), nullable=False),
        sa.Column("github_comment_id", sa.BigInteger(), nullable=True),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, default="info"),
        sa.Column("category", sa.String(100), nullable=False, default="general"),
        sa.Column("resolved", sa.Boolean(), nullable=False, default=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pull_request_id"], ["pull_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Inline review comments with severity and category",
    )

    # Indexes for review_comments
    op.create_index("idx_review_comments_review_id", "review_comments", ["review_id"])
    op.create_index("idx_review_comments_pull_request_id", "review_comments", ["pull_request_id"])
    op.create_index("idx_review_comments_github_comment_id", "review_comments", ["github_comment_id"])
    op.create_index("idx_review_comments_file_path", "review_comments", ["file_path"])
    op.create_index("idx_review_comments_severity", "review_comments", ["severity"])
    op.create_index("idx_review_comments_category", "review_comments", ["category"])
    # Composite index for file-based queries
    op.create_index("idx_review_comments_pr_file", "review_comments", ["pull_request_id", "file_path"])
    # Partial index for unresolved comments
    op.execute("""
        CREATE INDEX idx_review_comments_unresolved
        ON review_comments(pull_request_id, created_at DESC)
        WHERE resolved = false
    """)

    # ============================================================
    # WEBHOOK_EVENTS TABLE
    # ============================================================
    op.create_table(
        "webhook_events",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(255), nullable=False),
        sa.Column("delivery_id", sa.String(255), nullable=False, unique=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("payload", JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Audit trail of all GitHub webhook deliveries",
    )

    # Indexes for webhook_events
    op.create_index("idx_webhook_events_repository_id", "webhook_events", ["repository_id"])
    op.create_index("idx_webhook_events_delivery_id", "webhook_events", ["delivery_id"], unique=True)
    op.create_index("idx_webhook_events_event_type", "webhook_events", ["event_type"])
    op.create_index("idx_webhook_events_action", "webhook_events", ["action"])
    op.create_index("idx_webhook_events_processed", "webhook_events", ["processed"])
    op.create_index("idx_webhook_events_created_at", "webhook_events", ["created_at"])
    # Composite index for type + action queries
    op.create_index("idx_webhook_events_type_action", "webhook_events", ["event_type", "action"])
    # Partial index for pending events
    op.execute("""
        CREATE INDEX idx_webhook_events_pending
        ON webhook_events(created_at ASC)
        WHERE processed = false
    """)

    # ============================================================
    # TRIGGER FOR UPDATED_AT AUTO-UPDATE
    # ============================================================
    # Create a trigger function to automatically update updated_at
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql'
    """)

    # Apply the trigger to all tables with updated_at
    for table in ["users", "oauth_tokens", "github_installations", "repositories", "pull_requests", "reviews"]:
        op.execute(f"""
            CREATE TRIGGER update_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column()
        """)


def downgrade() -> None:
    """Drop all tables in reverse order due to foreign key dependencies.

    Note: This will lose all data. For production, consider archiving data
    before dropping tables.
    """
    # Drop triggers first
    for table in ["users", "oauth_tokens", "github_installations", "repositories", "pull_requests", "reviews"]:
        op.execute(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {table}")

    # Drop the trigger function
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")

    # Drop tables in reverse order of creation (due to foreign keys)
    op.drop_table("webhook_events")
    op.drop_table("review_comments")
    op.drop_table("reviews")
    op.drop_table("pull_requests")
    op.drop_table("repositories")
    op.drop_table("github_installations")
    op.drop_table("oauth_tokens")
    op.drop_table("users")

    # Drop extensions (optional, may fail if other objects use them)
    op.execute("DROP EXTENSION IF EXISTS \"pg_trgm\"")