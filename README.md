# Umnix / EduAI

Umnix is an educational platform with a FastAPI backend, Telegram bot, WebApp,
AI tutor, file workflows, teacher assignments, interactive applications, and
textbook digitization.

## Release architecture

```text
backend/
  auth/                  Telegram Bot/WebApp login and session/role security
  api/                   FastAPI routers
  bot/                   Aiogram bot, FSM states, and handlers
  digitization_books/    PDF/ZIP textbook digitization pipeline
  web/                   Shared application and AI business logic
  files/
    attachments/         Runtime user attachments
    books/               Source textbook PDFs and rendered page images
frontend/
  static/css/            Shared UI styles
  static/js/             Shared and role-specific browser logic
  templates/             Jinja pages
  digitization_books/    Admin digitization UI module
docs/                    API, database, and user documentation
tests/
  unit/                   Pure service tests
  contracts/              Architecture and feature contracts
  smoke/                  Python and JavaScript syntax checks
main.py                   FastAPI + Telegram polling entry point
config.py                 Environment configuration
database.py               asyncpg pool
database.sql              Clean PostgreSQL schema
logger_config.py          Compact application logging
```

The old top-level `api/`, `bot/`, `services/`, `static/`, and `templates/`
application trees are intentionally removed.

## Core behavior

### AI tutor

- Every WebApp chat has its own `session_id` and isolated memory.
- A request uses only the latest 15 messages from that chat.
- All previously attached files linked to that same chat are available to AI.
- Files from other chats are never added to that session context.
- Book Mode queries digitized `book` and `page` records before outside context.
- Normal AI requests are capped at 600 seconds.
- Textbook digitization is not subject to the 600-second application timeout.
- Telegram uses one persistent Telegram chat session per user; WebApp chats remain
  independent from each other.

### Attachments

Uploaded files are stored under `backend/files/attachments/` and registered in
PostgreSQL. Ownership is checked before preview, download, deletion, and AI use.
Chat attachment history is linked through `chat_message_attachments`, including
its `session_id`, so memory remains session-local.

### Interactive applications

Interactive applications are versioned. Authorized users can open/preview and
download an HTML version. Teachers/admins can assign an application to linked
students. Student submissions are graded on the backend rather than exposing a
private answer key in the learner document.

### Textbook digitization

Admin digitization follows this flow:

1. Upload one or more PDFs, or one ZIP containing up to 20 PDFs.
2. Read book metadata from the filename format:
   `class|subject|author|title.pdf`.
3. Review and edit class, subject, author, and title in the preview table.
4. Confirm the reviewed batch.
5. Process books sequentially, page by page.
6. Save the original PDF and per-page image, text, HTML, and Markdown.

Digitized pages populate `page_title`, `page_number`, `page_paragraph`,
`page_html`, `page_image`, `page_text`, and `page_markdown`. The digitizer asks
for a meaningful Russian page title and only falls back to a generic page number
when a meaningful topic cannot be established.

### Authentication and diagnostics

The browser supports two explicit login paths: Telegram ID for an existing user,
or Telegram Bot confirmation through `@EduAI_platform_bot`. Bot login uses a
10-minute one-time handshake stored in `web_auth_requests`; the bot confirms the
real `message.from_user.id`, after which the browser receives its session token.
The session is kept in local storage and is valid for 30 days. Logout clears it,
so another Telegram ID can be used immediately.

Every API action and Telegram message/callback is written to Terminal and
`app.log` in the diagnostic form
`DD.MM.YY_HH.MM.SS_tg_id_[HTTP status]_English explanation_file:line`.
Static assets are excluded. System lifecycle messages may use the regular
system-log format. Full searchable activity is also stored in PostgreSQL and the
Admin Activity screen can be filtered by `tg_id` and text.

## Responsive AI tutor

The smartphone layout keeps the existing mobile rules and interaction model.
For desktop widths the tutor workspace becomes a full-screen layout without a
centered chat-width restriction or decorative side columns. The same controls
remain in the same functional order.

## Requirements

- Python 3.11+
- PostgreSQL
- Telegram bot token
- OpenAI API key
- Node.js is optional and only used by the JavaScript syntax smoke test
- Public HTTPS URL for Telegram WebApp production use

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows, activate the environment with `.venv\Scripts\activate`.

Fill at least these `.env` variables:

```env
BOT_TOKEN=...
OPENAI_API_KEY=...
DATABASE_URL=postgresql://user:password@127.0.0.1:5432/umnix_db
ADMIN_IDS=123456789
WEBAPP_BASE_URL=http://127.0.0.1:8000
BOT_USERNAME=EduAI_platform_bot
```

Never commit the real `.env` file.

## Database

For a clean installation, create an empty PostgreSQL database and apply:

```bash
psql "$DATABASE_URL" -f database.sql
```

`backend/web/schema_migrations.py` contains idempotent compatibility updates for
an already existing database. Back up a production database before applying
schema changes.

## Run

Run API and Telegram polling together:

```bash
python main.py
```

For API development only:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Main pages:

- `/auth`
- `/student`
- `/parent`
- `/admin`
- `/files`
- `/interactive/{app_id}`

## Verification

The release test suite is intentionally split by purpose:

```bash
python -m pytest -q
python -m compileall -q backend tests main.py config.py database.py logger_config.py
```

When Node.js is installed, the smoke suite also runs `node --check` against all
frontend JavaScript files.

The line-length contract checks Python, JavaScript, CSS, HTML, and the root SQL
schema and rejects code lines over 120 characters.

External integration tests still require real infrastructure: PostgreSQL,
Telegram, OpenAI credentials, and network access. The repository does not embed
secrets, a database dump, or a virtual environment.

## Documentation

- `docs/api_spec.md`
- `docs/database_schema.md`
- `docs/user_guide.md`
