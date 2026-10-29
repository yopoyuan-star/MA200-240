"""抓取台股加權指數與美股三大指數,計算 MA 通道(進場 +2%、出場 -1%)與連續 3 日訊號,輸出 docs/index.html"""
import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go

# (名稱, Yahoo 代號, MA 天數)
INDICES = [
    ("台股加權指數 TAIEX", "^TWII", 200),
    ("道瓊工業指數 DJIA", "^DJI", 240),
    ("S&P 500", "^GSPC", 240),
    ("那斯達克綜合指數 NASDAQ", "^IXIC", 240),
]
UP_BAND, DN_BAND = 0.02, 0.01   # 進場:高於 MA+2%;出場:低於 MA-1%
DAYS, YEARS = 3, 3


def load(sym):
    """Yahoo 日線 OHLC(未還原)"""
    df = yf.download(sym, period="6y", interval="1d", auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    idx = pd.DatetimeIndex(df.index)
    df.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    return df[(df > 0).all(axis=1)]


TWSE_URLS = ["https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={d}&response=json",
             "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?response=json&date={d}"]


def twse_ohlc(months=3):
    """證交所加權指數每日開高低收(最近 months 個月);失敗回傳空表"""
    now = datetime.now(timezone(timedelta(hours=8)))
    first, parts = now.replace(day=1), []
    try:
        for k in range(months):
            dt = (first - timedelta(days=31 * k)).replace(day=1)
            js = None
            for u in TWSE_URLS:
                try:
                    req = urllib.request.Request(u.format(d=f"{dt:%Y%m}01"), headers={"User-Agent": "Mozilla/5.0"})
                    js = json.load(urllib.request.urlopen(req, timeout=30))
                    break
                except Exception as e:
                    err = e
            if js is None:
                raise RuntimeError(err)
            if js.get("stat") != "OK" or not js.get("data"):
                continue
            f = js["fields"]
            col = lambda key: next(i for i, n in enumerate(f) if key in n)
            ci, co, ch, cl, cc = col("日期"), col("開盤"), col("最高"), col("最低"), col("收盤")
            num = lambda v: float(str(v).replace(",", ""))
            rows = {}
            for r in js["data"]:
                y, m, d = str(r[ci]).strip().split("/")                      # 民國年 115/10/28
                rows[pd.Timestamp(int(y) + 1911, int(m), int(d))] = (num(r[co]), num(r[ch]), num(r[cl]), num(r[cc]))
            parts.append(pd.DataFrame.from_dict(rows, orient="index", columns=["Open", "High", "Low", "Close"]))
        if not parts:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close"])
        out = pd.concat(parts).sort_index()
        out = out[~out.index.duplicated(keep="last")]
        return out[(out > 0).all(axis=1) & (out.High >= out.Low)]
    except Exception as e:
        print("證交所抓取失敗(改用 Yahoo):", e)
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])


def streak(flag):
    """連續為 True 的天數"""
    return flag.groupby((~flag).cumsum()).cumsum()


def analyze(close, n):
    d = pd.DataFrame({"close": close})
    d["ma"] = close.rolling(n).mean()          # 用完整資料算 MA,再截取近三年
    d["up"], d["dn"] = d.ma * (1 + UP_BAND), d.ma * (1 - DN_BAND)
    d["ua"] = streak(d.close > d.up)
    d["ub"] = streak(d.close < d.dn)
    d["signal"] = ""
    d.loc[d.ua == DAYS, "signal"] = "買進"      # 連續第 3 天站上 MA+2%
    d.loc[d.ub == DAYS, "signal"] = "賣出"      # 連續第 3 天跌破 MA-1%
    return d[d.index >= d.index[-1] - pd.DateOffset(years=YEARS)]


def figure(d, title, n):
    f = go.Figure()
    f.add_scatter(x=d.index, y=d.up, name=f"MA{n}+{UP_BAND:.0%}", line=dict(color="#d9534f", width=1, dash="dot"))
    f.add_scatter(x=d.index, y=d.dn, name=f"MA{n}-{DN_BAND:.0%}", line=dict(color="#2e9e5b", width=1, dash="dot"),
                  fill="tonexty", fillcolor="rgba(150,150,150,0.10)")
    f.add_scatter(x=d.index, y=d.ma, name=f"MA{n}", line=dict(color="#f0ad4e", width=1.6))
    f.add_scatter(x=d.index, y=d.close, name="收盤", line=dict(color="#1f77b4", width=1.6))
    f.update_layout(title=title, height=460, margin=dict(l=50, r=20, t=50, b=30),
                    hovermode="x unified", legend=dict(orientation="h", y=-0.12),
                    template="plotly_white")
    return f


