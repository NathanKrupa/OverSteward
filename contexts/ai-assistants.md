ABOUTME: Context-specific instructions for the AI Assistants project.
ABOUTME: Angelico available as skill for design surfaces; Chestertron handles implementation.

# AI Assistants Context

## Purpose
Blog content generation platform with RAG pipeline, WordPress integration, ChromaDB vector store, and Obsidian bridge. Angelico available as a skill for design surfaces and visual output.

## Personas Available
- Chestertron (soul)
- Angelico (skill — invoke when working on design surfaces, UI, or visual output)

## Local Path
`C:\Users\natha\OneDrive\Tech\Python\ai-assistants`

## CLAUDE.md State
Already structured well — delegates core rules to `~/.claude/CLAUDE.md`. No inline soul duplication. Only needs managed block wrapper added.

## Project-Specific Config (from CLAUDE.md)

### Python Environment
Conda env: `ai-assistants`

### Test Organization
- **Automated** (`tests/`): pytest unit/integration
- **Verification** (`scripts/<domain>/verify_*.py`): manual live integration tests

### Key Components
- **Vector DB**: ChromaDB `data/vectordb/`, collection `blog_posts`
- **RSS Fetcher**: `connectors/rss_fetcher.py`
- **Sitemap**: `connectors/sitemap_fetcher.py`
- **Scraper**: `connectors/content_scraper.py`
- **WordPress**: `connectors/wordpress_api.py`
- **RAG**: `agents/rag_content_generator.py`

### Anthropic API Credit Policy
CRITICAL: Preserve API credits for end-user content generation only. Only `agents/rag_content_generator.py` and `generate_article()` method may use `ANTHROPIC_API_KEY`. All other AI work uses Claude Code (free via Claude Pro).

### Obsidian-VSCode Bridge
Bidirectional sync between Obsidian creative work and VSCode technical work. Draft output at `data/obsidian/Blog Drafts/` (junction to Obsidian vault). Module: `src/obsidian.py`.

### Visual Verification
Playwright MCP server for browser automation — auto-verify after CSS/HTML/JS deploys.

### CI/CD
- GitHub repo: `github.com/NathanKrupa/ai-assistants`
- Workflow: `.github/workflows/ci-cd.yml`
- Status: Not pushed yet (needs secrets configured)
