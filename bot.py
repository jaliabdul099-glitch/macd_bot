import os
import time
import requests
from datetime import datetime, timezone

# ─── CONFIG ───────────────────────────────────────────────────────────────────
SYMBOL         = "BTCUSDT"
INTERVAL       = "30m"
FAST           = 12
SLOW           = 26
SIGNAL_P       = 9

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT  = os.environ["TELEGRAM_CHAT_ID"]
# ──────────────────────────────────────────────────────────────────────────────

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
    url = f"https://api.mexc.com/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}&limit={limit}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    print(f"[FETCH] {len(data)} candle dari MEXC")
    return data


def calc_ema(values: list, period: int) -> list:
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def calc_macd(closes: list) -> list:
    """Hitung MACD — menghasilkan list sepanjang closes."""
    macd_line   = [f - s for f, s in zip(calc_ema(closes, FAST), calc_ema(closes, SLOW))]
    signal_line = calc_ema(macd_line, SIGNAL_P)
    return [
        {"macd": macd_line[i], "signal": signal_line[i], "histogram": macd_line[i] - signal_line[i]}
        for i in range(len(macd_line))
    ]


def get_states():
    """
    Ambil data dan kembalikan state histogram.

    candle[-1] = forming (belum close)  → untuk WARNING
    candle[-2] = baru closed            → untuk CONFIRMED (cur)
    candle[-3] = 2 candle lalu closed   → untuk CONFIRMED (prev) & WARNING (prev)
    candle[-4] = 3 candle lalu closed   → untuk CONFIRMED (prev-prev)
    """
    candles = fetch_candles(150)
    closes  = [float(c[4]) for c in candles]
    macd    = calc_macd(closes)

    h1 = macd[-1]["histogram"]  # forming
    h2 = macd[-2]["histogram"]  # closed terbaru
    h3 = macd[-3]["histogram"]  # closed sebelumnya
    h4 = macd[-4]["histogram"]  # closed 2x sebelumnya
    print(f"[HIST] forming={h1:.4f} | c1={h2:.4f} | c2={h3:.4f} | c3={h4:.4f}")

    # WARNING: apakah candle forming sudah beda warna vs candle closed sebelumnya?
    warn_cur  = get_hist_state(h1, h2)
    warn_prev = get_hist_state(h2, h3)

    # CONFIRMED: apakah candle yang baru closed beda warna vs sebelumnya?
    conf_cur  = get_hist_state(h2, h3)
    conf_prev = get_hist_state(h3, h4)

    print(f"[STATE] WARN {warn_prev}→{warn_cur} | CONF {conf_prev}→{conf_cur}")

    return {
        "warn_cur":  warn_cur,   "warn_prev": warn_prev,
        "conf_cur":  conf_cur,   "conf_prev": conf_prev,
        "macd_val":  macd[-2]["macd"],
        "sig_val":   macd[-2]["signal"],
        "hist_closed":   h2,
        "hist_forming":  h1,
        "btc":       closes[-1],
    }


def fmt(v: float) -> str:
    return f"{'+' if v >= 0 else ''}{v:.4f}"


def seconds_until(target_minute: int) -> float:
    now = datetime.now(timezone.utc)
    diff = (target_minute * 60) - (now.minute * 60 + now.second)
    return diff if diff > 0 else diff + 3600


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
        f"⚡ WARNING: XX:29 & XX:59\n"
        f"✅ CONFIRMED: XX:00 & XX:30"
    )

    while True:
        now = datetime.now(timezone.utc)
        m, s = now.minute, now.second

        # ── WARNING: detik 00–09 dari menit 29 atau 59 ───────────────────────
        if m in (29, 59) and s < 10:
            print(f"[{now.strftime('%H:%M:%S')} UTC] ⚡ WARNING ZONE")
            try:
                data = get_states()
                if data["warn_cur"] != data["warn_prev"]:
                    fe = STATE_EMOJI[data["warn_prev"]]
                    te = STATE_EMOJI[data["warn_cur"]]
                    meaning = TRANSITION_MEANING.get(
                        (data["warn_prev"], data["warn_cur"]), "Perubahan state"
                    )
                    send_telegram(
                        f"⚡ <b>WARNING — 1 Menit Sebelum Candle Close</b>\n\n"
                        f"{fe} <b>{STATE_LABEL[data['warn_prev']]}</b>\n"
                        f"        ↓\n"
                        f"{te} <b>{STATE_LABEL[data['warn_cur']]}</b>\n\n"
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
            # Tidur 50 detik, bangun lagi di detik ~00 menit berikutnya
            time.sleep(50)
            continue

        # ── CONFIRMED: detik 05–20 dari menit 00 atau 30 ─────────────────────
        if m in (0, 30) and 5 <= s <= 20:
            print(f"[{now.strftime('%H:%M:%S')} UTC] ✅ CONFIRMED ZONE")
            try:
                data = get_states()
                if data["conf_cur"] != data["conf_prev"]:
                    fe = STATE_EMOJI[data["conf_prev"]]
                    te = STATE_EMOJI[data["conf_cur"]]
                    meaning = TRANSITION_MEANING.get(
                        (data["conf_prev"], data["conf_cur"]), "Perubahan state"
                    )
                    send_telegram(
                        f"✅ <b>CONFIRMED — Candle 30M Closed</b>\n\n"
                        f"{fe} <b>{STATE_LABEL[data['conf_prev']]}</b>\n"
                        f"        ↓\n"
                        f"{te} <b>{STATE_LABEL[data['conf_cur']]}</b>\n\n"
                        f"💡 <i>{meaning}</i>\n\n"
                        f"📊 MACD: <code>{fmt(data['macd_val'])}</code>\n"
                        f"📈 Signal: <code>{fmt(data['sig_val'])}</code>\n"
                        f"📉 Histogram: <code>{fmt(data['hist_closed'])}</code>\n"
                        f"💰 BTC: <code>${data['btc']:,.2f}</code>\n"
                        f"🕐 {now.strftime('%H:%M:%S UTC')}"
                    )
                else:
                    print(f"[CONF] Warna sama ({data['conf_cur']}) — skip")
            except Exception as e:
                print(f"[ERROR CONFIRMED] {e}")
            time.sleep(40)
            continue

        # ── IDLE: tidur sampai mendekati event berikutnya ─────────────────────
        next_diff, next_min = sorted((seconds_until(t), t) for t in (29, 30, 59, 0))[0]
        sleep_sec = max(1, next_diff - 8)
        print(f"[{now.strftime('%H:%M:%S')} UTC] Idle → :{next_min:02d} dalam {int(next_diff)}s | tidur {int(sleep_sec)}s")
        time.sleep(sleep_sec)


if __name__ == "__main__":
    run()
