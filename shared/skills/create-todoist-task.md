ABOUTME: Shared skill to create Todoist tasks via API.
ABOUTME: Uses .env credentials. Deployable to any context via OverSteward.

Create a task in Todoist using the REST API.

## Required .env Variables

```
TODOIST_TOKEN=your_api_token_here
```

## Steps

1. Parse the user's request to extract:
   - Task content (what to do)
   - Project ID (from mappings below, or ask user)
   - Due date (natural language: 'tomorrow', 'Friday', 'next week', or specific date)
   - Priority (1-4: 4=urgent/P1, 3=high/P2, 2=normal/P3, 1=low/P4)

2. Load the API token from `.env` (`TODOIST_TOKEN`).

3. Execute:
   ```bash
   curl "https://api.todoist.com/api/v1/tasks" \
     -X POST \
     -H "Authorization: Bearer $TODOIST_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"content": "TASK", "project_id": "PROJECT_ID", "priority": PRIORITY, "due_string": "DUE"}'
   ```

   To load the token from .env in bash:
   ```bash
   export $(grep TODOIST_TOKEN .env | xargs) && curl ...
   ```

4. Parse the JSON response and confirm to user:
   - Task content
   - Project name
   - Due date
   - Priority level

## Project Mappings

Project IDs are environment-specific. Each context should define its project IDs in `.env`:

```
# Example .env project IDs (get from Todoist Settings > Projects)
TODOIST_PROJECT_INBOX=1234567890
TODOIST_PROJECT_GOLDEN_HARVEST=1234567891
TODOIST_PROJECT_GRANTS=1234567892
```

### Keyword Routing

When the user doesn't specify a project, route by keyword:
- General GH work → GOLDEN_HARVEST
- Grant work → grants
- Harvest Academy/cohort → fundraising_cohort
- Reports/data → reporting
- Major donors → major_gifts
- Meeting prep → agendas
- Direct mail campaigns → direct_mail
- DonorPerfect tasks → donor_perfect
- Online giving → online_giving
- Program development → programming
- Home tasks → home
- Personal work → my_work
- Alleluia Community → alleluia
- Robotics → robotics

If no match, ask the user which project.

## Defaults

- Due: 'today' if not specified
- Priority: 2 (normal) if not specified

## User Input

$ARGUMENTS
