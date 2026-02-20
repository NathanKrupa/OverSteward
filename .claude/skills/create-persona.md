ABOUTME: Skill for scaffolding a new persona end-to-end.
ABOUTME: Handles creation, cataloguing in OverSteward, and deployment to approved contexts.

# /create-persona

Scaffold a new persona for the House of Krupa persona catalogue and deploy it to approved contexts.

## Steps

1. **Name and concept.** Ask Nathan for:
   - Persona name (slug and display name)
   - Core identity in 2-3 sentences
   - Domain specialty (what does this persona handle that others don't?)
   - Relationship to Chestertron (peer, subordinate, specialist?)

2. **Scaffold the persona file.** Create `shared/personas/{name}.md` using the standard persona template. Show Nathan the draft for review and editing before proceeding.

3. **Commit to OverSteward.** Once approved:
   - Stage `shared/personas/{name}.md`
   - Commit to the OverSteward repo with message: "Add {Name} persona to catalogue"
   - Also sync to `~/.claude/shared/personas/{name}.md`

4. **Update the registry.** Show Nathan the full context grid and ask which contexts should get this persona, and whether each should be `personas_always_on` or `personas_available`. Update `registry.yaml` accordingly.

5. **Deploy.** Run sow.py for each approved context:
   - For `personas_always_on`: add the `@~/.claude/shared/personas/{name}.md` line to the managed block
   - For `personas_available`: deploy `persona-{name}.md` skill file to the context's skills directory

6. **Report.** Summarize what was created and where it was deployed.

## Persona File Template

```markdown
Soul Document: {Name}

1. Identity
[2-3 sentence identity statement]

2. Governing Principles
[Core principles that guide this persona's work]

3. Domain Expertise
[What this persona knows that others don't]

4. Tone
[How this persona communicates]

5. Relationship to Chestertron
[How this persona and Chestertron interact when both are relevant]
```
