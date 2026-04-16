# House of Krupa — Frontend Design Brief

> A reusable design constraint document for every frontend project in the House of Krupa ecosystem. Use this as a preamble prompt, a CLAUDE.md reference, or a handoff spec for any designer or AI coding assistant.

---

## 1. Purpose of This Document

AI models (including Claude and GPT) default to high-frequency training patterns when prompts are underspecified — generic card layouts, Inter/Roboto typography, purple-on-white palettes, dashboard-style grids. This document provides the **constraint architecture** that prevents generic output and steers every frontend toward a deliberate, branded, production-grade result.

**How to use it:**
- **In Claude chat/artifacts:** Paste the relevant Brand Profile section + the Universal Design Constraints section as context before any frontend request.
- **In Claude Code / CLAUDE.md:** Include the full document or relevant sections in your project's `CLAUDE.md` file.
- **In any AI coding tool:** Use as a system prompt preamble or skill file.
- **For human designers:** Use as a creative brief and brand guidelines reference.

---

## 2. Brand Profiles

Each project in the House of Krupa ecosystem has its own visual identity. Select the relevant profile when starting a design task.

---

### 2a. TheAlmoner.com — Fundraising Consulting Practice

**Brand positioning:** Expert fundraising counsel for small nonprofits ($500K–$5M), grounded in Catholic Social Teaching. The tone is authoritative but approachable — a seasoned mentor, not a corporate vendor.

**Audience:** Development directors, executive directors, and board members at small nonprofits. Typical user: mid-career professional, time-starved, often the only fundraiser on staff. They need to feel this is a trusted expert who understands their world, not another SaaS pitch.

**Visual direction:** Editorial / Warm Authority

**Canonical source:** `ai-assistants/documentation/brand_guidelines/STYLE_GUIDE.md` and `color_palette.yaml` (Palette 1 "Classic Burgundy & Gold", confirmed Feb 2026).

