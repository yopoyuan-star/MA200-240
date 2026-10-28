"""抓取台股加權指數與美股三大指數,計算 MA ±1% 通道與連續 3 日訊號,輸出 docs/index.html"""
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
BAND, DAYS, YEARS = 0.01, 3, 3


def load(sym):
    df = yf.download(sym, period="6y", interval="1d", auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"].dropna()


def streak(flag):
    """連續為 True 的天數"""
    return flag.groupby((~flag).cumsum()).cumsum()


def analyze(close, n):
    d = pd.DataFrame({"close": close})
    d["ma"] = close.rolling(n).mean()          # 用完整資料算 MA,再截取近三年
    d["up"], d["dn"] = d.ma * (1 + BAND), d.ma * (1 - BAND)
    d["ua"] = streak(d.close > d.up)
    d["ub"] = streak(d.close < d.dn)
    d["signal"] = ""
    d.loc[d.ua == DAYS, "signal"] = "買進"      # 連續第 3 天站上 MA+1%
    d.loc[d.ub == DAYS, "signal"] = "賣出"      # 連續第 3 天跌破 MA-1%
    return d[d.index >= d.index[-1] - pd.DateOffset(years=YEARS)]


def figure(d, title, n):
    f = go.Figure()
    f.add_scatter(x=d.index, y=d.up, name=f"MA{n}+1%", line=dict(color="#d9534f", width=1, dash="dot"))
    f.add_scatter(x=d.index, y=d.dn, name=f"MA{n}-1%", line=dict(color="#2e9e5b", width=1, dash="dot"),
                  fill="tonexty", fillcolor="rgba(150,150,150,0.10)")
    f.add_scatter(x=d.index, y=d.ma, name=f"MA{n}", line=dict(color="#f0ad4e", width=1.6))
    f.add_scatter(x=d.index, y=d.close, name="收盤", line=dict(color="#1f77b4", width=1.6))
    f.update_layout(title=title, height=460, margin=dict(l=50, r=20, t=50, b=30),
                    hovermode="x unified", legend=dict(orientation="h", y=-0.12),
                    template="plotly_white")
    return f


def section(name, d, n, first):
    last = d.iloc[-1]
    dev = (last.close / last.ma - 1) * 100
    if last.ua > 0:
        state = f"已連續 {int(last.ua)} 天站上 MA+1%"
    elif last.ub > 0:
        state = f"已連續 {int(last.ub)} 天跌破 MA-1%"
    else:
        state = "位於 ±1% 通道內"
    sigs = d[d.signal != ""].iloc[::-1]
    rows = "".join(
        f"<tr class='{'buy' if r.signal == '買進' else 'sell'}'><td>{i:%Y-%m-%d}</td>"
        f"<td>{r.signal}</td><td>{r.close:,.2f}</td><td>{r.ma:,.2f}</td></tr>"
        for i, r in sigs.iterrows()) or "<tr><td colspan=4>近三年無訊號</td></tr>"
    chart = figure(d, f"{name}(MA{n} ±1%)", n).to_html(
        full_html=False, include_plotlyjs="cdn" if first else False)
    return f"""<section><h2>{name}</h2>
<div class='status'>{d.index[-1]:%Y-%m-%d} 收盤 {last.close:,.2f}|MA{n} {last.ma:,.2f}|乖離 {dev:+.2f}%|<b>{state}</b></div>
{chart}
<details open><summary>買賣訊號(共 {len(sigs)} 筆,新到舊)</summary>
<table><tr><th>日期</th><th>訊號</th><th>收盤</th><th>MA</th></tr>{rows}</table></details></section>"""


def main():
    secs = []
    for i, (name, sym, n) in enumerate(INDICES):
        secs.append(section(name, analyze(load(sym), n), n, i == 0))
    now = datetime.now(timezone(timedelta(hours=8)))
    page = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>指數 MA 通道與訊號</title>
<style>body{{font-family:system-ui,"Noto Sans TC",sans-serif;max-width:1100px;margin:0 auto;padding:16px;color:#222}}
section{{margin-bottom:40px}}.status{{background:#f4f6f8;padding:8px 12px;border-radius:6px;font-size:14px}}
table{{border-collapse:collapse;width:100%;font-size:14px;margin-top:8px}}th,td{{padding:5px 10px;border-bottom:1px solid #e3e3e3;text-align:right}}
th:first-child,td:first-child{{text-align:left}}tr.buy td:nth-child(2){{color:#d9534f;font-weight:700}}
tr.sell td:nth-child(2){{color:#2e9e5b;font-weight:700}}summary{{cursor:pointer;margin-top:8px;font-weight:600}}
@media(prefers-color-scheme:dark){{body{{background:#14161a;color:#e6e6e6}}.status{{background:#22262d}}td,th{{border-color:#333}}}}</style></head>
<body><h1>指數 MA 通道與買賣訊號</h1>
<p>規則:收盤連續 3 天高於 MA×1.01 → 買進;連續 3 天低於 MA×0.99 → 賣出(於第 3 天觸發一次)。台股 MA200,美股 MA240。<br>
更新時間:{now:%Y-%m-%d %H:%M}(台北時間)|資料來源:Yahoo Finance|僅供參考,非投資建議。</p>
{''.join(secs)}</body></html>"""
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    main()
