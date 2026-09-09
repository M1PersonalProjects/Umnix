# Database schema

`database.sql` is the clean PostgreSQL schema for the release.

## Identity

`users` stores Telegram ID, username, technical role, optional mentor kind, and
student-to-mentor relationship. `web_auth_requests` stores short-lived hashed
browser/bot secrets for one-time Telegram Bot login confirmation. Raw secrets
are never written to the database.

## Textbooks

`book` stores class, subject/program, author, title, and the saved source PDF.
`page` stores one digitized page with title, number, paragraph/description, HTML,
image URL, plain text, and Markdown.

## Chats and files

`chat_sessions` owns isolated WebApp or Telegram sessions.
`chat_messages` belongs to a user and a session.
`attachments` stores file metadata, storage location, hash, parsed text, and
preview state.
`chat_message_attachments` links files to a concrete message and session.

AI memory is not global. Query code selects only the target session, the latest
15 messages in that session, and all attachment links in that session.

## Tasks

`tasks_history`, `task_submissions`, `task_attachments`, and
`task_submission_attachments` store teacher assignments, learner attempts, and
associated files. `task_drafts` keeps the review-before-send workflow.

## Interactive applications

`interactive_apps` stores app identity and current version.
`interactive_app_versions` stores versioned HTML.
`interactive_assignments` links apps to students.
`interactive_results` stores progress and grading results.

## Digitization jobs

`textbook_digitization_jobs` stores uploaded filename, queue path, checksum,
preview metadata, selected book, status/stage, page progress, retries, and error
information. The queue supports recovery of a job that was processing when the
application stopped.

## Activity

`activity_events` is the explicit audit log. It stores user ID, source, action,
detail, optional session/file references, JSON metadata, and timestamp. The
Admin Activity endpoint also searches existing chat/session/file/task history so
previous records remain visible even when they predate the audit table.

## Installation

Apply the clean schema only to an empty database:

```bash
psql "$DATABASE_URL" -f database.sql
```

For an existing database, take a backup and use the idempotent runtime migration
logic in `backend/web/schema_migrations.py` instead of dropping production data.
