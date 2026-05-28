import os
import time
import requests
from datetime import datetime, timezone

# ─── CONFIG ────────────────────────────────────────────────────────────────────
SYMBOL         = "BTCUSDT"
INTERVAL       = "30m"
FAST           = 12
SLOW           = 26
SIGNAL_P       = 9

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT  = os.environ["TELEGRAM_CHAT_ID"]
# ───────────────────────────────────────────────────────────────────────────────

STATE_HIJAU_TUA  = "HIJAU_TUA"
STATE_HIJAU_MUDA = "HIJAU_MUDA"
STATE_MERAH_TUA  = "MERAH_TUA"
STATE_MERAH_MUDA = "MERAH_MUDA"

STATE_EMOJI = {
    STATE_HIJAU_TUA:  "🟢",
    STATE_HIJAU_MUDA: "🟩",
    STATE_MERAH_TUA:  "🔴",
    STATE_MERAH_MUDA: "🩷",
}
STATE_LABEL = {
    STATE_HIJAU_TUA:  "Hijau Tua — Bullish Menguat",
    STATE_HIJAU_MUDA: "Hijau Muda — Bullish Melemah",
    STATE_MERAH_TUA:  "Merah Tua — Bearish Menguat",
    STATE_MERAH_MUDA: "Merah Muda — Bearish Melemah",
}
TRANSITION_MEANING = {
    (STATE_HIJAU_MUDA, STATE_HIJAU_TUA):  "📈 Momentum bullish kembali menguat",
    (STATE_HIJAU_TUA,  STATE_HIJAU_MUDA): "⚠️ Momentum bullish mulai melemah",
    (STATE_MERAH_MUDA, STATE_MERAH_TUA):  "📉 Momentum bearish kembali menguat",
    (STATE_MERAH_TUA,  STATE_MERAH_MUDA): "⚠️ Momentum bearish mulai melemah",
    (STATE_MERAH_TUA,  STATE_HIJAU_MUDA): "🚀 Crossover: Bearish → Bullish",
    (STATE_MERAH_MUDA, STATE_HIJAU_MUDA): "🚀 Crossover: Bearish → Bullish",
    (STATE_HIJAU_TUA,  STATE_MERAH_MUDA): "💀 Crossover: Bullish → Bearish",
    (STATE_HIJAU_MUDA, STATE_MERAH_MUDA): "💀 Crossover: Bullish → Bearish",
}


def get_hist_state(hist_now: float, hist_prev: float) -> str:
    if hist_now >= 0:
        return STATE_HIJAU_TUA if abs(hist_now) >= abs(hist_prev) else STATE_HIJAU_MUDA
    else:
        return STATE_MERAH_TUA if abs(hist_now) >= abs(hist_prev) else STATE_MERAH_MUDA


def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT,
            "text": msg,
            "parse_mode": "HTML",
        }, timeout=10)
        r.raise_for_status()
        print(f"[TG] Sent OK")
    except Exception as e:
        print(f"[TG ERROR] {e}")


def fetch_candles(limit=150):
    # MEXC — tidak diblokir oleh Railway
    url = (
        f"https://api.mexc.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit={limit}"
    )
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    print(f"[FETCH] {len(data)} candle dari MEXC OK")
    return data
    # Format: [openTime, open, high, low, close, vol, closeTime, ...]


def calc_ema(values: list, period: int) -> list:
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def calc_macd(closes: list):
    fast_ema  = calc_ema(closes, FAST)
    slow_ema  = calc_ema(closes, SLOW)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    start     = SLOW - 1
    sig_ema   = calc_ema(macd_line[start:], SIGNAL_P)
    results   = []
    for i, sig in enumerate(sig_ema):
        m = macd_line[start + SIGNAL_P - 1 + i]
        h = m - sig
        results.append({"macd": m, "signal": sig, "histogram": h})
    return results


def get_macd_states():
    candles = fetch_candles(150)
    closes  = [float(c[4]) for c in candles]
    macd    = calc_macd(closes)

    print(f"[MACD] {len(macd)} nilai | "
          f"h[-4]={macd[-4]['histogram']:.4f} "
          f"h[-3]={macd[-3]['histogram']:.4f} "
          f"h[-2]={macd[-2]['histogram']:.4f} "
          f"h[-1]={macd[-1]['histogram']:.4f}")

    # candles[-1] = forming (belum close)
    # candles[-2] = candle terakhir closed
    # candles[-3] = 2 candle lalu closed
    # candles[-4] = 3 candle lalu closed

    # WARNING: forming vs closed sebelumnya
    warn_cur  = get_hist_state(macd[-1]["histogram"], macd[-2]["histogram"])
    warn_prev = get_hist_state(macd[-2]["histogram"], macd[-3]["histogram"])

    # CONFIRMED: candle baru closed vs sebelumnya
    conf_cur  = get_hist_state(macd[-2]["histogram"], macd[-3]["histogram"])
    conf_prev = get_hist_state(macd[-3]["histogram"], macd[-4]["histogram"])

    print(f"[STATE] WARN {warn_prev}→{warn_cur} | CONF {conf_prev}→{conf_cur}")

    return {
        "warn_cur":     warn_cur,
        "warn_prev":    warn_prev,
        "conf_cur":     conf_cur,
        "conf_prev":    conf_prev,
        "macd_val":     macd[-2]["macd"],
        "signal_val":   macd[-2]["signal"],
        "hist_closed":  macd[-2]["histogram"],
        "hist_forming": macd[-1]["histogram"],
        "btc":          closes[-1],
    }


