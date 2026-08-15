ABOUTME: Voice and house style for client-facing product documentation across the estate.
ABOUTME: Derives from the Almoner "Fundraiser's Playbook" profile, adapted for help docs.

# Documentation voice

The reader is a staff member at a small nonprofit. They are competent at their job
and new to this software. They came here mid-task, slightly frustrated, looking for
one specific answer. They are not reading for pleasure and they will not read twice.

## Where this comes from

The estate voice is defined in `ai-assistants/config/style_profiles/playbook_style.yaml`
("Fundraiser's Playbook Style") and `nathan_krupa_style.md`. **That profile is the
authority on tone; this file is the authority on structure**, because the profile
describes *educational fundraising articles* and help documentation is a different
form with different obligations.

Three rules from the source profile are deliberately overridden here — see
"Departures" at the end. Do not silently re-import them.

## Tone — carried over unchanged

- **Expert-to-practitioner.** An experienced colleague sharing hard-won wisdom over
  coffee, not an academic at a podium. Respect the reader's intelligence; assume
  fundraising literacy, assume nothing about this software.
- **Direct address.** "You" throughout. Active voice. Action verbs.
- **Practical over theoretical.** Every paragraph should move the reader toward doing
  the thing.
- **Encouraging without hype.** Acknowledge that a task is fiddly when it is fiddly.
  Never oversell. A balanced, realistic perspective is part of the voice.
- **Define terms on first use**, with a parenthetical where it helps — the reader knows
  fundraising vocabulary, not ours.
- **Faith register: neutral here.** The source profile integrates faith selectively in
  church-context pieces and stays professionally neutral elsewhere. Product
  documentation is always the "elsewhere" case.

## Structure — the rules specific to help docs

**Length.** Explainers ~300 words. Procedures ~1,300. Nothing over 1,400. If a topic
needs more, it is two topics. (Measured across 13 comparable help centres; nobody
ships 3,000-word help articles — that length belongs on a blog.)

**Every `##` heading is a question the user would actually type.**

> ✅ `## How do I add a deadline for a funder?`
> ❌ `## Deadlines`

This is the single highest-leverage rule and the one that cannot be retrofitted
cheaply. It pays three ways at once: each section becomes a self-contained answer to a
real query; the headings are unambiguous chunk boundaries for retrieval; and it is the
right on-page SEO structure. The source profile's "What are you looking for?" opener is
the same instinct — this is that instinct applied to every section.

**Screenshots carry the load. No video, no GIF.** A full-width PNG after each step of a
procedure. Video rots the instant the UI changes and nobody in the sector ships it.

**Numbered steps for anything sequential.** Bullets for non-sequential sets. Introduce a
list with a sentence ending in a colon.

**Paragraphs of 3–6 sentences.** A single-sentence paragraph is a legitimate emphasis
device; a wall of text is not.

**End deliberately.** Close with the natural next action, or a short "if this didn't
work" pointer. Never trail off.

## The rule that outranks the others

**Never describe a button, menu, field, or setting you have not verified exists.**

A confidently invented UI path is worse than silence. The reader hunts for a control
that isn't there, fails, and concludes the product is broken rather than that the
documentation is wrong. Silence costs a support email; invention costs trust.

Verify against the running application or its source — templates, URL patterns, view
code. If you cannot verify a claim, cut it or flag it. "I'm not certain this screen
still looks like this" belongs in your report, never in the article.

The same applies to numbers. Hardcoded counts ("136,000+ foundations") rot silently and
are read as current. Either verify against the live system or write around it.

## Departures from the source profile

Three rules in `playbook_style.yaml` do not transfer. They are listed here so a future
reader can see they were considered rather than missed.

| Source rule | Why it's overridden |
|---|---|
| *"Articles often end mid-thought"* / *"avoid formal conclusions"* | An artifact of the source corpus being **scraped excerpts**, not a deliberate voice trait. A help article that trails off reads as unfinished — which is exactly the failure the live `/help/` articles already exhibit. |
| *"H3 subheadings, often 2–4 words, sometimes metaphorical"* | Help docs use `##`, phrased as full user questions. Short metaphorical headings are unsearchable and unchunkable. |
| *"Brief personal anecdotes to establish credibility"* | Right for a playbook, wrong for a help topic. The reader is mid-task and does not want a story. Keep the credibility, drop the anecdote. |
