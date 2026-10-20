# Share-count exclusion: exploration-period median vs point-in-time median (PR #18 review)

> **Survivorship (material, unbounded; added 2026-10-16 at the owner's request):** companies that delisted before the 2026 price download are missing from the universe entirely. The -30% and -100% missing-price rules do not address them and are not evidence that survivorship bias is bounded.

Large caps, 1-month IC, decisions 2015-01 to 2022-11, Stage 2's scoring, data cut at 2022-12. Registered before running as `QX-PIT-<trial>`; the programme's trial count is now 96.

| Eligible large-cap company-months | Count |
|---|---:|
| No exclusion | 43,216 |
| Approved rule (exploration-period median) | 42,963 |
| Point-in-time rule (expanding median) | 42,868 |
| Eligible under both | 42,848 |

| Rows excluded by one rule only | Company-months | Companies | Median market cap ($bn) | Top sector groups |
|---|---:|---:|---:|---|
| excluded only by period rule | 20 | 6 | 17.3 | instruments_medtech 9, services 6, transport_utilities_telecom 2, chemicals_pharma 2, software_it 1 |
| excluded only by pit rule | 115 | 12 | 20.6 | transport_utilities_telecom 47, chemicals_pharma 35, mining_energy 14, finance 7, other_manufacturing 6 |

| Trial | IC (approved) | t (approved) | IC (point in time) | t (point in time) |
|---|---:|---:|---:|---:|
| S1a | 0.0075 | 0.67 | 0.0074 | 0.67 |
| S1b | -0.0055 | -0.44 | -0.0053 | -0.42 |
| S2a | 0.0126 | 1.12 | 0.0121 | 1.07 |
| S2b | -0.0029 | -0.35 | -0.0027 | -0.33 |
| S3a | -0.0063 | -0.36 | -0.0065 | -0.37 |
| S3b | 0.0136 | 1.41 | 0.0130 | 1.35 |
| S4 | 0.0075 | 0.51 | 0.0074 | 0.51 |
| S5a | 0.0090 | 0.53 | 0.0091 | 0.53 |
| S5b | -0.0067 | -0.47 | -0.0071 | -0.49 |
| S6a | 0.0007 | 0.04 | 0.0005 | 0.03 |
| S6b | 0.0084 | 0.49 | 0.0086 | 0.50 |
| S6c | -0.0146 | -1.17 | -0.0145 | -1.16 |
| S7a | 0.0023 | 0.33 | 0.0024 | 0.34 |
| S7b | 0.0026 | 0.48 | 0.0027 | 0.50 |
| S9 | -0.0027 | -0.15 | -0.0028 | -0.15 |
