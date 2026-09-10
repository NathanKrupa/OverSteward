ABOUTME: Deep research on home page design for aigranthelper.com — what makes getcreo.ai dynamic, what AG's current page lacks, and ten-plus ranked ideas that use AG's own data as the visual.
ABOUTME: Prepared for the home page workshop on Wednesday 2026-09-09; every claim carries a source URL and every fetch failure is named rather than papered over.

# AI Grant Helper — Home Page Research

**Date:** 2026-09-04
**For:** the home page workshop, Wednesday 2026-09-09
**Verdict Nathan gave the 2026-09-02 rebuild:** boring and static — no images, no product demos, no animation.

---

## 0. The thesis in one paragraph

The current AG home page is not boring because it lacks animation. It is boring because
**it never shows the product, and it never shows the data.** Verified against the live
page: `templates/landing/index.html` is 732 lines long and contains **zero** `<img>`,
`<video>`, `<canvas>` or `<svg>` tags of its own. The only two images the page renders
are the logo lockup and the logomark. A visitor reaches the bottom of the page having
read a set of well-written claims and seen a company logo twice.

Meanwhile AG owns exactly the assets a good home page is made of — 206,400 real
opportunities, a nationwide coverage map, server-rendered inline-SVG giving-trend charts
built from real IRS 990-PF data, a deadline calendar, a grant studio, and a founder with
14 years and $15M raised behind him. The fix is not to bolt a motion library onto a text
page. **The fix is to put the real product and the real data on screen, and let motion be
the thing that reveals them.** That framing also protects the page's SEO job: real data
rendered server-side is crawlable, fast, and free; decorative chrome is none of those.

A second, less comfortable finding sits underneath the first: **the page is already slow
in a way that will get worse the moment you add visuals carelessly.** Four
`<script src>` tags sit in `<head>` with no `defer` and no `async` — lucide, htmx, d3 and
topojson, pulled from two third-party CDNs with no `preconnect` — and they block HTML
parsing before the hero paints. The single richest visual the site owns (the D3 coverage
map) is paid for on every home page load, then displayed below the fold behind a
"Loading map data…" spinner. That is the worst of both worlds, and the workshop should
treat it as a fix, not a feature request.

---

## 1. getcreo.ai — what actually makes it feel alive

I fetched the live page and both its stylesheets and read the raw markup, rather than
describing the impression it gives. Everything below is verified in the shipped bytes.

### 1.1 The hero is a video, a rotating word, and nothing else

```html
<header class="hero" id="top">
  <video class="hero__video" autoPlay muted loop playsInline
         preload="metadata" poster="/videos/hero-2026-poster.jpg" aria-hidden="true">
    <source src="/videos/hero-2026.mp4">
  </video>
  <div class="hero__overlay"></div>
  <div class="hero__inner">
    <h1 class="hero__title">
      <span class="sr-only">Authenticity at Scale.</span>
      <span class="line" aria-hidden="true">
        <span class="rotator">
          <span class="rotator__word is-active">Authenticity</span>
          <span class="rotator__word">Your Voice</span>
          <span class="rotator__word">Real Growth</span>
          <span class="rotator__word">Referrals</span>
          <span class="rotator__word">Bold Brands</span>
        </span>
      </span>
      <span class="line"><span class="hero__title-static">at Scale.</span></span>
    </h1>
    <p class="hero__sub reveal">…</p>
    <div class="hero__actions reveal">
      <a class="btn btn--primary btn--lg">Personalize my plan <span class="btn__arrow">→</span></a>
      <a class="btn btn--ghost btn--lg">See the network</a>
    </div>
  </div>
  <a class="hero__scroll" aria-label="Scroll down"><span class="hero__scroll-line"></span></a>
</header>
```

Five reproducible things in that block:

| Technique | Mechanism | Why it works | Reproduce for AG |
| --- | --- | --- | --- |
| Full-bleed background video | `autoplay muted loop playsinline preload="metadata"` + `poster` + a scrim `div` | Motion in the peripheral field reads as "alive" without asking the visitor to look at anything. The poster is the LCP candidate, so the video payload does not itself set LCP | Yes — but with AG's own footage or a screen recording, never stock |
| Rotating headline word | Five `<span>`s, one carrying `.is-active`, cycled by JS; the *whole* headline duplicated in an `sr-only` span and the rotator marked `aria-hidden` | Lets one hero make five promises. The `sr-only` twin means screen readers and crawlers get one clean sentence, not five fragments | Yes — high value, low cost |
| Second line rises in | `.hero__title-static { animation: creoRise 1s var(--ease) .18s forwards }` | A 180ms offset makes the headline feel *assembled* rather than merely present | Yes |
| Scroll affordance | `.hero__scroll-line:after { animation: creoScrollDown 1.8s var(--ease) infinite }` — a light bar travelling `top:-50% → 120%` | Tells the visitor there is more page, without a "scroll down" label | Yes, cheap |
| Dual CTA | Primary "Personalize my plan →" + ghost "See the network" | The ghost CTA catches the visitor who is curious but not ready — it converts a bounce into a scroll | Yes |

### 1.2 The one motion primitive that does most of the work

Creo's whole page feels animated because of a *single* three-rule CSS pattern, used
**61 times** in the markup:

```css
.creo-lp .reveal      { opacity: 0; transform: translateY(28px);
                        transition: opacity .8s var(--ease), transform .8s var(--ease); }
.creo-lp .reveal.in   { opacity: 1; transform: none; }
```

