"""Q230: screener factor design over 60 years (prereg /mnt/project-files/research/always-on/prereg/Q230.md)."""
import math, json, sys
F = "/mnt/project-files/research-data/french/"
END = "202212"


def block(path, col):
    """First monthly block (value-weighted) of a KF csv -> {yyyymm: return}."""
    out, hdr, on = {}, None, False
    for line in open(path, errors="replace"):
        s = line.strip()
        if not on:
            if s.startswith(","):
                hdr = [h.strip() for h in s.split(",")]
                on = True
            continue
        parts = [p.strip() for p in s.split(",")]
        if not parts[0].isdigit() or len(parts[0]) != 6:
            break
        v = float(parts[hdr.index(col)])
        if v > -99:
            out[parts[0]] = v / 100
    return out


op = block(F + "Portfolios_Formed_on_OP.csv", "Hi 20")
bm = block(F + "Portfolios_Formed_on_BE-ME.csv", "Hi 20")
mo = block(F + "10_Portfolios_Prior_12_2.csv", "Hi PRIOR")
mk = block(F + "F-F_Research_Data_Factors.csv", "Mkt-RF")
rf = block(F + "F-F_Research_Data_Factors.csv", "RF")
hml = block(F + "F-F_Research_Data_Factors.csv", "HML")
smb = block(F + "F-F_Research_Data_Factors.csv", "SMB")
months = sorted(m for m in op if m in bm and m in mo and m in mk and "196307" <= m <= END)
mkt = {m: mk[m] + rf[m] for m in months}


def series(legs, cost=0.005):
    return {m: sum(l[m] for l in legs) / len(legs) - mkt[m] - cost / 12 for m in months}


def stats(s, ms=None):
    x = [s[m] for m in (ms or months)]
    n = len(x); mu = sum(x) / n
    d = [v - mu for v in x]
    g0 = sum(v * v for v in d) / n
    lr = g0 + 2 * sum((1 - L / 7) * sum(d[i] * d[i - L] for i in range(L, n)) / n for L in range(1, 7))
    t = mu / math.sqrt(lr / n) if lr > 0 else 0
    return {"months": n, "ann": round(mu * 12, 4), "t_nw": round(t, 2), "sr_m": round(mu / math.sqrt(g0), 4)}


def ols_alpha(y, xs):
    # y = a + b'x ; returns (alpha_ann, t_alpha) with plain OLS se
    import numpy as np
    Y = np.array([y[m] for m in months]); X = np.column_stack([np.ones(len(months))] + [[x[m] for m in months] for x in xs])
    b, *_ = np.linalg.lstsq(X, Y, rcond=None)
    e = Y - X @ b; s2 = e @ e / (len(Y) - X.shape[1]); cov = s2 * np.linalg.inv(X.T @ X)
    return round(b[0] * 12, 4), round(b[0] / math.sqrt(cov[0, 0]), 2)


blend = series([op, bm, mo])
third = len(months) // 3
yrs = sorted({m[:4] for m in months})
mkt_year = {y: math.prod(1 + mkt[m] for m in months if m[:4] == y) - 1 for y in yrs}
res = {
    "period": f"{months[0]}-{months[-1]}",
    "V1_full": stats(blend),
    "V2_thirds": [stats(blend, months[i * third:(i + 1) * third if i < 2 else None]) for i in range(3)],
    "V3_2007_22": stats(blend, [m for m in months if m >= "200701"]),
    "V4_up_years": stats(blend, [m for m in months if mkt_year[m[:4]] > 0]),
    "V4_down_years": stats(blend, [m for m in months if mkt_year[m[:4]] <= 0]),
    "V5_legs": {"op": stats(series([op])), "value": stats(series([bm])), "mom": stats(series([mo])), "op+value": stats(series([op, bm]))},
    "V5_legs_2007_22": {k: stats(series([l]), [m for m in months if m >= "200701"]) for k, l in (("op", op), ("value", bm), ("mom", mo))},
    "V6_cost2": stats(series([op, bm, mo], 0.01)),
}
exret = {m: sum(l[m] for l in (op, bm, mo)) / 3 - rf[m] - 0.005 / 12 for m in months}
res["V7_ff3_alpha"] = ols_alpha(exret, [mk, smb, hml])
v1, v3 = res["V1_full"], res["V3_2007_22"]
res["valid"] = v1["ann"] > 0 and v1["t_nw"] >= 3.0 and v3["ann"] > 0 and sum(s["ann"] > 0 for s in res["V2_thirds"]) >= 2
print(json.dumps(res, indent=1))
