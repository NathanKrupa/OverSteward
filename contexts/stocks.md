ABOUTME: Context-specific instructions for the Stocks project.
ABOUTME: Data and analysis context — Analyst persona when built.

# Stocks Context

## Purpose
Portfolio tracking and analysis tool. Reads trades from Excel, fetches market data, builds formula-based Excel workbooks with portfolio analytics.

## Personas Available
- Chestertron (soul)
- Analyst (future — deploy when persona is built)

## Local Path
`C:\Users\natha\OneDrive\Tech\Python\Stocks`

## CLAUDE.md State
Contains full inline copy of working guidelines (duplicates global `~/.claude/CLAUDE.md`). Has project-specific config at the bottom. Migration should: add managed block with shared soul reference, strip duplicated guidelines, keep project-specific section in local block.

## Project-Specific Config (from CLAUDE.md)

### Python Environment
Conda env: `stocks`

### Key Components
- **config.py** — Portfolio parameters, styling, file paths
- **create_template.py** — Generates sample `My Portfolio.xlsx` with fake trade data
- **portfolio_builder.py** — Reads trades, fetches market data, builds formula-based Excel workbook
- **update_portfolio.py** — Daily update script (full sync, quick prices, manual trade entry)

### Key Files
- **Input:** `My Portfolio.xlsx` (Trade_Log sheet with user's trades)
- **Output:** `My Portfolio_BUILT.xlsx` (generated workbook — do NOT edit directly)
- **Ledger:** `Chestertron_Stewards_Ledger.md` (project status and session log)
