"""MA220 通知:收盤 > MA220×1.02 → 買進;收盤 < MA220×0.985 → 賣出(DAYS=1:訊號當天發一次,隔天收盤買賣)。
通道由環境變數(GitHub Secrets)決定,設了哪個就發哪個,都沒設就只印出訊息:
  簡訊 Twilio : TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, SMS_TO(例 +886912345678)
  Telegram    : TG_TOKEN, TG_CHAT_ID
  ntfy        : NTFY_TOPIC
  LINE 推播   : LINE_TOKEN, LINE_USER_ID
"""
import base64
import json
import os
import urllib.parse
import urllib.request

UP, DN, DAYS = 0.02, 0.015, 1     # 2026-11 改為當天收盤確認、賣出 −1.5%(回測)


def _streak(flag):
    return flag.groupby((~flag).cumsum()).cumsum()


def check(m):
    """回傳 (訊號, 訊息);沒有訊號則 (None, None)。m 需有「台股收盤價」「220日均線」欄。"""
    c, ma = m["台股收盤價"], m["220日均線"]
    ua, ub = _streak(c > ma * (1 + UP)), _streak(c < ma * (1 - DN))
    d, row = m.index[-1], m.iloc[-1]
    if ua.iloc[-1] == DAYS:
        sig, rule = "買進", (f"收盤站上 MA220×{1 + UP:.4g},隔天收盤下單買進" if DAYS == 1 else f"連續 {DAYS} 天站上 MA220×{1 + UP:.4g}")
    elif ub.iloc[-1] == DAYS:
        sig, rule = "賣出", (f"收盤跌破 MA220×{1 - DN:.4g},隔天收盤下單賣出" if DAYS == 1 else f"連續 {DAYS} 天跌破 MA220×{1 - DN:.4g}")
    else:
        return None, None
    return sig, (f"【加權指數{sig}訊號】{d:%Y-%m-%d}\n{rule}\n"
                 f"收盤 {row['台股收盤價']:,.2f}|MA220 {row['220日均線']:,.2f}")


def _post(url, data=None, headers=None, js=None):
    if js is not None:
        data, headers = json.dumps(js).encode(), {**(headers or {}), "Content-Type": "application/json"}
    elif isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    elif isinstance(data, str):
        data = data.encode("utf-8")
    urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers or {}), timeout=30).read()


def _line(token, uid, text, flex):
    def push(msg):
        _post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {token}"}, js={"to": uid, "messages": [msg]})
    if flex:
        try:
            return push(flex)
        except Exception as ex:                       # 卡片格式被 LINE 拒絕時,退回純文字,確保一定收得到
            print(f"Flex 卡片發送失敗({ex}),改發純文字")
    push({"type": "text", "text": text[:4900]})


def send(text, flex=None):
    e, sent = os.environ.get, []
    chans = [
        ("簡訊(Twilio)", all(e(k) for k in ("TWILIO_SID", "TWILIO_TOKEN", "TWILIO_FROM", "SMS_TO")), lambda: _post(
            f"https://api.twilio.com/2010-04-01/Accounts/{e('TWILIO_SID')}/Messages.json",
            {"From": e("TWILIO_FROM"), "To": e("SMS_TO"), "Body": text},
            {"Authorization": "Basic " + base64.b64encode(f"{e('TWILIO_SID')}:{e('TWILIO_TOKEN')}".encode()).decode()})),
        ("Telegram", all(e(k) for k in ("TG_TOKEN", "TG_CHAT_ID")), lambda: _post(
            f"https://api.telegram.org/bot{e('TG_TOKEN')}/sendMessage", {"chat_id": e("TG_CHAT_ID"), "text": text})),
        ("ntfy", bool(e("NTFY_TOPIC")), lambda: _post(f"https://ntfy.sh/{e('NTFY_TOPIC')}", text, {"Title": "MA220 signal"})),
        ("LINE", all(e(k) for k in ("LINE_TOKEN", "LINE_USER_ID")), lambda: _line(e("LINE_TOKEN"), e("LINE_USER_ID"), text, flex)),
    ]
    for name, ok, fn in chans:
        if ok:
            try:
                fn()
                sent.append(name)
            except Exception as ex:                      # 通知失敗不影響頁面更新
                print(f"通知失敗 {name}: {ex}")
    return sent


def run(m, summary=None, flex=None, alt=None):
    """summary:純文字日報(Telegram/ntfy/簡訊用);flex:LINE 卡片版 {bubble 內容};alt:LINE 通知預覽文字。
    若今天剛好出現訊號,警示放在最前面一起發(一天只發一則)。"""
    if os.environ.get("NOTIFY_TEST") == "1":
        print("測試通知已發送:", send("【測試】LINE 通道正常,收到這則代表設定成功。") or "(未設定任何通道)")
    sig, text = check(m)
    if not (sig or summary):
        print("今天沒有訊號也沒有日報,不發送")
        return
    msg = (f"🔔🔔 {text}\n\n" if sig else "") + (summary or "")
    fx = None
    if flex:
        if sig:                                     # 警示放最上面(紅底白字)
            flex["body"]["contents"].insert(0, {"type": "box", "layout": "vertical", "backgroundColor": "#D9534F", "cornerRadius": "md",
                "paddingAll": "md", "margin": "none", "contents": [{"type": "text", "text": "🔔 " + text.replace("\n", "\n"), "wrap": True, "color": "#FFFFFF", "size": "sm", "weight": "bold"}]})
        fx = {"type": "flex", "altText": (("🔔" + sig + "訊號｜") if sig else "") + (alt or "加權指數日報"), "contents": flex}
    print(msg)
    print("已發送:", send(msg.strip(), fx) or "(未設定任何通道,僅印出)")
