# Stage 1 research dataset: coverage and survivorship

Data: SEC bulk XBRL (companyfacts, submissions) and Yahoo monthly prices; months to 2026-09.
Built by `python -m equity research-data`; files in the shared project folder `research-data/`.

## Acceptance targets

| Target | Required | Minimum month | Median month | Met |
|---|---:|---:|---:|---|
| Scored US companies a month, 2012 on | 2,000 | 693 | 1,648 | no |
| Scored large caps a month, 2015 on | 300 | 297 | 504 | no |

Scored = filing within 15 months, a USD price of at least $1, a point-in-time market cap of at least $0.3bn, a next-month return and trailing revenue.

## Coverage each January

| Month | Filing | With price | With market cap | Large | Mid | Small | Scored | Scored large |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2010-01 | 478 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2011-01 | 1,515 | 796 | 781 | 221 | 364 | 188 | 298 | 184 |
| 2012-01 | 8,085 | 2,137 | 2,092 | 242 | 413 | 575 | 693 | 208 |
| 2013-01 | 8,830 | 2,287 | 2,247 | 267 | 450 | 588 | 1,063 | 235 |
| 2014-01 | 8,483 | 2,387 | 2,341 | 311 | 512 | 626 | 1,179 | 279 |
| 2015-01 | 8,270 | 2,538 | 2,492 | 347 | 526 | 636 | 1,232 | 318 |
| 2016-01 | 8,051 | 2,658 | 2,600 | 323 | 512 | 695 | 1,249 | 297 |
| 2017-01 | 7,560 | 2,754 | 2,700 | 375 | 588 | 698 | 1,358 | 345 |
| 2018-01 | 7,128 | 2,880 | 2,810 | 439 | 605 | 736 | 1,430 | 400 |
| 2019-01 | 7,337 | 3,079 | 2,999 | 427 | 659 | 769 | 1,491 | 386 |
| 2020-01 | 7,193 | 3,231 | 3,140 | 482 | 665 | 788 | 1,671 | 457 |
| 2021-01 | 7,153 | 3,482 | 3,336 | 553 | 734 | 876 | 1,857 | 525 |
| 2022-01 | 7,949 | 3,946 | 3,806 | 602 | 819 | 990 | 1,945 | 570 |
| 2023-01 | 8,132 | 4,198 | 4,094 | 592 | 818 | 1,038 | 2,092 | 562 |
| 2024-01 | 8,023 | 4,362 | 4,261 | 602 | 812 | 1,002 | 2,071 | 571 |
| 2025-01 | 7,519 | 4,582 | 4,485 | 685 | 832 | 1,059 | 2,174 | 638 |
| 2026-01 | 7,359 | 4,850 | 4,696 | 707 | 876 | 1,145 | 2,286 | 667 |

## Survivorship on the price side

Companies filing with total assets of at least $1bn, and the share of them with a price that month. Companies that later stopped filing (acquired, delisted, bankrupt, deregistered) mostly have no ticker in SEC's data today, so free prices miss them.

| Month | Still filing today: n | with price | Stopped since: n | with price |
|---|---:|---:|---:|---:|
| 2012-01 | 1,193 | 82% | 1,044 | 0% |
| 2015-01 | 1,452 | 82% | 1,107 | 0% |
| 2018-01 | 1,683 | 83% | 871 | 0% |
| 2021-01 | 2,093 | 81% | 611 | 0% |
| 2024-01 | 2,547 | 80% | 302 | 1% |

Operating companies that stopped periodic filing between 2010 and 2025-06-30: 8,998; with a ticker in SEC data today: 117.

Consequence: tests on this dataset include failed and acquired companies in the fundamentals but not in returns, so results are biased toward survivors. The gap is largest in early years, when more of that year's companies have since disappeared. Every Stage 2 result must state this; survivorship-free prices are an owner decision.

## Harness check

Equal-weighted large-band monthly return vs the Ken French US market return, 2012-01 to 2026-08 (176 months): correlation 0.969, mean 13.1% vs 15.2% a year. A correlation near 1 says returns, dates and bands line up; it tests no signal.
