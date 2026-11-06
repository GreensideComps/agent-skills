# Q200 pre-registration: pick-1 with a monthly review and sell discipline (3 Nov 2026, 14:50Z)

Owner 3 Nov 14:45Z (cmsg_01U4KMvkBYNknqm4HRVie8uvALWFQUEebAGWKxcXPt9tt9): the system should keep reviewing, not
buy and hold for a year. Written before any Q200 number was computed. Q199 result is already known (seen).

Same universe, gates, score and 15-name / max-3-per-SIC2 basket as Q199. Start: full basket at the first month.
Each month-end, re-score everything. A held name is SOLD if any of:
1. it fails a gate (FCF <= 0, operating income <= 0, ND/EBITDA >= 3, shares +>2% over 12m, equity <= 0),
2. its score rank falls outside the top 30% of the gated universe,
3. it leaves the universe (cap < $2bn, price < $5) or has no data.
Each sold name is replaced by the highest-scored gated name not held (respecting max 3 per SIC2).
Unchanged names are not traded. Cost 0.30% one way per name traded (both legs).

One trial (AO-Q200). Same tests and pass rule as Q199. Decision rule fixed now: if Q200's B1 excess after costs
is >= Q199's (+3.43%/yr) AND its lag view is > 0, the live demo basket switches to the monthly review rule;
otherwise it stays yearly. Either way it remains a low-confidence demo test (both fail DSR is expected).