def section(name, d, n, first, ohlc, src):
    last = d.iloc[-1]
    dev = (last.close / last.ma - 1) * 100
    if last.ua > 0:
        state = f"已連續 {int(last.ua)} 天站上 MA+{UP_BAND:.0%}"
    elif last.ub > 0:
        state = f"已連續 {int(last.ub)} 天跌破 MA-{DN_BAND:.0%}"
    else:
        state = f"位於 MA-{DN_BAND:.0%} ~ MA+{UP_BAND:.0%} 通道內"
    sigs = d[d.signal != ""].iloc[::-1]
    rows = "".join(
        f"<tr class='{'buy' if r.signal == '買進' else 'sell'}'><td>{i:%Y-%m-%d}</td>"
        f"<td>{r.signal}</td><td>{r.close:,.2f}</td><td>{r.ma:,.2f}</td></tr>"
        for i, r in sigs.iterrows()) or "<tr><td colspan=4>近三年無訊號</td></tr>"
    o_rows = "".join(f"<tr><td>{i:%Y-%m-%d}</td><td>{r.Open:,.2f}</td><td>{r.High:,.2f}</td><td>{r.Low:,.2f}</td><td>{r.Close:,.2f}</td></tr>"
                     for i, r in ohlc.tail(7).iterrows())
    chart = figure(d, f"{name}(MA{n} +{UP_BAND:.0%} / -{DN_BAND:.0%})", n).to_html(
        full_html=False, include_plotlyjs="cdn" if first else False)
    return f"""<section><h2>{name}</h2>
<div class='status'>{d.index[-1]:%Y-%m-%d} 收盤 {last.close:,.2f}|MA{n} {last.ma:,.2f}|乖離 {dev:+.2f}%|<b>{state}</b></div>
{chart}
<details open><summary>買賣訊號(共 {len(sigs)} 筆,新到舊)</summary>
<table><tr><th>日期</th><th>訊號</th><th>收盤</th><th>MA</th></tr>{rows}</table></details>
<h3>近 7 個交易日 開高低收(由舊到新|資料來源:{src})</h3>
<table><tr><th>日期</th><th>開盤</th><th>最高</th><th>最低</th><th>收盤</th></tr>{o_rows}</table></section>"""


def summary_row(name, d, n):
    last = d.iloc[-1]
    state = (f"連續 {int(last.ua)} 天站上 MA+{UP_BAND:.0%}" if last.ua > 0 else
             f"連續 {int(last.ub)} 天跌破 MA-{DN_BAND:.0%}" if last.ub > 0 else "通道內")
    sigs = d[d.signal != ""]
    if len(sigs):
        t, r = sigs.index[-1], sigs.iloc[-1]
        cls = "buy" if r.signal == "買進" else "sell"
        new = "(今日新訊號)" if t == d.index[-1] else ""
        sig = f"<td class='{cls}'>{r.signal}</td><td>{t:%Y-%m-%d}{new}</td>"
    else:
        sig = "<td>—</td><td>近三年無訊號</td>"
    return (f"<tr><td>{name}</td><td>{d.index[-1]:%Y-%m-%d}</td><td>{last.close:,.2f}</td><td>MA{n} {last.ma:,.2f}</td>"
            f"<td>{(last.close / last.ma - 1) * 100:+.2f}%</td><td>{state}</td>{sig}</tr>")


def main():
    secs, summ = [], []
    for i, (name, sym, n) in enumerate(INDICES):
        ohlc, src = load(sym), "Yahoo Finance"
        if sym == "^TWII":                                   # 台股以證交所為主:證交所有的日期一律覆蓋 Yahoo
            tw = twse_ohlc()
            if len(tw):
                ohlc = pd.concat([ohlc[~ohlc.index.isin(tw.index)], tw]).sort_index()
                src = "臺灣證券交易所"
                print("證交所資料:", f"{tw.index[0]:%Y-%m-%d} ~ {tw.index[-1]:%Y-%m-%d}")
        d = analyze(ohlc["Close"], n)
        summ.append(summary_row(name, d, n))
        secs.append(section(name, d, n, i == 0, ohlc, src))
    now = datetime.now(timezone(timedelta(hours=8)))
    page = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>指數 MA 通道與訊號</title>
<style>body{{font-family:system-ui,"Noto Sans TC",sans-serif;max-width:1100px;margin:0 auto;padding:16px;color:#222}}
section{{margin-bottom:40px}}.status{{background:#f4f6f8;padding:8px 12px;border-radius:6px;font-size:14px}}
table{{border-collapse:collapse;width:100%;font-size:14px;margin-top:8px}}th,td{{padding:5px 10px;border-bottom:1px solid #e3e3e3;text-align:right}}
th:first-child,td:first-child{{text-align:left}}tr.buy td:nth-child(2){{color:#d9534f;font-weight:700}}
tr.sell td:nth-child(2){{color:#2e9e5b;font-weight:700}}h3{{margin:18px 0 0;font-size:15px}}.sum td.buy{{color:#d9534f;font-weight:700}}.sum td.sell{{color:#2e9e5b;font-weight:700}}.sum td:nth-child(n+6){{text-align:left}}summary{{cursor:pointer;margin-top:8px;font-weight:600}}
@media(prefers-color-scheme:dark){{body{{background:#14161a;color:#e6e6e6}}.status{{background:#22262d}}td,th{{border-color:#333}}}}</style></head>
<body><h1>指數 MA 通道與買賣訊號</h1>
<h2>最新匯總</h2>
<table class=sum><tr><th>指數</th><th>日期</th><th>收盤</th><th>MA</th><th>乖離</th><th>目前狀態</th><th>最近訊號</th><th>訊號日期</th></tr>{''.join(summ)}</table>
<p>規則:收盤連續 3 天高於 MA×{1 + UP_BAND:.2f} → 買進;連續 3 天低於 MA×{1 - DN_BAND:.2f} → 賣出(於第 3 天觸發一次)。台股 MA200,美股 MA240。<br>
更新時間:{now:%Y-%m-%d %H:%M}(台北時間)|資料來源:台股為臺灣證券交易所(近 3 個月)搭配 Yahoo 歷史資料,美股為 Yahoo Finance|僅供參考,非投資建議。</p>
{''.join(secs)}</body></html>"""
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    main()
