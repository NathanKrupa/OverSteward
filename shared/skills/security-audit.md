ABOUTME: Security audit skill covering OWASP Top 10, secrets, dependencies, and infrastructure.
ABOUTME: Adapted from garrytan/gstack's /cso pattern for House of Krupa contexts.

# Security Audit

A structured security review for any codebase in the House of Krupa ecosystem. This skill is read-only — it identifies and reports findings but does NOT modify code.

## When to Use

Invoke `/security-audit` when:
- Before deploying a web application (aigranthelper, TheAlmoner, billions)
- After adding authentication, payment, or data-handling features
- Periodically as a health check on any active project
- Before open-sourcing any repository

## Audit Phases

### Phase 1: Stack Detection

Identify the project's technology stack from package files, config, and imports:
- Language and framework versions
- Authentication method
- Database and ORM
- Deployment target
- Third-party integrations (payment, email, analytics)

### Phase 2: Secrets Archaeology

Search for exposed credentials, API keys, and sensitive data:
- Grep for patterns: API keys, tokens, passwords, connection strings
- Check `.env` files — are they gitignored?
- Check `.env.example` — does it contain real values?
- Check git history: `git log --all --diff-filter=A -- "*.env" ".env*" "credentials*" "secrets*"`
- Check for hardcoded secrets in source files
- Check CI/CD config for exposed variables

### Phase 3: Dependency Audit

Review third-party dependencies for known vulnerabilities:
- Run `pip audit` (Python), `npm audit` (Node), or equivalent
- Check for outdated packages with known CVEs
- Flag dependencies that are unmaintained (no commits in 12+ months)
- Check for typosquatting risks on unusual package names

### Phase 4: OWASP Top 10 Check

For each applicable category, assess the codebase:

| # | Category | What to Check |
|---|----------|--------------|
| A01 | Broken Access Control | Auth middleware, permission checks, IDOR, path traversal |
| A02 | Cryptographic Failures | Password hashing, TLS config, sensitive data in logs |
| A03 | Injection | SQL injection, command injection, template injection, XSS |
| A04 | Insecure Design | Missing rate limiting, no CSRF protection, weak session management |
| A05 | Security Misconfiguration | DEBUG=True in prod, default credentials, verbose errors, CORS |
| A06 | Vulnerable Components | See Phase 3 |
| A07 | Auth Failures | Brute force protection, password policy, session fixation |
| A08 | Data Integrity | Deserialization, unsigned updates, CI/CD tampering |
| A09 | Logging Failures | Sensitive data in logs, missing audit trail |
| A10 | SSRF | User-supplied URLs, webhook handlers, file imports |

### Phase 5: Infrastructure Review

- Are environment variables properly separated (dev/staging/prod)?
- Is the database connection encrypted (SSL)?
- Are backups configured?
- Is the deployment pipeline using pinned dependencies?
- Are admin interfaces protected (not publicly accessible)?

### Phase 6: Django-Specific Checks (when applicable)

- `SECRET_KEY` not in source control
- `DEBUG = False` in production settings
- `ALLOWED_HOSTS` configured
- `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` enabled
- `X_FRAME_OPTIONS` set
- `django.middleware.security.SecurityMiddleware` in MIDDLEWARE
- Admin URL is not `/admin/`
- `SECURE_HSTS_SECONDS` configured

## False Positive Exclusions

Do NOT flag these as findings:
- `.env.example` with placeholder values (that's correct behavior)
- Test fixtures with fake credentials
- Development-only settings in `settings/local.py` or `settings/test.py`
- `DEBUG = True` in explicitly dev-only config files
- Localhost URLs in development config
- Self-signed certs in test environments
- Known test API keys (Stripe test keys starting with `sk_test_`)

## Confidence Gate

Only report findings with confidence 7/10 or higher. For findings below that threshold, note them in an "investigate further" section rather than presenting them as confirmed issues.

## Report Format

```
## Security Audit Report
**Project:** [name]
**Date:** [date]
**Stack:** [detected stack]
**Scope:** [what was audited]

### Critical Findings (fix before deploy)
[numbered list with file:line references]

### High Findings (fix soon)
[numbered list]

### Medium Findings (address in next sprint)
[numbered list]

### Investigate Further (below confidence threshold)
[numbered list]

### Passed Checks
[list of categories that passed cleanly]
```

## Important

This skill produces a REPORT. It does NOT modify code. After the report, Nathan decides what to fix and in what order.
