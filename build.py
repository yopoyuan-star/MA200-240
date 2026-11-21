"""每日更新:證交所開高低收 → 480天Z-SCORE 模型 + 日/週/月動態 KD → docs/zscore.html、docs/zscore_output.csv"""
import os
import re
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import model
import usma
import fx
import inst
from fetch_twse import update_data, TPE

PAGE_URL = "https://yopoyuan-star.github.io/Z-score/zscore.html"
CSV, OUT_HTML, OUT_CSV = "data/taiex.csv", "docs/zscore.html", "docs/zscore_output.csv"
TABLE_DAYS, CHART_DAYS, CSV_DAYS = 200, 750, 300
pct = lambda v: "" if pd.isna(v) else f"{v:+.1%}"
num = lambda v, n=2: "" if pd.isna(v) else f"{v:,.{n}f}"


def fmt(v):
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.2f}"


def today_marks(last):
    """最新交易日的垂直虛線與「最新」標籤"""
    x = last.to_pydatetime()
    return dict(shapes=[dict(type="line", xref="x", yref="paper", x0=x, x1=x, y0=0, y1=1, line=dict(color="#888", width=1, dash="dot"))],
                annotations=[dict(x=x, xref="x", y=1, yref="paper", text=f"最新 {last:%m-%d}", showarrow=False, yanchor="bottom", font=dict(size=11, color="#888"))])


def chart(df, cols, title, h=400, first=False):
    f = go.Figure()
    last = df.index[-1]
    for name, color, w, dash in cols:
        f.add_scatter(x=df.index, y=df[name], name=name, line=dict(color=color, width=w, dash=dash))
    for name, color, w, dash in cols:                       # 最新一天:圓點 + 數值
        v = df[name].iloc[-1]
        if pd.notna(v):
            f.add_scatter(x=[last], y=[v], name=name, mode="markers+text", text=[fmt(v)], textposition="middle left",
                          marker=dict(color=color, size=7), textfont=dict(color=color, size=11), showlegend=False, hoverinfo="skip")
    f.update_layout(title=title, height=h, template="plotly_white", hovermode="x unified",
                    margin=dict(l=50, r=20, t=50, b=30), legend=dict(orientation="h", y=-0.12), **today_marks(last))
    return f.to_html(full_html=False, include_plotlyjs="cdn" if first else False)


UP_BAND, DN_BAND, DAYS, YEARS = 0.02, 0.015, 1, 3     # DAYS=1:收盤一站上 +2% / 跌破 −1.5% 當天就是訊號,隔天收盤買賣(2026-11 回測:當天優於連 3 天;−1.5% 各期間不輸 −1% 且交易較少)


def streak(flag):
    return flag.groupby((~flag).cumsum()).cumsum()


SLOPE_DAYS, FLAT = 20, 0.005     # MA220 方向:與 20 個交易日前比,> +0.5% 上彎、< −0.5% 下彎、其餘走平


def ma_trend(ma):
    """回傳 (文字, 顏色, 說明);ma = 220 日均線序列"""
    s = ma.dropna()
    if len(s) <= SLOPE_DAYS:
        return "", "#888", ""
    sl = s.iloc[-1] / s.iloc[-1 - SLOPE_DAYS] - 1
    txt, col = ("↗上彎", "#d9534f") if sl > FLAT else ("↘下彎", "#2e9e5b") if sl < -FLAT else ("→走平", "#888")
    return txt, col, f"MA220 近 {SLOPE_DAYS} 個交易日 {sl * 100:+.2f}%"


def cross_run(states):
    """目前黃金/死亡交叉已連續幾個交易日(含今天);回傳 (天數, 是否到資料上限)"""
    v = list(states)
    if not v or not v[-1]:
        return 0, False
    n = 0
    for x in reversed(v):
        if x != v[-1]:
            return n, False
        n += 1
    return n, True


JS2 = r"""
(function(){var i=document.getElementById('cpx'),c=document.getElementById('ccap');if(!i||!c)return;
function f(v){var d=v>=1000?0:2;return v.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});}
function u(){var v=parseFloat(i.value),k=parseFloat(c.value);for(var p=5;p<=60;p+=5){var e=document.getElementById('cx'+p),q=document.getElementById('cs'+p);var px=(v>0)?v*(1-p/100):0;
if(e)e.textContent=px>0?f(px):'—';if(q)q.textContent=(px>0&&k>0)?Math.floor(k/px).toLocaleString('en-US'):'—';}
}
function sv(){try{localStorage.setItem('zs_cpx',i.value);localStorage.setItem('zs_cap',c.value);}catch(x){}}
try{var s=localStorage.getItem('zs_cpx');if(s)i.value=s;var t=localStorage.getItem('zs_cap');if(t)c.value=t;}catch(x){}
i.addEventListener('input',function(){u();sv();});c.addEventListener('input',function(){u();sv();});u();})();
(function(){var y=document.getElementById('cpy');if(!y)return;
function f(v){var d=v>=1000?0:2;return v.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});}
function u(){var v=parseFloat(y.value);for(var p=2;p<=20;p+=2){var e=document.getElementById('cy'+p);if(e)e.textContent=(v>0)?f(v*(1-p/100)):'—';}}
try{var s=localStorage.getItem('zs_cpy');if(s)y.value=s;}catch(x){}
y.addEventListener('input',function(){u();try{localStorage.setItem('zs_cpy',y.value);}catch(x){}});u();})();
(function(){var h=document.getElementById('cph');if(!h)return;
function f(v){var d=v>=1000?0:2;return v.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});}
function u(){var v=parseFloat(h.value);for(var p=10;p<=80;p+=10){var e=document.getElementById('ch'+p);if(e)e.textContent=(v>0)?f(v*(1-p/100)):'—';}}
try{var s=localStorage.getItem('zs_cph');if(s)h.value=s;}catch(x){}
h.addEventListener('input',function(){u();try{localStorage.setItem('zs_cph',h.value);}catch(x){}});u();})();

(function(){var t=document.getElementById('zmemo'),b=document.getElementById('zmemoclr'),K='zs_memo';
if(!t)return;try{t.value=localStorage.getItem(K)||''}catch(e){}
t.addEventListener('input',function(){try{localStorage.setItem(K,t.value)}catch(e){}});
b.addEventListener('click',function(){if(t.value&&!window.confirm('確定清除筆記?'))return;t.value='';try{localStorage.removeItem(K)}catch(e){}});})();
"""


def ma200_state(m):
    """220 日線狀態:BUY=收盤>MA220×1.02、SELL=收盤<MA220×0.985(單日狀態);DAYS 天(目前 1 天,當天收盤確認)即為『訊號』。
    回傳 (BUY/SELL/—, 連續天數, 說明, 今天是否剛好第 3 天)"""
    c, ma = m["台股收盤價"], m["220日均線"]
    ua, ub = streak(c > ma * (1 + UP_BAND)), streak(c < ma * (1 - DN_BAND))
    for lab, st, word, sig in (("BUY", ua, f"站上 MA220+{UP_BAND * 100:g}%", "買進"), ("SELL", ub, f"跌破 MA220−{DN_BAND * 100:g}%", "賣出")):
        n = int(st.iloc[-1])
        if n > 0:
            if n < DAYS:
                note = f"已連續 {n} 天{word}|再 {DAYS - n} 天確認{sig}訊號"
            elif n == DAYS:
                note = (f"今日收盤{word}|★{sig}訊號,隔天收盤{sig}" if DAYS == 1 else f"已連續 {n} 天{word}|★今日{sig}訊號(第 {DAYS} 天)")
            else:
                d3 = st[st == DAYS].index[-1]
                note = f"已連續 {n} 天{word}|{sig}訊號發出日 {d3:%Y-%m-%d}"
            return lab, n, note, n == DAYS
    return "—", 0, f"介於 MA220−{DN_BAND * 100:g}% ~ +{UP_BAND * 100:g}% 之間", False


def warn_state(m, extra=()):
    """過熱轉弱警示:Z 向上穿越 model.SEG_RESET_Z(0.5)起算一段,六條件同時成立 = 6/6。
    (原本是「Z 由負翻正」起算;回測顯示 Z 過熱後不一定會跌破 0,但近 25 年都會跌破 0.5)
    1 本段 Z 曾 >1.5;2 本段前 9 欄(5>10…80>90)曾同時全 BUY;3 現在 BUY 數 <=3;4 週KD、月KD 皆死亡交叉;5 本段 5 年線乖離率曾 >15%;6 本段 90>120、120>150、150>180 三欄曾同時全 BUY。
    Z<=0 的日子不計入統計、也不會觸發 6/6;但不會清掉本段已成立的條件,要等 Z 再次向上穿越 0.5 才重新統計。
    備用重算:加權指數跌破 220 日線至少 20 個交易日後再站回,也開始新的一段(以防 Z 沒跌破 0.5;回測 25 年不影響任何進出)。
    買回重算(extra):右側全部買回的那一天也開始新的一段,過熱條件從頭累積(台股大漲時不必等 Z 或 MA220;回測 25 年不影響任何進出)。"""
    z = m["Z-SCORE"]
    x = model.SEG_RESET_Z
    cnt = sum((m[c] == "BUY").astype(int) for c in XCOLS[:9])
    zup = (z > x) & (z.shift() <= x)                                # 向上穿越 0.5 → 新的一段
    c_, ma_ = m["台股收盤價"], m[f"{model.SEG_MA}日均線"]
    below = c_ < ma_
    run = below.astype(int).groupby((~below).cumsum()).cumsum()     # 連續在 220 日線下的天數
    maup = (~below) & below.shift(fill_value=False) & (run.shift(fill_value=0) >= model.SEG_MA_MIN_BELOW)  # 跌破 ≥20 天後站回
    ext = pd.Series(m.index.isin(list(extra)), index=m.index)       # 全部買回日 → 新的一段
    up = zup | maup | ext
    sid = up.cumsum()
    live = (z > 0) & (sid > 0)                                      # Z<=0 期間不計
    seg = lambda f: (f & live).astype(int).groupby(sid).cummax().astype(bool) & live
    c = [seg(z > 1.5), seg(cnt == 9), cnt <= 3, (m["週KD"] == "死亡交叉") & (m["月KD"] == "死亡交叉"), seg(m["5年線乖離%"] > 0.15),
         seg((m[XCOLS[9]] == "BUY") & (m[XCOLS[10]] == "BUY") & (m[XCOLS[11]] == "BUY"))]
    allok = c[0] & c[1] & c[2] & c[3] & c[4] & c[5] & live
    now_ok = [bool(v.iloc[-1]) for v in c]
    first = start = None
    start_by_ma = None
    if live.iloc[-1]:
        start = up[up].index[-1]                                    # 本段起點:最近一次 Z 上穿 0.5、站回 220 日線或全部買回
        start_by_ma = ("buy" if bool(ext.loc[start]) else "ma" if bool(maup.loc[start]) and not bool(zup.loc[start]) else "z")
        cur = allok & (sid == sid.iloc[-1])
        first = cur[cur].index[0] if cur.any() else None            # 本段第一次 6/6 的日期
    return now_ok, first, (start, start_by_ma), allok, sid


# ===== 買賣規則(2026-11 回測定案,G1 版)=====
LEFT = [(0.10, 0.05), (0.15, 0.075), (0.20, 0.10), (0.25, 0.125), (0.30, 0.15)]   # 舊版:距一年高點跌幅 → 加碼比例(2026-11-20 以前的轉出循環沿用)
# 2026-11-21 起左側改看 MA220 乖離:收盤 ≤ MA220×(1−x) → 左側補到 t(累計,占總資金,左側合計 50%)
LEFT_MA = [(0.15, 0.15), (0.20, 0.30), (0.30, 0.50)]   # 乖離 −15% 買 15%、−20% 再買 15%、−30% 再買 20%(2026-11 回測優於 −25%)
LEFT_CUT = pd.Timestamp("1900-01-01")                # 2026-11-20 起全部改用 MA220 乖離規則(含目前這一輪,不保留舊規則買進的部位)
HALF_Z, ARM_DD, BACKUP_DAYS, STOP_DD = -2.5, 0.20, 252, 0.20
# 保險 B(MA220,與 A 並行,任一成立就轉出;2026-11 回測 D 版):全部買回後曾站上 MA220,之後
#   收盤 < MA220×0.99(當天)且 MA220 比 20 個交易日前低 0.5% 以上 → 轉出;轉出後連 3 天收盤站回 MA220 → 全部買回(不等 KD)
INS_DAYS, INS_BAND, INS_SLOPE = 3, 0.01, -0.005
INS_SELL_DAYS = 1      # 保險 B 賣出:收盤 < MA220×0.99 當天(+年線下彎)即成立;買回仍需連 INS_DAYS 天站回 MA220(2026-11 回測)
# ④ 左側停損(2026-11):收盤跌破左側已買部位平均成本 15% → 左側全部賣出,本次循環不再做左側,只等右側全部買回
#   回測 2006~2026:近 20 年回撤 −31.8% → −22.5%,年化 16.8% → 16.9%(只在 2008/9 觸發一次)
LEFT_STOP = 0.15
# 左側:Z<-2.5 時直接補到 50%;右側先決:Z≤0 或距一年高點跌 20% 或轉出滿 252 個交易日 → 已收完月K KD 金叉全部買回
# 保險 A(2026-11 改為移動停損):全部買回後收盤 ≤ 買回以來最高收盤 ×0.8 → 轉出
# 保險 A 或 B 轉出後:一律連 3 天收盤站回 MA220 → 全部買回(不等 KD);回測 2000~今 年化 12.5%、回撤 −46%(原規則 11.3%、−64%)


# 一般股災(2011/2015/2018/2020/2022/2025,剔除 2000/2008):高點=最高收盤,低點=之後的最低價(盤中)
# 平均與標準差每次建置時用完整歷史重算;抓不到資料時用下面的備用值
CRASH_AVG = {"台股": (0.265, 0.052), "那斯達克": (0.252, 0.070), "費半": (0.339, 0.083), "S&P 500": (0.219, 0.069), "道瓊": (0.209, 0.083)}   # 顯示順序固定
CRASH_WIN = [("2011-01-01", "2011-12-31"), ("2015-03-01", "2016-03-31"), ("2018-01-01", "2019-01-31"),
             ("2020-01-01", "2020-06-30"), ("2021-11-01", "2023-03-31"), ("2024-12-01", "2025-06-30")]
CRASH_DD = {}   # 本波跌幅(落底指標共用)
CRASH_SYM = {"道瓊": "%5EDJI", "S&P 500": "%5EGSPC", "那斯達克": "%5EIXIC", "費半": "%5ESOX"}


