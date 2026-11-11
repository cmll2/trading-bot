---
name: Trading-bot dashboard
description: Local, single-operator Streamlit + Plotly monitor for the Kraken spot bot. It reads the store, and its only write is engaging the kill switch.
status: draft
created: 2026-11-11
updated: 2026-11-11
sources:
  - ../prd.md
  - ../../../first_brief.txt
colors:
  # Semantic only. Everything else inherits the Streamlit default theme (light/dark follows the OS). [ASSUMPTION AS-UX-01]
  mode-dryrun: '#1D4ED8'
  mode-live: '#B91C1C'
  mode-unknown: '#525252'
  on-mode: '#FFFFFF'
  pass: '#15803D'
  fail: '#B91C1C'
  warn: '#B45309'
  simulated-tag: '#6D28D9'
  series-strategy: '#1D4ED8'
  series-buyhold: '#737373'
  series-cash: '#A3A3A3'
  series-backtest: '#B45309'
typography:
  banner:
    fontSize: 1.25rem
    fontWeight: 700
    letterSpacing: 0.04em
  metric: { note: 'Streamlit st.metric default' }
  body: { note: 'Streamlit default' }
rounded:
  DEFAULT: 4px
spacing:
  banner-pad: 12px
components:
  mode-banner-dryrun: { background: '{colors.mode-dryrun}', text: '{colors.on-mode}', type: '{typography.banner}' }
  mode-banner-live: { background: '{colors.mode-live}', text: '{colors.on-mode}', type: '{typography.banner}' }
  mode-banner-unknown: { background: '{colors.mode-unknown}', text: '{colors.on-mode}', type: '{typography.banner}' }
  simulated-tag: { background: '{colors.simulated-tag}', text: '{colors.on-mode}', rounded: '{rounded.DEFAULT}' }
  verdict-pass: { text: '{colors.pass}' }
  verdict-fail: { text: '{colors.fail}' }
  decaying-badge: { background: '{colors.warn}', text: '{colors.on-mode}' }
---

# Trading-bot dashboard: visual spine

## Brand & Style

This is an instrument panel, not a product, and has no brand. It uses Streamlit defaults throughout. Colour is reserved for meaning: the mode, simulated data, pass/fail results, and warnings. If something is coloured, it carries information.

## Colors

- `{colors.mode-dryrun}` / `{colors.mode-live}` / `{colors.mode-unknown}` are used for the mode banner only. Nothing else on any page uses the live red as a background, so a red bar at the top always means real money.
- `{colors.pass}` / `{colors.fail}` / `{colors.warn}` mark GL-02 results, limit usage, health and the DECAYING badge. They always come with a text word (PASS, FAIL, DECAYING) and never stand alone.
- `{colors.simulated-tag}` is used only for the SIMULATED tag.
- Chart series use fixed colours on every chart: strategy `{colors.series-strategy}`, buy-and-hold `{colors.series-buyhold}`, cash `{colors.series-cash}` (dashed), backtest prediction `{colors.series-backtest}` (dotted). Line style also tells the series apart, so the charts still read without colour.

The hex values are placeholders [ASSUMPTION AS-UX-01]. Each pair must reach WCAG AA contrast against `{colors.on-mode}` in both Streamlit themes.

## Typography

Streamlit defaults. The banner text is the only override (`{typography.banner}`): bold, uppercase, slightly letter-spaced.

## Layout & Spacing

Wide layout (`layout="wide"`). Every page has the same order, top to bottom:

1. Mode banner, full width.
2. Status strip: engine status, last heartbeat, kill switch state, halt state, DECAYING badge, last refresh time.
3. Page content.

The sidebar holds the page navigation, the pair selector and the refresh controls.

## Components

- **Mode banner.** A full-width bar with an icon and an uppercase label. It can't be dismissed or collapsed. See EXPERIENCE.md for the wording.
- **SIMULATED tag.** A small pill that sits in the title row of every chart, table, metric group and export derived from a backtest, the paper broker or the plumbing strategy.
- **Verdict cell.** The word PASS or FAIL in `{colors.pass}` / `{colors.fail}`, followed by the measured value and the threshold, e.g. `FAIL 0.71% > 0.50%`.
- **Kill switch button.** The only primary button in the app. It uses Streamlit's `type="primary"` style and appears only on the Risk page.

## Do's and Don'ts

- Do keep the mode banner as the first element rendered on every page, before any data loads.
- Don't use red or blue backgrounds anywhere except the mode banner.
- Don't show a pass or fail result as colour alone.
- Don't put simulated and real figures in one chart or table unless each series or row is labelled.
