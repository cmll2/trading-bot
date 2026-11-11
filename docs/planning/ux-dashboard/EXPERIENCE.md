---
name: Trading-bot dashboard
status: draft
created: 2026-11-11
updated: 2026-11-11
sources:
  - ../prd.md            # FR-49 to FR-56, SAF-15, NFR-09, GL-02, GL-04, FR-42
  - ../../../first_brief.txt   # section 7
  - ../../../PROGRESS.md       # GL-02 tolerance, risk limits, daily candles, post-only orders
---

# Trading-bot dashboard: experience spine

Visual tokens are defined in `DESIGN.md`. Where the two documents disagree, these two spines override any mock-up.

## Foundation

- **Form factor:** a desktop browser on the same Windows PC as the bot. There is one operator (Camille) and no login.
- **UI system:** Streamlit multipage app with Plotly charts (brief section 6). No extra dependencies (SAF-13). Auto-refresh uses Streamlit's built-in `st.fragment(run_every=…)`, not a third-party component.
- **Network:** binds only to `127.0.0.1` (SAF-15). The project's Streamlit config sets `server.address = "127.0.0.1"`, and a test asserts it (BI-10). The dashboard shows `127.0.0.1:<port>` in the sidebar footer so the binding can be checked by eye.
- **Data access is read-only.** The SQLite store is opened with a read-only URI (`mode=ro`). The dashboard never writes to the store, never edits config, and never calls Kraken.
- **One write:** the dashboard can create the kill-switch file. This is the same file the engine already watches (FR-36), so the dashboard and file triggers share one mechanism (GL-04).

## Control boundary (decision)

| Action | Where | Why |
|---|---|---|
| **Engage** the kill switch | Dashboard (Risk page, with confirmation) or by creating the file | FR-36, FR-49 |
| **Disengage** the kill switch (re-arm trading) | **CLI only** | A one-click way to resume trading from a browser tab is the riskiest control the app could offer. Re-arming should happen at the terminal, on purpose. |
| Reset a halt (daily loss, drawdown) | **CLI only** | FR-33 requires a manual reset, OD-10 leaves the mechanism open, and SAF-05 means no path may touch limits. |
| Approve a pending order (approval mode) | **Not the dashboard.** The dashboard shows pending approvals read-only and names the channel. | OD-13 is still open. FR-49 allows exactly one action. |
| Edit limits, config or strategy | Nowhere at runtime | SAF-04, SAF-05 |

This **narrows FR-49's "toggling"** to engage-only. **OQ-UX-01:** confirm with the PM and record it in the PRD and in OD-10. Architecture names the CLI commands. This spec calls them `<rearm-cmd>` and `<halt-reset-cmd>`.

## Information Architecture

On every page, top to bottom: mode banner, then status strip, then content. The sidebar holds the navigation, the pair selector and the refresh controls.

| # | Page | Content (FR) | Pair-scoped? |
|---|---|---|---|
| 1 | **Overview** | Mode, engine status and last heartbeat, equity, cash, open position, return since start, total fees, equity curve against buy-and-hold and cash (FR-50) | Position and curve: yes. Equity, cash and fees: account-wide, labelled as such. |
| 2 | **Signals & trades** | Price chart with indicator, entry and exit markers, current target position. Below it, the signal journal with each outcome (filled / not filled / rejected / skipped) and the would-have-returned value for untraded signals (FR-51, FR-40). | Yes |
| 3 | **Orders & fills** | Orders table with status. Fills with price, fee, and slippage against the signal price. Date-range filter (FR-52). | Yes |
| 4 | **Risk** | Each limit with current usage against its configured value, read-only. History of rejections, halts and kill-switch events with reasons. Kill switch state and button (FR-53). | No (account-wide) |
| 5 | **Dry-run vs backtest** | GL-02 verdict, per-trade comparison, equity overlay, weekly review, DECAYING status (FR-54, FR-41, FR-42) | Yes |
| 6 | **Health** | Recent errors, API latency, rate-limit events, data freshness against the stale thresholds (candle older than 2 intervals, ticker older than 120 s), uptime (FR-55) | No |
| 7 | **Ledger** | Fills ledger, CSV export, calendar-year disposal running total (FR-56, FR-47) | Table: filterable by pair. **Disposal total: always account-wide.** |

**Pair selector** (sidebar, applies to every page, kept in session state). It lists every pair in config. In v0 there is one pair, so the selector shows that pair and is disabled. The tooltip reads "v0 runs one pair". A pair that is in config but has no data in the store is listed as `<PAIR> (no data)`. Account-wide panels say "All pairs" in their title so the selector doesn't seem to apply to them.

## Mode banner

The mode is read from the engine's run record in the store. It is never read from the dashboard's own config or an environment variable.

| Mode | Banner text | Browser tab title |
|---|---|---|
| Dry-run | `DRY-RUN — simulated orders, no real money` | `[DRY-RUN] Trading bot` |
| Live | `LIVE — real orders on Kraken, real money` | `[LIVE] Trading bot` |
| Unknown (store missing or unreadable, no run record) | `MODE UNKNOWN — cannot read engine state` | `[?] Trading bot` |

