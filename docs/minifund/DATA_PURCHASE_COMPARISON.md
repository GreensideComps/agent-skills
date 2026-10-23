# Data-source comparison, checked against vendors' own pages (owner decision D-E)

Owner decision D-E (2026-10-23 10:19Z, `cmsg_01U4KMvkBYNknqm4HRVie8uv964VkQcqvQbBHhfQQbHd8Z`): "YES, research only:
prepare a vendor-source-verified data-purchase comparison. No purchase, subscription, account creation or paid API
activation is authorised."

**Method.** All facts below come from public vendor pages read on 2026-10-23, with no account, sign-up, trial, API
key or contact form. [V] = stated on the vendor's own page as cited. [NS] = the page does not state it.
[U] = could not be read (the page renders its content in the browser), so the fact is unverified. Prices are list
prices on that day, in the vendor's currency, and are not quotes. Licence summaries paraphrase the pages; the
vendor's own terms govern.

## 1. What the research needs

| Need | Why | Stage |
|---|---|---|
| N1 US prices **including delisted** companies | Survivorship bias (D13) blocks Stage 2's exit criterion | 2–3 |
| N2 Point-in-time fundamentals including delisted companies | Cross-check of SEC-derived facts; Check 4 | 2–3 |
| N3 Timestamped news with history from ~2015 | Stage 4 candidates 4–5, after the 8-K baselines | 4 |
| N4 Consensus estimates and revisions | S8, never tested | 3 |
| N5 Licence fit | Personal research by the owner, run in cloud sessions | all |

## 2. Free sources (no purchase needed)

| Source | Covers | Facts | Licence |
|---|---|---|---|
| SEC EDGAR | N2 (as filed), filing events | "Current max request rate: 10 requests/second"; declare a User-Agent with contact email; "Anyone can access and download this information for free" [V: sec.gov, Accessing EDGAR Data] | Free; the SEC "does not allow botnets or automated tools to crawl the site" [V] |
| GDELT | N3 metadata, tone (no article text) | Monitoring "stretches back to January 1, 1979" [V: gdeltproject.org/about]; the 2.0 15-minute data starts Feb 2015 [R: codebook via secondary source] | "unlimited and unrestricted use for any academic, commercial, or governmental use … without fee"; citation and link required [V] |

## 3. Paid vendors

### Norgate Data: N1
- **Packages** [V: norgatedata.com/prices.php]:
  - Silver: 10-year daily history, no delisted;
  - Gold: 20-year, no delisted;
  - **Platinum: back to 1990, delisted included**;
  - Diamond: back to 1950, delisted included.
- **Price:** [NS] on the static page (the calculator is blank). It says "12 month subscriptions enjoy a 10% discount relative to 6 months". "Subscriptions may be taken out for 6 months or 12 (monthly subscriptions are not available)" [V: norgatedata.com]. The ~$630/yr Platinum figure in project notes (14 Oct) is **not re-verified**.
- **Licence:** "can only be licensed for personal use by individuals … There is no alternative business/commercial licensing" [V: faq.php].
- **Delivery:** through the Norgate Data Updater (NDU) application, which "can be installed and used on two machines concurrently". A VM, Cloud PC or VPS install counts [V: faq.php].
- **Fit:** strongest for N1. Delivery needs NDU running on a machine the owner controls, then exporting to the research data folder. That doesn't fit cloud-only sessions directly [A].

### Sharadar (direct): N1, N2
- **Plans** [V: sharadar.com/subscribe], each with monthly / annual prices:

  | Plan | 5 years | 10 years | Full history |
  |---|---|---|---|
  | Fundamentals | $19 / $199 | $29 / $299 | $39 / $399 |
  | Prices | $9 / $99 | $19 / $199 | $39 / $299 |
  | Investors | $19 / $99 | $29 / $199 | $39 / $299 |
  | **Bundle** | $29 / $299 | $49 / $399 | **$69 / $499** ("Full History Bundle is $69/month ($499/year)") |

- **Coverage** [V: sharadar.com, /bundle]:
  - "both active and delisted securities, minimizing survivorship bias";
  - Bundle history from "January 1998" (prices from December 1997);
  - "point-in-time ready";
  - fundamentals for active or delisted common stock on Nasdaq, NYSE and NYSEMKT;
  - tables include actions, events, sp500, insiders and holdings.
- **Licence:** "Subscriptions are subject to the Personal Use License Terms" [V: /subscribe].
- **Fit:** covers N1 and N2 together, US only, from 1998. It is an API/file download, so it suits cloud sessions [A]. Its as-reported (AR) vs restated (MR) handling is now verified in its public docs; `datekey`, delisting returns and cloud-processing rights stay open (`SHARADAR_VALIDATION_CHECKLIST.md`).