def yahoo_hl(sym, retries=2, start=946684800, min_len=1000):
    """Yahoo 日線(2000 年起)的最低價與收盤價"""
    import json, time, urllib.request
    for _ in range(retries + 1):
        for host in ("query1", "query2"):
            try:
                url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?period1={start}&period2={int(time.time()) + 86400}&interval=1d"
                r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30))["chart"]["result"][0]
                q = r["indicators"]["quote"][0]
                d = pd.DataFrame({"Low": q["low"], "Close": q["close"]}, dtype=float,
                                 index=pd.to_datetime(r["timestamp"], unit="s").normalize())
                d = d[~d.index.duplicated(keep="last")].dropna()
                if len(d) > min_len: return d
            except Exception as e:
                print("Yahoo 抓取失敗", sym, host, e)
        time.sleep(3)
    return None


TOP5 = [("2330", "台積電"), ("2317", "鴻海"), ("2308", "台達電"), ("2454", "聯發科"), ("2382", "廣達")]   # 市值前五大(可自行修改)


def top5_html():
    """五大權值股:價格、一年高點、高點後最低價跌幅、季線(60)/半年線(120)/年線(240)位置"""
    import time
    tr = []
    for code, nm in TOP5:
        try:
            d = yahoo_hl(f"{code}.TW", retries=1, start=int(time.time()) - 3 * 365 * 86400, min_len=300)
            if d is None or len(d) < 260: continue
            c = d.Close; px = float(c.iloc[-1]); c250 = c.iloc[-250:]; hi = float(c250.max())
            low = float(d.Low.loc[c250.idxmax():].min())
            cells = []
            for n in (60, 120, 240):
                ma = float(c.iloc[-n:].mean()); x = px / ma - 1
                cells.append(f"<td style='color:{'#d9534f' if x >= 0 else '#2e9e5b'};font-weight:700' title='{n}日線 {ma:,.1f}'>{x:+.1%}</td>")
            dd = low / hi - 1; now_dd = px / hi - 1
            tr.append(f"<tr><td title='{code}'>{nm}</td><td style='font-weight:700'>{px:,.0f}</td><td>{hi:,.0f}</td>"
                      f"<td title='高點 {c250.idxmax():%Y-%m-%d} 後最低 {low:,.1f};目前距高點 {now_dd:.1%}'>{dd:.1%}</td>" + "".join(cells) + "</tr>")
        except Exception as e:
            print("權值股抓取失敗", code, e)
    if not tr: return ""
    return ("<div class=t5b><b title='資料:Yahoo 日線。最低跌幅=近一年最高收盤後的最低價;均線位置=收盤 ÷ 均線 − 1,紅=在線上、綠=在線下'>🏆 五大權值股</b>"
            "<table><tr><th>股票</th><th>價格</th><th>年高</th><th>最低跌幅</th><th>季線</th><th>半年</th><th>年線</th></tr>"
            + "".join(tr) + "</table></div>")


def calc_html(df, mc_k, consts):
    """盤中試算:把最近 1600 個交易日的最高/最低/收盤放進網頁,輸入假設收盤價後在瀏覽器重算"""
    import json
    x = df.iloc[-1600:]
    data = {"d": [t.strftime("%Y-%m-%d") for t in x.index], "h": [round(v, 2) for v in x.High], "l": [round(v, 2) for v in x.Low],
            "c": [round(v, 2) for v in x.Close], "mck": round(float(mc_k), 1), **consts}
    return ("<div class=calc><b>🧮 盤中試算</b><span>(輸入假設今日收盤,立即重算;不影響正式數字)</span>"
            "<div class=cin><label>假設收盤 <input id=cc type=number inputmode=decimal step=1></label>"
            "<label>最高 <input id=ch type=number inputmode=decimal placeholder=可不填></label>"
            "<label>最低 <input id=cl type=number inputmode=decimal placeholder=可不填></label>"
            "<button id=cgo>試算</button></div><div id=cout></div>"
            "<script>window.CALC=" + json.dumps(data, separators=(",", ":")) + ";</script>"
            + CALC_JS + "</div>")


CALC_JS = r"""<script>
(function(){
var D=window.CALC, $=function(i){return document.getElementById(i)};
$('cc').placeholder=Math.round(D.c[D.c.length-1]);$('cc').title='昨收 '+D.c[D.c.length-1].toLocaleString();
function kd(h,l,c){var k=[],d=[],pk=50,pd=50;for(var i=0;i<c.length;i++){var s=Math.max(0,i-8),hh=-1e18,ll=1e18;for(var j=s;j<=i;j++){if(h[j]>hh)hh=h[j];if(l[j]<ll)ll=l[j];}
 var r=hh>ll?(c[i]-ll)/(hh-ll)*100:50;pk=2/3*pk+r/3;pd=2/3*pd+pk/3;k.push(pk);d.push(pd);}return [k[k.length-1],d[d.length-1]];}
function dyn(H,L,C,bar,win){var n=C.length;if(win&&n>win){H=H.slice(n-win);L=L.slice(n-win);C=C.slice(n-win);n=win;}
 var m=Math.floor(n/bar)*bar,o=n-m,h=[],l=[],c=[];for(var b=0;b<m/bar;b++){var hh=-1e18,ll=1e18;for(var j=o+b*bar;j<o+b*bar+bar;j++){if(H[j]>hh)hh=H[j];if(L[j]<ll)ll=L[j];}h.push(hh);l.push(ll);c.push(C[o+b*bar+bar-1]);}
 return kd(h,l,c);}
function mean(a){var s=0;for(var i=0;i<a.length;i++)s+=a[i];return s/a.length;}
function f1(x){return x.toLocaleString(undefined,{maximumFractionDigits:0});}
function pc(x){return (x>=0?'+':'')+(x*100).toFixed(1)+'%';}
function ok(b){return b?'<b style="color:#d9534f">✔</b>':'<span style="color:var(--mut)">—</span>';}
function run(){
 var cc=parseFloat($('cc').value);if(!(cc>0)){$('cout').innerHTML='<span style="color:#d9534f">請輸入假設收盤價</span>';return;}
 var pc0=D.c[D.c.length-1],hh=parseFloat($('ch').value),ll=parseFloat($('cl').value);
 if(!(hh>0))hh=Math.max(cc,pc0);if(!(ll>0))ll=Math.min(cc,pc0);hh=Math.max(hh,cc);ll=Math.min(ll,cc);
 var H=D.h.concat([hh]),L=D.l.concat([ll]),C=D.c.concat([cc]),n=C.length;
 var kD=dyn(H,L,C,1,0),kW=dyn(H,L,C,5,1400),kM=dyn(H,L,C,22,0);
 var w1=dyn(H.slice(0,n-1),L.slice(0,n-1),C.slice(0,n-1),5,1400)[0],w2=dyn(H.slice(0,n-2),L.slice(0,n-2),C.slice(0,n-2),5,1400)[0],w3=dyn(H.slice(0,n-3),L.slice(0,n-3),C.slice(0,n-3),5,1400)[0];
 var wr=0;if(kW[0]>w1){wr=1;if(w1>w2){wr=2;if(w2>w3)wr=3;}}
 var mkY=dyn(H.slice(0,n-1),L.slice(0,n-1),C.slice(0,n-1),22,0)[0];
 var ma=mean(C.slice(n-220)),ma0=mean(D.c.slice(D.c.length-220)),dv=cc/ma-1,dv0=pc0/ma0-1;
 var z480=C.slice(n-480),mu=mean(z480),sd=0;for(var i=0;i<480;i++)sd+=(z480[i]-mu)*(z480[i]-mu);sd=Math.sqrt(sd/479);var z=(cc-mu)/sd;
 var c250=C.slice(n-250),hi=-1,hiI=0;for(var i=0;i<250;i++)if(c250[i]>hi){hi=c250[i];hiI=n-250+i;}
 var wl=1e18,wdv=9;for(var i=hiI;i<n;i++){if(L[i]<wl)wl=L[i];var mi=mean(C.slice(Math.max(0,i-219),i+1));if(L[i]/mi-1<wdv)wdv=L[i]/mi-1;}
 var wdd=wl/hi-1;
 var sig=dv>=D.up?'<b style="color:#d9534f">BUY 訊號(明日收盤買進)</b>':dv<=-D.dn?'<b style="color:#2e9e5b">SELL 訊號(明日收盤賣出)</b>':'通道內,無訊號';
 if(dv>=D.up&&dv0>=D.up)sig='已在 +'+(D.up*100)+'% 之上(延續)';if(dv<=-D.dn&&dv0<=-D.dn)sig='已在 −'+(D.dn*100)+'% 之下(延續)';
 var s3=wr>=3&&wdd<=-0.20&&dv<=-0.10;
 var B=[['最低價跌幅',wdd,D.a_dd,'p'],['最低價乖離',wdv,D.a_dv,'p'],['動態週K',kW[0],D.a_wk,'k'],['動態月K',kM[0],D.a_mk,'k'],['已收完月K',D.mck,D.a_ck,'k'],['Z-SCORE<0',z,0,'z']];
 var n1=0,n2=0,rows='';B.forEach(function(r){var v=r[1],a=r[2],h1,h2,th;
  if(r[3]=='p'){th=a*0.85;h1=v<=a;h2=v<=th;}else if(r[3]=='k'){th=a/0.85;h1=v<=a;h2=v<=th;}else{th=null;h1=h2=v<0;}n1+=h1;n2+=h2;
  var fv=r[3]=='p'?pc(v):r[3]=='z'?v.toFixed(2):v.toFixed(1);rows+='<tr><td>'+r[0]+'</td><td><b>'+fv+'</b></td><td>'+ok(h1)+'</td><td>'+ok(h2)+'</td></tr>';});
 var lv=D.left.map(function(x){return 'MA220−'+(x*100)+'% '+f1(ma*(1-x))+(cc<=ma*(1-x)?' ✔':'');}).join('、');
 var cr=function(k){return k[0]>k[1]?'<b style="color:#d9534f">金叉</b>':'<b style="color:#2e9e5b">死叉</b>';};
 $('cout').innerHTML='<div class=cres>'+
  '<div>假設收盤 <b>'+f1(cc)+'</b>('+pc(cc/pc0-1)+')・最高 '+f1(hh)+'・最低 '+f1(ll)+'</div>'+
  '<table><tr><th></th><th>K / D</th><th>狀態</th></tr>'+
  '<tr><td>動態日KD</td><td>'+kD[0].toFixed(1)+' / '+kD[1].toFixed(1)+'</td><td>'+cr(kD)+'</td></tr>'+
  '<tr><td>動態週KD</td><td>'+kW[0].toFixed(1)+' / '+kW[1].toFixed(1)+'</td><td>'+cr(kW)+'・K '+(kW[0]>w1?'↑':'↓')+' 連升 '+wr+' 日</td></tr>'+
  '<tr><td>動態月KD</td><td>'+kM[0].toFixed(1)+' / '+kM[1].toFixed(1)+'</td><td>'+cr(kM)+'・K '+(kM[0]>mkY?'↑':'↓')+'</td></tr></table>'+
  '<div>MA220 '+f1(ma)+'・乖離 <b>'+pc(dv)+'</b>・'+sig+'</div>'+
  '<div>Z-SCORE <b>'+z.toFixed(2)+'</b>'+(z<0?'(跌破 0)':'')+'</div>'+
  '<div>左側價位:'+lv+'</div>'+
  '<div class=s3 style="background:'+(s3?'#fde2e1':'transparent')+'">🚦 止跌訊號:週K連升 '+Math.min(wr,3)+'/3・跌幅≤−20% '+ok(wdd<=-0.2)+'・乖離≤−10% '+ok(dv<=-0.1)+'→ '+(s3?'<b style="color:#d9534f">成立</b>':'未成立')+'</div>'+
  '<table><tr><th>落底指標(台股)</th><th>試算</th><th>達平均</th><th>達85%</th></tr>'+rows+'</table>'+
  '<div style="color:var(--mut)">達成平均 '+n1+'/6・達成85% '+n2+'/6(那斯達克、費半不試算)</div></div>';
}
$('cgo').addEventListener('click',run);$('cc').addEventListener('keydown',function(e){if(e.key==='Enter')run();});
})();
</script>"""


def crash_avg(d):
    """六次一般股災:窗口內最低價 ÷ 之前一年內最高收盤 − 1,回傳 (平均跌幅, 標準差)"""
    v = []
    for a, b in CRASH_WIN:
        w = d.loc[a:b]
        if w.empty: return None
        t = w.Low.idxmin()
        peak = d.Close.loc[pd.Timestamp(a) - pd.DateOffset(years=1):t].max()
        v.append(1 - w.Low.min() / peak)
    return float(np.mean(v)), float(np.std(v, ddof=1))


def wave_dd(d):
    """近一年(250 個交易日)最高收盤 → 之後到今天的最低價 的跌幅"""
    c = d.Close.dropna().iloc[-250:]
    hd = c.idxmax(); lo = d.Low.loc[hd:]
    return float(lo.min() / c.max() - 1), hd, lo.idxmin()


def crash_html(tw):
    rows = []
    for nm in CRASH_AVG:
        try:
            d = tw if nm == "台股" else yahoo_hl(CRASH_SYM[nm])
            if d is None or len(d) < 260: continue
            ca = crash_avg(d)
            if ca: CRASH_AVG[nm] = ca                     # 用最新完整資料重算平均
            rows.append((nm,) + wave_dd(d)); CRASH_DD[nm] = rows[-1][1]
        except Exception as e:
            print("股災跌幅抓取失敗", nm, e)
    tr = []
    for nm, dd, hd, ld in rows:
        mu, sd = CRASH_AVG[nm]; x = -dd
        tag, col = (("超過+1σ", "#b3261e") if x > mu + sd else ("超過平均", "#d9534f") if x > mu else
                    ("平均−1σ內", "#e67e22") if x > mu - sd else ("尚淺", "#2e9e5b"))
        tr.append(f"<tr title='{nm}:近一年高點 {hd:%Y-%m-%d} → 最低價 {ld:%Y-%m-%d};一般股災平均 −{mu:.1%}(±1σ:−{mu - sd:.1%}~−{mu + sd:.1%})'>"
                  f"<td>{nm}</td><td style='color:{col};font-weight:700'>{dd:.1%}</td><td>−{mu:.1%}</td><td>−{mu + sd:.1%}</td>"
                  f"<td style='color:{col};font-weight:700'>{tag}</td></tr>")
    if not tr: return ""
    pk = ""
    try:                                                   # 股災前高點的 MA220 正乖離(台股)
        v = []
        for a, b in CRASH_WIN:
            w = tw.loc[a:b]; t = w.Low.idxmin()
            p = tw.Close.loc[pd.Timestamp(a) - pd.DateOffset(years=1):t].idxmax(); v.append(tw.Close[p] / tw.MA[p] - 1)
        mu, sd = float(np.mean(v)), float(np.std(v, ddof=1))
        c = tw.Close.iloc[-250:]; p = c.idxmax(); now_ = float(tw.Close[p] / tw.MA[p] - 1)
        tag, col = (("超過+1σ", "#b3261e") if now_ > mu + sd else ("超過平均", "#d9534f") if now_ > mu else
                    ("超過85%", "#e67e22") if now_ > mu * 0.85 else ("未過熱", "#2e9e5b"))
        pk = (f"<div class=pkb title='股災前最高收盤日的 MA220 正乖離;平均/標準差=2011、2015、2018、2020、2022、2025 六次一般股災。各次:"
              + "、".join(f"{x:+.1%}" for x in v) + "'>"
              f"<b>台股股災前高點乖離</b> 本波 <b style='color:{col}'>{now_:+.1%}</b>({p:%m/%d})・平均 {mu:+.1%}・"
              f"±1σ {mu - sd:+.1%}~{mu + sd:+.1%}・85% {mu * 0.85:+.1%} <b style='color:{col}'>{tag}</b></div>")
    except Exception as e:
        print("高點乖離計算失敗", e)
    return ("<div class=crash><b title='跌幅一律用最低價:本波=近一年最高收盤後的最低價;平均/+1σ=2011、2015、2018、2020、2022、2025 六次一般股災(剔除 2000/2008),高點收盤→之後最低價'>📉 股災跌幅比較</b><span>(以最低價計;平均=一般股災,不含2000/2008)</span>"
            "<table><tr><th>市場</th><th>本波</th><th>平均</th><th>+1σ</th><th>位置</th></tr>" + "".join(tr) + "</table>" + pk + "</div>")


