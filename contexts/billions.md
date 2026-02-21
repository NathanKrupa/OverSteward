ABOUTME: Context-specific instructions for the billions project.
ABOUTME: Design is core — Angelico always-on. Uses a David-specific Chestertron soul variant.

# billions Context

## Purpose
React + TypeScript game built with Vite, deployed to Vercel with Google Analytics. Design is core to the product — Angelico is always-on.

## Personas Active
- Chestertron (soul) — **David variant**: addresses partner as "Sir" / "David Jude Krupa". This is intentional and must not be overridden by the standard Nathan-facing soul.
- Angelico (always-on — design is core to this project)

## Local Path
`C:\Users\natha\OneDrive\Tech\Python\billions`

## Managed Block Notes
The managed block for billions should inject `@~/.claude/shared/personas/angelico.md` but should NOT inject the standard Chestertron soul. The David-specific soul variant lives inline in the local section of the CLAUDE.md.

## Project-Specific Config (from CLAUDE.md)

### Game Stack
- **Framework**: React + TypeScript, bundled with Vite
- **Source**: `game/src/`
- **Deployment**: Vercel with Google Analytics
- **Feature Queue**: `game/FEATURES.md`

### Lean Development
Follows lean startup principles. Reference text at `.claude/leanstartup.md`. Core loop: Build → Measure → Learn.

### CI/CD
- GitHub repo: `github.com/NathanKrupa/billions`
- Vercel handles deployment from the main branch