The mode never defaults to dry-run. If the store holds runs in more than one mode, the banner shows the mode of the latest run, and the history views filter to that run's mode, with a sidebar toggle to view the other.

## Simulated-data labelling (NFR-09)

- Anything derived from the backtest, the paper broker or the plumbing strategy carries the **SIMULATED** tag (`DESIGN.md` `simulated-tag`) in its title row. In dry-run, that is every page. In live, it is the backtest series and the Dry-run vs backtest page.
- Plumbing-strategy rows (FR-09) also carry `plumbing — no edge`.
- In dry-run, the Ledger title reads `Ledger — SIMULATED (paper fills, not for tax)`, and the disposal total reads `Simulated disposal total — not a tax figure`.
- **CSV export:** the filename includes the mode (`ledger_<year>_dry-run_SIMULATED.csv` / `ledger_<year>_live.csv`), and every row has a `simulated` column (true/false). Simulated and live fills are never exported together.

## Component Patterns

| Component | Behaviour |
|---|---|
| **Status strip** | Shows: engine status (running / stopped / heartbeat stale), last heartbeat as relative time plus UTC, kill switch (ARMED / ENGAGED), halt (none / HALTED: reason), DECAYING badge, last refresh time. The heartbeat is flagged stale after [ASSUMPTION AS-UX-02] 2 × the engine loop interval. |
| **Kill switch button** | Risk page only. When the switch is armed, the label reads `Engage kill switch`. Clicking it opens a confirmation dialog (`st.dialog`): title "Stop all new orders?", followed by what it does under the OD-09 scope ("Blocks new orders. Open orders: <per OD-09>. Position: <per OD-11>.") and the line "Re-arming is done from the terminal with `<rearm-cmd>`, not here." Buttons: `Engage` (primary) and `Cancel`. Confirming takes one click, with no typing: emergency friction stays low. |
| **Kill switch engaged** | The button is replaced by a read-only panel: `ENGAGED since <UTC> by <dashboard / file>`, plus "To resume trading, run `<rearm-cmd>` in a terminal." There is no disengage button. If the file has been written but the engine hasn't recorded the event yet, the panel shows `Requested — waiting for engine (last heartbeat <t>)`. |
| **Halt panel** | Shows `HALTED: <daily loss / drawdown> <value> breached <limit> at <UTC>` and "Reset with `<halt-reset-cmd>` in a terminal." This panel also appears in the status strip on every page. |
| **Limit usage row** | Shows the limit name, the configured value, current usage, and a bar coloured by usage (warn at 80% [ASSUMPTION AS-UX-03], fail at 100%). Limits: max position (fraction and €), orders per day, daily loss, drawdown from start, stale data, price sanity. Values are read-only, with no edit control. |
| **GL-02 verdict block** | Top of the Dry-run vs backtest page, two lines. (1) `Per fill: PASS/FAIL — n of N fills within 0.5% of backtest price (worst x.xx%)`. (2) `Equity: PASS/FAIL — difference x.x pp (limit 2 pp) over <window>`. The default window is the M5 four weeks, or since dry-run start if shorter, with a "window incomplete (d/28 days)" note. The tolerance is shown as fixed text: it is not a setting. |
| **Per-trade diff table** | One row per signal: signal time, side, backtest price, paper fill price, diff %, fee in each, per-trade return in each, PASS/FAIL. Trades that happened in only one of the two (for example, post-only "not filled" in dry-run) are shown as `MISSING in dry-run` / `MISSING in backtest` and count as FAIL. Default sort puts failures first. |
| **Equity overlay** | Backtest-predicted and paper-recorded equity on one Plotly chart, with a difference subplot in pp and a horizontal line at ±2 pp. |
| **DECAYING status** | Below 20 trades: `DECAYING check: n/20 trades — not evaluated`. At 20 or more: `OK` or `DECAYING`, with avg/trade realised against avg/trade backtest. While flagged, the DECAYING badge also appears in the status strip on every page. If the backtest average is ≤ 0 (OD-15), show `Not evaluable — backtest avg ≤ 0 (OD-15)` rather than guessing. |
| **Disposal running total** | Ledger header: `Crypto→EUR disposals, <year>: € <total> (k fills)`, with a year selector that defaults to the current year in UTC [ASSUMPTION AS-UX-04: calendar year in UTC; French tax year may need Europe/Paris]. Disposal rows are marked in the table, and a running-total column accumulates them. |
| **Pending approvals** | Approval mode only. A read-only list on Overview: "Awaiting approval via <OD-13 channel>". There are no approve or reject buttons. |

## State Patterns