def closed_month_gold(df):
    """每天可用的「已收完月 K」KD 是否黃金交叉(月底最後一個交易日算當月已收完,其餘看上個月)"""
    per = df.index.to_period("M")
    g = df.groupby(per).agg(High=("High", "max"), Low=("Low", "min"), Close=("Close", "last"))
    k, d = model._kd(g.High.to_numpy(), g.Low.to_numpy(), g.Close.to_numpy())
    gold = pd.Series(k > d, index=g.index)
    last = pd.Series(per != pd.Series(per, index=df.index).shift(-1).values, index=df.index)
    t = df.index[-1]
    last.iloc[-1] = t.normalize() >= (t + pd.offsets.MonthEnd(0)).normalize()
    use = [p if l else p - 1 for p, l in zip(per, last)]
    return pd.Series([bool(gold.get(p, False)) for p in use], index=df.index)


def exit_cycle(m, allok, sid, mgold):
    """依買賣規則逐日追蹤目前所在階段(與 ladder7_grid.py 的 G1 回測相同)。
    6/6 成立 → 轉出;左側:距一年高點 -10/-15/-20/-25/-30% 各買 5/7.5/10/12.5/15%(Z<-2.5 直接補到 50%);
    右側:先決(Z≤0 / 距一年高點跌 20% / 轉出滿 252 日)成立後,已收完月K KD 金叉 → 全部買回;
    全部買回後跌破均價 20% → 再轉出(月 KD 需重新金叉)。
    全部買回當天即開始新的一段(過熱條件從頭累積),之後才會再判斷 6/6。"""
    c = m["台股收盤價"].to_numpy(); hi = m["台股收盤價"].rolling(250, min_periods=1).max().to_numpy()
    z = m["Z-SCORE"].to_numpy(); ok = allok.to_numpy(); sd = sid.to_numpy(); g = mgold.reindex(m.index).fillna(False).to_numpy()
    mav = m["220日均線"].to_numpy(dtype=float)
    dnr = streak(pd.Series(c < mav * (1 - INS_BAND), index=m.index)).to_numpy()
    upr = streak(pd.Series(c > mav, index=m.index)).to_numpy()
    slp = (m["220日均線"] / m["220日均線"].shift(SLOPE_DAYS) - 1).to_numpy()
    st = dict(pos=1.0, ex=None, why=None, arm=None, done=set(), buys=[], blk=None, fresh=False, back=None, avg=None,
              seen=False, maout=False, top=None, leftoff=False, lstop=None)
    backs = []
    for i in range(len(m)):
        if st["pos"] >= 1:
            if st["avg"] is not None:
                if mav[i] == mav[i] and c[i] > mav[i]: st["seen"] = True
                st["top"] = max(st["top"] or c[i], c[i])
                if c[i] <= st["top"] * (1 - STOP_DD):          # 保險 A:跌破買回以來最高收盤 20%(移動停損)
                    st.update(pos=0.0, ex=i, why="A", arm=None, done=set(), buys=[], fresh=False, avg=None, seen=False, maout=True)
                    continue
                if st["seen"] and dnr[i] >= INS_SELL_DAYS and slp[i] < INS_SLOPE:      # 保險 B:MA220
                    st.update(pos=0.0, ex=i, why="B", arm=None, done=set(), buys=[], fresh=False, avg=None, seen=False, maout=True)
                    continue
            if ok[i] and sd[i] != st["blk"]:
                st.update(pos=0.0, ex=i, why="6/6", arm=None, done=set(), buys=[], fresh=False, avg=None, seen=False, leftoff=False, lstop=None)
            continue
        if st["maout"]:                                   # 保險 A 或 B 轉出後:連 3 天站回 MA220 → 全部買回
            if upr[i] >= INS_DAYS:
                st.update(pos=1.0, maout=False, avg=c[i], seen=True, back=i, top=c[i])
            continue
        dd = c[i] / hi[i] - 1
        if st["arm"] is None:
            if z[i] <= 0: st["arm"] = ("Z≤0", i)
            elif dd <= -ARM_DD: st["arm"] = (f"跌{ARM_DD:.0%}", i)
            elif i - st["ex"] >= BACKUP_DAYS: st["arm"] = ("轉出滿 12 個月", i)
        if st["pos"] > 0 and not st["leftoff"] and st["buys"]:                    # ④ 左側停損
            la = sum(w * p for _, w, p in st["buys"]) / sum(w for _, w, _ in st["buys"])
            if c[i] <= la * (1 - LEFT_STOP):
                st.update(pos=0.0, buys=[], leftoff=True, lstop=(i, c[i], la))
        new = st["pos"]
        if not st["leftoff"]:
            if z[i] < HALF_Z and new < 0.5: new = 0.5
            if m.index[i] < LEFT_CUT:
                for k, (x, w) in enumerate(LEFT):
                    if k not in st["done"] and dd <= -x:
                        st["done"].add(k); new = min(0.5, new + w)
            elif mav[i] == mav[i]:
                for x, t in LEFT_MA:                       # MA220 乖離:跌到哪一級,左側就補到該級的累計比例
                    if c[i] <= mav[i] * (1 - x): new = max(new, min(0.5, t))
        if not g[i]: st["fresh"] = False
        if st["arm"] is not None and g[i] and not st["fresh"]: new = 1.0
        if new > st["pos"]:
            st["buys"].append((i, new - st["pos"], c[i])); st["pos"] = new
            if new >= 1:
                st["avg"] = sum(w * p for _, w, p in st["buys"]) / sum(w for _, w, _ in st["buys"])
                st["back"] = i; backs.append(m.index[i]); st["seen"] = False; st["top"] = c[i]; st["leftoff"] = False; st["lstop"] = None
                st["blk"] = None      # 全部買回當天即重算本段(由 warn_state 的 extra 處理),不再封鎖
    idx = m.index; h = hi[-1]
    nxt = next(((x, t - st["pos"]) for x, t in LEFT_MA if t > st["pos"] + 1e-9), None) if st["pos"] < 0.5 else None
    inv = [(w, p) for _, w, p in st["buys"]] if st["pos"] < 1 else []
    return dict(state="持有" if st["pos"] >= 1 else "空手", pos=st["pos"], exit=idx[st["ex"]] if st["ex"] is not None else None,
                n=(len(m) - 1 - st["ex"]) if st["ex"] is not None else 0, why=st["why"],
                arm=(st["arm"][0], idx[st["arm"][1]]) if st["arm"] else None, hi=h,
                left_avg=(sum(w * p for w, p in inv) / sum(w for w, _ in inv)) if inv else None,
                nxt=(nxt[0], nxt[1], float(mav[-1]) * (1 - nxt[0])) if nxt else None, arm_px=h * (1 - ARM_DD),
                avg=st["avg"], top=st["top"] if st["avg"] else None, stop_px=st["top"] * (1 - STOP_DD) if st["avg"] else None, back=idx[st["back"]] if st["back"] is not None else None,
                backs=backs, maout=st["maout"], seen=st["seen"], leftoff=st["leftoff"],
                lstop=(idx[st["lstop"][0]], st["lstop"][1], st["lstop"][2]) if st["lstop"] else None,
                ins=dict(dn=int(dnr[-1]), up=int(upr[-1]), slope=float(slp[-1]), ma=float(mav[-1]), ma99=float(mav[-1]) * (1 - INS_BAND),
                         close=float(c[-1])))


def _p(x):
    return f"{x * 100:g}%"


def cycle_lines(cy, z):
    """已轉出期間的提示(LINE 與網頁滑鼠說明用);持有中只在保險有效時提示停損價"""
    if cy["state"] == "持有":
        return [f"保險A:收盤跌破 {cy['stop_px']:,.0f}(買回後最高 {cy['top']:,.0f} 的 −20%)→ 轉出"] if cy["stop_px"] else []
    if cy["maout"]:
        i_ = cy["ins"]; nm = "保險 A(高點−20%)" if cy["why"] == "A" else "保險 B(MA220)"
        return [(f"今日{nm}成立,請轉出:一半反1(00632R)、一半中華電" if cy["n"] == 0 else
                 f"{nm}轉出 {cy['n']} 個交易日({cy['exit']:%Y-%m-%d} 起)"),
                f"連 {INS_DAYS} 天收盤站回 MA220({i_['ma']:,.0f})→ 全部買回(不等 KD);目前 {min(i_['up'], INS_DAYS)}/{INS_DAYS}"]
    head = ("今日 6/6 成立,請開始執行轉出" if cy["n"] == 0 and cy["why"] == "6/6" else
            f"已轉出 {cy['n']} 個交易日({cy['exit']:%Y-%m-%d} 起)")
    if cy["leftoff"]:
        d_, px_, la_ = cy["lstop"]
        left = f"左側停損:{d_:%Y-%m-%d} 收 {px_:,.0f} 跌破左側均價 {la_:,.0f} 的 −15%,左側已全賣,本次只等右側"
    else:
        left = (f"左側已投入 {_p(cy['pos'])}" + (f"(均價 {cy['left_avg']:,.0f},跌破 {cy['left_avg'] * (1 - LEFT_STOP):,.0f} 左側全賣)" if cy["left_avg"] else "")
                + (f";下一筆 MA220−{cy['nxt'][0]:.0%} {cy['nxt'][2]:,.0f} 加 {_p(cy['nxt'][1])}" if cy["nxt"] else ";左側已滿 50%"))
    if cy["arm"]:
        right = f"右側已啟動({cy['arm'][0]} {cy['arm'][1]:%m/%d}),等已收完月K KD 金叉全部買回"
    else:
        right = f"右側等 Z≤0 或跌 20%({cy['arm_px']:,.0f});{max(BACKUP_DAYS - cy['n'], 0)} 個交易日後未成立 → 改只看月 KD 金叉"
    return [head, left, right]


def cycle_short(cy):
    """網頁卡片用的一行版本(維持卡片高度)"""
    if cy["state"] == "持有":
        return f"保險:跌破 {cy['stop_px']:,.0f} 再轉出" if cy["stop_px"] else ""
    if cy["n"] == 0 and cy["why"] == "6/6":
        return "今日 6/6 成立,請開始執行轉出"
    if cy["maout"]:
        return (f"今日保險 {cy['why']} 成立,請轉出" if cy["n"] == 0 else
                f"保險{cy['why']}轉出{cy['n']}日｜站回MA220 {min(cy['ins']['up'], INS_DAYS)}/{INS_DAYS}")
    tail = "等月KD金叉" if cy["arm"] else "等跌20%"
    return f"已轉出{cy['n']}日｜{'左側已停損' if cy['leftoff'] else '左' + _p(cy['pos'])}｜{tail}"


def z_level(closes, target, n=480):
    """明天收盤要到多少,480 日 Z-SCORE 才會剛好等於 target(視窗含當天收盤,二分法求解)"""
    w = [float(x) for x in closes[-(n - 1):]]
    def zf(c):
        a = w + [c]; mu = sum(a) / n
        sd = (sum((x - mu) ** 2 for x in a) / (n - 1)) ** 0.5
        return (c - mu) / sd if sd else 0.0
    lo, hi = min(w) * 0.3, max(w) * 2.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if zf(mid) < target: lo = mid
        else: hi = mid
    return (lo + hi) / 2


def rule_checks(cy):
    """買賣規則框:本次轉出循環中已發生的步驟打勾"""
    ck = lambda o: '<b style="color:#1a7f37">☑</b>' if o else '<b style="color:#aaa;font-weight:400">☐</b>'
    out = cy["state"] != "持有" and cy["why"] == "6/6"
    pos = cy["pos"] if out else 0
    lo = out and cy["leftoff"]
    lab = "MA220乖離−15/20/30%"
    left = (f"{lab},已停損賣出" if lo else f"{lab},已{_p(pos)}/50%" if 0 < pos < 0.5 else
            f"{lab},已滿 50%" if pos >= 0.5 else f"{lab},共 50%")
    stop = (f"{cy['lstop'][0]:%m/%d} 左側部位已全賣,本輪停止左側,只等右側" if lo else
            f"跌破{cy['left_avg'] * (1 - LEFT_STOP):,.0f}(均價−15%)→左側部位全賣,本輪停止左側" if out and cy["left_avg"] else "跌破左側均價15%→左側部位全賣,本輪停止左側")
    return [ck(out), ck(pos > 0 or lo), left, ck(out and bool(cy["arm"])), ck(False), ck(lo), stop]


def ins_checks(cy):
    """買回後保險(A 高點 −20% 移動停損、B MA220)各條件是否成立"""
    i_ = cy["ins"]; held = cy["state"] == "持有" and cy["avg"] is not None
    a = [held, held and i_["close"] <= cy["stop_px"]]
    b = [held, held and cy["seen"], i_["dn"] >= INS_SELL_DAYS, i_["slope"] < INS_SLOPE]
    return held, a, b, cy["maout"] and i_["up"] >= INS_DAYS      # 只有保險 A/B 賣出後才判斷站回


def ins_status(cy):
    held, a, b, _ = ins_checks(cy)
    if cy["state"] != "持有":
        if cy["maout"]:
            return (f"⚠ 保險 {cy['why']} 成立:今天轉出!" if cy["n"] == 0 else f"保險 {cy['why']} 轉出中({cy['exit']:%m/%d} 起 {cy['n']} 日),等站回 MA220"), "#c1121f"
        return "目前空手(6/6 轉出中),全部買回後才啟動", "#c1121f"
    if not held:
        return "持有中(資料內尚未有全部買回),保險未啟動", "#888"
    return f"持有中,保險啟動中(B 已 {sum(b)}/4)", "#1a7f37"


