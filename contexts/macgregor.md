ABOUTME: Context-specific instructions for the MacGregor project.
ABOUTME: Soul-protected context — MacGregor's identity is separate and must not be contaminated.

# MacGregor Context

## Soul Protection
MacGregor uses its own soul document (`shared/souls/macgregor.md`). Chestertron does NOT enter this context. sow.py will deploy `@~/.claude/shared/souls/macgregor.md` in the managed block — never the Chestertron soul.

## Personas
None. MacGregor is a standalone context with its own identity system.

## Local Path
`C:\Users\natha\OneDrive\Tech\Python\MacGregor`

## CLAUDE.md State
Already references `@.claude/soul.md` (local soul file). Migration should: replace local soul reference with `@~/.claude/shared/souls/macgregor.md` in managed block. The local soul.md at `.claude/soul.md` remains as a deployment artifact but the canonical source is now `shared/souls/macgregor.md` in OverSteward.

## Project-Specific Config (from CLAUDE.md)

### Python Environment
Conda env: `MacGregor`

### Key Components
- **API:** `src/api.py` — FastAPI backend with auth, device management, notifications
- **Auth:** `src/auth.py` — JWT tokens, password hashing, permission checks
- **Config:** `src/config.py` — Environment variable loading and validation
- **Audit:** `src/audit.py` — Security event logging
- **FCM:** `src/fcm.py` — Firebase Cloud Messaging for push notifications
- **Models:** `src/models.py` — SQLAlchemy ORM (User, Device, AuditLog)
- **DB:** `src/db.py` — Database initialization and session management
- **Streamlit UI:** `src/streamlit_app.py` — Web control panel

### Key Files
- **Soul:** `.claude/soul.md` (MacGregor identity and security doctrine)
- **Security Audit:** `docs/SECURITY_AUDIT.md`
- **Session:** `SESSION_STATE.md`
- **Todo:** `MASTER_TODO.md` + `TODO_BACKLOG.md` + `TODO_COMPLETED.md`

### Environment Variables
Required in `.env`:
- `MACGREGOR_SECRET_KEY` — JWT signing key (32+ chars)
- `MACGREGOR_DATABASE_URL` — SQLAlchemy database URL
- `FIREBASE_CREDENTIALS_PATH` — Firebase service account JSON (optional)