def fmt(v: float) -> str:
    return f"{'+' if v >= 0 else ''}{v:.4f}"


def seconds_until(target_minute: int) -> float:
    now = datetime.now(timezone.utc)
    current_sec = now.minute * 60 + now.second
    target_sec  = target_minute * 60
    diff = target_sec - current_sec
    if diff <= 0:
        diff += 3600
    return diff


def run():
    print(f"[START] MACD Alert Bot — {SYMBOL} 30M via MEXC")
    send_telegram(
        f"🤖 <b>MACD Alert Bot aktif</b>\n"
        f"Pair: <code>{SYMBOL}</code> | TF: <code>30 menit</code>\n"
        f"Sumber: <code>MEXC</code>\n\n"
        f"🟢 Hijau Tua → Bullish menguat\n"
        f"🟩 Hijau Muda → Bullish melemah\n"
        f"🔴 Merah Tua → Bearish menguat\n"
        f"🩷 Merah Muda → Bearish melemah\n\n"
        f"⚡ WARNING: jam XX:29 & XX:59 (hanya jika warna berubah)\n"
        f"✅ CONFIRMED: jam XX:30 & XX:00 (hanya jika warna berubah)"
    )

    while True:
        now = datetime.now(timezone.utc)
        m   = now.minute
        s   = now.second

        # ── WARNING: menit 29 atau 59, detik 0–10 ────────────────────────────
        if m in (29, 59) and s < 10:
            print(f"[{now.strftime('%H:%M:%S')} UTC] ⚡ WARNING ZONE")
            try:
                data = get_macd_states()
                if data["warn_cur"] != data["warn_prev"]:
                    from_e  = STATE_EMOJI[data["warn_prev"]]
                    to_e    = STATE_EMOJI[data["warn_cur"]]
                    meaning = TRANSITION_MEANING.get(
                        (data["warn_prev"], data["warn_cur"]), "Perubahan state"
                    )
                    send_telegram(
                        f"⚡ <b>WARNING — 1 Menit Sebelum Candle Close</b>\n\n"
                        f"{from_e} <b>{STATE_LABEL[data['warn_prev']]}</b>\n"
                        f"        ↓\n"
                        f"{to_e} <b>{STATE_LABEL[data['warn_cur']]}</b>\n\n"
                        f"💡 <i>{meaning}</i>\n\n"
                        f"📉 Histogram forming: <code>{fmt(data['hist_forming'])}</code>\n"
                        f"💰 BTC: <code>${data['btc']:,.2f}</code>\n"
                        f"🕐 {now.strftime('%H:%M:%S UTC')}\n\n"
                        f"<i>⏳ Belum confirmed — tunggu candle close</i>"
                    )
                else:
                    print(f"[WARN] Warna sama ({data['warn_cur']}) — skip")
            except Exception as e:
                print(f"[ERROR WARNING] {e}")

            time.sleep(55)
            continue

        # ── CONFIRMED: menit 0 atau 30, detik 5–15 ───────────────────────────
        if m in (0, 30) and 5 <= s <= 15:
            print(f"[{now.strftime('%H:%M:%S')} UTC] ✅ CONFIRMED ZONE")
            try:
                data = get_macd_states()
                if data["conf_cur"] != data["conf_prev"]:
                    from_e  = STATE_EMOJI[data["conf_prev"]]
                    to_e    = STATE_EMOJI[data["conf_cur"]]
                    meaning = TRANSITION_MEANING.get(
                        (data["conf_prev"], data["conf_cur"]), "Perubahan state"
                    )
                    send_telegram(
                        f"✅ <b>CONFIRMED — Candle 30M Closed</b>\n\n"
                        f"{from_e} <b>{STATE_LABEL[data['conf_prev']]}</b>\n"
                        f"        ↓\n"
                        f"{to_e} <b>{STATE_LABEL[data['conf_cur']]}</b>\n\n"
                        f"💡 <i>{meaning}</i>\n\n"
                        f"📊 MACD: <code>{fmt(data['macd_val'])}</code>\n"
                        f"📈 Signal: <code>{fmt(data['signal_val'])}</code>\n"
                        f"📉 Histogram: <code>{fmt(data['hist_closed'])}</code>\n"
                        f"💰 BTC: <code>${data['btc']:,.2f}</code>\n"
                        f"🕐 {now.strftime('%H:%M:%S UTC')}"
                    )
                else:
                    print(f"[CONF] Warna sama ({data['conf_cur']}) — skip")
            except Exception as e:
                print(f"[ERROR CONFIRMED] {e}")

            time.sleep(50)
            continue

        # ── IDLE ──────────────────────────────────────────────────────────────
        candidates = sorted((seconds_until(t), t) for t in (29, 30, 59, 0))
        next_diff, next_min = candidates[0]
        sleep_sec = max(1, next_diff - 8)
        print(
            f"[{now.strftime('%H:%M:%S')} UTC] Idle → "
            f":{next_min:02d} dalam {int(next_diff)}s | tidur {int(sleep_sec)}s"
        )
        time.sleep(sleep_sec)


if __name__ == "__main__":
    run()
