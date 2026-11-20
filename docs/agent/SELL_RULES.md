# When professionals sell, when this system sells, and whether it makes sense

Written 13 Nov 2026 for the owner's question (cmsg_01U4KMvkBYNknqm4HRVie8uvJzLWK1ecccchLDVCtHNzv6). Demo account only.
The live rules are generated from config in [RULES.md](RULES.md); this page explains and judges them.

## 1. When professionals sell

There is no single rule. What a professional sells on depends on why they bought.

| Style | They sell when | Typical holding time |
|---|---|---|
| Long-term fundamental (most stock-picking funds) | the reason they bought is no longer true (thesis broken); the price has reached what they think the business is worth; they find something clearly better for the same money; the position has grown too big (many trim at 4% to 5% of the fund) | 1 to 3 years. Large-blend US funds turn over about 46% of the portfolio a year, so about two years a holding |
| Momentum and trend (trend-following funds, CTAs) | the trend that got them in reverses. The exit is the entry signal flipping, or a trailing stop that follows the price up, usually set by the asset's own volatility and not a fixed percentage. No profit targets: winners run | weeks to months |
| Short-term and event traders | the event has played out (a fixed number of days, the deal closes, the bounce has happened), or a tight stop is hit | hours to weeks |
| Funds as a whole (risk rules) | a holding or sector breaches a size limit; the portfolio drifts from its targets (rebalancing, typically yearly or when 5 points off); a strategy loses more than its drawdown limit and is cut or switched off | continuous |

Three findings from the research matter more than any rule of thumb:

1. **Professionals are measurably bad at selling.** A study of 783 institutional portfolios (2000 to 2016) found
   their buys beat the market but their sells lost to simply selling a random other holding. They sell what has
   moved most, up or down, because it catches their eye, not what has the worst prospects
   ([Akepanidtaworn, Di Mascio, Imas, Schmidt, Journal of Finance 2023](https://nber.org/papers/w29076);
   [summary](https://www.institutionalinvestor.com/article/b1cnb33z8ml9rr/Portfolio-Managers-Are-Good-at-Buying-but-Stink-at-Selling)).
   Private investors do the same thing worse: they sell winners and keep losers
   ([Odean 1998](https://faculty.haas.berkeley.edu/odean/papers/disposition/disposition.html)).
2. **Stops only help when prices trend.** If returns are random, a stop-loss can only cost money; it adds value only
   when falls tend to be followed by more falls ([Kaminski and Lo 2014](https://dspace.mit.edu/handle/1721.1/114876)).
   On momentum stocks a 10% stop cut the worst month from about -50% to about -11%
   ([Han, Zhou, Zhu](https://alphaarchitect.com/2016/08/taming-the-momentum-roller-coaster-fact-or-fiction/)).
   On a stock bought because it fell, a stop sells the rebound.
3. **Trend funds exit on the signal, and rebalancing frequency barely matters.** A century of trend-following data
   uses "the past return turned negative" as the exit
   ([Hurst, Ooi, Pedersen](https://www.TrendFollowing.com/whitepaper/Century_Evidence_Trend_Following.pdf)).
   Vanguard found monthly, quarterly and yearly rebalancing give about the same result, so the cheapest one wins
   ([Vanguard](https://www.vanguard.ca/en/investor/insights/when_and_how_to_rebalance)).

So the professional standard is not "a cleverer stop". It is: decide at the time of buying what would make you sell,
make that the mirror image of why you bought, and do not sell for any other reason.

## 2. When this system sells today

Every sale has a recorded reason, and every open trade gets a daily `exit_review` line saying why it is held and what
will sell it. Nothing is held without a rule that will sell it (the self-check enforces this).

| Strategy | Why it buys | What sells it | Professional equivalent | Makes sense? |
|---|---|---|---|---|
| VWRP core | owns the world market | nothing | index fund | Yes |
| value_timing, momentum_timing | a month-end signal picks one of two funds | the signal names the other fund | trend fund: exit when the signal flips | Yes |
| january_small | calendar | the month ends | event trade | Yes |
| quality_tilt | permanent tilt | only the kill rule | strategic allocation | Yes |
| merger_arb | agreed cash takeover | deal pays out, deal is called off, or -10% | event trade: sell when the event resolves | Yes |
| gap_rebound, news_shock_vix_hi | a stock overreacted to news | a fixed number of trading days (60, 5) | event trade: sell when the bounce window ends | Yes. The holding time is the one tested; shorter, longer and target exits all tested worse or no better |
| buyback_value | cheap company buying back shares | 9 months | value fund's holding period | Yes. 3 months tested much worse, 9 and 12 better than 6 |
| stock_screen | top 15 on quality, value and momentum | a 12-month review, a hard SEC event (bankruptcy, delisting, restatement, takeover) | fundamental fund: re-check the thesis, sell on a broken one | Mostly. One flaw found and fixed today (below) |
| social_trend | attention spike in a consumer brand | attention back to normal, -12%, +25%, 84 days | thesis exit (the reason for buying has gone) | Yes |
| vol_squeeze | breakout from a tight range | -8% or the 20-day low, 28 days, a trailing stop only after +10% | trend trade | **Paused 14 Nov.** Tested: the rule lost 2.0% a year against the same stocks held equally (Q253a). A trailing exit and a volatility stop were no better (Q251a, Q252a) |
| breakout_momentum | up 5% in a day | -5%, +10% target, 5 days | trend trade | **Paused 14 Nov.** Tested: the rule lost 9.0% a year (Q253b). Letting winners run was better by 7.9% a year but still not profitable (Q251b) |
| gap_go | morning gap that holds | first-30-minute low, +6%, end of day | day trade | Standard for the style; untested |
| drop_rebound | down 5% in a day | -8%, +6%, 10 days | bounce trade | Paused since 7 Nov (its closest test lost money) |
| everything with no stop of its own | | a broker stop 30% below the buy price | catastrophe stop | A safety net, not an edge: every tighter stop tested cost money |
| every strategy | | the kill rule: off after 30 closed trades (or 24 months) if it has not beaten VWRP | a fund closing a strategy that does not earn its keep | Yes |
| the book | | 5% cap per name; from December the screener names are reset to equal size monthly | position limits and rebalancing | Yes |

## 3. Does it make sense? The verdict

**Mostly yes, and more than the "time exit" label suggests.** For the rebound and value strategies the exit is the
holding period the idea was tested with, which is exactly what an event or value fund does. The system's record on
this is unusually thorough: 42 alternative sell rules were tested between 3 and 14 Nov (profit targets, profit
locks, thesis-broken exits, trailing and volatility stops, momentum and relative-strength exits, drop-out swaps,
drawdown switches, volatility sizing, trims, averaging down, sell-when-expensive). None beat holding. That matches
finding 1 and 2 above: these are buy-weakness strategies, and every rule that sells weakness sells the rebound.

**Three things did not make sense. All three are now dealt with.**

1. *Fixed 9 Nov:* the screener used to sell a name as soon as it slipped out of the top 15. That was the worst rule
   tested (-2.5% a name-year against holding) and is off.
2. *Fixed today (agent-1.25):* with that rule off, the screener would sell each name at 12 months **even if it was
   still in the top 15**, and buy a lower-ranked one. The tested rule keeps a name that still qualifies. Now a name
   that is still in the top list at 12 months is kept and its clock restarts; only a name that no longer qualifies is
   replaced. This is the professional "would I buy it again today?" test. Nothing had been sold under the old code
   (the oldest holding is from 3 Nov 2026).
3. *Tested and switched off 14 Nov (Q251 to Q253, pre-registered 13 Nov before any data was read):* the two trend
   strategies, vol_squeeze and breakout_momentum, had never been backtested and their exits were the least
   professional in the book. Six tests on 1996 to 2022 daily prices (449 US stocks) found:
   - **The exits were not the real problem. The entries have no edge.** breakout_momentum lost 9.0% a year against
     simply holding the same stocks (t -3.8, negative in every third of the sample): a stock up 5% in a day earns
     nothing extra over the next few days, and about 290 trades a year of fees do the rest. vol_squeeze lost 2.0% a
     year. Both are paused for new buys; open trades keep their exits.
   - **Letting winners run did help the breakout trade**, as the trend-following research says: dropping the +10%
     target and the 5-day limit for a trailing exit at the 10-day low was better by 7.9% a year. It was strong in
     1996 to 2009 and faded after, so it failed the confirmation test (p 0.10), and it only lifts the strategy to
     about -1% a year. It is recorded as the rule to use if the strategy is ever switched back on.
   - A volatility-sized stop (3x ATR) instead of a fixed-percentage stop made no difference on the squeeze trade
     and a small, unconfirmed difference on the breakout trade.
   Full numbers: research results/Q251.md.

**One honest limit.** The earlier sell tests ran on a price panel with no delisted companies, which flatters holding
over selling. For large companies the effect is small (most that vanish are taken over at a premium), but rules that
sell on a broken thesis are the ones most likely to be under-rated. They get re-tested when prices for delisted
companies are added (research item Q250, from 1 Dec).

## 4. What is still open

| Item | When |
|---|---|
| Thesis-broken and stop rules re-tested with delisted companies included | after Q250, December |
| Live check of the two benched rules (monthly equal-size reset, 9-month buyback hold) against their shadows | February 2027 (Q241) |