def ins_lines(cy):
    """LINE 用:保險 A / B 狀態"""
    held, a, b, up = ins_checks(cy); i_ = cy["ins"]; ck = lambda o: "☑" if o else "☐"
    if cy["maout"]:
        return []                       # 已在 cycle_lines 說明
    if not held:
        return ["保險 A/B:全部買回後才啟動(A 高點−20%、B MA220)"] if cy["state"] != "持有" else []
    return [f"保險B(MA220){sum(b)}/4:{ck(b[1])}站上過年線 {ck(b[2])}收盤<{i_['ma99']:,.0f} "
            f"{ck(b[3])}年線下彎({i_['slope'] * 100:+.2f}%)→ 全打勾就轉出"]


def ins_html(cy):
    held, a, b, up = ins_checks(cy); i_ = cy["ins"]
    ck = lambda o: "<b class=ok>☑</b>" if o else "<b class=no>☐</b>"
    msg, col = ins_status(cy)
    stop = f"{cy['stop_px']:,.0f}(最高 −20%)" if held else "買回後最高收盤 −20%"
    topt = f"(買回後最高 {cy['top']:,.0f})" if held else ""
    upt = f"{min(i_['up'], INS_DAYS)}/{INS_DAYS}" if cy["maout"] else "(賣出後才判斷)"
    return f"""<div class=ins><div><b class=it>🛡 買回後保險</b><br><span class=mu>兩種並行,任一成立就轉出</span><br><b style="color:{col}">{msg}</b></div>
<div class=ic><b>A 高點 −20%(移動停損)</b><br>{ck(a[0])} 已全部買回{topt}<br>{ck(a[1])} 收盤跌破 {stop} → 轉出</div>
<div class=ic><b>B MA220</b> <span class=mu>4 格全打 V → 轉出</span><br>{ck(b[0])} 已全部買回　{ck(b[1])} 買回後站上過 MA220<br>
{ck(b[2])} 收盤 &lt; MA220−1%({i_['ma99']:,.0f})　{ck(b[3])} 年線下彎(20日 {i_['slope'] * 100:+.2f}%)</div>
<div class=ib><span class=mu>↳ A 或 B 賣出後:</span>{ck(up)} 連 {INS_DAYS} 天站回 MA220({i_['ma']:,.0f}){upt} → 全部買回(不等 KD)</div></div>"""


CSS_INS = """
.ins{display:grid;grid-template-columns:minmax(170px,.8fr) 1fr 1.5fr;gap:4px 18px;border:2px solid #2f6fb5;border-radius:8px;padding:6px 12px;margin:0 0 10px;font-size:12.5px;line-height:1.55;background:var(--card)}
.ins .ic{border-left:1px solid #ccd;padding-left:12px}.ins .ib{grid-column:2/4;border-top:1px dashed #ccd;padding-top:2px}.ins .it{font-size:13.5px}.ins .mu{color:var(--mut)}
.ins b.ok{color:#1a7f37;font-size:14px}.ins b.no{color:#aaa;font-weight:400;font-size:14px}
@media(max-width:760px){.ins{grid-template-columns:1fr}.ins .ic{border-left:0;padding-left:0;border-top:1px solid #ccd;padding-top:4px}.ins .ib{grid-column:1}}
"""

CSS_TREND = """
.trend{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;align-items:center;border-radius:8px;padding:10px 14px;margin-bottom:10px}
.trend.s_bull{background:#fdecea;box-shadow:inset 0 0 0 2px #e0857c}.trend.s_pull{background:#fff4d6;box-shadow:inset 0 0 0 2px #e3bd52}
.trend.s_bounce{background:#e8f0fb;box-shadow:inset 0 0 0 2px #9db9e3}.trend.s_bear{background:#e5f4ea;box-shadow:inset 0 0 0 2px #8fcba5}
@media (prefers-color-scheme:dark){.trend.s_bull{background:#4a2326}.trend.s_pull{background:#4a3d1c}.trend.s_bounce{background:#1f2f4a}.trend.s_bear{background:#1f3b2a}.trend .chips span{background:#22262d!important;border-color:#333!important}}
.trend .lab{font-size:12px;font-weight:800;color:var(--mut)}.trend .st{font-size:24px;font-weight:800;line-height:1.15}.trend .sub{font-size:12px;color:var(--mut)}
.trend .steps{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px}.trend .steps i{font-style:normal;font-size:12px;font-weight:700;padding:2px 10px;border-radius:12px;background:#ececec;color:#999}
.trend .steps i.on{color:#fff}.trend .chips{display:flex;gap:6px;flex-wrap:wrap}.trend .chips span{font-size:12px;padding:2px 8px;border-radius:6px;background:#fff;border:1px solid #e3e3e3}
.trend .ok{color:#d9534f}.trend .ng{color:#2e9e5b}.trend .nt{color:#c77700}.trend .foot{grid-column:1/3;font-size:11.5px;color:var(--mut);border-top:1px dashed rgba(0,0,0,.18);padding-top:4px}
@media (max-width:640px){.trend{grid-template-columns:1fr}.trend .foot{grid-column:1}}
"""


TREND_STYLE = {   # 狀態 → (class, 文字色, 說明)
    "多頭": ("s_bull", "#c62828", "年線上彎、月KD金叉,趨勢向上"),
    "多頭修正": ("s_pull", "#c77700", "長期多頭架構仍在｜高檔轉弱,尚未轉空"),
    "空頭反彈": ("s_bounce", "#1f5fbf", "長期趨勢偏弱｜月KD金叉多為反彈,留意年線壓力"),
    "空頭": ("s_bear", "#2e7d4f", "跌破年線或深度回檔,趨勢向下"),
}


def trend_state(m, dd, mc, wk_state, wk_run):
    """多空狀態:看 MA220 位置與方向、已收完月 KD、距一年高點跌幅。
    空頭結構 = 連 3 天收在 MA220×0.99 以下且年線不再上彎;深度回檔 = 距一年高點跌逾 20% 且月KD死叉。"""
    c, ma = m["台股收盤價"], m[f"{model.SEG_MA}日均線"]
    px, mav = c.iloc[-1], ma.iloc[-1]
    s_ = ma.dropna()
    slope = s_.iloc[-1] / s_.iloc[-1 - SLOPE_DAYS] - 1 if len(s_) > SLOPE_DAYS else 0.0
    brk = bool((c.iloc[-3:] < ma.iloc[-3:] * 0.99).all())
    up, down = slope > FLAT, slope < -FLAT
    gold = mc["state"] == "黃金交叉"
    deep = dd <= -0.20 and not gold
    if up and not brk and not deep:
        st = "多頭" if gold else "多頭修正"
    else:
        st = "空頭反彈" if gold else "空頭"
    ok, ng, nt = "<b class=ok>✔</b>", "<b class=ng>✘</b>", "<b class=nt>▲</b>"
    chips = [f"{ok if px > mav else ng} 年線{'上方' if px > mav else '下方'} {px / mav - 1:+.1%}(MA{model.SEG_MA} {mav:,.0f})",
             f"{ok if up else ng if down else nt} 年線{'上彎' if up else '下彎' if down else '走平'} {slope:+.2%}/20日",
             f"{ok if gold else ng} 已收完月KD {'金叉' if gold else '死叉'} {mc['K']:.1f} / {mc['D']:.1f}",
             f"{ok if wk_state == '黃金交叉' else ng} 週KD {'金叉' if wk_state == '黃金交叉' else '死叉'}{(' ' + wk_run) if wk_run else ''}",
             f"{nt} 距一年高點 {dd:+.1%}({'已逾' if dd <= -0.20 else '未達'} −20%)"]
    reason = (f"年線{'上' if px > mav else '下'}方{px / mav - 1:+.1%}、年線{'上彎' if up else '下彎' if down else '走平'}、"
              f"月KD{'金叉' if gold else '死叉'}、距高點{dd:+.1%}")
    return dict(state=st, chips=chips, reason=reason, ma=mav)


def trend_html(t, asof):
    cls, col, sub = TREND_STYLE[t["state"]]
    steps = "".join(f"<i class=on style='background:{col}'>● {n}</i>" if n == t["state"] else f"<i>{n}</i>" for n in TREND_STYLE)
    return (f"<div class='trend {cls}'><div><div class=lab>📈 多空狀態({asof:%Y-%m-%d})</div>"
            f"<div class=st style='color:{col}'>{t['state']}</div><div class=sub>{sub}</div></div>"
            f"<div><div class=steps>{steps}</div><div class=chips>{''.join(f'<span>{x}</span>' for x in t['chips'])}</div></div>"
            f"<div class=foot>轉空確認:連 3 天收在 MA{model.SEG_MA}×0.99(約 {t['ma'] * 0.99:,.0f})以下且年線轉下彎,或距一年高點跌逾 20% 且月KD死叉"
            f"｜回到多頭:年線上彎且已收完月K KD 金叉</div></div>")


def ma_channel(m):
    d = pd.DataFrame({"close": m["台股收盤價"], "ma": m["220日均線"]})
    d["up"], d["dn"] = d.ma * (1 + UP_BAND), d.ma * (1 - DN_BAND)
    d["ua"], d["ub"] = streak(d.close > d.up), streak(d.close < d.dn)
    d["signal"] = ""
    d.loc[d.ua == DAYS, "signal"] = "買進"      # 收盤站上 MA220+2% 的第一天
    d.loc[d.ub == DAYS, "signal"] = "賣出"      # 收盤跌破 MA220-1.5% 的第一天
    d = d[d.index >= d.index[-1] - pd.DateOffset(years=YEARS)]
    last = d.iloc[-1]
    state = (f"已連續 {int(last.ua)} 天站上 MA+{UP_BAND * 100:g}%" if last.ua > 0 else
             f"已連續 {int(last.ub)} 天跌破 MA-{DN_BAND * 100:g}%" if last.ub > 0 else
             f"位於 MA-{DN_BAND * 100:g}% ~ MA+{UP_BAND * 100:g}% 通道內")
    f = go.Figure()
    f.add_scatter(x=d.index, y=d.up, name=f"MA220+{UP_BAND * 100:g}%", line=dict(color="#d9534f", width=1, dash="dot"))
    f.add_scatter(x=d.index, y=d.dn, name=f"MA220-{DN_BAND * 100:g}%", line=dict(color="#2e9e5b", width=1, dash="dot"),
                  fill="tonexty", fillcolor="rgba(150,150,150,0.10)")
    f.add_scatter(x=d.index, y=d.ma, name="MA220", line=dict(color="#f0ad4e", width=1.6))
    f.add_scatter(x=d.index, y=d.close, name="收盤", line=dict(color="#1f77b4", width=1.6))
    f.update_layout(title=f"台股加權指數 TAIEX(MA220 +{UP_BAND * 100:g}% / -{DN_BAND * 100:g}%)", height=460, template="plotly_white",
                    hovermode="x unified", margin=dict(l=50, r=20, t=50, b=30), legend=dict(orientation="h", y=-0.12))
    sigs = d[d.signal != ""].iloc[::-1]
    rows = "".join(f"<tr class='{'buy' if r.signal == '買進' else 'sell'}'><td>{i:%Y-%m-%d}</td><td>{r.signal}</td>"
                   f"<td>{r.close:,.2f}</td><td>{r.ma:,.2f}</td></tr>" for i, r in sigs.iterrows()) or "<tr><td colspan=4>近三年無訊號</td></tr>"
    return f"""<h2>台股加權指數 MA220 通道與買賣訊號</h2>
<div class=status>{d.index[-1]:%Y-%m-%d} 收盤 {last.close:,.2f}|MA220 {last.ma:,.2f}|乖離 {(last.close / last.ma - 1) * 100:+.2f}%|<b>{state}</b></div>
<p class=n><span style="display:inline-block;background:#fff3c4;border-left:5px solid #f0a500;border-radius:6px;padding:6px 12px;font-weight:700;color:#5a3d00">📌 規則:收盤高於 MA220×{1 + UP_BAND:.4g} → 買進;收盤低於 MA220×{1 - DN_BAND:.4g} → 賣出(收盤確認當天即為訊號,隔天收盤下單;每次跨越觸發一次)。</span></p>
{f.to_html(full_html=False, include_plotlyjs="cdn")}
<details open><summary>買賣訊號(共 {len(sigs)} 筆,新到舊)</summary><div class=wrap><table><tr><th>日期</th><th>訊號</th><th>收盤</th><th>MA220</th></tr>{rows}</table></div></details>""", sigs


ZHOT = 1.5                                                      # Z-SCORE 高於此值 → 粉紅底
WINS = [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 120, 150, 180]
ZCOLS = [f"{w}天 Z-SCORE" for w in WINS]                        # Excel AH~AT
XCOLS = [f"{a}>{b}天Z" for a, b in zip(WINS[:-1], WINS[1:])]    # Excel AU~BF
MACOLS = {"20日均線", "60日均線", "220日均線", "240日均線"}      # 收盤>均線 粉紅底、<均線 淡綠底
TEXT = {"生命線60*3%", "BUY(220日)2%", "SELL(220日)1%", "Z方向"} | set(XCOLS)
PCT1 = {"5-AVG", "5-STD", "10-AVG", "10-STD"}


def cell(c, r):
    v = r[c]
    if c in ("週KD", "月KD"):
        v = v if isinstance(v, str) else ""
        return f"<td class='{'gold' if v == '黃金交叉' else 'dead' if v == '死亡交叉' else ''}'>{v}</td>"
    if c in TEXT:
        return f"<td{' class=xc' if c in XCOLS else ''}>{v if isinstance(v, str) else ''}</td>"
    if pd.isna(v):
        return "<td></td>"
    if c in MACOLS:
        return f"<td class='{'pk' if r['台股收盤價'] > v else 'gr' if r['台股收盤價'] < v else ''}'>{v:,.2f}</td>"
    if c == "Z-SCORE":
        return f"<td class='{'pk' if v > ZHOT else ''} {'neg' if v < 0 else ''}'>{v:.2f}</td>"
    if c in ZCOLS:                                              # 當天 Z-SCORE 大於該格(N天 Z-SCORE)→ 淡粉底
        return f"<td class='{'pk' if r['Z-SCORE'] > v else ''}'>{v:.2f}</td>"
    if "乖離" in c:
        return f"<td>{pct(v)}</td>"
    if c in PCT1:
        return f"<td>{v:.1%}</td>"
    return f"<td>{num(v, 2)}</td>"


