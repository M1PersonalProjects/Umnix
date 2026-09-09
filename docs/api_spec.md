# API specification

All application APIs use the `/api/v1` prefix.

## Authentication

- `POST /api/v1/auth/telegram-webapp` validates signed Telegram WebApp init data.
- `POST /api/v1/auth/browser-login` signs in an existing user by Telegram ID.
- `POST /api/v1/auth/telegram-bot/start` creates a one-time Telegram Bot login request.
- `POST /api/v1/auth/telegram-bot/status` polls the one-time request and returns a session after approval.
- `POST /api/v1/auth/logout` records logout before the browser clears the local session.
- `GET /api/v1/auth/session` validates the locally remembered session token.

## AI tutor

- `GET /api/v1/tutor/profile`
- `GET /api/v1/tutor/sessions`
- `POST /api/v1/tutor/sessions`
- `PATCH /api/v1/tutor/sessions/{session_id}`
- `DELETE /api/v1/tutor/sessions/{session_id}`
- `GET /api/v1/tutor/sessions/{session_id}/messages`
- `PUT /api/v1/tutor/sessions/{session_id}/context`
- `DELETE /api/v1/tutor/sessions/{session_id}/context`
- `POST /api/v1/tutor/transcribe`
- `POST /api/v1/tutor/messages`

Tutor requests are scoped by both user ID and chat `session_id`.

## Attachments

- `POST /api/v1/attachments`
- `GET /api/v1/attachments`
- `GET /api/v1/attachments/library`
- `DELETE /api/v1/attachments/{attachment_id}/memory`
- `GET /api/v1/attachments/{attachment_id}/preview`
- `GET /api/v1/attachments/{attachment_id}/download`
- `DELETE /api/v1/attachments/{attachment_id}`

Every operation validates ownership or assignment access.

## Books

- `GET /api/v1/books`
- `GET /api/v1/books/{book_id}/pages`
- `GET /api/v1/books/{book_id}/download`
- `GET /api/v1/books/{book_id}/pages/{page_number}/image`

## Interactive applications

- `GET /api/v1/interactive/students`
- `GET /api/v1/interactive/{app_id}`
- `GET /api/v1/interactive/{app_id}/answers`
- `GET /api/v1/interactive/{app_id}/versions`
- `GET /api/v1/interactive/{app_id}/download`
- `POST /api/v1/interactive/{app_id}/assign`
- `POST /api/v1/interactive/{app_id}/result`

## Student

- `GET /api/v1/student/dashboard`
- `POST /api/v1/student/tasks/{task_id}/submit`

## Teacher / parent

Teacher routes are grouped under `/api/v1/parent/...` for database compatibility
with the technical `parent` role. They cover dashboards, task drafts, sending,
reviewing, cancelling, deleting, and task history.

## Admin

Admin APIs use `/api/v1/admin` and cover overview, books, pages, users, family
links, and activity search.

Activity search accepts `tg_id` and text query parameters so the administrator
can find one user or matching words across aggregated activity.

## Textbook digitization

Prefix: `/api/v1/admin/digitization`.

- `POST /upload` accepts PDFs or one ZIP.
- `GET /jobs` returns recent digitization jobs and progress.
- `PATCH /jobs/{job_id}/metadata` changes previewed book metadata.
- `GET /empty-books` lists compatible existing books when needed.
- `POST /jobs/{job_id}/assign/{book_id}` links a job to an existing book.
- `POST /batches/{batch_id}/confirm` creates/updates books and queues processing.
- `POST /jobs/{job_id}/retry` retries a failed job.

The worker claims one pending job at a time and processes its pages sequentially.
