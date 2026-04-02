---
name: review
description: Code review for Mulan BI Platform — checks security, architecture, conventions, and quality based on project standards and agent-os best practices.
user_invocable: true
---

# /review — Mulan BI Platform Code Review

Review the current diff (staged + unstaged changes, or a specified PR/commit range). Produce a structured review report covering all sections below.

## Review Process

1. **Gather scope** — run `git diff` and `git diff --cached` (or the user-specified range) to collect all changed files.
2. **Classify changes** — group files into: Frontend, Backend, Config, Tests, Docs.
3. **Run each checklist section** below against the relevant file group.
4. **Output a report** using the Report Format at the bottom.

---

## 1. Security (P0 — must block merge if violated)

- [ ] **Auth enforcement** — every backend route handler calls `get_current_user()` / `get_current_admin()` / `require_roles()` from `backend/app/core/dependencies.py`. No endpoint may skip auth unless explicitly public.
- [ ] **No hardcoded secrets** — no API keys, passwords, encryption keys, or tokens in source. Must use env vars (`SESSION_SECRET`, `DATASOURCE_ENCRYPTION_KEY`, `TABLEAU_ENCRYPTION_KEY`).
- [ ] **Sensitive data encrypted at rest** — DB passwords, PAT tokens, LLM keys must go through `CryptoHelper` (PBKDF2 + Fernet). Never store plaintext.
- [ ] **JWT cookie flags** — `httponly=True`, `samesite="lax"`. `secure` flag controlled by `SECURE_COOKIES` env var.
- [ ] **CORS whitelist** — new origins must be added to `ALLOWED_ORIGINS`, not open `*`.
- [ ] **Input validation** — Pydantic models validate all request bodies. No raw `request.json()` parsing without a model.
- [ ] **SQL injection** — all DB access via SQLAlchemy ORM. No raw SQL string concatenation.
- [ ] **XSS** — no `dangerouslySetInnerHTML` unless sanitized. React JSX escaping must not be bypassed.
- [ ] **Permission checks** — frontend `<ProtectedRoute>` and backend role/permission checks must agree on access control for the same resource.

## 2. Architecture & Patterns

- [ ] **Singleton consistency** — Database and Service classes use the `_instance` / `__new__` singleton pattern. New services must follow this.
- [ ] **API layer separation** — frontend API calls live in `frontend/src/api/*.ts` as typed async functions, not inline in components.
- [ ] **Service layer separation** — backend business logic in `backend/services/`, route handlers in `backend/app/api/`. Handlers should not contain business logic.
- [ ] **State management** — global state uses `AuthContext` only. No new React Context or global store without justification. Page-level state uses `useState`.
- [ ] **Routing** — new routes added to `frontend/src/router/config.tsx` as flat `RouteObject[]`. Route `element` must be JSX (enforced by `local-route/route-element-jsx` ESLint rule). Protected routes use `<ProtectedRoute>`.
- [ ] **Layout wrapping** — business pages use `<MainLayout>`, admin pages use `<AdminSidebarLayout>`.
- [ ] **Database per domain** — each domain has its own SQLite file in `data/`. Don't mix tables across databases.

## 3. TypeScript & Frontend Quality

- [ ] **Interfaces defined** — request/response types declared as TypeScript interfaces in the corresponding `src/api/*.ts` file.
- [ ] **fetch convention** — use native `fetch` with `credentials: 'include'`. Import `API_BASE` from `../config`. No Axios.
- [ ] **Error handling pattern** — API functions: check `res.ok`, parse `res.json().detail`, throw `Error` with Chinese user-facing message. Components: `try/catch` with `useState` for error display.
- [ ] **No `any` without reason** — `@typescript-eslint/no-explicit-any` is warn-level. New `any` usage should have a comment explaining why.
- [ ] **Auto-import awareness** — React hooks, Router hooks, and `useTranslation` are auto-imported via `unplugin-auto-import`. Don't add redundant manual imports for these.
- [ ] **Tailwind only** — use Tailwind utility classes. No CSS modules, styled-components, or inline `style={}` objects unless unavoidable.
- [ ] **Component convention** — `export default function ComponentName()`. Functional components only, no class components.