def zchart(m):
    """對應 Excel 的「台股 Z-SCORE」圖:左軸收盤價、右軸 Z-SCORE(-5~5)"""
    f = go.Figure()
    f.add_scatter(x=m.index, y=m["台股收盤價"], name="台股收盤價", line=dict(color="#1f77b4", width=1.4))
    f.add_scatter(x=m.index, y=m["Z-SCORE"], name="Z-SCORE", yaxis="y2", line=dict(color="#c0392b", width=1.4))
    last = m.index[-1]
    f.add_scatter(x=[last], y=[m["台股收盤價"].iloc[-1]], name="台股收盤價", mode="markers+text", text=[fmt(m["台股收盤價"].iloc[-1])],
                  textposition="middle left", marker=dict(color="#1f77b4", size=7), showlegend=False, hoverinfo="skip")
    f.add_scatter(x=[last], y=[m["Z-SCORE"].iloc[-1]], name="Z-SCORE", yaxis="y2", mode="markers+text", text=[fmt(m["Z-SCORE"].iloc[-1])],
                  textposition="top left", marker=dict(color="#c0392b", size=7), showlegend=False, hoverinfo="skip")
    f.update_layout(**today_marks(last))
    f.update_layout(title="台股 Z-SCORE(全部歷史:左軸收盤價、右軸 Z-SCORE)", height=440, template="plotly_white", hovermode="x unified",
                    margin=dict(l=50, r=50, t=50, b=30), legend=dict(orientation="h", y=-0.12),
                    yaxis=dict(title="收盤價"), yaxis2=dict(title="Z-SCORE", overlaying="y", side="right", range=[-5, 5], showgrid=False))
    return f.to_html(full_html=False, include_plotlyjs=False)


JS = """
(function(){
var tbl=document.getElementById('bigtbl'),rows=tbl.querySelectorAll('tr.r'),cx=tbl.querySelectorAll('.xc'),
    btns=document.querySelectorAll('.ctl button[data-n]'),xt=document.getElementById('xt');
function setRows(n){rows.forEach(function(t,i){t.style.display=i<n?'':'none'});
  btns.forEach(function(b){b.classList.toggle('on',+b.dataset.n===n)});}
function setX(show){cx.forEach(function(e){e.style.display=show?'':'none'});
  xt.textContent=show?'隱藏':'顯示';xt.dataset.s=show?'1':'0';}
btns.forEach(function(b){b.onclick=function(){setRows(+b.dataset.n)}});
xt.onclick=function(){setX(xt.dataset.s!=='1')};
var wide=window.innerWidth>=700;
setRows(wide?200:60);setX(wide);
})();
"""
CSS2 = """
.ctl{margin:6px 0;font-size:13px}.ctl button{margin-left:6px;padding:3px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
.ctl button.on{background:#1f77b4;color:#fff;border-color:#1f77b4}
.big{max-height:72vh;overflow:auto}.big th{position:sticky;top:0;z-index:2;background:var(--bg)}
.big th:first-child{left:0;z-index:3}.big th.xh{background:#ffe3a3;color:#222}
"""