An IntersectionObserver adds `.in` as each element enters the viewport. That is the
entire mechanism. It animates only `opacity` and `transform` — the two properties the
compositor can handle without touching layout or paint
([web.dev](https://web.dev/articles/stick-to-compositor-only-properties-and-manage-layer-count)),
so it costs essentially nothing.

**The lesson for AG: you do not need GSAP or Framer Motion to stop being static.** You
need one reveal class and an observer, roughly 15 lines of CSS and 8 lines of JS.

⚠️ One caveat worth carrying into the workshop: elements parked at `opacity: 0` waiting
on an observer are invisible to a reader who lands mid-page, and to any thumbnail or
social preview. Creo mitigates this correctly — see §1.4 — but AG should consider
revealing from a *visible* resting state (e.g. `opacity: .001` → 1 is a bug;
`translateY(20px)` at full opacity → `0` is safe).

### 1.3 The rest of the motion vocabulary

Creo defines 37 keyframes. Stripped to what actually runs on the marketing page:

| Keyframe | Attached to | Effect |
| --- | --- | --- |
| `creoMarquee` (40s linear infinite) | `.trust__track` | An endlessly scrolling logo/trust strip — `transform: translateX(-50%)` on a doubled track |
| `creoBlink` (1s `steps(2)` infinite) | `.demo__caret` | A typewriter caret in the product demo block — the cheapest "the product is working" signal there is |
| `creoSoundwave` (1.5s infinite) | `.dna-wave span` | Bars scaling on Y, staggered — an equaliser for the "brand voice" section |
| `creoAgentPulse` (3s infinite) | `.fd__agent:before` | An expanding box-shadow ring — "this node is live" |
| `creoAurora`, `creoFloat1/2`, `creoSmoke1/2` (9–38s) | pricing + CTA backgrounds | Very slow, very large blurred blobs drifting. Ambient, sub-conscious |
| `creoBtnWave` (1.6s, two offset copies) | `.btn:hover:before/:after` | A double ripple on button hover |
| `creoGlowBreathe`, `creoSpinSlow` | closing CTA wordmark + mark | A 30s rotation you never consciously see |

The pattern: **long durations (9–40s) for ambient background motion, short durations
(0.8–3s) for anything the eye lands on.** Nothing between 3s and 9s. That separation is
why it reads as atmosphere rather than fidget.

Also note `--w:64%` as an inline custom property driving a bar's width in the
attribution widget. CSS-variable-driven mini-charts are how you get "data visualisation"
into a marketing page without a charting library.

### 1.4 Accessibility done properly — copy this exactly

```css
@media (prefers-reduced-motion: reduce) {
  .creo-lp *, .creo-lp :after, .creo-lp :before {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .01ms !important;
  }
  .creo-lp .reveal { opacity: 1; transform: none; }
  html:has(.creo-lp) { scroll-behavior: auto; }
}
.creo-lp :focus-visible { outline: 2.5px solid var(--violet-glow); outline-offset: 3px; }
```

The second line is the one people forget: a global animation kill-switch that does *not*
also un-hide `.reveal` elements leaves a reduced-motion visitor staring at a blank page.
Creo handles it. Any AG implementation must.

### 1.5 Section rhythm and copy voice

Thirteen sections, in this order: **problem → front door → network → pillars → SEO →
scale → engine → features → how it works → pricing → playbook → FAQ → CTA.** Dark
sections (`section--dark`) alternate with light ones, which is the entire trick behind
"the page has rhythm" — a background flip is read as a chapter break.

Every `<h2>` is two beats, the second in italic `<em>`:

> "Marketing shouldn't feel / *this complicated.*"
> "Every channel. / *One front door.*"
> "Trust isn't a funnel. / *It's a network.*"
> "One system. / *Three superpowers.*"
> "One voice. / *Infinite reach.*"
> "From zero to thriving / *in three moves.*"

Short declarative sentence, then a reframe. It is a formula, it is applied twelve times
without deviation, and it is the strongest thing on the page. **AG's headings are
currently descriptive ("Three steps from research to funded.", "Foundations, state by
state.") — competent, but they never turn.**

CTA count: **10+ instances**, and — importantly — the label *changes with the section*.
"Personalize my plan" in the hero and front-door sections, "Map my network" in the
network section, "Get the Playbook" mid-page. Julian Shapiro's rule exactly: a CTA should
be a continuation of the section's narrative, not a generic "Sign up"
([julian.com](https://www.julian.com/guide/growth/landing-pages)).

---

## 2. aigranthelper.com today — measured on the same rubric

Fetched 2026-09-04 (39,603 bytes of HTML) and cross-read against
`aigranthelper/templates/landing/index.html` (732 lines).

### 2.1 What is there

| Section | Content | Visual |
| --- | --- | --- |
| Nav | Foundations · Federal Grants · Features · The Almoner · Sign In · **Get Started** | logo lockup PNG |
| Hero | Eyebrow "For grant writers. By a grant writer." → H1 "We don't replace grant writers. **We make them unstoppable.**" → tagline → "Start your free trial" + "First month free with code LAUNCH1. No credit card to start." | **a static SVG logomark** |
| Pull quote | "Organizations serving the most vulnerable shouldn't be the ones least equipped to find funding." — Nathan Krupa · 14 years in fundraising · $15M+ raised | none |
| Coverage map | H2 "**206,400** grant opportunities across the United States", Foundations/Government toggle, category chips, D3 choropleth, state detail panel, density legend | D3 map — **below the fold, behind "Loading map data…"** |
| Three steps | "Three steps from research to funded." → Find the grants (206,136+ funders, 1,254+ federal) → Build your grant calendar → Write the grants | none |
| Benefits | "When research takes minutes, not days." — four bullets | none |
| State directory | 51 links | none |
| Close | "Spend less time researching. Spend more time writing." + repeat CTA | none |

### 2.2 The rubric, scored

| Rubric item | Creo | AG | Note |
| --- | --- | --- | --- |
| Product visible above the fold | ✅ (video) | ❌ | AG shows a logo where the product should be |
| Any product screenshot anywhere | ✅ | ❌ | **Zero on the whole page** |
| Motion vocabulary | 37 keyframes, 61 reveals | `page-fade-in` only | AG's `motion.css` is 5,986 bytes and defines 5 keyframes, none used on the landing page |
| Section rhythm (dark/light alternation) | ✅ 13 sections | ❌ single cream ground throughout | |
| Headline formula with a turn | ✅ 12/12 | ❌ descriptive | |
| CTA variety | 10+, section-specific | 2, identical | |
| Social proof | trust marquee, named persona | **founder quote only — no photo, no customer, no logo, no count of users** | |
| `prefers-reduced-motion` | ✅ scoped kill-switch | ✅ present in `motion.css` | AG is already correct here |
| Render-blocking JS in `<head>` | 0 | **4** | see below |

### 2.3 Three concrete defects worth fixing regardless of the redesign

**(a) Four render-blocking scripts in `<head>`.** Verified positions in the served HTML
(`</head>` is at byte 18,874):

```
HEAD  4626  https://unpkg.com/lucide@0.460.0/dist/umd/lucide.min.js
HEAD  4729  https://unpkg.com/htmx.org@2.0.4
HEAD  5152  https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js
HEAD  5225  https://cdn.jsdelivr.net/npm/topojson-client@3/dist/topojson-client.min.js
```

None carry `defer` or `async`. d3@7 minified is roughly 280 KB. There is a `preconnect`
for Google Fonts but **none for `unpkg.com` or `cdn.jsdelivr.net`**, so each adds a fresh
DNS + TLS round trip on the critical path. The hero cannot paint until all four have
downloaded and executed. LCP's "good" threshold is ≤2.5s at the 75th percentile
([web.dev](https://web.dev/articles/lcp)); this is the single largest thing standing
between AG and that number.

*Fix:* `defer` all four; `preconnect` (or better, self-host) the CDNs; and load d3 +
topojson **only when the map scrolls into view**, via the same one-shot IntersectionObserver
pattern Bloomerang uses (`rootMargin: "200px 0px"` then `unobserve`). That alone removes
~310 KB from the critical path for every visitor who never scrolls to the map.

**(b) AG owns a founder headshot and does not use it on the home page.**
`static/images/nathan-krupa-headshot.webp` is 54 KB, already WebP, already
`srcset`-wired — and referenced **only** in `templates/pages/about.html`. The home page
pull quote attributes to Nathan with no face attached. CXL's research finds testimonials
carrying a real photo and full name are recalled and trusted materially more than
anonymous ones ([cxl.com](https://cxl.com/blog/is-social-proof-really-that-important/)).
This is a one-line template change for a real credibility gain.

**(c) `static/images/hero-community.png` is 2.48 MB and unused.** If the workshop
reaches for it, it must be converted to AVIF/WebP with a `srcset` first. Dropping a
2.5 MB PNG into the hero would move LCP the wrong way by seconds.

### 2.4 The asset AG has and is not exploiting

`templates/research/_detail_giving_trend.html` renders the foundation giving trend as a
**server-side inline `<svg>` with a `<polyline>` and a full `aria-label` describing every
data point.** No D3. No canvas. No client JS at all. Real IRS 990-PF numbers, 44 lines of
template.

That is the ideal home page visual: it is real data, it is crawlable text to a search
engine, it costs zero kilobytes of library, it is accessible by construction, and a
`stroke-dasharray`/`stroke-dashoffset` draw-on animation is about six lines of CSS. **The
home page should be built out of this pattern, not out of the D3 map.**

---

## 3. What the research says

### 3.1 The spine: Shapiro's equation

> **Purchase Rate = Desire − (Labor + Confusion)**
> — [julian.com/guide/growth/landing-pages](https://www.julian.com/guide/growth/landing-pages)

Every proposal below should be tested against it. A hero animation that delays the
headline adds Labor. A clever headline that does not say what you sell adds Confusion. A
real foundation record moving on screen adds Desire. Shapiro's headline litmus test is
the one to bring to the workshop: *"If the visitor reads only this text on your page,
will they know exactly what you sell?"*

His page order — nav → hero (header + subheader + **imagery**) → social proof →
features paired one-to-one with objections → repeated CTA → footer — is the default AG
should deviate from only deliberately.

### 3.2 Above the fold still decides

NN/g eye-tracking (≈1.5M gaze instances) puts **57–80% of viewing time above the fold**,
concentrated top-left/top-centre
([nngroup.com](https://www.nngroup.com/articles/designing-effective-carousels/)). Some
2025-era re-analyses put it nearer 40% as scrolling habits mature — treat the range, not
the point estimate, as the finding. Either way the hero is the highest-leverage block on
the page, which is precisely where AG currently spends its space on a logo.

### 3.3 Do not build a carousel

NN/g's carousel research is unambiguous: users "immediately scroll past" large rotating
heroes, typically register only the first frame, and attend to animated ad-like content
only **27% of the time**. Their standing recommendation is that a single strong static
hero usually beats a carousel, because the effort concentrates on one good visual instead
of five weak ones ([nngroup.com](https://www.nngroup.com/articles/designing-effective-carousels/)).

This matters because the obvious "make it dynamic" instinct is a rotating feature
showcase. Don't. Givebutter runs one and it is the least persuasive part of their page.
The rotating *word* in Creo's headline is a different thing — it is one visual with five
labels, not five visuals.

### 3.4 Copy is worth about twice what design is

Unbounce's analysis of 36,928 landing page variants found **copy has roughly twice the
influence on conversion that design does**
([unbounce.com](https://unbounce.com/copywriting/value-proposition/)). The workshop
should therefore spend at least as long on the twelve headings as on the motion.

Frameworks worth having on the whiteboard:

- **Problem–Agitate–Solve.** Name the problem, agitate it in the customer's own words,
  then resolve. Copyhackers' point is that the *agitation* carries the persuasion, and
  that its language must be mined from real customer speech — support tickets, feedback,
  forums ([copyhackers.com](https://copyhackers.com/write-compelling-agitation-copy/)).
  AG has a live in-app feedback queue; that is the mine.
- **Before–After–Bridge.** Current painful state → desired state → the product as bridge
  ([copyhackers.com](https://copyhackers.com/2015/10/copywriting-formula/)).
- **The 4 U's** for headlines: Useful, Urgent, Unique, Ultra-specific, in that priority
  order ([swipefile.com](https://swipefile.com/the-4-us-copywriting-formula)).

### 3.5 Social proof: what and where

- **Client logos are the most efficient form** — high recall, low cognitive load; and
  recognisable beats obscure ([cxl.com](https://cxl.com/blog/is-social-proof-really-that-important/)).
- **Photo + full name** materially lifts testimonial trust versus anonymous quotes (ibid.).
- **Placement**: the two strongest positions are *directly below the hero* and *directly
  beside the primary CTA* — proof works as friction relief at the moment of hesitation,
  not as page decoration.
- Baymard-derived e-commerce work found moving trust indicators above the fold produced a
  **34% lift** on tested pages — directionally relevant to SaaS, though the underlying
  study is e-commerce, so treat it as a prompt rather than a promise.

Notion's framing is worth stealing on principle: **"Trusted by 98% of the Forbes
Cloud 100"** — a percentile, not a raw count. When your absolute number is small, a
percentile or a domain-specific proof point beats a headcount. AG's honest equivalents
today are *"206,400 opportunities"*, *"$15M+ raised"* and *"14 years in fundraising"* —
all of which are real and none of which are currently presented as social proof.

### 3.6 Show, don't tell — the techniques ranked by cost

| Technique | Weight | 2026 support | When to use |
| --- | --- | --- | --- |
| **Server-rendered inline SVG + CSS transition** | ~0 KB | universal | AG's default. Charts, maps, counters, draw-on lines |
| **IntersectionObserver reveal** (`opacity`/`transform`) | ~8 lines JS | universal | Section entrances. Compositor-only, no layout cost |
| **Native CSS scroll-driven animation** (`animation-timeline: view()`) | 0 KB JS | ~84% (Chrome/Edge 115+, FF 132+ behind a flag in stable, Safari 18+); **not Baseline** | Progressive enhancement only — author the finished state as default and layer this on ([MDN](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Scroll-driven_animations)) |
| **Autoplay muted looping `<video>` + poster** | 200 KB–2 MB | universal | Hero atmosphere or a screen recording. Poster is the LCP candidate, so a good poster largely protects LCP |
| **Lottie** | ~50 KB runtime + JSON | universal | Small vector loops. Reported ~5× faster to load than equivalent GIF |
| **GSAP + ScrollTrigger** | ~30 KB | universal | Genuine scroll-storytelling only |
| **Framer Motion** | ~32–59 KB gz | React only | Not applicable — AG is Django + htmx |
| **Rive** | state-machine runtime | universal | Interactive illustration responding to input |
| **Interactive demo embed** (Navattic/Storylane/Arcade) | third-party JS | universal | Storylane ≈ $40/user/mo, screenshot-based, ships in minutes; Navattic ≈ $500/mo, live-HTML replicas |

⚠️ **On interactive-demo conversion numbers:** vendors publish figures like "18–24% lift
at the awareness stage" and "92% lift" case studies
([walnut.io](https://www.walnut.io/blog/product-demos/interactive-demos-conversion-rates-b2b-2026-data/),
[storylane.io](https://www.storylane.io/blog/awesome-interactive-demo-examples)). These
are vendor-published and self-serving. The direction is plausible; the magnitudes should
not be quoted to anyone.

### 3.7 Performance and accessibility — the hard constraints

The home page is an SEO asset. These are non-negotiable:

- **LCP ≤ 2.5s** at p75. Candidates include `<img>`, SVG `<image>`, `<video>` poster or
  first frame, CSS `background-image`, and large text blocks. Crucially, **changes to an
  element after it paints do not create a new LCP entry** — so a long hero fade-in gets no
  credit for finishing, and a reveal animation on the hero headline is a straightforward
  way to make LCP worse ([web.dev](https://web.dev/articles/lcp)).
  **Rule: never animate the LCP element in.**
- **CLS < 0.1.** The dominant cause is unsized media — the 2025 Web Almanac found 62% of
  mobile pages ship at least one image without width/height. Font swap is the other.
  Every image AG adds needs explicit dimensions ([web.dev](https://web.dev/articles/cls)).
- **INP ≤ 200ms**, and it is now the most commonly failed vital (~43% of sites)
  ([web.dev](https://web.dev/blog/inp-cwv-march-12)). Every kilobyte of head-blocking JS
  is INP risk as well as LCP risk.
- **Animate `transform` and `opacity` only.** They are the two properties the compositor
  handles without layout or paint. Animating `width`, `height`, `top` or `left` triggers
  layout and blows the 16.7ms frame budget
  ([web.dev](https://web.dev/articles/stick-to-compositor-only-properties-and-manage-layer-count)).
  **Correctly built animation does not hurt Core Web Vitals; badly built animation does.**
- **`prefers-reduced-motion`.** web.dev's guidance is to reduce or replace decorative
  motion rather than strip all of it, keep essential feedback at shortened durations, and
  mirror the check in JS with `matchMedia('(prefers-reduced-motion: reduce)')`
  ([web.dev](https://web.dev/articles/prefers-reduced-motion)).
  **Bloomerang's architecture is the one to copy:** elements are visible at rest in CSS,
  and JS only *adds* motion when the query permits — so a reduced-motion visitor never
  risks a blank page. Vercel does the same structurally with Tailwind's `motion-safe:` /
  `motion-reduce:` prefixes.
- **NN/g on animation:** legitimate purposes are feedback, state change, spatial
  navigation and signifiers. "Gratuitous animations distract and annoy the user," and
  animation used to hijack attention is a dark pattern; motion should stay "unobtrusive,
  brief, and subtle" ([nngroup.com](https://www.nngroup.com/articles/animation-purpose-ux/)).
  This sits comfortably with AG's own `motion.css` philosophy — *"whispered transitions,
  never loud"* — and the two are reconcilable: **the motion should reveal the product,
  not decorate the page.**

### 3.8 Nonprofit buyers specifically

The weakest-evidenced section, and it should be labelled as such in the workshop. No
primary homepage-UX research scoped to nonprofit SaaS buyers was found. What exists:

- B2B purchases now clear buying committees averaging 10+ stakeholders evaluating ~4.5
  vendors — a home page has to serve the end user, the budget-holder and a sceptical
  reviewer at once ([martal.ca](https://martal.ca/b2b-buying-process-lb/)).
- Nonprofit budget scrutiny is structural: a purchase "must clear financial scrutiny,
  show a credible payback story, and beat competing internal priorities for the same
  funds" (ibid.). This argues for **visible pricing** over "contact us", and for a
  payback framing in the copy.
- NTEN's Tech Accelerate dataset (1,200+ nonprofits) found organisation size, budget and
  tech investment are the strongest predictors of technology risk — the buyer to reduce
  friction for is the *small, resource-constrained* org
  ([nten.org](https://www.nten.org/blog/tech-accelerate-analysis)).

Read together: **peer proof from similarly-sized nonprofits will outperform enterprise
logos**, and AG's "for the servants of the poor" positioning is a genuine asset rather
than a softness — provided it is paired with a hard payback claim.

---

## 4. Comparable home pages worth stealing from

Ten pages fetched and grepped in raw HTML on 2026-09-04. All ten fetched successfully;
`www.candid.org` does not resolve (DNS), the bare domain was used.

### 4.1 The direct sector comparables

**Instrumentl** — *"Your intelligent grant operating system."*
Illustration/screenshot hero; no `<video>` anywhere on the page.
1. **A scroll-synced lifecycle rail** (Find → Write → Manage → Track) driven by
   `aria-current="step"` toggling, with the active step's label the only one shown below
   1200px. The state hook is accessible, not merely a CSS class — screen readers get the
   progress too.
2. **Logo marquee** for the "5,500+ organizations" band.
3. ⚠️ **Anti-pattern to avoid:** 9 `loading="lazy"` and 7 `rel="preload"` but **no
   `fetchpriority="high"`** — the hero image is not prioritised for LCP. AG should not
   copy this.

**Grantable** — *"Meet your AI grants department."*
> "AI grant writing that finds your funders, drafts proposals in your voice, and never misses a deadline — the capacity of a whole grants team, getting smarter with every grant."

1. **The hero visual is a live, working chat widget** — *"This is real — chat with
   Grantable right here"* with a "Let's go" button. Not a screenshot of the product; the
   product. This is the single most aggressive "show don't tell" move in the whole sweep.
2. **157 `muted` hits** — silent looping clips standing in for animated screenshots
   throughout the tour sections. Cheap to produce, no player chrome.
3. One **Rive** embed for a state-driven illustration.
4. Social proof as a stat strip near the top: *"Trusted by 30,000+ grant professionals."*

**Bloomerang** — *"Fundraising and nonprofit software built for purpose."* CTAs "Book a Demo" / "Tour the Giving Platform".
1. **The best reusable technique found anywhere in this research** — a pinned panel whose
   image swaps as bullets scroll past, driven by IntersectionObserver rather than scroll
   maths:

   ```js
   const io = new IntersectionObserver((entries) => {
     const active = entries.filter(e => e.isIntersecting).map(e => e.target);
     const viewportCenter = window.innerHeight / 2;
     active.sort((a,b) => Math.abs(centerA-viewportCenter) - Math.abs(centerB-viewportCenter));
     setObjectSrc(obj, active[0].getAttribute("data-svg-src"));
   }, { root: null, rootMargin: "-50% 0px -50% 0px", threshold: 0 });
   ```

   `rootMargin: "-50% 0px -50% 0px"` collapses the viewport to a 1px trigger line at dead
   centre. Whichever bullet is nearest the line wins and its `data-svg-src` becomes the
   panel image. **Zero scroll listeners, naturally debounced, GPU-cheap.** This is exactly
   the mechanism for AG's "Three steps" section.
2. **A second, separate observer** for lazy media with `rootMargin: "200px 0px"` then
   `obs.unobserve()` — a proper one-shot preload.
3. **Reduced motion handled by architecture:** `var reduce = matchMedia('(prefers-reduced-motion: reduce)'); if(!reduce.matches) scan(document);` — CSS shows elements at rest, JS only adds motion. No flash-of-invisible-content is possible.
4. A CSS `hero-float` keyframe (translateY 0 → −6px → 0) bobbing an illustrated widget — a two-line idle animation that makes a static hero feel alive.

**Givebutter** — *"Where changemakers go to grow."* CTA "Watch a demo".
1. **Autoplay muted looping `<video>` with the JPEG poster set as `background-image`** —
   the Webflow IX2 pattern; the poster paints instantly behind the video element.
2. **Lottie** for the "giving" header illustration.
3. **95 `loading="lazy"` against 33 `loading="eager"`** — above-the-fold assets explicitly
   opted *out* of lazy loading. A deliberate LCP strategy, and the correct one.
4. Splide logo marquee immediately under *"Trusted by millions of changemakers at
   nonprofits like yours."*

**Candid** — *"Where nonprofit data meets decision makers."*
**The hero visual is a functional search box.** No keyframes, no video, no Lottie found —
static-first, utility-led. For AG this is the most instructive page in the set, because
Candid is the closest analogue: a nonprofit *data* company, and it leads with the data
being searchable rather than with a marketing image. Its weakness is that no "Trusted by"
string appears anywhere — social proof is effectively absent.

### 4.2 The best-in-class general SaaS

**Linear** — *"The product development system for teams and agents."*
A **procedurally generated ambient dot grid**: 150 `@keyframes` blocks named as a
coordinate matrix (`grid-dot-0-0-agent`, `grid-dot-0-0-pong`, `grid-dot-0-1-upDown`…).
Each cell gets its *own* keyframe so cells run at different phases and states, producing
organic non-repeating motion from pure CSS — no canvas, no WebGL, no JS animation loop.
Clearly build-time generated. **The transferable idea is the principle, not the grid:
uniform motion reads mechanical; per-element phase offsets read organic.** A cheap version
is `animation-delay: calc(var(--i) * 45ms)` — which is precisely what Creo does with
`.deal-stagger > * { animation-delay: calc(var(--i, 0) * 45ms) }`.

**Attio** — *"Welcome to agentic revenue."*
1. **A fanned 3D card stack**, each card given a different `transform-origin`
   (`100% 0%`, `0% 100%`, `100% 100%`) so they pivot as a physical deck rather than flat
   overlapping divs.
2. **Blur-in reveal** — `filter: blur(Npx) → blur(0)` animated alongside opacity and
   transform. Higher polish, but heavier: `filter` is not compositor-free, and Attio
   carries 40 `will-change` hits to compensate. Use sparingly.
3. 26 `rel="preload"` — the most aggressive hero-asset prioritisation in the set.

**Clay** — *"Build systems to grow revenue."*
1. Autoplay muted looping `<video>` hero, plus **six section-gated background videos**,
   each `preload="none"` so bandwidth is deferred until the section is needed. Only the
   hero video preloads.
2. A `data-desktop` attribute on each implies a responsive swap so phones never receive
   desktop-weight video.
3. GSAP + SplitText for per-line scroll text animation.
4. **218 `loading="lazy"` hits** on a 502 KB page — the heaviest lazy-loading discipline
   in the set, and the reason a video-dense page stays viable.
5. Proof at two altitudes: a logo band near the top ("500,000+ GTM teams") and narrative
   case studies mid-page.

**Vercel** — *"Agentic Infrastructure."*
1. **The accessibility guard is structural**: `motion-safe:will-change-transform
   motion-safe:animate-marquee` with `motion-reduce:overflow-y-hidden`. The marquee
   animation is only ever *applied* under `motion-safe:`, so a reduced-motion user gets a
   static list by default rather than an animation that has to be cancelled. This is the
   pattern AG should adopt wholesale.
2. `data-cdp-track="homepage_hero_secondary_cta_clicked"` on the CTA itself — analytics
   event names declared in the markup. Worth copying for the workshop's measurement plan.
3. Only 2 `@keyframes` on the whole page. Vercel's richness is typography and layout, not
   motion — proof that "dynamic" is not synonymous with "animated".

**Notion** — *"Where teams and agents Think together."*
1. `<video preload="metadata" playsinline>` paired with a responsive `<source>` srcset at
   640/1080/1200/1920/2048w — the video's fallback/poster is a properly responsive image.
2. **CSS-custom-property-parameterised marquee**:
   `--logo-wall-marquee-item-count-js: 17`, `--logo-wall-marquee-max-rows: 2` — one
   component, reconfigured per instance without a CSS rebuild.
3. 42 `rel="preload"` on a 241 KB page — the leanest, most preload-dense page fetched.
4. Percentile social proof: *"Trusted by 98% of the Forbes Cloud 100."*

### 4.3 The comparison

| Page | Hero visual | Primary motion technique | Social proof placement |
| --- | --- | --- | --- |
| **AG (today)** | **static SVG logomark** | **none** | **founder quote, no photo** |
| Creo | autoplay muted video + poster | IntersectionObserver `.reveal` ×61 | trust marquee |
| Instrumentl | illustration / screenshot | `aria-current="step"` lifecycle rail | logo marquee, mid-page |
| Grantable | **live chat widget** | 157 muted looping demo clips + Rive | stat strip near top |
| Bloomerang | floating illustrated widget | IO pinned-panel image swap | Swiper testimonials, mid-page |
| Givebutter | autoplay video, poster-as-background | Webflow IX2 + Lottie | Splide marquee under hero |
| Candid | **live functional search box** | none | absent |
| Linear | text only | 150 per-cell generated keyframes | logo marquee |
| Attio | fanned 3D card stack | per-card `transform-origin` + blur reveal | dedicated section, ~⅔ down |
| Clay | autoplay video background | GSAP + SplitText, 7 gated videos | logo band + case studies |
| Vercel | text only, dual CTA | `motion-safe:` gated marquee | logo marquee |
| Notion | responsive video + srcset | CSS-var-parameterised marquee | near footer, percentile framing |

Two patterns stand out for AG. **First: the two nonprofit-data companies closest to AG —
Candid and Grantable — both put a working thing in the hero** (a search box; a chat
widget), not a picture of one. **Second: every page in this set has a visual in the hero
except Linear and Vercel, and both of those substitute exceptional typography.** AG has
neither a visual nor exceptional typography, which is why it reads as flat.

---

## 5. Thirteen ideas for AG, ranked

Ranked by (visitor impact × feasibility) ÷ risk. Cost is engineering effort: **S** ≤ 1
day, **M** 2–4 days, **L** ≥ 1 week. Assets marked *(exists)* need no new data work.

### Tier 1 — do these first; they are cheap and they are the whole difference

**1. Put a working search over real foundations in the hero.**
*What the visitor sees:* a search field, pre-filled and already showing three real
foundation result cards — name, state, total giving, last filing year. On load, the
placeholder types a query ("food insecurity in Georgia") character by character and the
results below swap in. The visitor can immediately type their own.
*Assets:* the existing foundation search endpoint; htmx *(already loaded on the page)*.
*Cost:* **M**. *Risk:* **Medium** — search latency is visible in the hero, and an empty
or slow result set is worse than no demo at all. **Mitigation is mandatory: server-render
the initial three results into the HTML** so the hero paints complete, is crawlable, and
works with JS disabled; the typing and the swap are enhancement only. Never animate the
LCP element in.
*Why:* this is what Candid and Grantable both do. It is the single highest-conviction
idea in this report — it demonstrates the product, proves the data is real, and answers
Shapiro's litmus test in one glance.

**2. Give Nathan a face, above the fold.**
*What the visitor sees:* the pull quote with the existing 54 KB WebP headshot beside it,
moved up to sit directly under the hero.
*Assets:* `static/images/nathan-krupa-headshot.webp` *(exists, already srcset-wired in
`pages/about.html`)*.
*Cost:* **S** — a template include. *Risk:* **Very low.**
*Why:* CXL finds photo + full name materially lifts testimonial trust; below-the-hero is
one of the two highest-impact proof positions. AG already owns the asset and does not use it.

**3. Adopt one reveal primitive across every section.**
*What the visitor sees:* each section rises 20px and fades as it enters view; nothing
else changes.
*Assets:* ~15 lines of CSS + ~8 lines of JS.
*Cost:* **S**. *Risk:* **Low**, with one condition — **build it Bloomerang's way**:
elements visible at rest in CSS, JS only *adds* the animation when
`matchMedia('(prefers-reduced-motion: reduce)')` does not match. Never park content at
`opacity: 0` waiting on an observer.
*Why:* 61 uses of one three-rule pattern is the entire reason Creo feels alive. This is
the highest ratio of perceived dynamism to engineering cost available.

**4. Alternate section grounds for rhythm.**
*What the visitor sees:* the map section and the "how it works" section on a deep navy
ground, the rest on cream.
*Assets:* existing tokens.
*Cost:* **S** — CSS only. *Risk:* **Very low**; check contrast on both grounds.
*Why:* Creo's thirteen sections read as chapters purely because `section--dark`
alternates. A background flip is the cheapest structural signal there is.

**5. Rewrite the twelve headings so each one turns.**
*What the visitor sees:* "Three steps from research to funded." becomes something with a
second beat — e.g. *"You are not short of grants. / You are short of hours."*
*Assets:* a whiteboard and the in-app feedback queue for real customer language.
*Cost:* **S**. *Risk:* **Low** — but Rule #1 applies: Nathan's voice, not a formula
applied mechanically.
*Why:* Unbounce's 36,928-variant analysis puts copy at roughly twice design's influence
on conversion. This is the cheapest and most under-weighted item on the list.

### Tier 2 — the real showpieces

**6. Promote the coverage map to the hero — but rebuild it as server-rendered SVG.**
*What the visitor sees:* a US choropleth already painted when the page arrives, states
filling from pale to deep over ~1.2s with a per-state `animation-delay` stagger, the
206,400 counter beside it.
*Assets:* the state-level counts *(exist)*; a static TopoJSON→SVG path set generated at
build time.
*Cost:* **M**. *Risk:* **Low–Medium.** The prize is large: it **removes d3 + topojson
(~310 KB) from the critical path entirely**, and lazily hydrates the interactive version
only when the visitor scrolls to or clicks the map (Bloomerang's `rootMargin: "200px 0px"`
one-shot observer). Faster *and* more dynamic than today.
*Why:* AG's best visual currently sits below the fold behind "Loading map data…". This
fixes the boring problem and the slow problem with one change.

**7. Turn "Three steps" into a pinned-panel scroll walkthrough of a real foundation page.**
*What the visitor sees:* the three step headings scroll on the left; a pinned panel on the
right swaps between real crops — the search results, the foundation page with its
giving-by-sector treemap, the deadline calendar.
*Assets:* three cropped screenshots or, better, three server-rendered SVG/HTML fragments
of real surfaces *(the underlying pages exist: `templates/research/detail.html`,
`templates/app/calendar/`)*.
*Cost:* **M**. *Risk:* **Medium** — screenshots rot the moment the UI changes. Prefer
rendered fragments of the live templates over PNGs; if PNGs, add them to the release
checklist.
*Why:* Bloomerang's IntersectionObserver `rootMargin: "-50% 0px -50% 0px"` swap is a
proven, jank-free mechanism, and this section is currently three headings with no visual
at all.

**8. Draw the giving-trend chart on, using a real foundation.**
*What the visitor sees:* beside "Find the grants", a real foundation's giving trend —
name, five fiscal years, dollar figures — with the polyline drawing itself left to right
over ~900ms.
*Assets:* `templates/research/_detail_giving_trend.html` *(exists — server-rendered
inline SVG `<polyline>` with a full `aria-label`, zero JS)*; one representative foundation.
*Cost:* **S**. *Risk:* **Low.** `stroke-dasharray` / `stroke-dashoffset` is ~6 lines of
CSS. Pick a foundation whose trend is honest and unremarkable, not cherry-picked.
*Why:* real IRS 990-PF data, crawlable as text, zero kilobytes of library. This is the
best-value visual AG owns and it has never appeared on the home page.

**9. The calendar that fills itself.**
*What the visitor sees:* a month grid; real upcoming deadlines drop in one at a time with
a ~45ms stagger, each chip carrying **the funder name alongside the date**.
*Assets:* real federal + foundation deadline data *(exists)*.
*Cost:* **M**. *Risk:* **Medium** — a deadline shown without its funder is a house rule
violation, and stale dates on a marketing page are worse than no dates. Needs a freshness
guard.
*Why:* "Build your grant calendar" is currently a heading with nothing under it. A
calendar populating itself is the clearest possible statement of what the step does.

**10. The studio drafting a real paragraph.**
*What the visitor sees:* a need-statement prompt on the left; on the right, a paragraph
types itself with a blinking caret (`@keyframes blink { 50% { opacity: 0 } }` on
`steps(2)` — Creo's `creoBlink` exactly).
*Assets:* one pre-approved, genuinely-produced studio output; the full text present in the
DOM from the start (typing is a CSS/JS reveal over static text, so it is crawlable and
the reduced-motion path just shows the finished paragraph).
*Cost:* **S–M**. *Risk:* **Medium–High** — this is the claim most likely to be tested by
a sceptical grant professional. The paragraph must be real output Nathan would sign, and
the framing must stay "drafts stronger applications", never "writes your grant". The
positioning line — *"We don't replace grant writers"* — is the guard, and it is already
in the hero.
*Why:* "Write the grants" is the step that sells the product and the step with no
evidence attached.

### Tier 3 — worth discussing, with reservations

**11. A marquee of real foundation names.**
*What the visitor sees:* a slow horizontal band of foundation names drawn from the corpus.
*Assets:* foundation names *(exist)*.
*Cost:* **S** — a doubled track and `transform: translateX(-50%)` over 40s, gated behind
`motion-safe:` per Vercel.
*Risk:* **High, and it is a truthfulness risk, not a technical one.** A logo/name band in
the position where customer logos normally sit reads as endorsement. If this is built it
must be unambiguously labelled — *"A few of the 206,136 foundations in the database"* —
and must never use foundation logos. My recommendation: **use it only if the label makes
the meaning unmissable**, and prefer idea 12 instead.

**12. Honest social proof in place of logos AG does not have.**
*What the visitor sees:* a three-up band under the hero — *"206,400 opportunities
tracked"* · *"14 years in fundraising"* · *"$15M+ raised"*.
*Assets:* live counts from the GS seam *(exist)*; Nathan's record.
*Cost:* **S**. *Risk:* **Low.**
*Why:* Notion proves a framing that is not a customer count can carry the proof slot.
These three numbers are true, specific, and currently scattered or absent.

**13. A rotating word in the headline.**
*What the visitor sees:* "We make them unstoppable" holds, while a preceding line cycles
through *researchers · writers · one-person shops · consultants*.
*Assets:* five spans and a timer.
*Cost:* **S**. *Risk:* **Low–Medium** — must be built Creo's way: the complete headline
in an `sr-only` span, the rotator `aria-hidden="true"`, and **the rotator must not be the
LCP element**.
*Why:* lets one hero address four audiences. Cheap. But it is chrome, and it should be
built after ideas 1–8, not instead of them.

### Explicitly not recommended

- **A hero carousel / rotating feature showcase.** NN/g: users scroll past, register only
  the first frame, attend to animated ad-like content 27% of the time.
- **GSAP, Framer Motion, or Rive.** AG is Django + htmx; ideas 1–13 need none of them, and
  each adds head weight to a page already carrying four blocking scripts.
- **A paid interactive-demo embed (Storylane/Navattic) — for now.** $40–500/mo of
  third-party JS to do what idea 1 does with the product AG already owns. Revisit if idea
  1 proves the appetite.
- **`static/images/hero-community.png` as-is.** 2.48 MB PNG. If it is used at all,
  AVIF/WebP with a `srcset` first.

---

## 6. Proposed page skeleton for the workshop

Fifteen minutes of this table will be worth an hour of arguing about animation.

| # | Section | Ground | Visual | Pitch copy direction | CTA |
| --- | --- | --- | --- | --- | --- |
| 1 | **Nav** | cream | logo lockup | unchanged | "Get Started" |
| 2 | **Hero** | cream | **live search + 3 real foundation cards, server-rendered** (idea 1) | Keep *"For grant writers. By a grant writer."* / *"We don't replace grant writers. We make them unstoppable."* — it passes Shapiro's litmus test and it is Nathan's own voice. Subhead states *how*: one tool from research to submission. | "Start your free trial" + ghost "Search 206,400 grants" |
| 3 | **Proof band** | cream | Nathan's headshot (idea 2) + three numbers (idea 12) | 206,400 tracked · 14 years · $15M+ raised. The quote sits here, attributed with a face. | — |
| 4 | **Problem** | **navy** | none — let type carry it | PAS. *"You are not short of grants. You are short of hours."* Three cards agitating the real pain, in customers' words from the feedback queue: research eats the week; deadlines arrive unannounced; the blank page. | — |
| 5 | **Step 1 — Find** | cream | **coverage map, server-rendered SVG, states filling in** (idea 6) + **giving-trend polyline drawing on** (idea 8) | *"Every foundation in America, and what each one actually funds."* Name the data source — IRS 990-PF — because a grant professional will ask. | "Explore the map" |
| 6 | **Step 2 — Track** | cream | **calendar filling itself, funder names on every chip** (idea 9) | *"The deadline you miss is the grant you lose."* Before/After: a spreadsheet you forget vs. a calendar that tells you. | "See the calendar" |
| 7 | **Step 3 — Write** | **navy** | **studio typing a real paragraph** (idea 10) | *"A first draft in your voice, not a robot's."* Handle the objection in the copy: it drafts, you write. | "Try the studio" |
| 8 | **Walkthrough** | cream | **pinned-panel scroll through a real foundation page** (idea 7) | *"This is one funder record. There are 206,136."* One narrated pass — treemap, trend, contacts, deadlines. | — |
| 9 | **Objections** | cream | none | Four to six blunt Q&As mined from real sales conversations: *Is the data current? What does it cost? Do I need to be technical? What if my org is tiny?* Nonprofit buyers clear budget scrutiny — put the payback story here. | — |
| 10 | **Pricing** | **navy** | none | Visible numbers, not "contact us". Small-org buyers are the ones to de-risk. | tier CTAs |
| 11 | **State directory** | cream | 51 links | unchanged — this is the SEO hub and it is doing its job | — |
| 12 | **Close** | cream | slow ambient gradient | *"Spend less time researching. Spend more time writing."* | "Start your free trial" |

Notes for the room:

- **CTA labels change per section** (Shapiro; Creo does this 10+ times). "Get Started" six
  times is a wasted opportunity.
- **Every `<h2>` gets two beats.** Statement, then turn. Twelve of them, no exceptions —
  that consistency is what made Creo's page feel authored.
- **Sections 4, 7 and 10 are dark.** That alternation is the rhythm.
- **Nothing above the fold animates in.** The hero must paint complete; LCP takes no
  credit for a finished fade.
- **Build order:** ideas 2, 3, 4, 12 (a day, and the page stops being flat) → idea 1 (the
  hero) → idea 6 (the map, which also fixes the performance defect) → ideas 8, 9, 10 →
  ideas 5 and 7 as the copy settles.

### The performance budget to agree in the room

| Constraint | Target | Today |
| --- | --- | --- |
| Render-blocking scripts in `<head>` | **0** | 4 |
| `preconnect` for every third-party origin | all | fonts only |
| JS on the critical path | < 50 KB | ~350 KB (lucide + htmx + d3 + topojson) |
| LCP (p75) | ≤ 2.5s | unmeasured — **measure before the workshop** |
| CLS | < 0.1 | every new image needs explicit width/height |
| Animated properties | `transform` + `opacity` only | n/a |
| `prefers-reduced-motion` | motion added by JS only when permitted | CSS guard present, honour it |
| Above-the-fold images | `loading="eager"`, `fetchpriority="high"` | n/a |
| Below-the-fold media | `loading="lazy"`, one-shot IO preload | n/a |

⚠️ **Unmeasured:** I did not run Lighthouse or pull CrUX field data for
aigranthelper.com. The performance findings above are read from the served markup — four
un-deferred head scripts, no CDN preconnects, ~310 KB of map libraries on every load —
not from a measured LCP. **Get a real Lighthouse and CrUX reading before Wednesday** so
the workshop argues from numbers.

---

## 7. Sources

**Primary artefacts fetched 2026-09-04** (raw HTML and CSS read directly)

- https://getcreo.ai — plus `/_next/static/css/{12e9cf0f,8e0b4b7a,f76ca38b}*.css`
- https://www.aigranthelper.com/ — plus `/static/css/motion.f7572e083e8a.css`
- https://www.instrumentl.com · https://grantable.co · https://bloomerang.com · https://givebutter.com · https://candid.org
- https://linear.app · https://attio.com · https://www.clay.com · https://vercel.com · https://www.notion.com

**Fetch failures (recorded, not worked around)**

- `https://www.aigranthelper.com/foundations/ga/` — **HTTP 403** to both `curl` and
  WebFetch. AG's state hub pages are behind bot protection, so I could not read a live
  foundation page. The foundation-page detail in this report comes from the repository
  templates (`templates/research/_detail_giving_trend.html`, `_detail_giving_visuals.html`,
  `detail.html`), not from the rendered page.
- `https://cxl.com/research-study/social-proof/` — **HTTP 403**. CXL social-proof findings
  are taken from `cxl.com/blog/is-social-proof-really-that-important/` and search-indexed
  summaries instead.
- `https://www.candid.org` — DNS does not resolve on the `www` subdomain; bare domain used.

**Landing page and conversion research**

- https://www.julian.com/guide/growth/landing-pages
- https://www.nngroup.com/articles/designing-effective-carousels/
- https://www.nngroup.com/articles/animation-purpose-ux/
- https://www.nngroup.com/articles/scrolling-and-attention-original-research/
- https://unbounce.com/copywriting/value-proposition/
- https://cxl.com/blog/is-social-proof-really-that-important/
- https://cxl.com/blog/persuasive-writing/
- https://cxl.com/blog/how-to-build-a-high-converting-landing-page/
- https://copyhackers.com/write-compelling-agitation-copy/
- https://copyhackers.com/2015/10/copywriting-formula/
- https://swipefile.com/the-4-us-copywriting-formula
- https://www.strategyzer.com/library/the-value-proposition-canvas
- https://wynter.com/products/value-proposition-testing
- https://instapage.com/blog/short-vs-long-form-landing-pages
- https://sam-saenz.medium.com/baymard-cliff-notes-homepage-ux-best-practices-92d15a0b0cb3
- https://uxplanet.org/the-usability-of-carousel-design-4e3930a10b29

**Performance and accessibility**

- https://web.dev/articles/lcp
- https://web.dev/articles/cls
- https://web.dev/articles/optimize-cls
- https://web.dev/blog/inp-cwv-march-12
- https://web.dev/articles/stick-to-compositor-only-properties-and-manage-layer-count
- https://web.dev/articles/animations-and-performance
- https://web.dev/articles/prefers-reduced-motion
- https://web.dev/learn/performance/video-performance
- https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Scroll-driven_animations
- https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/animation-timeline
- https://www.debugbear.com/blog/optimize-video-lcp
- https://www.corewebvitals.io/core-web-vitals/interaction-to-next-paint

**Animation and demo tooling**

- https://www.framer.com/blog/web-animation-tools/
- https://lab.good-fella.com/blog/gsap-vs-framer-motion-vs-react-spring
- https://www.arcade.software/post/arcade-vs-navattic
- https://www.naoma.ai/articles/navattic-vs-storylane-2026
- https://www.walnut.io/blog/product-demos/interactive-demos-conversion-rates-b2b-2026-data/ ⚠️ vendor-published
- https://www.storylane.io/blog/awesome-interactive-demo-examples ⚠️ vendor-published

**Nonprofit and B2B buyer behaviour** *(weakest-evidenced section — no primary
homepage-UX research scoped to nonprofit buyers was found)*

- https://martal.ca/b2b-buying-process-lb/
- https://www.nten.org/blog/tech-accelerate-analysis
- https://www.nten.org/publications/state-of-nonprofit-ai

**AG repository files read**

- `aigranthelper/templates/landing/index.html` (732 lines, 0 `<img>`/`<video>`/`<svg>`)
- `aigranthelper/templates/landing/_grant_map.html`
- `aigranthelper/templates/research/_detail_giving_trend.html`
- `aigranthelper/templates/pages/about.html`
- `aigranthelper/static/images/` (headshot 54 KB WebP; `hero-community.png` 2.48 MB, unused)