### EODHD: N1 (partial), N2, N3
- **Plans** [V: eodhd.com/pricing], monthly / annual:

  | Plan | Price | Contents |
  |---|---|---|
  | Free | $0 | 20 calls/day, 1-year EOD |
  | Historian (EOD All-World) | $19.99 / $199.00 | 30+ years EOD |
  | Active trader | $29.99 / $299.90 | adds intraday |
  | Equity analyst (Fundamentals) | $59.99 / $599.90 | no EOD prices |
  | **ALL-IN-ONE** | **$99.99 / $999.90** | everything |

  News and sentiment are listed as included in every plan.
- **Delisted** [V: eodhd.com/financial-apis/delisted-stock-companies-data-2]: "tens of thousands of symbols". Delisted before 2018: EOD only. After 2018: also fundamentals, dividends and splits.
- **News** [V: news API page]: `date` is "Publication date and time of the article, ISO 8601", for example `+00:00`. The history start is [NS] ("Full history" for paid plans).
- **Licence:** personal and commercial pricing pages are separate. Terms are [NS] on the pricing page. The site disclaimer says data is "not necessarily real-time nor accurate" [V].
- **Fit:**
  - delisted fundamentals before 2018 are missing, so N2 is weaker than Sharadar;
  - news has no stated depth;
  - prices are in dollars on today's page, where project notes from 14 Oct had euros (the earlier figure came from a secondary source).

### Massive (formerly Polygon): N3, prices
- **Stocks plans** [V: massive.com/pricing] ("Individual use"):

  | Plan | Price | History |
  |---|---|---|
  | Basic | $0 | 2 years |
  | **Starter** | **$29/month** | 5 years |
  | Developer | $79 | 10 years |
  | Advanced | $199 | 20+ years ("Non-pros only") |

  Annual billing "Save 20%" (annual prices [NS]). Business plans are on a separate page.
- **News** [V: massive.com/docs/rest/stocks/news]: "Included in all Stocks plans"; records "date back to June 22, 2016". Basic is limited to 2 years; Starter and above have all history. Each article has `published_utc` (RFC 3339, UTC). Updated hourly.
- **Delisted:** [NS] on the pricing page.
- **Fit:** the cheapest verified route to N3 with UTC publication times from mid-2016, which is inside the 2015–2022 exploration window but misses 2015. News licensing terms are [NS] on the docs page.

### Tiingo: N3 (short), prices
- **Plans** [V: tiingo.com/about/pricing]: Starter $0 and Power $30/month, both "Internal Use Only". "$50/month (or $499/year) for internal commercial use".
- **News:** "News API allows 3 Months of queryable history and all data going forward". "For commercial clients who require more history (up to 15 years available)" contact sales [V].
- **Fit:** poor for N3 back-testing at personal prices (3 months of history). Fine only for forward collection.

### Finnhub: N3, N4
- **Pricing and news-history pages:** [U] (rendered in the browser; nothing readable).
- **Not included:** no figures, because nothing could be verified. A secondary source's "from ~$50/month" stays unverified.

### Consensus estimates (N4)
- **Not verified.** No vendor page with a personal price for point-in-time estimate revisions was found in this pass. Institutional sources (for example I/B/E/S) publish no list price. S8 stays untested.

## 4. Summary against the needs

| Need | Best verified option | Cost (list, 23 Oct) | Main caveat |
|---|---|---|---|
| N1 delisted prices | Sharadar Bundle full history, or Norgate Platinum | $499/yr; Norgate price [NS] | Both personal-use only; Norgate needs NDU on an owner machine |
| N2 PIT fundamentals with delisted | Sharadar Bundle (same subscription) | included above | "point-in-time ready" only; as-reported handling unverified |
| N3 news from ~2015 | Massive Starter (from June 2016) | $29/month | Misses 2015; news licence terms not stated |
| N3 free alternative | GDELT (metadata, tone) + SEC 8-K | free | No article text from GDELT |
| N4 estimates | none verified | — | S8 remains untestable |

**No recommendation to buy is made here.** Under O7 and D-E, a purchase case needs a separate owner request. The
cheapest verified way to lift the binding constraint (survivorship bias, N1+N2) would be the Sharadar full-history
bundle at $499 a year. Before any case it needs three checks: its as-reported handling, its personal-use terms for
cloud processing, and a sample comparison against SEC data.

## 5. Open items

- Norgate's current price: read with the site's own calculator (a browser page) or ask the owner to check. No
  contact form is used.
- Finnhub: page unreadable here; needs a browser view.
- For each candidate, the licence must allow processing in cloud sessions and storage of derived data in the
  project folder, and must not need redistribution. Licence texts were summarised, not legally reviewed.