def main():
    force = os.environ.get("FORCE") == "1"
    df, added = update_data(CSV, retries=int(os.environ.get("RETRIES", "0")))
    inst_data = inst.fetch()                              # 三大法人 + 外資期貨 + 散戶多空比(網頁與 LINE 共用)
    inst_only = False
    if not added and not force and os.path.exists(OUT_HTML):
        # 證交所沒有新資料時,檢查期交所(外資台指期、散戶多空比)是否出了新資料日;有就只重建網頁、不再發 LINE
        old = open(OUT_HTML, encoding="utf-8").read()
        def _old(pat):
            mm = re.search(pat, old); return mm.group(1) if mm else ""
        _, fut, ret = inst_data
        newer = [(inst.fmt_date(x[0]) if x else "") for x in (fut, ret)]
        olds = [_old(r"淨未平倉\(多−空\)\|資料日 ([0-9-]+)"), _old(r"散戶偏空\|資料日 ([0-9-]+)")]
        if not any(n and n > o for n, o in zip(newer, olds)):
            print(f"沒有新資料,不重建頁面(期交所資料日 {newer},頁面上 {olds})")
            return
        inst_only = True
        print(f"期交所資料更新 {olds} → {newer},只重建網頁,不發 LINE")
    m = model.zscore_model(df)
    kd = model.kd_log(df, max(CSV_DAYS, CHART_DAYS))
    m = m.join(kd)
    now = m.iloc[-1]
    k = model.kd_now(df)
    mc = model.closed_month_kd(df)                      # 已收完月 K(日曆月)

    z, lo, hi = now["Z-SCORE"], now["Z低檔"], now["Z高檔"]
    zread = "高於 Z高檔(偏熱)" if z > hi else "低於 Z低檔(偏冷)" if z < lo else "在 Z低檔~Z高檔之間"
    prev = m["台股收盤價"].iloc[-2]
    chg = now["台股收盤價"] - prev
    chg_pct = chg / prev
    chg_col = "#d9534f" if chg > 0 else "#2e9e5b" if chg < 0 else "inherit"        # 台股慣例:漲紅、跌綠
    arrow = "▲" if chg > 0 else "▼" if chg < 0 else "－"
    chg_html = f"<small style='color:{chg_col};font-size:15px;font-weight:600'>{arrow} {abs(chg):,.2f}　({chg_pct:+.2%})</small>"
    ma_lab, ma_n, ma_note, ma_today = ma200_state(m)
    top5 = top5_html()
    crash = crash_html(pd.DataFrame({"Low": m["最低價"], "Close": m["台股收盤價"], "MA": m["220日均線"]}))
    # 標題旁:MA220 負乖離 −15%~−45% 對應指數(歷史:一般股災底約 −20~−23%,2000/2008 大空頭 −41~−45%)
    _ma, _cl = float(now["220日均線"]), float(m["台股收盤價"].iloc[-1])
    _tip = {-0.20: "2015/2020/2022/2025 股災底約 −20~−23%", -0.40: "2000 年最大 −40.9%", -0.45: "2008 年最大 −44.5%"}
    dev_html = ("<div class=devb title='乖離率 = (當日收盤價 − MA220) ÷ MA220 × 100%;價位 = MA220 × (1 + 乖離率);歷史最大負乖離:2015 −19.5%、2022 −21.6%、2020 −21.7%、2025 −22.7%、2000 −40.9%、2008 −44.5%'>"
                f"<b class=t>📉 MA220 乖離</b> <span class=x>現在 {_cl / _ma - 1:+.1%}</span><div class=g>"
                + "".join(f"<div title='{_tip.get(x, '')}'><i>{x:.0%}</i><b{' class=x' if _cl <= _ma * (1 + x) else ''}>{_ma * (1 + x):,.0f}</b></div>"
                          for x in (-0.15, -0.20, -0.25, -0.30, -0.35, -0.40, -0.45))
                + "<div><i>股災底</i><i>−20~23%</i></div></div></div>")
    # 明日收盤關鍵點位:明天 MA220 = (近 219 天 + 明日收盤)/220,解出剛好等於 MA220×(1+UP)/(1−DN) 的收盤價
    _c = m["台股收盤價"]
    _base = float(_c.iloc[-219:].sum())
    nx_up = (1 + UP_BAND) * _base / (220 - (1 + UP_BAND))
    nx_dn = (1 - DN_BAND) * _base / (220 - (1 - DN_BAND))
    _px = float(_c.iloc[-1])
    _below, _above = _px < now["220日均線"] * (1 - DN_BAND), _px > now["220日均線"] * (1 + UP_BAND)
    _ln = lambda tip, inner: (f"<div title='{tip}' style='margin-top:5px;padding:2px 7px;background:#fff3c4;border-left:4px solid #f0a500;border-radius:4px;"
                              f"font-size:13px;font-weight:800;line-height:1.45'>{inner}</div>")
    nx_up_t = f"▶ 明日收盤 ≥ {nx_up:,.0f}({nx_up / _px - 1:+.1%})即站上 MA220+{UP_BAND * 100:g}%" + (",不必賣" if _below else "")
    nx_dn_t = f"▶ 明日收盤 < {nx_dn:,.0f}({nx_dn / _px - 1:+.1%})即跌破 MA220−{DN_BAND * 100:g}%"
    _r = lambda t: f"<span style='display:inline;font-size:13px;color:#c62828'>{t}</span>"
    _g = lambda t: f"<span style='display:inline;font-size:13px;color:#2e7d32'>{t}</span>"
    nx_html = (_ln(nx_up_t, _r(f"▶ 明日≥{nx_up:,.0f} 站上+{UP_BAND * 100:g}%")) if _below else
               _ln(nx_dn_t, _g(f"▶ 明日<{nx_dn:,.0f} 跌破−{DN_BAND * 100:g}%")) if _above else
               _ln(nx_up_t + "|" + nx_dn_t, "▶ 明日" + _r(f"≥{nx_up:,.0f}買") + "｜" + _g(f"<{nx_dn:,.0f}賣")))
    nx_line = ("\n    " + nx_up_t.replace("▶ ", "") if _below else "\n    " + nx_dn_t.replace("▶ ", "") if _above
               else "\n    " + nx_up_t.replace("▶ ", "") + "\n    " + nx_dn_t.replace("▶ ", ""))
    tr_txt, tr_col, tr_note = ma_trend(m["220日均線"])
    tr_html = (f"<span title='{tr_note}' style='display:inline;font-size:15px;font-weight:700;margin-left:8px;color:{tr_col}'>年線{tr_txt}</span>" if tr_txt else "")
    _dk, _dd = model._kd(df.High.to_numpy(), df.Low.to_numpy(), df.Close.to_numpy())
    _dst = ["黃金交叉" if a > b else "死亡交叉" if a < b else "" for a, b in zip(_dk, _dd)]
    runs = {"日": cross_run(_dst), "週": cross_run(m["週KD"]), "月": cross_run(m["月KD"])}
    run_txt = lambda n: ("" if not runs[n][0] else f"連{'≥' if runs[n][1] else ''}{runs[n][0]}日")
    kd_run_html = {n: (f' <small style="display:inline;font-size:12px">{run_txt(n)}</small>' if run_txt(n) else "") for n in runs}
    fx_card, fx_rows = fx.card(20)                         # 美元兌台幣 + 近 20 日小走勢圖(整合進收盤卡片);抓不到時顯示『暫無資料』
    fx_html = ("<div style='margin-top:10px;font-size:12px;color:var(--mut);font-weight:400'>美元兌台幣 USD/TWD</div>"
               "<div style='font-size:18px;font-weight:700'>" + fx_card[1].replace("<small>數字上升 = 台幣貶值</small>", "") + "</div>")
    cards = [(f"收盤(收盤日 {m.index[-1]:%Y-%m-%d})", f"{num(now['台股收盤價'])}{chg_html}<div style='margin-top:10px'>{inst.html(inst_data)}</div>"), ("Z-SCORE(480天)", f"{z:.2f}<small>{zread}</small><small>Z低檔 {lo:.2f}｜Z高檔 {hi:.2f}</small><small style='margin-top:8px'>MAD ZSCORE <i style='font-style:normal;font-weight:700;font-size:16px'>{now['MAD ZSCORE']:.2f}</i></small><small>MAD 低檔 {now['MAD 低檔']:.2f}｜高檔 {now['MAD 高檔']:.2f}</small>"),
             ("MAD ZSCORE", f"{now['MAD ZSCORE']:.2f}<small>低 {now['MAD 低檔']:.2f}|高 {now['MAD 高檔']:.2f}</small>"),
             ("220日線 ±", f"{ma_lab}{tr_html}<small>{ma_note.replace('|', '<br>')}</small>{nx_html}<small>MA220 {num(now['220日均線'])}</small><small>生命線 60×3%:{now['生命線60*3%'] or '—'}</small>"),
             ("季線 / 年線乖離", f"{pct(now['季線乖離'])} / {pct(now['年線乖離'])}"),
             ("5年 / 10年線乖離", f"{pct(now['5年線乖離%'])} / {pct(now['10年線乖離%'])}<small>歷史均值 5年 {pct(now['5-AVG'])}|10年 {pct(now['10-AVG'])}</small>")]
    buy9 = [c for c in XCOLS[:9] if now[c] == "BUY"]
    cards.append(("5>10 ~ 80>90天Z 的 BUY 數", f"{len(buy9)} / 9<small>{'、'.join(c.replace('天Z', '') for c in buy9) or '目前沒有 BUY'}|全部 12 欄:{sum(now[c] == 'BUY' for c in XCOLS)} 個</small>"))
    yr = df[df.index > df.index[-1] - pd.DateOffset(years=1)]                       # 近一年(含最新一天)
    hi_px, hi_dt = yr["High"].max(), yr["High"].idxmax()
    dd = now["台股收盤價"] / hi_px - 1
    _aft = df.loc[hi_dt:]                                                           # 高點以來(含當天)的最低點
    lo_px, lo_dt = _aft["Low"].min(), _aft["Low"].idxmin()
    lo_dd = lo_px / hi_px - 1
    trend = trend_state(m, dd, mc, k["週"]["state"], run_txt("週"))
    # 落底指標:台股 6 次一般股災(2011/2015/2018/2020/2022/2025,剔除 2000/2008)的平均底部 vs 目前
    #   達成=到平均;接近=到平均的 85%(跌幅/乖離為平均×0.85;月 K 越低越接近底,門檻為平均÷0.85)
    _cl_now = float(m["台股收盤價"].iloc[-1]); _c250 = m["台股收盤價"].iloc[-250:]; _hi1 = float(_c250.max())
    _wave_low = float(m["最低價"].loc[_c250.idxmax():].min())        # 一年高點之後的最低價(盤中)
    _wave_dev = float((m["最低價"] / m["220日均線"] - 1).loc[_c250.idxmax():].min())   # 一年高點之後,最低價對 MA220 的最大負乖離
    _ma_now = float(now["220日均線"])
    BOTTOM = [("最低價跌幅", _wave_low / _hi1 - 1, -CRASH_AVG["台股"][0], "pct"), ("最低價乖離", _wave_dev, -0.204, "pct"),
              ("動態週K", float(k["週"]["K"]), 12.4, "k"), ("動態月K", float(k["月"]["K"]), 32.6, "k"), ("已收完月K", float(mc["K"]), 37.8, "k"),
              ("Z-SCORE<0", float(z), 0.0, "z")]
    for nm in ("那斯達克", "費半"):                            # 美股科技:本波跌幅 vs 一般股災平均
        if nm in CRASH_DD: BOTTOM.append((f"{nm}跌幅", CRASH_DD[nm], -CRASH_AVG[nm][0], "pct"))
    _rows, _n1, _n2 = [], 0, 0
    for nm, v, avg, kind in BOTTOM:
        if kind == "pct":
            th = avg * 0.85; hit, near = v <= avg, v <= th; f = lambda x: f"{x:.1%}"
        elif kind == "z":
            th = None; hit = near = v < 0; f = lambda x: f"{x:.2f}"
        else:
            th = avg / 0.85; hit, near = v <= avg, v <= th; f = lambda x: f"{x:.1f}"
        _n1 += hit; _n2 += near
        _rows.append(f"<tr><td>{nm}</td><td style='font-weight:700'>{f(v)}</td><td>{'&lt;0' if kind == 'z' else f(avg)}</td><td>{'—' if th is None else f(th)}</td>"
                     f"<td class={'y' if hit else 'n'}>{'✔' if hit else '—'}</td><td class={'y' if near else 'n'}>{'✔' if near else '—'}</td></tr>")
    def _rise(col):                                        # K 值比前一日高/低,連續幾日
        d = m[col].diff().dropna().to_numpy(); up = d[-1] > 0; n = 0
        for x in d[::-1]:
            if (x > 0) == up and x != 0: n += 1
            else: break
        return ("<b style='color:#d9534f'>↑上升</b>" if up else "<b style='color:#2e9e5b'>↓下降</b>") + f" 連{n}日"
    _kdr, _ng = [], 0
    for n in ("週", "月"):
        v = k[n]; g = "黃金" in v["state"] or "金叉" in v["state"]; _ng += g
        _kdr.append(f"<tr><td>動態{n}KD</td><td>{v['K']:.1f} / {v['D']:.1f}</td><td style='color:{'#d9534f' if g else 'var(--mut)'};font-weight:700'>{'金叉' if g else '死叉'}</td>"
                    f"<td>{run_txt(n) or '—'}</td><td>{_rise(n + 'K')}</td><td class={'y' if g else 'n'}>{'✔' if g else '—'}</td></tr>")
    # 止跌訊號(2009~2026 回測):動態週K連續上升 3 日 + 距高點跌幅 ≤ −20% + MA220 乖離 ≤ −10%
    #   嚴格=三項同一天成立(5 次,4 次之後 60 日沒再跌超過 3%);寬鬆=跌幅/乖離近 5 日內曾達標(9 次,含 2025/04/25)
    _wk = m["週K"].to_numpy(); _wr = 0
    for _i in range(len(_wk) - 1, 0, -1):
        if _wk[_i] > _wk[_i - 1]: _wr += 1
        else: break
    _cs = m["台股收盤價"]; _dvS = _cs / m["220日均線"] - 1; _wdd = _wave_low / _hi1 - 1      # 跌幅=一年高點後最低價
    _s1 = _wr >= 3 and _wdd <= -0.20 and _dvS.iloc[-1] <= -0.10
    _s2 = _wr >= 3 and _wdd <= -0.20 and _dvS.iloc[-6:].min() <= -0.10
    _ok = lambda b: "<b style='color:#d9534f'>✔</b>" if b else "<span style='color:var(--mut)'>—</span>"
    _stop_html = ("<div style='margin-top:5px;padding:3px 6px;border-radius:6px;background:" + ("#fde2e1" if (_s1 or _s2) else "var(--bg)") + ";font-size:12px' "
                  "title='跌幅=近一年最高收盤後的最低價(盤中)。回測 2009~2026:嚴格版 8 次訊號(含 2025/04/25),62% 之後 60 日內沒再跌超過 3%,20 日後平均 +6.1%、勝率 88%;寬鬆版 9 次,67%。訊號通常比最低點晚 2 天~2 週'>"
                  f"<b>🚦 止跌訊號</b> 週K連升 <b>{min(_wr, 3)}/3</b> 日・跌幅≤−20% {_ok(_wdd <= -0.20)}・乖離≤−10% {_ok(_dvS.iloc[-1] <= -0.10)}"
                  f"<br>嚴格(今日乖離) {_ok(_s1)}　寬鬆(近5日乖離) {_ok(_s2)}</div>")
    calc = calc_html(df, mc["K"], {"up": UP_BAND, "dn": DN_BAND, "left": [x for x, _ in LEFT_MA],
                                   "a_dd": -CRASH_AVG["台股"][0], "a_dv": -0.204, "a_wk": 12.4, "a_mk": 32.6, "a_ck": 37.8})
    mk_html = ("<div class=mkb title='平均=台股 2011、2015、2018、2020、2022、2025 六次一般股災的底部平均(不含 2000/2008 長空頭)。跌幅、乖離都以一年高點後的最低價計(會保留波段最深值);動態週K平均 12.4。"
               "85% 門檻:跌幅與乖離=平均×0.85;月 K 越低越接近底,門檻=平均÷0.85。僅供參考,長空頭會遠超過平均'>"
               f"<b>🎯 台股落底指標</b> <span>達成平均 {_n1}/{len(BOTTOM)}・達成85% {_n2}/{len(BOTTOM)}・金叉 {_ng}/2</span>"
               "<div class=mkg><div><table><tr><th>指標</th><th>目前</th><th>平均</th><th>85%</th><th>達平均</th><th>達85%</th></tr>"
               + "".join(_rows) + "</table></div><div>"
               + _stop_html +
               "<table style='margin-top:4px'><tr><th>動態KD</th><th>K / D</th><th>狀態</th><th>連續</th><th>K vs 前日</th><th>金叉</th></tr>"
               + "".join(_kdr) + "</table></div></div></div>")
    row = lambda p: f"<div class=lvr><span>-{p}%</span><i>→</i><em>{hi_px * (1 - p / 100):,.0f}</em></div>"
    _mg = closed_month_gold(df)
    _extra = []
    for _ in range(4):                                  # 全部買回日會開新的一段 → 反覆計算到買回日期不再改變
        wok, wfirst, (wstart, wstart_ma), wall, wsid = warn_state(m, _extra)
        cyc = exit_cycle(m, wall, wsid, _mg)
        if cyc["backs"] == _extra:
            break
        _extra = cyc["backs"]
    cyl = cycle_lines(cyc, z)
    insl = ins_lines(cyc)
    _tip = "\n".join(cyl).replace("'", "")
    cyl_html = (f"<br><span title='{_tip}' style='display:inline;font-size:11px;font-weight:700;color:#ffd60a'>{cycle_short(cyc)}</span>" if cyl and (cyc["state"] != "持有" or not all(wok))
                else "<br>(目前已達 6/6,請開始執行)" if all(wok) else "")
    mk = lambda ok: "✔" if ok else "✖"
    wlines = (f"{mk(wok[0])} 本段曾 Z>1.5　{mk(wok[1])} 9 欄曾全 BUY<br>{mk(wok[2])} BUY 數≤3(現 {int(sum(now[c] == 'BUY' for c in XCOLS[:9]))})　{mk(wok[3])} 週月 KD 雙死叉<br>{mk(wok[4])} 本段 5 年乖離曾>15%(現 {pct(now['5年線乖離%'])})<br>{mk(wok[5])} 本段 90>120、120>150、150>180 曾同時全 BUY")
    wnote = ((f"本段自 {wstart:%Y-%m-%d} 全部買回重算" if wstart_ma == "buy" else
              f"本段自 {wstart:%Y-%m-%d} 站回 MA{model.SEG_MA}" if wstart_ma == "ma" else f"本段自 {wstart:%Y-%m-%d} Z 上穿 {model.SEG_RESET_Z:g}")
             if wstart is not None else "Z 目前在 0 以下") + (f"|首次 6/6:{wfirst:%Y-%m-%d}" if wfirst is not None and all(wok) else "")
    cards.append(("過熱轉弱警示", f"{sum(wok)} / 6{'　⚠' if all(wok) else ''}<small>{wlines}</small><small>{wnote}</small><div class='ptip{' hot' if all(wok) else ''}'>⚠ 6/6 成立須轉出：一半反1(00632R)、一半中華電!!{cyl_html}</div>"))
    cards.append(("近一年最高價", f"{hi_px:,.2f}<small>{hi_dt:%Y-%m-%d}|目前收盤距高點 <b style='color:{'#d9534f' if dd < 0 else 'inherit'}'>{dd:+.1%}</b></small>" + (f"<small>高點後最低 {lo_px:,.2f}({lo_dt:%Y-%m-%d})|最大跌幅 <b style='color:#d9534f'>{lo_dd:+.1%}</b></small>" if lo_dd < 0 else "")))
    cards.append(("距高點下跌 10~25% 對應指數", "".join(row(p) for p in (10, 15, 20, 25))))
    cards.append(("距高點下跌 30~40% 對應指數", "".join(row(p) for p in (30, 35, 40))))
    # 卡片排序(依你的箭頭):第一排 收盤、Z-SCORE、220日線、BUY 數、近一年最高價;第二排 季年線乖離、5/10年乖離、下跌對應指數 兩格、MAD
    assert len(cards) == 11
    cards = [cards[i] for i in (0, 7, 3, 1, 6, 8, 4, 5, 9, 10, 2)]     # 第一排:收盤、過熱轉弱警示、220日線、Z-SCORE、BUY 數
    # Z-SCORE 卡片整合三組數字(Z-SCORE / MAD ZSCORE / BUY 數),各用不同顏色與編號分區,避免看錯
    def zsec(color, label, big, lines):
        return (f"<div class=zsec style='border-left-color:{color}'><i class=zlab style='color:{color}'>{label}</i>"
                f"<i class=zbig>{big}</i>{''.join(f'<small>{x}</small>' for x in lines)}</div>")
    _cl = m["台股收盤價"].tolist(); _px = now["台股收盤價"]
    zlv = [(t, z_level(_cl, t)) for t in (0.0, 0.5)]
    zlv_html = ("<span style='display:inline-block;margin-left:10px;vertical-align:middle;font-size:11px;line-height:1.35;font-weight:700;color:#1f6feb' "
                "title='收盤要到約這個價位,480 日 Z-SCORE 才會等於 0(右側先決條件)或 0.5(本段重算門檻);每天重算'>"
                + "<br>".join(f"{'Z≤0' if t == 0 else 'Z=0.5'} ≈ {v:,.0f} <span style='display:inline;font-size:11px;color:#d9534f'>{v / _px - 1:+.1%}</span>" for t, v in zlv)
                + "</span>")
    zhtml = (zsec("#1f6feb", "① Z-SCORE(480天)", f"{z:.2f}{zlv_html}", [zread, f"Z低檔 {lo:.2f}｜Z高檔 {hi:.2f}"])
             + zsec("#8250df", "② MAD ZSCORE", f"{now['MAD ZSCORE']:.2f}", [f"MAD 低檔 {now['MAD 低檔']:.2f}｜高檔 {now['MAD 高檔']:.2f}"])
             + zsec("#d97706", "③ BUY 數(5>10 ~ 80>90 共 9 欄)", f"{len(buy9)} / 9",
                    ['、'.join(c.replace('天Z', '') for c in buy9) or '目前沒有 BUY', f"全部 12 欄:{sum(now[c] == 'BUY' for c in XCOLS)} 個"]))
    # ④ 動態 KD 摘要(與下方「日 / 週 / 月 動態 KD」表同一份資料,只是複製一份到上方)
    def kdline(n, v):
        col = "#d9534f" if v["state"] == "黃金交叉" else "#2e9e5b" if v["state"] == "死亡交叉" else "var(--mut)"
        tip = f"{n}KD K {v['K']:.1f}|D {v['D']:.1f}|K 合理低檔~高檔 {v['low']:.1f}~{v['high']:.1f}" + (f"|{v['zone']}" if v["zone"] else "")
        return (f"<div title='{tip}' style='display:flex;justify-content:space-between;gap:4px;font-size:12px;font-weight:700;line-height:1.55;white-space:nowrap'>"
                f"<span style='display:inline;font-size:12px;color:var(--fg)'>{n}KD {v['K']:.1f}/{v['D']:.1f}</span>"
                f"<span style='display:inline;font-size:12px;color:{col}'>{v['state']}{(' ' + run_txt(n)) if run_txt(n) else ''}</span></div>")
    zhtml += ("<div class=zsec style='border-left-color:#00897b'><i class=zlab style='color:#00897b'>④ 日 / 週 / 月 動態KD</i>"
              + "".join(kdline(n, v) for n, v in k.items()) + "</div>")
    zi = next(k for k, c in enumerate(cards) if c[0] == "Z-SCORE(480天)")
    cards[zi] = ("Z-SCORE 區(①藍 ②紫 ③橘 ④綠)", zhtml)
    cards = [c for c in cards if not c[0].startswith("5>10 ~ 80>90天Z")]
    # 220日線卡片整合四組數字(220日線訊號 / 近一年最高價 / 季年線乖離 / 5·10年線乖離),各用不同顏色與編號分區
    def wrapsec(color, label, html):
        return f"<div class=zsec style='border-left-color:{color}'><i class=zlab style='color:{color}'>{label}</i>{html}</div>"
    byt = {c[0]: c[1] for c in cards}
    ma_color = {"BUY": "#c62828", "SELL": "#2e7d32"}.get(ma_lab, "#1565c0")
    mhtml = (wrapsec(ma_color, "① 220日線 訊號", byt["220日線 ±"])
             + wrapsec("#0f9d8f", "② 近一年最高價", byt["近一年最高價"])
             + wrapsec("#c2185b", "③ 季線 / 年線乖離", byt["季線 / 年線乖離"])
             + wrapsec("#6d4c41", "④ 5年 / 10年線乖離", byt["5年 / 10年線乖離"]))
    mi = next(k for k, c in enumerate(cards) if c[0] == "220日線 ±")
    cards[mi] = ("220日線區(①~④ 分區顯示)", mhtml)
    cards = [c for c in cards if c[0] not in ("近一年最高價", "季線 / 年線乖離", "5年 / 10年線乖離")]
    # 美元兌台幣(含小走勢圖)移到「過熱轉弱警示」卡片下方,讓收盤卡片不要太長
    _w = next(k for k, c in enumerate(cards) if c[0] == "過熱轉弱警示")
    # 已收完月 K(日曆月,當月未過完不算):放在警示紅框下方、美元兌台幣上方
    _mc_col = "#d9534f" if mc["state"] == "黃金交叉" else "#2e9e5b" if mc["state"] == "死亡交叉" else "inherit"
    # 注意:卡片 CSS 有 .card span{display:block},所以這裡的 span 都要寫 display:inline
    # 寫成一行,並把美元兌台幣小走勢圖從 44px 壓到 26px,讓這張卡片總高度幾乎不變(不撐高第一排)
    # 一行顯示日期、交叉、K、D;12px 會超出卡片 232px 的內寬(208px),所以用 11px(實測約 201px)
    _s = "display:inline;font-size:11px"
    mc_html = (f"<div style='margin-top:6px;font-size:11px;font-weight:700;white-space:nowrap'>"
               f"<span style='{_s};font-weight:400;color:var(--mut)'>已收完月K {mc['date']:%m/%d}</span> "
               f"<span style='{_s};color:{_mc_col}'>{mc['state'] or '—'}</span> K {mc['K']:.1f} "
               f"<span style='{_s};font-weight:400;color:var(--mut)'>D {mc['D']:.1f}</span></div>")
    fx_html = re.sub(r"height:\s*44px", "height:26px", fx_html)                 # fx.py 小走勢圖原本 44px
    cards[_w] = (cards[_w][0], cards[_w][1] + mc_html + "<div style='margin-top:10px;border-top:1px solid var(--line);padding-top:2px'>" + fx_html + "</div>")
    # 距高點下跌 10~25% 與 30~40% 合併成一張(-10% ~ -40%)
    _i1 = next(k for k, c in enumerate(cards) if c[0].startswith("距高點下跌 10~25%"))
    _i2 = next(k for k, c in enumerate(cards) if c[0].startswith("距高點下跌 30~40%"))
    cards[_i1] = ("距高點下跌 10~40% 對應指數", cards[_i1][1] + cards[_i2][1])
    del cards[_i2]
    cards.insert(4, usma.card())                           # 美股四大指數 MA 通道狀態:放第一排最右邊(原 BUY 數卡片的位置)
    cards = [c for c in cards if c[0] != "MAD ZSCORE"]            # MAD 已整合進 Z-SCORE 卡片
    cards.append(("最高價回檔對應價(輸入最高價)", "<div class=cin><label>最高價<input id=cph type=number inputmode=decimal step=any value='" + f"{hi_px:.2f}" + "' aria-label='最高價'></label></div>" + "".join(f"<div class=lvr2 style='grid-template-columns:3em 1fr'><span>-{p}%</span><em id=ch{p}>—</em></div>" for p in range(10, 90, 10))))
    cards.append(("跌 2~20% 對應價(輸入股價)", "<div class=cin><label>股價<input id=cpy type=number inputmode=decimal step=any value='" + f"{now['台股收盤價']:.2f}" + "' aria-label='股價'></label></div>" + "".join(f"<div class=lvr2 style='grid-template-columns:3em 1fr'><span>-{p}%</span><em id=cy{p}>—</em></div>" for p in range(2, 22, 2))))
    crow = lambda p: f"<div class=lvr2><span>-{p}%</span><em id=cx{p}>—</em><u id=cs{p}>—</u></div>"
    chead = "<div class=lvr2 style='font-size:11px;color:var(--mut)'><span>跌幅</span><em>價格</em><u>可買股數</u></div>"
    cards.append(("跌幅對應價與可買股數", f"<div class=cin><label>可用資金<input id=ccap type=number inputmode=decimal step=any placeholder='例:1000000' aria-label='可用資金'></label><label>股價<input id=cpx type=number inputmode=decimal step=any value='{now['台股收盤價']:.2f}' aria-label='股價'></label></div>{chead}{''.join(crow(p) for p in range(5, 45, 5))}"))
    cards.append(("跌幅對應價與可買股數(續)", chead + "".join(crow(p) for p in range(45, 65, 5)) + "<small>股數 = 可用資金 ÷ 對應價(無條件捨去,不含手續費)</small>"))
    wcls = "w3" if all(wok) else "w2" if sum(wok) >= 4 else "w1"                   # 警示卡底色:全中=紅、4~5 項=黃、其餘=綠
    mcls = {"BUY": "m_buy", "SELL": "m_sell"}.get(ma_lab, "m_mid")                  # 220日線底色:BUY=紅(台股慣例)、SELL=綠、其餘=藍灰
    _pal = ["#1565c0", "#0f9d8f", "#c2185b", "#e08a00", "#7b3fc9"]
    cards_html = "".join(
        f"<div class='card{' ' + wcls if a == '過熱轉弱警示' else ' ' + mcls if a.startswith('220日線') else ''}'>"
        f"<span class=ct style='color:{_pal[k % 5]};border-bottom-color:{_pal[k % 5]}'>{a}</span><b>{b}</b></div>"
        for k, (a, b) in enumerate(cards))
    kd_rows = "".join(
        f"<tr><td>{n}KD</td><td>{v['K']:.1f}</td><td>{v['D']:.1f}</td><td>{v['low']:.1f} ~ {v['high']:.1f}</td>"
        f"<td class='{'hi' if v['zone'] == 'K值高檔' else 'lo' if v['zone'] == 'K值低檔' else ''}'>{v['zone'] or '—'}</td><td class='{'gold' if v['state'] == '黃金交叉' else 'dead' if v['state'] == '死亡交叉' else ''}'>{v['state']}{kd_run_html[n]}</td></tr>"
        for n, v in k.items())

    cols = ["開盤價", "最高價", "最低價", "台股收盤價", "20日均線", "60日均線", "220日均線", "240日均線",
            "生命線60*3%", "BUY(220日)2%", "SELL(220日)1%", "季線乖離", "年線乖離", "5年線乖離%", "10年線乖離%",
            "Z-SCORE", "Z低檔", "Z高檔", "Z方向", "MAD ZSCORE"] + ZCOLS + XCOLS + ["週KD", "月KD"]
    head = "".join(f"<th class='{'xh xc' if c in XCOLS else ''}'>{c.replace('台股', '')}</th>" for c in ["日期"] + cols)
    body = ""
    for d, r in m.iloc[::-1].head(TABLE_DAYS).iterrows():
        body += f"<tr class=r><td>{d:%Y-%m-%d}</td>{''.join(cell(c, r) for c in cols)}</tr>"

    c1 = chart(m.tail(CHART_DAYS), [("台股收盤價", "#1f77b4", 1.5, None), ("20日均線", "#f0ad4e", 1, None), ("60日均線", "#8e44ad", 1, None),
                                   ("220日均線", "#d9534f", 1.4, None), ("240日均線", "#2e9e5b", 1.4, None)], "台股加權指數 與均線")
    c2 = chart(m.tail(CHART_DAYS), [("Z-SCORE", "#1f77b4", 1.6, None), ("Z高檔", "#d9534f", 1, "dot"), ("Z低檔", "#2e9e5b", 1, "dot")], "480天 Z-SCORE 與動態高低檔")
    c3 = chart(m.tail(CHART_DAYS), [("MAD ZSCORE", "#1f77b4", 1.6, None), ("MAD 高檔", "#d9534f", 1, "dot"), ("MAD 低檔", "#2e9e5b", 1, "dot")], "MAD ZSCORE 與動態高低檔")
    c4 = zchart(m)
    c5 = chart(m.tail(CHART_DAYS), [("週K", "#1f77b4", 1.5, None), ("週D", "#f0ad4e", 1.5, None), ("週K高檔", "#d9534f", 1, "dot"), ("週K低檔", "#2e9e5b", 1, "dot")], "動態週 KD(K、D 與 K 合理高低檔)", 360)
    c6 = chart(m.tail(CHART_DAYS), [("月K", "#1f77b4", 1.5, None), ("月D", "#f0ad4e", 1.5, None), ("月K高檔", "#d9534f", 1, "dot"), ("月K低檔", "#2e9e5b", 1, "dot")], "動態月 KD(K、D 與 K 合理高低檔)", 360)
    ma_html, _ = ma_channel(m)
    stamp = datetime.now(TPE)
    rk = rule_checks(cyc)
    page = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>480天 Z-SCORE 與日週月動態 KD</title><style>
