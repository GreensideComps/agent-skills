# Survivorship-free price data: feasibility and the accepted limitation

Written 2026-10-16 at the owner's request (item 1 of 2026-10-16 10:12Z). No data was bought or downloaded for this
note. The prices of paid services are as recorded on 2026-10-14 and have not been re-checked.

## 1. The problem

- The research prices come from Yahoo's free daily history, which keeps only tickers that still trade.
- A company that was acquired, merged, went bankrupt or otherwise delisted before the price download has **no
  price at all**. Stage 1: no delisted company with more than $1bn of assets is priced. For 2023-26: 318 of 323
  large companies that stopped filing are unpriced.
- Two effects follow for 2015-2022 exploration:
  1. **Missing exits.** A name a strategy held that later delisted would have a final return we cannot see. The
     engine's −30% (and −100% stress) rule bounds this only for names it holds that lose their price mid-window.
  2. **Missing names (larger).** A company that delisted before the download never enters the universe, even in
     the years it traded. No missing-price rule can bound this, because the strategy never sees the name.
- **Likely direction for large caps (inferred, not measured):** most large-cap delistings are acquisitions, which
  usually end at a premium; large-cap bankruptcies are rare. So the bias in a large-cap long-only strategy is
  probably modest and could run either way. It cannot be sized without the missing data.

## 2. Options

| Option | Delisted US prices? | Cost | Feasible now? |
|---|---|---|---|
| Yahoo (current) | No | Free | Already in use; this is the source of the bias |
| SEC EDGAR | No prices at all | Free | No |
| Other free sources (Stooq and similar) | Patchy, undocumented, no CIK link | Free | No: coverage cannot be verified, so it would add unknown bias rather than remove it |
| CRSP via WRDS | Yes, the research standard | Institutional licence only | No: not available to an individual |
| Norgate Data | Yes, delisted US stocks included | About $630 a year (recorded 2026-10-14) | Technically yes; paid, not approved |
| EODHD | Claims delisted tickers; coverage and quality unverified | About $20 a month (recorded 2026-10-14) | Technically possibly; paid, not approved, quality unknown |
| Nasdaq Data Link (Sharadar) and similar | Yes, delisted included | Paid subscription (not priced here) | Paid, not approved |

**Work any paid source would still need:** matching each source's tickers to SEC CIKs point in time (tickers are
reused and change), a cross-check against the current Yahoo prices for surviving names, and a rebuild of Stage 1
and B1 with new hashes. None of this is proven yet.

## 3. Conclusion

**Survivorship-free historical prices are not feasible on free data.** They are feasible only with a paid source,
which has not been approved, and even then only after a ticker-to-CIK matching project.

## 4. The accepted limitation (owner, 2026-10-16; recorded as D13)

For **exploratory research only**, the programme proceeds on survivor-only prices, with these conditions:

1. Every result states the limitation (`edge_rules.STANDING_LIMITATIONS`, enforced by `require_disclosure`).
2. Every trial reports the missing-price exits and the −100% stress (P6 in `B5_PREREGISTRATION.md`).
3. Large caps decide; mid and small caps stay information only, where the bias is larger.
4. The acceptance does **not** extend to confirmation testing, an E3 claim, demo allocation or any real-money
   decision. Before any of those, the owner decides again: buy survivorship-free data, or accept the limitation
   explicitly for that step.
