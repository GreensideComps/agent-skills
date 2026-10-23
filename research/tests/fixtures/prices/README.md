# Price fixtures (synthetic)

Hand-written for `research/tests/test_price_provenance.py` (mini fund Stage 2 §2). **Nothing here was downloaded.**
The files follow the shape of a Yahoo chart v8 response for a fictional ticker `SYN` with five sessions to
2022-12-30 and a 1-for-10 reverse split on 2022-12-29 (split-adjusted closes 10.0 to 13.5; actual pre-split prices
1.00 to 1.20).

| File | Case |
|---|---|
| chart_SYN_pull1.json | first pull, split event included |
| chart_SYN_pull2_dividend.json | later pull: adjclose of the two earliest sessions scaled by 0.99 (a dividend) |
| chart_SYN_pull3_unexplained.json | later pull: one close changed on its own |
| chart_SYN_with_2023.json | contains a 2023 bar (must be refused) |
| chart_SYN_no_tz.json | no exchange time zone (must be refused) |
| sessions_synthetic.csv | a three-row session calendar; the 13:00 close on 2022-12-23 is invented to test the early-close path |
| manifest_copy_2026-10-23.json | an exact copy of `research-data/edge/manifest.json` as of 2026-10-23 (metadata only), to prove existing entries survive an addition |