:root{{--bg:#fff;--fg:#222;--mut:#666;--card:#f4f6f8;--line:#e3e3e3;--hi:#fde8e8;--pk:#fde0ec;--gr:#dcf3e4}}
@media(prefers-color-scheme:dark){{:root{{--bg:#14161a;--fg:#e6e6e6;--mut:#999;--card:#22262d;--line:#333;--hi:#4a2326;--pk:#5a2a3f;--gr:#1f3b2a}}}}
body{{font-family:system-ui,"Noto Sans TC",sans-serif;max-width:1200px;margin:0 auto;padding:16px;background:var(--bg);color:var(--fg)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}}.card{{background:var(--card);border-radius:8px;padding:10px 12px}}
.card.m_buy{{background:#fdecea;box-shadow:inset 0 0 0 2px #e0857c}}.card.m_sell{{background:#e5f4ea;box-shadow:inset 0 0 0 2px #8fcba5}}.card.m_mid{{background:#e8f0fb;box-shadow:inset 0 0 0 2px #9db9e3}}
.card.w3{{background:#fdecea;box-shadow:inset 0 0 0 2px #e0857c}}.card.w2{{background:#fff4d6;box-shadow:inset 0 0 0 2px #e3bd52}}.card.w1{{background:#e5f4ea;box-shadow:inset 0 0 0 2px #8fcba5}}
@media(prefers-color-scheme:dark){{.card.m_buy{{background:#4a2326;box-shadow:inset 0 0 0 2px #b9534b}}.card.m_sell{{background:#1f3b2a;box-shadow:inset 0 0 0 2px #3f8a5c}}.card.m_mid{{background:#1f2f4a;box-shadow:inset 0 0 0 2px #4a6fa5}}.card.w3{{background:#4a2326;box-shadow:inset 0 0 0 2px #b9534b}}.card.w2{{background:#4a3d1c;box-shadow:inset 0 0 0 2px #a98a2e}}.card.w1{{background:#1f3b2a;box-shadow:inset 0 0 0 2px #3f8a5c}}}}
.card .usr{{display:grid;grid-template-columns:1fr auto;column-gap:6px;margin:4px 0 14px;font-weight:400}}.card .usr b{{font-size:17px}}.card .usr b span{{font-size:13px!important}}.card .usr em{{font-style:normal;font-weight:700;font-size:17px;text-align:right}}.card .usr small{{grid-column:1/3;font-size:13.5px;color:var(--mut);line-height:1.45}}
.card .ptip{{margin-top:8px;padding:6px 8px;border-radius:6px;background:#c1121f;color:#fff;font-size:13px;font-weight:800;line-height:1.4;border:2px solid #ffd60a}}.card .ptip.hot{{animation:ptipb 1.6s ease-in-out infinite}}@keyframes ptipb{{50%{{background:#ff6b00}}}}@media(prefers-reduced-motion:reduce){{.card .ptip.hot{{animation:none}}}}
.card .zsec{{border-left:5px solid;padding:2px 0 3px 8px;margin:8px 0 6px;border-radius:2px}}.card .zlab{{display:block;font-style:normal;font-size:12px;font-weight:800}}.card .zbig{{display:block;font-style:normal;font-size:22px;font-weight:700;line-height:1.25}}
.cin{{display:flex;gap:6px;margin:4px 0 6px}}.cin label{{flex:1;min-width:0;font-size:11px;font-weight:400;color:var(--mut)}}.cin input{{width:100%;box-sizing:border-box;font-size:16px;font-weight:700;padding:4px 6px;border:1px solid var(--mut);border-radius:6px;background:transparent;color:inherit}}
.lvr2{{display:grid;grid-template-columns:3em 1fr 1fr;gap:4px;font-size:14px;font-weight:400;line-height:1.6;font-variant-numeric:tabular-nums}}.lvr2 em{{font-style:normal;font-weight:700;text-align:right}}.lvr2 u{{text-decoration:none;text-align:right;color:var(--mut)}}
.card span{{display:block;font-size:12px;color:var(--mut)}}.card>span.ct{{font-size:15px;font-weight:800;padding-bottom:4px;margin-bottom:6px;border-bottom:2px solid;line-height:1.3}}.card b{{font-size:20px}}.lvr{{display:grid;grid-template-columns:3.4em 1.6em 1fr;font-size:14px;font-weight:400;line-height:1.55;font-variant-numeric:tabular-nums}}.lvr span{{color:var(--mut)}}.lvr i{{font-style:normal;color:var(--mut)}}.lvr em{{font-style:normal;font-weight:700;text-align:right;padding-right:30%}}.card small{{display:block;font-size:12px;font-weight:400;color:var(--mut)}}
.hd{{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}}.hl{{flex:1 1 520px;min-width:0}}.memo{{flex:0 1 330px;min-width:240px;margin-top:2px}}.memo .mh{{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;font-size:14px}}.memo textarea{{width:100%;box-sizing:border-box;height:122px;resize:vertical;font:inherit;font-size:14px;line-height:1.6;padding:8px 10px;border:2px solid #f2b705;border-radius:8px;background:var(--card);color:var(--fg)}}.memo button{{font:inherit;font-size:12px;padding:3px 10px;border:1px solid var(--mut);border-radius:6px;background:transparent;color:var(--fg);cursor:pointer}}.mkg{{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}}.mkg>div{{flex:0 1 auto;min-width:0}}.mkb{{flex:0 1 auto;box-sizing:border-box;border:2px solid #1a5fb4;border-radius:8px;padding:3px 9px;background:var(--card);font-size:12px}}.mkb table{{font-size:11.5px;margin-top:2px;border-collapse:collapse}}.mkb th,.mkb td{{padding:2px 3px;white-space:nowrap;border-bottom:1px solid var(--line)}}.mkb span{{font-size:11px;color:#d9534f;font-weight:700}}.mkb td.y{{color:#d9534f;font-weight:800;text-align:center}}.mkb td.n{{text-align:center}}.mkb td.n{{color:var(--mut)}}.pkb{{margin-top:4px;padding-top:3px;border-top:1px dashed var(--line);font-size:11.5px;width:0;min-width:100%;line-height:1.5}}.calc{{margin-top:8px;box-sizing:border-box;border:2px solid #16a085;border-radius:8px;padding:4px 9px;background:var(--card);font-size:12px}}.calc span{{color:var(--mut);font-size:11px;margin-left:4px}}.calc .cin{{display:flex;gap:4px 10px;flex-wrap:wrap;margin:5px 0;align-items:center}}.calc label{{width:auto!important;flex:0 0 auto;display:inline-flex;align-items:center;gap:4px;margin:0;font-size:12px;white-space:nowrap}}.calc input{{box-sizing:border-box;width:76px!important;min-width:0;flex:0 0 76px;padding:3px 5px;font-size:13px;border:1px solid var(--line);border-radius:5px}}.calc button{{padding:4px 12px;border-radius:5px;border:1px solid #16a085;background:#16a085;color:#fff;font-weight:700}}.cres div{{margin:3px 0;line-height:1.45}}.cres table{{border-collapse:collapse;margin:3px 0;font-size:11.5px}}.cres th,.cres td{{padding:1px 5px;border-bottom:1px solid var(--line);white-space:nowrap}}.cres .s3{{padding:2px 5px;border-radius:5px}}.t5b{{margin-top:8px;box-sizing:border-box;overflow-x:auto;border:2px solid #c0392b;border-radius:8px;padding:3px 8px;background:var(--card);font-size:12px}}.t5b table{{font-size:11px;margin-top:2px;border-collapse:collapse}}.t5b th,.t5b td{{padding:2px 3px;border-bottom:1px solid var(--line);white-space:nowrap;text-align:right}}.t5b td:first-child,.t5b th:first-child{{text-align:left}}.t5b small{{color:var(--mut);margin-left:3px;font-size:10px}}.crash{{flex:0 0 auto;box-sizing:border-box;border:2px solid #8e44ad;border-radius:8px;padding:3px 8px;background:var(--card);font-size:12px}}.crash span{{color:var(--mut);font-size:10.5px;margin-left:4px}}.crash table{{font-size:12px;margin-top:2px}}.crash th,.crash td{{padding:1px 4px;border-bottom:1px solid var(--line)}}.hrow{{display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap;flex-wrap:wrap;margin:-6px 0 -4px}}.hrow h1{{margin:0}}.devb{{flex:0 0 auto;box-sizing:border-box;border:2px solid #1a5fb4;border-radius:8px;padding:3px 9px;font-size:11.5px;line-height:1.4;background:var(--card)}}.devb b.t{{font-size:12.5px}}.devb .g{{display:grid;grid-template-columns:auto auto;column-gap:14px}}.devb .g div{{display:flex;justify-content:space-between;gap:8px}}.devb i{{font-style:normal;color:var(--mut)}}.devb .x{{color:#d9534f;font-weight:700}}.rules{{flex:0 1 290px;min-width:250px;max-width:300px;box-sizing:border-box;border:2px solid #d9534f;border-radius:8px;padding:3px 9px;font-size:11.5px;line-height:1.4;background:var(--card)}}.rules b.t{{font-size:12.5px}}.rules span{{color:var(--mut)}}
table{{border-collapse:collapse;font-size:13px;width:100%}}th,td{{padding:4px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}.wrap{{overflow-x:auto}}.wrap td:first-child,.wrap th:first-child{{position:sticky;left:0;background:var(--bg)}}td.hi{{background:var(--hi)}}td.pk{{background:var(--pk)}}td.gr{{background:var(--gr)}}.neg{{color:#d9534f;font-weight:700}}th.xh{{background:#ffe3a3;color:#222}}
p.n{{color:var(--mut);font-size:13px}}.gold{{color:#d9534f;font-weight:700}}.dead{{color:#2e9e5b;font-weight:700}}
.status{{background:var(--card);padding:8px 12px;border-radius:6px;font-size:14px}}tr.buy td:nth-child(2){{color:#d9534f;font-weight:700}}
tr.sell td:nth-child(2){{color:#2e9e5b;font-weight:700}}summary{{cursor:pointer;margin:8px 0;font-weight:600}}{CSS2}{CSS_TREND}{CSS_INS}</style></head><body>
<div class=hd><div class=hl>
<nav style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 10px">
<h1 style="margin:0 6px 0 0;font-size:22px;white-space:nowrap">480天 Z-SCORE 與日週月動態 KD</h1>
<span style="padding:7px 14px;border-radius:999px;background:#222;color:#fff;font-size:14px;font-weight:600">📈 Z-SCORE 與動態 KD</span>
<a href="https://yopoyuan-star.github.io/MA200-240/" style="padding:7px 14px;border-radius:999px;background:#eef1f5;color:#1a5fb4;font-size:14px;font-weight:600;text-decoration:none">📊 MA220/240 均線訊號(台股/美股) →</a>
<a href="https://yopoyuan-star.github.io/Pyramid-Layout-Spreadsheet/" style="padding:7px 14px;border-radius:999px;background:#eef1f5;color:#1a5fb4;font-size:14px;font-weight:600;text-decoration:none">🔺 金字塔加碼試算 →</a>
<a href="https://www.macromicro.me/collections/46/tw-stock-relative/53117/taiwan-taiex-maintenance-margin" target="_blank" rel="noopener" title="同時開啟:財經M平方 融資維持率 + 玩股網 融資融券" onclick="window.open('https://www.wantgoo.com/stock/margin-trading/exclude-etf/taiex','_blank')" style="padding:7px 12px;border-radius:999px;background:#eef1f5;color:#1a5fb4;font-size:14px;font-weight:600;text-decoration:none">📊 大盤融資 ↗</a></nav>
<div class=hrow>{dev_html}<div class=rules><b class=t>📋 買賣規則</b><span title="目前全部規則:左側 MA220 乖離分批、④ 左側停損、保險 A/B、空手時一半反1(00632R)一半中華電。加權指數(不含息)回測至 2026-11-20:近 20 年 20.0%(回撤 −17.0%)、近 10 年 26.8%(−16.4%)、2002/8 起 18.3%(−22.5%);00632R 2014 年前為模擬;0050 含息每年約再高 3~4%">　近20年年化 20.0%、回撤 −17.0%</span><div title="6/6 本段重算:Z 向上穿越 {model.SEG_RESET_Z:g},或加權指數跌破 {model.SEG_MA} 日線至少 {model.SEG_MA_MIN_BELOW} 個交易日後再站回;或右側全部買回當天">① {rk[0]}<b>轉出</b>:6/6 全成立→<b>一半反1(00632R)、一半中華電</b></div><div title="收盤跌到 MA220 乖離 −15% 買 15%、−20% 再買 15%、−30% 再買 20%(占總資金,左側合計 50%);Z&lt;−2.5 直接補到 50%。舊規則:距一年高點 −10~−30% 分 5 筆 5/7.5/10/12.5/15%">② {rk[1]}<b>左側</b>:{rk[2]}</div><div title="先決(三選一):Z≤0、距一年高點跌 20%、轉出滿 12 個月;成立後已收完月K KD 金叉 → 全部買回。保險(兩種並行):A 收盤跌破買回後最高收盤 20%;B 站上過 MA220 後收盤跌破 MA220×0.99 且年線下彎 → 轉出;轉出後連 3 天站回 MA220 全部買回">③ <b>右側</b>:{rk[3]}跌20%或Z≤0 → {rk[4]}月KD金叉全買</div><div title="收盤跌破左側已買部位平均成本 15% → 左側全部賣出(一半反1(00632R)、一半中華電),本次轉出循環不再做左側,只等右側全部買回">④ {rk[5]}<b>左側停損</b>:{rk[6]}</div></div>{crash}{mk_html}</div>
<p class=n>資料日期:<b>{m.index[-1]:%Y-%m-%d}</b>|頁面更新:{stamp:%Y-%m-%d %H:%M}(台北)|資料來源:臺灣證券交易所 加權指數歷史資料|
<a href="zscore_output.csv">下載最近 {CSV_DAYS} 天完整欄位 CSV</a></p>
</div><div class=memo><div class=mh><b>📝 筆記</b><button type=button id=zmemoclr>清除筆記</button></div><textarea id=zmemo maxlength=3000 placeholder="在這裡做筆記(自動儲存在這個瀏覽器)"></textarea>{top5}{calc}</div></div>
{ins_html(cyc)}
{trend_html(trend, m.index[-1])}
<div class=cards>{cards_html}</div>
<h2>日 / 週 / 月 動態 KD</h2><div class=wrap><table><tr><th>週期</th><th>K</th><th>D</th><th>K 合理低檔 ~ 高檔</th><th>位階</th><th>K 與 D</th></tr>{kd_rows}</table></div>
<p class=n>動態:以最新一天為終點,週 K=5 個交易日、月 K=22 個交易日,KD 取 9 根;黃金交叉 = K&gt;D、死亡交叉 = K&lt;D;「連 N 日」= 目前的交叉狀態已連續 N 個交易日。</p>
{ma_html}
{c1}{c5}{c6}{c4}{c2}{c3}
<h2>最近 {TABLE_DAYS} 個交易日(Z-SCORE &gt; {ZHOT} 粉紅底、&lt; 0 紅字;當天 Z-SCORE 大於某天期 Z-SCORE → 該格粉紅底;收盤高於 20/60/220/240 日線 → 該均線格粉紅、低於 → 淡綠)</h2>
<div class=ctl>顯示列數:<button data-n=60>60</button><button data-n=120>120</button><button data-n=200>200</button>
<span style="margin-left:14px">Z 交叉欄(5&gt;10 … 150&gt;180):</span><button id=xt>隱藏</button></div>
<div class="wrap big"><table id=bigtbl><tr>{head}</tr>{body}</table></div><script>{JS}</script><script>{JS2}</script>
<p class=n>本頁欄位對應 Excel「480天Z-SCORE -2.0」工作表。僅供研究參考,非投資建議。</p>
<div id=tipbox style="display:none;position:fixed;left:8px;right:8px;bottom:12px;z-index:9999;background:#222;color:#fff;font-size:14px;line-height:1.55;padding:10px 34px 10px 12px;border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,.35);white-space:pre-line"></div>
<script>
(function(){{
  // 手機沒有滑鼠:點一下有說明的地方,就在畫面下方顯示說明;再點別處或點說明框關閉
  var box=document.getElementById('tipbox');
  var touch=('ontouchstart' in window)||navigator.maxTouchPoints>0;
  if(!touch) return;
  document.querySelectorAll('[title]').forEach(function(el){{
    if(el.closest('a,button,textarea,input,select')) return;
    el.setAttribute('data-tip',el.getAttribute('title')); el.removeAttribute('title');
    el.style.cursor='pointer';
    if(/^(B|SPAN|SMALL)$/.test(el.tagName)){{ el.style.textDecoration='underline dotted'; el.style.textUnderlineOffset='3px'; }}
  }});
  document.addEventListener('click',function(e){{
    var el=e.target.closest('[data-tip]');
    if(el && !e.target.closest('#tipbox')){{
      box.textContent=el.getAttribute('data-tip').replace(/;/g,'\\n');
      box.style.display='block'; e.stopPropagation(); return;
    }}
    box.style.display='none';
  }});
}})();
</script></body></html>"""
    os.makedirs("docs", exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(page)
    m.tail(CSV_DAYS).to_csv(OUT_CSV, encoding="utf-8-sig", float_format="%.4f")
    import notify
    fxd = fx.summary(fx_rows)
    insd = inst.summary(inst_data)
    kdl = "\n".join(f"{n}KD  K {v['K']:.1f}|D {v['D']:.1f}|{v['state']}{(' ' + run_txt(n)) if run_txt(n) else ''}\n    合理低~高檔 {v['low']:.1f}~{v['high']:.1f}|{v['zone'] or '—'}"
                    for n, v in k.items())
    summary = (f"📊 加權指數日報 {m.index[-1]:%Y-%m-%d}\n"
               f"收盤 {now['台股收盤價']:,.2f}  {arrow} {abs(chg):,.2f}({chg_pct:+.2%})\n"
               f"多空狀態:{trend['state']}\n    {trend['reason']}\n"
               f"Z-SCORE(480天) {z:.2f}({zread})\n    Z低檔 {lo:.2f}|Z高檔 {hi:.2f}\n"
               + "    " + "|".join(f"{'Z≤0' if t == 0 else 'Z=0.5'} 約當 {v:,.0f}({v / _px - 1:+.1%})" for t, v in zlv) + "\n"
               f"220日線 {ma_lab}|MA220 {num(now['220日均線'])}{('|年線' + tr_txt + '(' + tr_note.replace('MA220 ', '') + ')') if tr_txt else ''}\n    {ma_note.replace('|', '|')}{nx_line}\n"
               f"生命線 60×3%:{now['生命線60*3%'] or '—'}\n"
               f"BUY 數 {len(buy9)}/9|全部 12 欄 {sum(now[c] == 'BUY' for c in XCOLS)} 個\n"
               f"近一年最高 {hi_px:,.2f}({hi_dt:%Y-%m-%d})|距高點 {dd:+.1%}\n"
               + (f"高點後最低 {lo_px:,.2f}({lo_dt:%Y-%m-%d})|最大跌幅 {lo_dd:+.1%}\n" if lo_dd < 0 else "") +
               f"季線 / 年線乖離 {pct(now['季線乖離'])} / {pct(now['年線乖離'])}\n"
               f"5年 / 10年線乖離 {pct(now['5年線乖離%'])} / {pct(now['10年線乖離%'])}\n"
               f"MAD ZSCORE {now['MAD ZSCORE']:.2f}(低 {now['MAD 低檔']:.2f}|高 {now['MAD 高檔']:.2f})\n"
               f"{fxd['text'] if fxd else '美元兌台幣 暫無資料'}\n"
               f"{insd['text'] if insd else '三大法人/外資期貨 暫無資料'}\n"
               f"過熱轉弱警示 {sum(wok)}/6:曾Z>1.5 {mk(wok[0])}|9欄曾全BUY {mk(wok[1])}|BUY≤3 {mk(wok[2])}|週月KD雙死叉 {mk(wok[3])}|5年乖離曾>15% {mk(wok[4])}|90>120~150>180曾全BUY {mk(wok[5])}\n"
               f"⚠ 6/6 成立須轉出：一半反1(00632R)、一半中華電!!{'' if cyl else '(目前已達 6/6,請開始執行)' if all(wok) else ''}\n"
               + "".join(f"    {t}\n" for t in cyl + insl) +
               f"{kdl}\n\n詳細頁面:{PAGE_URL}")
    import flexmsg
    fd = dict(date=f"{m.index[-1]:%Y-%m-%d}", close=now["台股收盤價"], chg=chg, chg_pct=chg_pct,
              ma200_sig=ma_lab, ma200_note=ma_note + "\n" + nx_line.strip().replace("\n    ", "\n"), ma200=now["220日均線"], ma200_trend=(f"年線{tr_txt}({tr_note.replace('MA220 ', '')})" if tr_txt else ""), life=now["生命線60*3%"] or "—",
              buy9=len(buy9), z=z, zread=zread, zlo=lo, zhi=hi, mad=now["MAD ZSCORE"], madlo=now["MAD 低檔"], madhi=now["MAD 高檔"],
              q_y=f"{pct(now['季線乖離'])} / {pct(now['年線乖離'])}", y5_10=f"{pct(now['5年線乖離%'])} / {pct(now['10年線乖離%'])}",
              hi_px=hi_px, hi_dt=f"{hi_dt:%Y-%m-%d}", dd=dd, trend=trend["state"], trend_reason=trend["reason"],
              kd=[(f"{n}KD", v["K"], v["D"], v["state"], v["zone"], v["low"], v["high"], run_txt(n)) for n, v in k.items()],
              warn=list(zip(["本段 Z 曾大於 1.5", "本段 9 欄曾同時全 BUY", "BUY 數剩 3 個以下", "週、月 KD 雙死叉", "本段 5 年乖離曾大於 15%", "本段 90>120、120>150、150>180 曾同時全 BUY"], wok)),
              warn_n=sum(wok), cycle=cyl + insl, url=PAGE_URL, fx=fxd, inst=insd)
    if not inst_only:
        notify.run(m, summary, flexmsg.bubble(fd), flexmsg.alt_text(fd))                          # 每天發日報;連續第 3 天突破/跌破時,日報最上面加警示
    print(f"完成:資料至 {m.index[-1]:%Y-%m-%d},Z={z:.2f},週KD {k['週']['state']},月KD {k['月']['state']}")


if __name__ == "__main__":
    main()