| State | Treatment |
|---|---|
| Store missing or unreadable | Banner: MODE UNKNOWN. Page body: "Cannot read `<store path>`: <error>". No figures are shown, and stale numbers are never kept on screen. |
| Store locked by an engine write | Retry on the next refresh and keep showing the previous data with `refresh failed <t>` in the strip. After 3 consecutive failures, switch to the unreadable state. |
| Engine stopped / heartbeat stale | The strip shows `ENGINE STOPPED` or `HEARTBEAT STALE <age>` in `{colors.fail}`. The data stays visible, marked "as of <last heartbeat>". |
| No trades yet | Each page shows a one-line explanation, e.g. "No fills yet. The strategy trades at daily candle close." GL-02 shows `Not evaluable — 0 fills`, never PASS. |
| Backtest prediction missing for the period | The Dry-run vs backtest page shows "No backtest run covers <period>. Run `<backtest-cmd>`." It shows FAIL/n.a., never PASS. |
| Kill switch requested, not yet acknowledged | See the Kill switch engaged row above. |

## Interaction Primitives

- **Auto-refresh:** data fragments re-run every 30 s [ASSUMPTION AS-UX-05: daily candles make faster pointless; Health is the most time-sensitive page]. The sidebar has a pause toggle and a "Refresh now" button. Refresh pauses while the confirmation dialog is open. The mode banner and status strip refresh on every cycle.
- **Time:** stored and shown in UTC (NFR-03). Hovering shows local time.
- **Filters:** date range (Orders & fills, Ledger, Risk history) and pair, both kept in session state.
- **No keyboard shortcuts, no drag, no inline editing.**

## Voice and Tone

Plain and factual. Give the number and the threshold. State what the operator must do and where to do it.

| Do | Don't |
|---|---|
| `FAIL 0.71% > 0.50%` | "Slightly off" |
| `Reset with <halt-reset-cmd> in a terminal.` | "Click to resume" |
| `Simulated disposal total — not a tax figure` | "Disposals: €12.40" (in dry-run) |
| `Not evaluable — 0 fills` | `PASS` on empty data |

## Accessibility Floor

Information never depends on colour alone: every status has a word, and chart series also differ by line style. The mode appears three times: in the banner, in the tab title, and in the CSV filename. Text contrast meets WCAG AA in both Streamlit themes (see `DESIGN.md`).

## Key Flows

**F1: Morning check during dry-run (Camille, coffee, before work).**
1. Opens `127.0.0.1:<port>`. A blue `DRY-RUN` banner is at the top, and the tab reads `[DRY-RUN]`.
2. The status strip shows the engine running, a heartbeat 40 s old, the kill switch ARMED, no halt, and `DECAYING check: 3/20`.
3. Overview: equity against buy-and-hold and cash, all tagged SIMULATED.
4. Signals & trades: last night's candle closed above the moving average, the target is long, and the journal shows the order as `not filled — post-only window expired`.
5. **Climax:** Health shows data freshness green and no errors. Camille closes the tab knowing nothing needs her attention.

**F2: Weekly GL-02 review (Camille, Sunday, end of week 2 of M5).**
1. Opens Dry-run vs backtest. The verdict reads `Per fill: FAIL — 6 of 7 within 0.5% (worst 0.71%)` and `Equity: PASS — 0.9 pp`, with "window incomplete (14/28 days)".
2. Failures are sorted first: one fill at 0.71%, plus one `MISSING in dry-run` (post-only not filled).
3. **Climax:** she can see that the backtest's fill assumption is too optimistic for post-only orders, which is exactly what this page exists to show. She writes the finding into the weekly review. She changes nothing on the dashboard, because it has no settings to change.

**F3: Emergency stop in live (Camille, sees an exchange outage on the news).**
1. Red `LIVE` banner. She goes to Risk and clicks `Engage kill switch`.
2. The dialog says what is blocked under OD-09 and that re-arming is a terminal action. She clicks `Engage`.
3. The panel shows `Requested — waiting for engine`, then `ENGAGED since 14:02 UTC by dashboard` after the next refresh. The status strip shows ENGAGED on every page.
4. **Climax:** the outage ends and she wants to resume. The dashboard has no button for that, only `run <rearm-cmd>`. She re-arms from the terminal on purpose.

**F4: Year-end export (Camille, January, preparing her tax return).**
1. Ledger, year selector 2027, mode LIVE. The header reads `Crypto→EUR disposals, 2027: € <total> (k fills)`.
2. **Climax:** she exports `ledger_2027_live.csv`. Every row has `simulated=false`, and the disposal rows are marked with a running total. The dry-run paper fills from M5 can't end up in this file.

## Open questions and assumptions

- **OQ-UX-01:** FR-49 says "toggling". This spec makes the dashboard engage-only and moves re-arming to the CLI. The PRD and OD-10 need updating.
- **OQ-UX-02:** the text of the kill-switch dialog depends on OD-09 and OD-11 (whether open orders are cancelled and whether the position is exited).
- **OQ-UX-03:** the approval channel (OD-13) still has to be named in the Pending approvals panel.
- **AS-UX-01:** placeholder hex values. **AS-UX-02:** stale heartbeat at 2 × the loop interval. **AS-UX-03:** warn at 80% of a limit. **AS-UX-04:** disposal year boundary in UTC (Europe/Paris may be required). **AS-UX-05:** 30 s refresh.