| Element | Specification |
|---|---|
| **Primary palette** | Deep Burgundy (#8B1A1A), Rich Gold (#D4AF37), Deep Navy (#1E3A5F), Warm Cream (#FAF0E6), Charcoal text (#2C2C2C) |
| **Supporting colors** | Warm White (#FEFCF8) page background, Soft Gray (#E8E8E8) dividers, Medium Gray (#98A0A9) metadata/captions |
| **Semantic colors** | Gains (#2E7D32), Losses (#C62828), Alert (#E53D3C) |
| **Typography — Display** | Playfair Display Bold for H1/hero headlines, Playfair Display SemiBold for H2 section headers. |
| **Typography — Subheading** | Lora Bold for H3/sub-sections within chapters. |
| **Typography — Body** | Georgia Regular for all web body copy. Merriweather Regular for print/PDF long-form reading. |
| **Typography — UI** | Open Sans Regular/SemiBold for navigation, buttons, form labels, metadata. Open Sans Light for captions, footnotes, dates. |
| **Typography — Pull Quotes** | Cormorant Garamond Italic for featured quotes and testimonials. |
| **Typography — Brand Accent** | Cornet for logo wordmark and author signatures only. |
| **Imagery style** | Warm, documentary-style photography of real people — food bank volunteers, community meals, nonprofit offices. No stock-photo polish. Warm natural light, golden-hour quality preferred. When photography isn't available, use textured backgrounds (paper grain, linen, subtle noise) rather than flat color. |
| **Layout tone** | Magazine editorial. Generous whitespace (60/30/10 rule: 60% neutral, 30% primary, 10% accent). Full-bleed hero images. One idea per viewport. 720px max content width, 1200px max page width. 8px base grid. |
| **Motion** | Restrained. Subtle fade-ins on scroll (150–300ms), gentle parallax on hero images. No bouncing, no sliding cards. Respect `prefers-reduced-motion`. Motion should feel like turning a page, not playing a game. |
| **Voice test** | If the first viewport could belong to HubSpot, Salesforce, or any SaaS platform, start over. This should feel like opening a well-made book, not logging into software. |

**CSS Variables Template:**
```css
:root {
  /* Brand colors (Palette 1: Classic Burgundy & Gold) */
  --color-primary: #8B1A1A;
  --color-primary-dark: #6B1414;
  --color-gold: #D4AF37;
  --color-navy: #1E3A5F;
  --color-cream: #FAF0E6;
  --color-bg: #FEFCF8;
  --color-text: #2C2C2C;
  --color-text-muted: #98A0A9;
  --color-border: #E8E8E8;
  /* Semantic */
  --color-success: #2E7D32;
  --color-error: #C62828;
  --color-alert: #E53D3C;
  /* Typography */
  --font-display: 'Playfair Display', serif;
  --font-subheading: 'Lora', serif;
  --font-body: 'Georgia', serif;
  --font-ui: 'Open Sans', sans-serif;
  --font-quote: 'Cormorant Garamond', serif;
  /* Layout (8px base grid) */
  --radius-sm: 4px;
  --radius-md: 8px;
  --spacing-section: 80px;
  --spacing-section-mobile: 48px;
  --spacing-content: 2rem;
  --max-width-content: 720px;
  --max-width-page: 1200px;
  --transition-default: 300ms ease;
}
```

---

### 2b. AI Grant Helper — Grant Management SaaS

**Brand positioning:** A full-lifecycle grant management tool for grant writers at small-to-mid nonprofits. "We don't replace grant writers. We make them unstoppable." Approachable AI — not intimidating, not cutesy. The feeling should be "finally, someone who gets this."

**Audience:** Development directors and grant writers at small-to-mid nonprofits — the person searching for funders at 11 PM on their phone. Same universe as TheAlmoner.com but in "tool mode" — accomplishing tasks (find grants, track relationships, manage deadlines), not browsing content.

**Visual direction:** Almoner Brand, Application Treatment

The AI Grant Helper shares TheAlmoner's brand palette and type system, applied with denser information hierarchy appropriate for an application interface. This is not a separate brand — it is a tool built by The Almoner.

| Element | Specification |
|---|---|
| **Primary palette** | Same as TheAlmoner: Deep Burgundy (#8B1A1A), Rich Gold (#D4AF37), Deep Navy (#1E3A5F), Warm Cream (#FAF0E6), Charcoal (#2C2C2C) |
| **Supporting colors** | Same as TheAlmoner: Warm White (#FEFCF8), Soft Gray (#E8E8E8), Medium Gray (#98A0A9) |
| **Semantic colors** | Success (#2E7D32) for funded/awarded, Error (#C62828) for declined/overdue, Alert (#E53D3C) for deadlines approaching |
| **Typography — Display** | Playfair Display Bold/SemiBold for page titles and section headers |
| **Typography — Body** | Georgia Regular for content areas; Open Sans Regular/SemiBold for UI elements, navigation, form labels, buttons, and metadata |
| **Imagery style** | Minimal. UI-forward. Use Lucide line icons (consistent with brand iconography). When images appear, they should be functional (data visualizations, foundation logos), not decorative. |
| **Layout tone** | Application interface. Dense list results (not cards) for search. Clear hierarchy, obvious affordances, generous touch targets. Progressive disclosure — don't show everything at once. Mobile-first (375px). |
| **Motion** | Functional. Loading states, success confirmations, smooth transitions between steps. Micro-interactions that confirm user actions (button press feedback, form validation). No decorative animation. Respect `prefers-reduced-motion`. |
| **Voice test** | If a first-time user can't figure out what to do within 5 seconds of seeing any screen, simplify. |
| **Responsible AI** | All AI tool pages must include the required compliance elements per the Fundraising.AI Framework (data handling notice, PII guardrails, output guidance, methodology summary, feedback mechanism, version indicator, signatory badge). See STYLE_GUIDE.md §13. |

**CSS Variables Template:**
```css
:root {
  /* Brand colors (same as TheAlmoner — Palette 1) */
  --color-primary: #8B1A1A;
  --color-primary-dark: #6B1414;
  --color-gold: #D4AF37;
  --color-navy: #1E3A5F;
  --color-cream: #FAF0E6;
  --color-bg: #FEFCF8;
  --color-bg-muted: #FAF0E6;
  --color-text: #2C2C2C;
  --color-text-muted: #98A0A9;
  --color-border: #E8E8E8;
  /* Semantic */
  --color-success: #2E7D32;
  --color-error: #C62828;
  --color-alert: #E53D3C;
  /* Typography */
  --font-display: 'Playfair Display', serif;
  --font-body: 'Georgia', serif;
  --font-ui: 'Open Sans', sans-serif;
  /* Layout (tighter spacing for app context) */
  --radius-sm: 4px;
  --radius-md: 8px;
  --spacing-section: 4rem;
  --spacing-content: 1.5rem;
  --max-width-content: 720px;
  --max-width-page: 1200px;
  --transition-default: 200ms ease;
}
```

---

### 2c. YourFirstBillion.com — Web Game

**Brand positioning:** A fun, educational economics game. The tone is playful but not childish — think "Monopoly meets a TED talk." Built with Nathan's son as a co-development project.

**Visual direction:** Playful Retro / Game UI

| Element | Specification |
|---|---|
| **Primary palette** | Rich green (#1B6B3A) for money/growth, deep navy (#1A2744) for backgrounds, warm white (#FFF8F0) for cards |
| **Accent** | Bright gold (#FFD700) for achievements/currency; coral red (#FF6B5A) for alerts and losses |
| **Typography — Display** | A bold, characterful face: Space Mono, Syne, or Archivo Black. Headlines should feel like a game title screen. |
| **Typography — Body** | Space Mono for data/numbers (monospace feels like a financial terminal), paired with a clean sans like Outfit or Manrope for reading text. |
| **Imagery style** | Illustrated, not photographic. Flat design with subtle gradients and texture. Think: isometric buildings, stylized currency symbols, simple character avatars. Pixel art accents are welcome sparingly. |
| **Layout tone** | Dashboard-game hybrid. Information density is acceptable here (scores, stats, timers) but organized into clear zones. Cards ARE appropriate for game elements (property cards, event cards, player stats). |
| **Motion** | Expressive. Number counters that tick up, cards that flip, progress bars that fill, confetti on milestones. Motion IS the reward loop. Use Framer Motion or CSS keyframes. |
| **Voice test** | If a 12-year-old wouldn't immediately want to click something, add more juice. If an adult feels like it's for toddlers, pull back. |

**CSS Variables Template:**
```css
:root {
  --color-primary: #1B6B3A;
  --color-secondary: #1A2744;
  --color-accent-gold: #FFD700;
  --color-accent-coral: #FF6B5A;
  --color-bg: #FFF8F0;
  --color-bg-dark: #1A2744;
  --color-text: #1A2744;
  --color-text-light: #FFF8F0;
  --color-border: #D4CFC5;
  --font-display: 'Syne', sans-serif;
  --font-body: 'Outfit', sans-serif;
  --font-mono: 'Space Mono', monospace;
  --radius-sm: 8px;
  --radius-md: 16px;
  --radius-lg: 24px;
  --spacing-section: 3rem;
  --spacing-content: 1.5rem;
  --max-width-page: 1400px;
  --transition-default: 250ms ease;
  --transition-bounce: 400ms cubic-bezier(0.34, 1.56, 0.64, 1);
}
```

---

### 2d. Chestertron / Catholic Science Fiction Project

**Brand positioning:** A serious speculative fiction project exploring AI moral agency through Catholic Social Teaching. The tone is thoughtful, literary, and slightly mysterious — C.S. Lewis meets Blade Runner.

**Visual direction:** Speculative / Literary Sci-Fi

| Element | Specification |
|---|---|
| **Primary palette** | Near-black (#0D1117), cool steel (#B0BEC5), warm parchment (#F5F0E6), liturgical gold (#C49A2A) |
| **Accent** | Electric blue (#4FC3F7) for AI/tech elements; deep burgundy (#7B1F3A) for human/incarnational elements |
| **Typography — Display** | Something that bridges old and new: Cormorant Garamond (literary weight) or Cinzel (monumental). |
| **Typography — Body** | A refined sans-serif: Libre Franklin or Alegreya Sans. Should feel readable and serious. |
| **Imagery style** | Atmospheric. Dark environments with selective warm light (candlelight, screen glow, starlight). Architectural photography of cathedrals, observatories, server rooms. Juxtaposition of ancient and technological. AI-generated concept art is appropriate here when needed. |
| **Layout tone** | Immersive. Full-viewport sections. Cinematic aspect ratios. Text over dark backgrounds with careful contrast. Think: a film's production design website. |
| **Motion** | Atmospheric. Slow parallax, subtle particle effects (stars, dust motes), text that fades in like it's being revealed. Nothing fast. Everything deliberate. |
| **Voice test** | If it feels like a Marvel movie tie-in site, start over. If it feels like the website for a Terrence Malick film or a Vatican observatory exhibit, you're close. |

**CSS Variables Template:**
```css
:root {
  --color-primary: #0D1117;
  --color-secondary: #B0BEC5;
  --color-accent-gold: #C49A2A;
  --color-accent-tech: #4FC3F7;
  --color-accent-human: #7B1F3A;
  --color-bg: #0D1117;
  --color-bg-warm: #F5F0E6;
  --color-text: #E8E6E0;
  --color-text-dark: #2D2D2D;
  --color-border: #2A2F38;
  --font-display: 'Cormorant Garamond', serif;
  --font-body: 'Libre Franklin', sans-serif;
  --radius-sm: 2px;
  --radius-md: 4px;
  --spacing-section: 100vh;
  --spacing-content: 2.5rem;
  --max-width-content: 680px;
  --max-width-page: 1400px;
  --transition-default: 600ms ease;
  --transition-slow: 1200ms ease;
}
```

---

## 3. Universal Design Constraints

**Apply these to EVERY frontend project regardless of brand.** These are the "hard rules" that prevent generic AI output.

### 3a. Composition & Layout

- **One composition per first viewport.** The above-the-fold area must read as a single, intentional composition — not a collection of components assembled on a page. Exception: dashboards and application interfaces.
- **Brand first.** On branded pages, the brand or product name is a hero-level signal — not nav text, not an eyebrow label. No headline should overpower the brand. **Brand test:** If the first viewport could belong to another organization after removing the nav, the branding is too weak.
- **Full-bleed hero only** on landing pages and promotional surfaces. The hero image is an edge-to-edge visual plane or background. No inset hero images, side-panel heroes, rounded media cards, tiled collages, or floating image blocks — unless the established design system explicitly requires it.
- **Hero budget.** The first viewport contains: brand, one headline, one short supporting sentence, one CTA group, and one dominant image. Nothing else. No stats, no schedules, no event listings, no address blocks, no promos, no "this week" callouts, no metadata rows, no secondary marketing content.
- **No hero overlays.** No detached labels, floating badges, promo stickers, info chips, or callout boxes placed on top of hero media.
- **One job per section.** Each section has one purpose, one headline, and usually one short supporting sentence. If a section is doing two things, split it.
- **Real visual anchor.** Every major section needs imagery that shows the product, place, atmosphere, or context. Decorative gradients and abstract backgrounds do not count as the main visual idea.

### 3b. Cards & Components

- **Default: no cards.** Never use cards in the hero. Cards are allowed only when they serve as the container for a user interaction (clicking into detail, selecting an option, comparing items). **The card test:** If removing a border, shadow, background, or radius does not hurt interaction or understanding, it should not be a card.
- **Reduce clutter.** Avoid pill clusters, stat strips, icon rows, boxed promos, schedule snippets, and multiple competing text blocks. If everything is emphasized, nothing is emphasized.

### 3c. Typography

- **Use expressive, purposeful fonts.** Never default to Inter, Roboto, Arial, or system font stacks on marketing/brand pages. (Utility/app interfaces may use readable defaults — see individual brand profiles.)
- **Two typefaces maximum** unless the brand profile specifies otherwise. One display, one body.
- **Establish a type scale** using CSS variables. Define sizes for H1 through H4, body, small, and caption. Use `clamp()` for fluid scaling.

### 3d. Color & Atmosphere

- **No purple-on-white defaults.** No dark mode bias unless the brand profile calls for it.
- **Define all colors as CSS variables** at the document root. Every color in the design must trace back to a variable.
- **Build atmosphere.** Don't rely on flat, single-color backgrounds. Use gradients, images, textures, subtle patterns, or layered transparencies to create depth. Match the brand profile's visual direction.

### 3e. Motion & Animation

- **2–3 intentional motions** for visually-led work (landing pages, marketing). Focus on high-impact moments: a well-orchestrated page load with staggered reveals creates more delight than scattered micro-interactions.
- **Motion serves hierarchy.** Use animation to guide the eye, confirm actions, or create atmosphere — not to demonstrate technical ability.
- **Prefer CSS-only solutions** for HTML projects. Use Framer Motion for React when available. Use `animation-delay` for staggered entrances. Use `scroll-trigger` and `IntersectionObserver` for scroll-based reveals.

### 3f. Responsiveness & Quality

- **Every page must load properly on both desktop and mobile.** Test at minimum: 375px (mobile), 768px (tablet), 1440px (desktop).
- **Use real content.** Never use Lorem Ipsum or "Your headline here" placeholder text. Real content produces better structure, better hierarchy, and more believable design.
- **Accessibility baseline.** Semantic HTML. ARIA labels on interactive elements. Color contrast ratios meeting WCAG AA. Keyboard navigability on all interactive elements.
- **Gold contrast rule.** Gold (#D4AF37) fails WCAG AA contrast on cream/white backgrounds (1.9:1). Use gold only for decorative elements (borders, backgrounds) — never for text on light backgrounds. Pair gold backgrounds with navy text (#1E3A5F on #D4AF37 = ~7:1, passes AAA). Burgundy (#8B1A1A) passes AAA on all light backgrounds including cream.

---

## 4. Design Process Checklist

Use this sequence when starting any frontend design task:

### Step 1: Select Brand Profile
- [ ] Which project is this for? (TheAlmoner / Grant Helper Pro / YourFirstBillion / Chestertron / Other)
- [ ] Load the corresponding CSS variables template
- [ ] Load the corresponding typography and imagery guidelines

### Step 2: Define the Page
- [ ] What is this page's single purpose? (Landing page / Product page / Tool interface / Content page / Game screen)
- [ ] Who is the specific audience for this page?
- [ ] What is the one action we want the visitor to take?
- [ ] What is the one thing someone should remember after seeing this page?

### Step 3: Content First
- [ ] Write the real headline
- [ ] Write the real supporting sentence
- [ ] Write the real CTA label
- [ ] Identify the real image/visual (or describe what should be generated)
- [ ] Map out section purposes: Section 1 does ___, Section 2 does ___, etc.

### Step 4: Constraints Check
Before coding or generating, verify:
- [ ] First viewport has one composition with hero budget met (brand + headline + sentence + CTA + image, nothing else)
- [ ] No cards in the hero
- [ ] Brand test passes (viewport couldn't belong to another organization)
- [ ] Typography uses brand-specified fonts, not defaults
- [ ] Colors defined as CSS variables
- [ ] Real content, not placeholder text
- [ ] Background builds atmosphere (no flat white or flat dark unless brand-specified)

### Step 5: Build & Verify
- [ ] Code the page
- [ ] Check mobile (375px), tablet (768px), desktop (1440px)
- [ ] Verify 2–3 intentional motions are present (for marketing/brand pages)
- [ ] Run the voice test from the brand profile
- [ ] Accessibility spot-check (contrast, keyboard nav, semantic HTML)

---

## 5. Prompt Templates

### 5a. Landing Page Prompt

```
Using the House of Krupa Frontend Design Brief for [PROJECT NAME]:

Build a landing page for [SPECIFIC PURPOSE].

**Content:**
- Brand: [NAME]
- Headline: "[REAL HEADLINE TEXT]"
- Supporting sentence: "[REAL SUPPORTING SENTENCE]"
- Primary CTA: "[CTA LABEL]" → [destination]
- Hero image: [describe or attach]

**Sections (one job each):**
1. Hero — [purpose]
2. [Section name] — [purpose]
3. [Section name] — [purpose]
4. [Section name] — [purpose]
5. CTA / Footer — [purpose]

**Constraints:**
- Follow Universal Design Constraints from the brief
- Use the [PROJECT NAME] CSS variables template
- [Any additional constraints specific to this page]

**Visual references:** [attach screenshots or describe mood]
```

### 5b. Application Interface Prompt

```
Using the House of Krupa Frontend Design Brief for [PROJECT NAME]:

Build [SPECIFIC INTERFACE/COMPONENT].

**User task:** A user needs to [specific task description].
**Entry state:** They arrive at this screen from [context].
**Success state:** They leave this screen having [accomplished what].

**Content:**
- Page title: "[REAL TITLE]"
- Key data displayed: [list]
- Actions available: [list]
- Empty state message: "[REAL MESSAGE]"
- Error state message: "[REAL MESSAGE]"

**Constraints:**
- Follow Universal Design Constraints from the brief
- Use the [PROJECT NAME] CSS variables template
- Progressive disclosure: show [X] first, reveal [Y] on interaction
- Mobile-first: this will be used on phones as often as desktops
```

### 5c. Quick Iteration Prompt

```
Looking at [the current design / this screenshot], apply the House of Krupa
constraints check:

1. Does the first viewport pass the hero budget test?
2. Does the brand test pass?
3. Are there unnecessary cards?
4. Is typography using brand-specified fonts?
5. Is there real content or placeholders?
6. Does the background build atmosphere?
7. Are there 2-3 intentional motions?

Fix any failures and show me the updated version.
```

---

## 6. Anti-Patterns Reference

When reviewing AI-generated frontend output, check for these common failures and fix them immediately:

| Anti-Pattern | What It Looks Like | Fix |
|---|---|---|
| **Dashboard hero** | First viewport has 3–4 cards, stats, and multiple CTAs | Reduce to hero budget: brand + headline + sentence + CTA + image |
| **SaaS sameness** | Looks like it could be any B2B landing page | Apply brand-specific palette, fonts, and imagery direction |
| **Purple plague** | Purple gradients on white background | Use brand-defined palette from CSS variables |
| **Font amnesia** | Inter or Roboto everywhere | Switch to brand-specified display and body fonts |
| **Card carpet** | Everything is in a bordered, rounded, shadowed card | Remove cards. Use whitespace and typography for separation. |
| **Pill party** | Row of colored pills/badges/tags as navigation or features | Replace with clear headlines and prose, or a simple nav |
| **Stock photo syndrome** | Generic smiling people in an office | Use documentary-style imagery or textured backgrounds per brand |
| **Motion sickness** | Everything bounces, slides, and spins | Limit to 2–3 intentional motions. Remove decorative animation. |
| **Flat void** | Pure white or pure dark background with no texture | Add subtle gradient, pattern, noise, or image treatment |
| **Placeholder laziness** | "Lorem ipsum" or "Your headline here" | Write real content before designing |

---

## 7. Technical Defaults

Unless a project specifies otherwise:

- **Framework:** React (JSX) for interactive components and applications; HTML/CSS for static marketing pages
- **Styling:** Tailwind CSS utility classes + CSS custom properties for brand tokens
- **Motion:** CSS transitions/animations for HTML; Framer Motion for React when available
- **Icons:** Lucide React (clean, consistent line icons)
- **Font loading:** Google Fonts via `<link>` tag or `@import` — always specify `display=swap`
- **Image handling:** Responsive images with `srcset` when possible; `object-fit: cover` for hero images; lazy loading on below-fold images
- **Output format:** Single-file artifacts (all HTML/CSS/JS in one file) unless project complexity requires splitting

---

## 8. Version History

| Date | Change | Author |
|---|---|---|
| 2026-03-23 | Initial creation. Synthesized from OpenAI's GPT-5.4 Frontend Playbook, Claude's frontend-design skill, and House of Krupa brand context. | Nathan + Chestertron |
| 2026-03-23 | Aligned TheAlmoner and AI Grant Helper profiles with canonical brand standards from `ai-assistants/documentation/brand_guidelines/`. Corrected colors to Palette 1 "Classic Burgundy & Gold", corrected typography to full type system (Playfair Display, Lora, Georgia, Open Sans, Cormorant Garamond). Added Responsible AI requirements for AI tool pages. | Chestertron |

---

*This document is a living reference. Update brand profiles as visual identities evolve. Add new project profiles as the House of Krupa ecosystem grows.*
