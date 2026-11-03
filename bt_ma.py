"""年線進出場回測:收盤 > MA×1.02 連續3天 → 進場;收盤 < MA×0.99 連續3天 → 出場。比較 MA 200/220/240。
訊號在第3天收盤確認,隔天起才持有/空手(避免偷看未來)。空手期報酬 0。指數為價格指數(不含股息),不計手續費。
用法: python bt_ma.py            (抓 Yahoo:日經225 ^N225、韓國 KOSPI ^KS11)
      python bt_ma.py file.csv   (自備 CSV,欄位 Date,Close)"""
import sys, json, urllib.request, pandas as pd, numpy as np
UP, DN, DAYS, MAS = 0.02, 0.01, 3, (200, 220, 240)

def yahoo(sym):
    import time
    for host in ("query1", "query2"):
        # period1/period2 明確指定,避免 range=max 被 Yahoo 自動降成月資料
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2={int(time.time())}&interval=1d&events=history"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            r = json.load(urllib.request.urlopen(req, timeout=60))["chart"]["result"][0]
            s = pd.Series(r["indicators"]["quote"][0]["close"], index=pd.to_datetime(r["timestamp"], unit="s").normalize(), dtype=float)
            s = s[~s.index.duplicated()].dropna()
            gap = s.index.to_series().diff().dt.days.median()
            print(f"{sym}: {len(s)} 筆 {s.index[0]:%Y-%m-%d}~{s.index[-1]:%Y-%m-%d} 中位間隔 {gap} 天")
            if gap <= 4: return s
            print("  資料不是日資料,換下一個主機重試")
        except Exception as e:
            print(f"  {host} 失敗: {e}")
    raise SystemExit(f"{sym} 抓不到日資料")

def streak(f):
    g = (f != f.shift()).cumsum()
    return f.groupby(g).cumsum().where(f, 0)

def run(c, n):
    ma = c.rolling(n).mean()
    buy = streak(c > ma * (1 + UP)) >= DAYS
    sell = streak(c < ma * (1 - DN)) >= DAYS
    pos = np.zeros(len(c)); cur = 0
    for i in range(len(c)):
        if np.isnan(ma.iloc[i]): continue
        if cur == 0 and buy.iloc[i]: cur = 1
        elif cur == 1 and sell.iloc[i]: cur = 0
        pos[i] = cur
    pos = pd.Series(pos, index=c.index).shift(1).fillna(0)           # 隔天才生效
    r = c.pct_change().fillna(0) * pos
    return r, pos

def stats(r, pos, c):
    eq = (1 + r).cumprod(); yrs = (c.index[-1] - c.index[0]).days / 365.25
    dd = (eq / eq.cummax() - 1).min()
    ent = (pos.diff() == 1); ex = (pos.diff() == -1)
    # 每筆交易報酬
    tr = []; e = None
    for d, p in pos.diff().items():
        if p == 1: e = c[d]
        elif p == -1 and e: tr.append(c[d] / e - 1); e = None
    if e: tr.append(c.iloc[-1] / e - 1)
    return dict(總報酬=eq.iloc[-1] - 1, 年化=eq.iloc[-1] ** (1 / yrs) - 1, 最大回撤=dd, 交易次數=int(ent.sum()),
                勝率=(np.mean([t > 0 for t in tr]) if tr else np.nan), 持有時間比=pos.mean(),
                報酬回撤比=(eq.iloc[-1] ** (1 / yrs) - 1) / abs(dd) if dd else np.nan)

def report(name, c, start=None):
    if start: c = c[c.index >= start]
    rows = {}; w = c.index[max(MAS)]                              # 三條均線同一起點(最長均線暖機後)才公平
    cw = c[c.index >= w]
    bh = cw.pct_change().fillna(0); rows["買進持有"] = stats(bh, pd.Series(1.0, index=cw.index), cw)
    for n in MAS:
        r, pos = run(c, n); rows[f"MA{n}"] = stats(r[r.index >= w], pos[pos.index >= w], cw)
    c = cw
    df = pd.DataFrame(rows).T
    print(f"\n===== {name}  {c.index[0]:%Y-%m-%d} ~ {c.index[-1]:%Y-%m-%d} =====")
    f = df.copy()
    for k in ("總報酬", "年化", "最大回撤", "勝率", "持有時間比"): f[k] = (f[k] * 100).map("{:.1f}%".format)
    f["報酬回撤比"] = f["報酬回撤比"].map("{:.2f}".format)
    print(f.to_string())
    return df

if __name__ == "__main__":
    if len(sys.argv) > 1:
        d = pd.read_csv(sys.argv[1]); d.columns = [x.strip() for x in d.columns]
        col = "Close" if "Close" in d.columns else d.columns[1]; c = pd.Series(d[col].astype(float).values, index=pd.to_datetime(d.iloc[:, 0])); sets = {sys.argv[1]: c}
    else:
        sets = {"日經225 ^N225": yahoo("%5EN225"), "韓國 KOSPI ^KS11": yahoo("%5EKS11")}
    out = []
    for name, c in sets.items():
        for start in (None, "2000-01-01", "2010-01-01"):
            cc = c if not start else c[c.index >= start]
            if len(cc) < max(MAS) + 250: print(f"{name} 自{start} 資料不足,略過"); continue
            df = report(name + ("" if not start else f"(自{start[:4]})"), c, start)
            df.insert(0, "區間", name + ("" if not start else f"(自{start[:4]})")); out.append(df)
    pd.concat(out).to_csv("ma_backtest_result.csv", encoding="utf-8-sig")
