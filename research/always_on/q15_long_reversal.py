"""Q15 long-term reversal, always-on loop. Prereg: /mnt/project-files/research/always-on/prereg/Q15.md.
`q01_low_vol.portfolio` buys the lowest values, i.e. the biggest long-run losers."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q01_low_vol as q  # noqa: E402


def features():
    df = q.features(q.xs.load()).sort_values(["cik", "month"])
    g = df.groupby("cik")["ret"]

    def comp(k):
        return g.transform(lambda s: (1 + s.shift(1)).rolling(k, min_periods=k).apply(lambda x: x.prod(), raw=True) - 1)
    df["lr36"], df["lr24"], m12 = comp(35), comp(23), comp(11)
    df["lr36_turn"] = df["lr36"].where(m12 > 0)
    return df


if __name__ == "__main__":
    r = q.main(Path(sys.argv[1]), (("Q15a", "lr36"), ("Q15b", "lr24"), ("Q15c", "lr36_turn")), features())
    for k, v in r.items():
        print(k, "ann %.2f%% t %.2f dsr %.3f thirds %s qtr %.2f%% mid %.2f%% c2 %.2f%% lag %.2f%% bull/bear %.1f/%.1f pass %s" % (
            100 * v["T1_main"]["ann"], v["T1_main"]["t_nw"] or 0, v["dsr"],
            [round(100 * t, 1) for t in v["T2_thirds_ann"]], 100 * v["T4_quarterly"]["ann"], 100 * v["T5_mid"]["ann"],
            100 * v["T6_cost2"]["ann"], 100 * v["T6_lag1"]["ann"], 100 * v["T3_bull_ann"], 100 * v["T3_bear_ann"], v["pass"]))