## 4. Python & Backend Quality

- [ ] **Pydantic v2 models** — all request/response schemas use `BaseModel`. Field validation (e.g., regex, min length) at the model level.
- [ ] **HTTPException messages** — user-facing error messages in Chinese. Use standard status codes (400, 401, 403, 404, 409, 500).
- [ ] **Logging** — use `logger` (Python logging module). Broad `except Exception` blocks must log with `exc_info=True`.
- [ ] **No new sys.path hacks** — existing `sys.path.insert` patterns are legacy. New code should use proper relative imports or package structure.
- [ ] **DB session safety** — no long-lived uncommitted transactions. Commit or rollback promptly.

## 5. Testing

- [ ] **Smoke test coverage** — new pages/features should have a corresponding Playwright smoke test in `frontend/tests/smoke/`.
- [ ] **No hardcoded test credentials** beyond the default `admin/admin123` used in existing tests.
- [ ] **CI must pass** — `type-check`, `lint`, `build` (frontend) and `py_compile` + import verification (backend) must all succeed.

## 6. Agent-OS Best Practices (from buildermethods/agent-os)

> Reference: https://github.com/buildermethods/agent-os

### 6.1 Standards-Driven Development
- [ ] **Lead with the rule** — code comments and docs state *what to do* first, *why* second. No preamble.
- [ ] **Show, don't tell** — prefer code examples over prose descriptions in docs and comments.
- [ ] **Skip the obvious** — don't document what the code already makes clear. No trivial comments like `// increment counter`.
- [ ] **Every word costs tokens** — keep CLAUDE.md, comments, and docs concise. Standards are injected into AI context windows.

### 6.2 Spec-Driven Changes
- [ ] **Non-trivial features need a spec** — for features touching 3+ files or introducing new patterns, create a spec folder: `docs/specs/YYYY-MM-DD-HHMM-{feature-slug}/` containing `plan.md` and `shape.md` before implementation.
- [ ] **Task 1 is save the spec** — document the plan before writing code, not after.

### 6.3 Script & Automation Hygiene
- [ ] **Fail fast** — shell scripts use `set -e`. Validate prerequisites early before doing work.
- [ ] **Backup before overwrite** — destructive file operations create timestamped backups first.
- [ ] **Color-coded output** — CLI scripts use structured output helpers (success/error/warning/status), not raw `echo`.

### 6.4 PR & Commit Discipline
- [ ] **PR summary** — every PR has: what changed, why, test steps, backwards compatibility notes.
- [ ] **One concern per PR** — don't bundle unrelated changes. Refactors, features, and bug fixes are separate PRs.
- [ ] **Backwards compatibility** — if changing an API response shape or DB schema, document the migration path.

### 6.5 Configuration & Discoverability
- [ ] **Index-driven organization** — new modules/features should be reflected in `CLAUDE.md` project structure section.
- [ ] **File naming** — lowercase, hyphen-separated for docs and configs. PascalCase for React components, snake_case for Python.

---

## Report Format

Output the review as:

```
## Review: <short summary>

### Scope
- Files changed: <count>
- Categories: Frontend / Backend / Config / Tests / Docs

### P0 Blockers (must fix before merge)
- [ ] <file:line> — <issue description>

### P1 Warnings (should fix)
- [ ] <file:line> — <issue description>

### P2 Suggestions (nice to have)
- [ ] <file:line> — <suggestion>

### Positive Highlights
- <good patterns observed>

### Verdict: APPROVE / REQUEST CHANGES / NEEDS DISCUSSION
```

Rules:
- P0 = security vulnerabilities, auth bypass, data leaks, broken builds → always REQUEST CHANGES.
- P1 = convention violations, missing types, missing tests → REQUEST CHANGES if > 3 items.
- P2 = style preferences, minor improvements → never block on these alone.
- If no P0 or P1 issues: APPROVE with P2 suggestions as comments.
