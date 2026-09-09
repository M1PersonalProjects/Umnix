from logger_config import logger


async def ensure_runtime_schema(pool) -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS web_auth_requests (
            request_id UUID PRIMARY KEY,
            browser_token_hash TEXT NOT NULL,
            bot_token_hash TEXT NOT NULL UNIQUE,
            tg_id BIGINT,
            approved_at TIMESTAMPTZ,
            consumed_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_web_auth_requests_expires
        ON web_auth_requests(expires_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_web_auth_requests_tg_id
        ON web_auth_requests(tg_id, created_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS activity_events (
            activity_id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
            source TEXT NOT NULL CHECK (source IN ('web', 'telegram', 'system')),
            action TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            session_id UUID REFERENCES chat_sessions(session_id) ON DELETE SET NULL,
            attachment_id BIGINT REFERENCES attachments(attachment_id) ON DELETE SET NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_activity_user_created
        ON activity_events(user_id, created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_activity_created
        ON activity_events(created_at DESC)
        """,
        "ALTER TABLE book ADD COLUMN IF NOT EXISTS source_pdf_name TEXT",
        "ALTER TABLE book ADD COLUMN IF NOT EXISTS source_pdf_path TEXT",
        "ALTER TABLE textbook_digitization_jobs ADD COLUMN IF NOT EXISTS proposed_book_class INTEGER",
        "ALTER TABLE textbook_digitization_jobs ADD COLUMN IF NOT EXISTS proposed_book_program TEXT",
        "ALTER TABLE textbook_digitization_jobs ADD COLUMN IF NOT EXISTS proposed_book_author TEXT",
        "ALTER TABLE textbook_digitization_jobs ADD COLUMN IF NOT EXISTS proposed_book_title TEXT",
    )
    async with pool.acquire() as conn:
        for statement in statements:
            await conn.execute(statement)
    logger.info("runtime_schema_ready")
