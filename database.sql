-- Umnix clean PostgreSQL schema
-- Creates only structures used by the current application.

BEGIN;

DROP TYPE IF EXISTS task_status CASCADE;
DROP TYPE IF EXISTS user_role CASCADE;

CREATE TYPE user_role AS ENUM ('student', 'parent', 'admin');
CREATE TYPE task_status AS ENUM ('created', 'in_progress', 'pending_review', 'completed', 'evaluated', 'cancelled');

CREATE TABLE users (
    tg_id BIGINT PRIMARY KEY,
    username TEXT,
    role user_role NOT NULL,
    mentor_kind TEXT CHECK (mentor_kind IS NULL OR mentor_kind IN ('teacher', 'parent')),
    parent_id BIGINT REFERENCES users(tg_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (parent_id IS NULL OR parent_id <> tg_id)
);
CREATE INDEX idx_users_parent_role ON users(parent_id, role);
CREATE INDEX idx_users_role_mentor_kind ON users(role, mentor_kind);

CREATE TABLE web_auth_requests (
    request_id UUID PRIMARY KEY,
    browser_token_hash TEXT NOT NULL,
    bot_token_hash TEXT NOT NULL UNIQUE,
    tg_id BIGINT,
    approved_at TIMESTAMPTZ,
    consumed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_web_auth_requests_expires ON web_auth_requests(expires_at);
CREATE INDEX idx_web_auth_requests_tg_id ON web_auth_requests(tg_id, created_at DESC);

CREATE TABLE book (
    book_id SERIAL PRIMARY KEY,
    book_title TEXT NOT NULL,
    book_program TEXT NOT NULL,
    book_class INTEGER NOT NULL CHECK (book_class BETWEEN 1 AND 11),
    book_author TEXT,
    source_pdf_name TEXT,
    source_pdf_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (book_title, book_program, book_class)
);
CREATE INDEX idx_book_class_program ON book(book_class, book_program);

CREATE TABLE page (
    page_id BIGSERIAL PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES book(book_id) ON DELETE CASCADE,
    page_title TEXT,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    page_paragraph TEXT,
    page_html TEXT,
    page_image TEXT,
    page_text TEXT,
    page_markdown TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (book_id, page_number)
);
CREATE INDEX idx_page_book_paragraph ON page(book_id, page_paragraph);
CREATE INDEX idx_page_book_number ON page(book_id, page_number);

CREATE TABLE chat_sessions (
    session_id UUID PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'Новый чат',
    chat_type TEXT NOT NULL DEFAULT 'web' CHECK (chat_type IN ('web', 'telegram_default')),
    book_id INTEGER REFERENCES book(book_id) ON DELETE SET NULL,
    page_id BIGINT REFERENCES page(page_id) ON DELETE SET NULL,
    context_locked BOOLEAN NOT NULL DEFAULT FALSE,
    active_context_mode TEXT NOT NULL DEFAULT 'general'
        CHECK (active_context_mode IN ('general', 'book', 'attachment')),
    active_paragraph TEXT,
    active_attachment_ids INTEGER[] NOT NULL DEFAULT '{}'::INTEGER[],
    active_context_updated_at TIMESTAMPTZ,
    memory_state JSONB NOT NULL DEFAULT '{}'::JSONB,
    memory_summary TEXT NOT NULL DEFAULT '',
    memory_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((NOT context_locked) OR book_id IS NOT NULL)
);
CREATE UNIQUE INDEX idx_chat_sessions_telegram_default ON chat_sessions(user_id) WHERE chat_type='telegram_default';
CREATE INDEX idx_chat_sessions_user_updated ON chat_sessions(user_id, updated_at DESC);

CREATE TABLE chat_messages (
    message_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    session_id UUID REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    sender TEXT NOT NULL CHECK (sender IN ('user', 'ai')),
    message_text TEXT NOT NULL DEFAULT '',
    attachment_name TEXT,
    attachment_type TEXT,
    message_source TEXT NOT NULL DEFAULT 'web' CHECK (message_source IN ('web', 'telegram')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_chat_messages_session_created ON chat_messages(session_id, created_at, message_id);
CREATE INDEX idx_chat_messages_user_session ON chat_messages(user_id, session_id, message_id DESC);

CREATE TABLE attachments (
    attachment_id BIGSERIAL PRIMARY KEY,
    owner_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    storage_name TEXT NOT NULL,
    storage_path TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL,
    extension TEXT,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    sha256 CHAR(64) NOT NULL,
    extracted_text TEXT,
    preview_status TEXT NOT NULL DEFAULT 'not_required',
    preview_path TEXT,
    processing_status TEXT NOT NULL DEFAULT 'ready',
    processing_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_attachments_owner_created ON attachments(owner_id, created_at DESC);
CREATE INDEX idx_attachments_sha256 ON attachments(sha256);

CREATE TABLE chat_message_attachments (
    message_id BIGINT NOT NULL REFERENCES chat_messages(message_id) ON DELETE CASCADE,
    attachment_id BIGINT NOT NULL REFERENCES attachments(attachment_id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (message_id, attachment_id)
);
CREATE INDEX idx_chat_message_attachments_session ON chat_message_attachments(session_id, message_id);

CREATE TABLE tasks_history (
    task_id BIGSERIAL PRIMARY KEY,
    student_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    parent_id BIGINT REFERENCES users(tg_id) ON DELETE CASCADE,
    assignment_source TEXT NOT NULL DEFAULT 'teacher' CHECK (assignment_source IN ('teacher', 'tutor_practice')),
    assignment_batch_id UUID,
    title TEXT NOT NULL DEFAULT '',
    parent_comment TEXT NOT NULL DEFAULT '',
    ai_instructions TEXT,
    subject TEXT NOT NULL DEFAULT 'Практика',
    topic TEXT NOT NULL DEFAULT '',
    topic_context JSONB NOT NULL DEFAULT '{}'::JSONB,
    questions_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    student_answers_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    status task_status NOT NULL DEFAULT 'created',
    sent_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    cancellation_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (assignment_source='teacher' AND parent_id IS NOT NULL)
        OR (assignment_source='tutor_practice' AND parent_id IS NULL)
    )
);
CREATE INDEX idx_tasks_student_source_status ON tasks_history(student_id, assignment_source, status, created_at DESC);
CREATE INDEX idx_tasks_teacher_source ON tasks_history(parent_id, assignment_source, created_at DESC);
CREATE INDEX idx_tasks_batch ON tasks_history(assignment_batch_id);

CREATE TABLE task_submissions (
    submission_id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES tasks_history(task_id) ON DELETE CASCADE,
    student_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    answer_text TEXT NOT NULL DEFAULT '',
    attempt_number INTEGER NOT NULL DEFAULT 1 CHECK (attempt_number > 0),
    ai_feedback TEXT,
    teacher_comment TEXT,
    reviewed_by BIGINT REFERENCES users(tg_id) ON DELETE SET NULL,
    score DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'pending_review'
        CHECK (status IN ('pending_review', 'reviewed', 'completed', 'needs_revision')),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMPTZ,
    UNIQUE(task_id, student_id, attempt_number)
);
CREATE INDEX idx_task_submissions_task_student ON task_submissions(task_id, student_id, attempt_number DESC);

CREATE TABLE task_attachments (
    task_id BIGINT NOT NULL REFERENCES tasks_history(task_id) ON DELETE CASCADE,
    attachment_id BIGINT NOT NULL REFERENCES attachments(attachment_id) ON DELETE CASCADE,
    visible_to_student BOOLEAN NOT NULL DEFAULT TRUE,
    use_as_ai_context BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(task_id, attachment_id)
);

CREATE TABLE task_submission_attachments (
    submission_id BIGINT NOT NULL REFERENCES task_submissions(submission_id) ON DELETE CASCADE,
    attachment_id BIGINT NOT NULL REFERENCES attachments(attachment_id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(submission_id, attachment_id)
);

CREATE TABLE interactive_apps (
    app_id UUID PRIMARY KEY,
    owner_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    source_message_id BIGINT REFERENCES chat_messages(message_id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    app_type TEXT NOT NULL DEFAULT 'educational',
    question_count INTEGER NOT NULL DEFAULT 0 CHECK (question_count >= 0),
    original_request TEXT NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1 CHECK (current_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_interactive_apps_owner_session ON interactive_apps(owner_id, session_id, updated_at DESC);

CREATE TABLE task_drafts (
    draft_id UUID PRIMARY KEY,
    teacher_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    source_message_id BIGINT REFERENCES chat_messages(message_id) ON DELETE SET NULL,
    interactive_app_id UUID REFERENCES interactive_apps(app_id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT 'Практика',
    topic TEXT NOT NULL DEFAULT '',
    parent_comment TEXT NOT NULL DEFAULT '', ai_instructions TEXT, reference_answer TEXT NOT NULL DEFAULT '',
    book_id INTEGER REFERENCES book(book_id) ON DELETE SET NULL,
    page_id BIGINT REFERENCES page(page_id) ON DELETE SET NULL,
    student_ids JSONB NOT NULL DEFAULT '[]'::JSONB, attachment_ids JSONB NOT NULL DEFAULT '[]'::JSONB,
    attachment_options JSONB NOT NULL DEFAULT '[]'::JSONB, generated_items JSONB NOT NULL DEFAULT '[]'::JSONB,
    source_trace JSONB NOT NULL DEFAULT '[]'::JSONB, context_mode TEXT, used_pages JSONB NOT NULL DEFAULT '[]'::JSONB,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMPTZ
);
CREATE INDEX idx_task_drafts_teacher_updated ON task_drafts(teacher_id, updated_at DESC);

CREATE TABLE interactive_app_versions (
    app_id UUID NOT NULL REFERENCES interactive_apps(app_id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    version_id UUID NOT NULL UNIQUE,
    parent_version_id UUID REFERENCES interactive_app_versions(version_id) ON DELETE SET NULL,
    source_message_id BIGINT REFERENCES chat_messages(message_id) ON DELETE SET NULL,
    html_document TEXT NOT NULL,
    change_request TEXT NOT NULL DEFAULT '',
    created_by BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(app_id, version_no)
);
CREATE INDEX idx_interactive_versions_parent ON interactive_app_versions(parent_version_id);
CREATE INDEX idx_interactive_versions_source_message ON interactive_app_versions(source_message_id);

CREATE TABLE interactive_assignments (
    assignment_id BIGSERIAL PRIMARY KEY,
    app_id UUID NOT NULL REFERENCES interactive_apps(app_id) ON DELETE CASCADE,
    teacher_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    student_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    task_id BIGINT REFERENCES tasks_history(task_id) ON DELETE SET NULL,
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(app_id, student_id)
);
CREATE INDEX idx_interactive_assignments_student ON interactive_assignments(student_id, assigned_at DESC);
CREATE INDEX idx_interactive_assignments_version ON interactive_assignments(app_id, student_id, version_no);

CREATE TABLE interactive_results (
    result_id BIGSERIAL PRIMARY KEY,
    app_id UUID NOT NULL REFERENCES interactive_apps(app_id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    student_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    assignment_id BIGINT REFERENCES interactive_assignments(assignment_id) ON DELETE CASCADE,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    max_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    progress JSONB NOT NULL DEFAULT '{}'::JSONB,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_interactive_results_student_app ON interactive_results(student_id, app_id, created_at DESC);

CREATE TABLE textbook_digitization_jobs (
    job_id BIGSERIAL PRIMARY KEY,
    batch_id UUID NOT NULL,
    requested_by BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    book_id INTEGER REFERENCES book(book_id) ON DELETE SET NULL,
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    checksum_sha256 CHAR(64) NOT NULL,
    proposed_book_class INTEGER,
    proposed_book_program TEXT,
    proposed_book_author TEXT,
    proposed_book_title TEXT,
    status TEXT NOT NULL
        CHECK (status IN (
            'matching', 'waiting_for_book', 'pending', 'processing',
            'completed', 'failed', 'cancelled'
        )),
    stage TEXT,
    match_type TEXT,
    error_text TEXT,
    processed_pages INTEGER NOT NULL DEFAULT 0,
    total_pages INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    matched_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_digitization_jobs_status_created ON textbook_digitization_jobs(status, created_at);
CREATE INDEX idx_digitization_jobs_batch ON textbook_digitization_jobs(batch_id, created_at);
CREATE INDEX idx_digitization_jobs_checksum ON textbook_digitization_jobs(checksum_sha256);


CREATE TABLE activity_events (
    activity_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('web', 'telegram', 'system')),
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    session_id UUID REFERENCES chat_sessions(session_id) ON DELETE SET NULL,
    attachment_id BIGINT REFERENCES attachments(attachment_id) ON DELETE SET NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_activity_user_created ON activity_events(user_id, created_at DESC);
CREATE INDEX idx_activity_created ON activity_events(created_at DESC);

COMMIT;
