# Q244 pre-registration: how the stock screener holds its top 15 (owner 11 Nov 2026 09:28Z, cmsg_01U4KMvkBYNknqm4HRVie8uv8KHjb9pWG7twM3nxm2izvR)

Written 11 Nov 2026 before any of these variants were run. Registry ids AO-SCR-Q244b/c/d, N = 484-486. Owner clarified 09:29Z (cmsg_01U4KMvkBYNknqm4HRVie8uvW53W7yG1SaivwpuaHbdh43): keep the sector limit; hold only top-15 names that fit it, no fillers, leftover slots to VWRP, keep each until it leaves the top 15. That is Q244c, the MAIN test. No-cap variants (a, e) dropped before any run.
Data: pick-1 panel (pick1.py load), months Dec 2014 - Nov 2022 decisions, returns to Dec 2022 (exploration only, no holdout).
Survivor-biased monthly panel (see Q231 addendum): longer holds are flattered; read every positive as an upper bound.

Common mechanics: 15 equal slots, re-equalised monthly at no cost; a swap costs 2 x 0.30% x 1/15.
Ranks = pick1.score() order (gated names only). "Capped" = pick1 SIC2 cap (max 3) plus an approximate
sector cap (max 6 of 15 names in one broad sector, SIC -> rough GICS map in code; stands in for the live
+-10pt vs VWRP limit, whose history we do not have). Empty slot earns the cap-weighted universe return (VWRP proxy).

- R0 (control, current live rule): any held name that leaves the gated list is replaced at once; plus one
  scheduled swap a month: the lowest-scored held name, if outside the top 15, is replaced by the best unheld name that
  fits the caps (at any rank, so fillers like rank 27 are allowed).
- Q244b: top 15 (SIC2 cap) every month, names over the sector cap dropped, their slots held in the VWRP proxy.
- Q244c (MAIN, owner's rule): keep each name until it leaves the top 15 (or fails the gates); replace only from the top 15 within caps,
  else the slot sits in the VWRP proxy. No monthly limit on swaps.
- Q244d: as c with a buffer: sell only when rank > 30 (or gates fail); buy only from the top 15 within caps.
Reference only (not a trial): Q199 yearly plain hold.

Statistic: d = variant monthly net return - R0 monthly net return, 96 months. Report t, DSR at N, thirds,
costs x2, 1-month implementation lag, plus each leg vs EW universe and vs VWRP (GBP).
PASS (edge claim): DSR > 0.95, >= 2 of 3 thirds positive, d > 0 with costs x2 and with lag.
DEMO SWITCH (rule choice between unproven demo rules, not an edge claim): switch the live stock_screen rule to the
variant with the highest mean d if mean d > 0, t >= 1.0, >= 2 thirds positive, and d > 0 under costs x2 and lag.
Main test is c (the owner's rule). If c meets the bar it is switched in even if b or d score higher, unless one of them
also meets the bar with a higher mean d. Otherwise R0 stays.
