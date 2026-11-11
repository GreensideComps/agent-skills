# Q201 pre-registration: pick-1 with continuous hard-break exits (3 Nov 2026, 15:10Z)

Owner 14:46Z (cmsg_01U4KMvkBYNknqm4HRVie8uvXJLm1iCcuhTUUy6sNXAXst): checks must be on all the time. Q200 (rank-based
monthly selling) already seen: it failed. Written before any Q201 number.

Same basket as Q199 with the January yearly rebalance kept. In between, at every month-end (monthly_metrics only
change when a filing lands, so this approximates checking at each filing), a held name is sold ONLY if:
1. it fails a gate on its latest filing (FCF <= 0, op income <= 0, ND/EBITDA >= 3, shares +>2%/12m, equity <= 0), or
2. its price is 25%+ below its entry price (crash guard), or
3. it leaves the data (delisted / merged).
A sold name is replaced by the best-scored gated unheld name (max 3 per SIC2). No rank-based selling.
Cost 0.30% one way per traded name. One trial AO-Q201.

Decision rule fixed now: the live demo uses Q201's exits if its B1 excess after costs >= +3.0%/yr
(within ~0.4%/yr of yearly Q199) and lag view > 0; otherwise exits are limited to rule 1 + rule 3 events and
the crash guard is reported only. 8-K red-flag items (1.03 bankruptcy, 3.01 delisting, 4.01 auditor change,
4.02 non-reliance) are a live-only risk rule, not tested here (too rare in large caps for a backtest).
