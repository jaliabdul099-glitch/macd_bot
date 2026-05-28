import os
import time
import requests
from datetime import datetime, timezone

# ─── CONFIG ────────────────────────────────────────────────────────────────────
SYMBOL        = "BTCUSDT"
INTERVAL      = "30"          # 30 menit
FAST          = 12
SLOW          = 26
SIGNAL_P      = 9
CANDLE_SEC    = 30 * 60       # 1800 detik
WARN_BEFORE   = 60            # detik sebelum close → kirim warning
LOOP_SLEEP    = 15            # cek tiap 15 detik

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT  = os.environ["TELEGRAM_CHAT_ID"]
# ───────────────────────────────────────────────────────────────────────────────

# ─── 4 STATE HISTOGRAM (seperti TradingView) ───────────────────────────────────
#
#   HIJAU TUA   → histogram positif & bar sekarang > bar sebelumnya  (bullish menguat)
#   HIJAU MUDA  → histogram positif & bar sekarang < bar sebelumnya  (bullish melemah)
#   MERAH TUA   → histogram negatif & bar sekarang < bar sebelumnya  (bearish menguat)
#   MERAH MUDA  → histogram negatif & bar sekarang > bar sebelumnya  (bearish melemah)
#
# Catatan: "menguat/melemah" dilihat dari nilai absolut histogram
# ───────────────────────────────────────────────────────────────────────────────

STATE_HIJAU_TUA  = "HIJAU_TUA"    # positif, menguat
STATE_HIJAU_MUDA = "HIJAU_MUDA"   # positif, melemah
STATE_MERAH_TUA  = "MERAH_TUA"    # negatif, menguat
STATE_MERAH_MUDA = "MERAH_MUDA"   # negatif, melemah

STATE_EMOJI = {
    STATE_HIJAU_TUA:  "🟢",
    STATE_HIJAU_MUDA: "🟩",
    STATE_MERAH_TUA:  "🔴",
    STATE_MERAH_MUDA: "🩷",
}
STATE_LABEL = {
    STATE_HIJAU_TUA:  "Hijau Tua (Bullish Menguat)",
    STATE_HIJAU_MUDA: "Hijau Muda (Bullish Melemah)",
    STATE_MERAH_TUA:  "Merah Tua (Bearish Menguat)",
    STATE_MERAH_MUDA: "Merah Muda (Bearish Melemah)",
}

# Makna trading tiap perubahan state
TRANSITION_MEANING = {
    (STATE_HIJAU_MUDA, STATE_HIJAU_TUA):  "📈 Momentum bullish kembali menguat",
    (STATE_HIJAU_TUA,  STATE_HIJAU_MUDA): "⚠️ Momentum bullish mulai melemah",
    (STATE_MERAH_MUDA, STATE_MERAH_TUA):  "📉 Momentum bearish kembali menguat",
    (STATE_MERAH_TUA,  STATE_MERAH_MUDA): "⚠️ Momentum bearish mulai melemah",
    # crossover
    (STATE_MERAH_TUA,  STATE_HIJAU_MUDA): "🚀 Crossover: Bearish → Bullish",
    (STATE_MERAH_MUDA, STATE_HIJAU_MUDA): "🚀 Crossover: Bearish → Bullish",
    (STATE_HIJAU_TUA,  STATE_MERAH_MUDA): "💀 Crossover: Bullish → Bearish",
    (STATE_HIJAU_MUDA, STATE_MERAH_MUDA): "💀 Crossover: Bullish → Bearish",
}


def get_hist_state(hist_now: float, hist_prev: float) -> str:
    """Tentukan state histogram berdasarkan nilai sekarang vs sebelumnya."""
    if hist_now >= 0:
        # Positif territory
        if abs(hist_now) >= abs(hist_prev):
            return STATE_HIJAU_TUA   # bar makin besar → menguat
        else:
            return STATE_HIJAU_MUDA  # bar makin kecil → melemah
    else:
        # Negatif territory
        if abs(hist_now) >= abs(hist_prev):
            return STATE_MERAH_TUA   # bar makin besar (makin negatif) → menguat
        else:
            return STATE_MERAH_MUDA  # bar makin kecil → melemah


def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT,
        "text": msg,
        "parse_mode": "HTML",
        "disable_notification": False,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print(f"[TG SENT] {msg[:80]}...")
    except Exception as e:
        print(f"[TG ERROR] {e}")


def fetch_candles(limit=120):
    url = (
        f"https://api.bybit.com/v5/market/kline"
        f"?category=linear&symbol={SYMBOL}&interval={INTERVAL}&limit={limit}"
    )
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data["retCode"] != 0:
        raise RuntimeError(data["retMsg"])
    return list(reversed(data["result"]["list"]))


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


def fmt(v: float) -> str:
    return f"{'+' if v >= 0 else ''}{v:.4f}"


def run():
    print(f"[START] MACD 4-State Alert Bot — {SYMBOL} {INTERVAL}m")
    send_telegram(
        f"🤖 <b>MACD 4-State Alert Bot aktif</b>\n"
        f"Pair: <code>{SYMBOL}</code> | TF: <code>{INTERVAL} menit</code>\n\n"
        f"Deteksi 4 state histogram:\n"
        f"🟢 Hijau Tua → Bullish menguat\n"
        f"🟩 Hijau Muda → Bullish melemah\n"
        f"🔴 Merah Tua → Bearish menguat\n"
        f"🩷 Merah Muda → Bearish melemah\n\n"
        f"⚡ Warning: {WARN_BEFORE}s sebelum close\n"
        f"✅ Confirmed: saat candle close"
    )

    last_warned_candle    = None
    last_confirmed_candle = None

    while True:
        try:
            candles    = fetch_candles()
            closes     = [float(c[4]) for c in candles]
            open_times = [int(c[0]) for c in candles]

            macd_data  = calc_macd(closes)

            # 3 candle terakhir dari macd_data:
            #   [-3] = 2 candle lalu (closed) → untuk referensi prev state
            #   [-2] = 1 candle lalu (closed) → prev state
            #   [-1] = candle forming sekarang → current state

            cur  = macd_data[-1]   # forming
            prev = macd_data[-2]   # closed sebelumnya
            pp   = macd_data[-3]   # closed 2 candle lalu

            # State forming: bandingkan hist forming vs hist candle closed sebelumnya
            cur_state  = get_hist_state(cur["histogram"],  prev["histogram"])
            # State prev (confirmed): bandingkan hist prev vs hist 2 candle lalu
            prev_state = get_hist_state(prev["histogram"], pp["histogram"])

            # Timing candle forming
            macd_offset      = (SLOW - 1) + (SIGNAL_P - 1)
            forming_open_ms  = open_times[macd_offset + len(macd_data) - 1]
            forming_close_ms = forming_open_ms + CANDLE_SEC * 1000
            now_ms           = int(time.time() * 1000)
            secs_to_close    = max(0, (forming_close_ms - now_ms) // 1000)

            state_changed = (cur_state != prev_state)
            btc_price     = closes[-1]
            now_str       = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

            print(
                f"[{now_str}] "
                f"Hist={fmt(cur['histogram'])} | "
                f"State={cur_state} | "
                f"Prev={prev_state} | "
                f"Changed={state_changed} | "
                f"CloseIn={secs_to_close}s"
            )

            meaning = TRANSITION_MEANING.get(
                (prev_state, cur_state),
                f"{STATE_LABEL[prev_state]} → {STATE_LABEL[cur_state]}"
            )

            # ── WARNING: N detik sebelum close ────────────────────────────────
            if (
                state_changed
                and 0 < secs_to_close <= WARN_BEFORE
                and forming_open_ms != last_warned_candle
            ):
                last_warned_candle = forming_open_ms
                from_e = STATE_EMOJI[prev_state]
                to_e   = STATE_EMOJI[cur_state]
                msg = (
                    f"⚠️ <b>WARNING — {secs_to_close}s Sebelum Candle Close</b>\n\n"
                    f"{from_e} <b>{STATE_LABEL[prev_state]}</b>\n"
                    f"        ↓\n"
                    f"{to_e} <b>{STATE_LABEL[cur_state]}</b>\n\n"
                    f"💡 <i>{meaning}</i>\n\n"
                    f"📊 MACD: <code>{fmt(cur['macd'])}</code>\n"
                    f"📈 Signal: <code>{fmt(cur['signal'])}</code>\n"
                    f"📉 Histogram: <code>{fmt(cur['histogram'])}</code>\n\n"
                    f"⏱ Close dalam: <b>{secs_to_close} detik</b>\n"
                    f"💰 BTC: <code>${btc_price:,.2f}</code>\n"
                    f"🕐 {now_str}\n\n"
                    f"<i>Belum confirmed — tunggu candle close</i>"
                )
                send_telegram(msg)

            # ── CONFIRMED: candle close ────────────────────────────────────────
            if (
                state_changed
                and secs_to_close <= 5
                and forming_open_ms != last_confirmed_candle
            ):
                last_confirmed_candle = forming_open_ms
                from_e = STATE_EMOJI[prev_state]
                to_e   = STATE_EMOJI[cur_state]
                msg = (
                    f"✅ <b>CONFIRMED — Candle 30M Closed</b>\n\n"
                    f"{from_e} <b>{STATE_LABEL[prev_state]}</b>\n"
                    f"        ↓\n"
                    f"{to_e} <b>{STATE_LABEL[cur_state]}</b>\n\n"
                    f"💡 <i>{meaning}</i>\n\n"
                    f"📊 MACD: <code>{fmt(cur['macd'])}</code>\n"
                    f"📈 Signal: <code>{fmt(cur['signal'])}</code>\n"
                    f"📉 Histogram: <code>{fmt(cur['histogram'])}</code>\n\n"
                    f"💰 BTC: <code>${btc_price:,.2f}</code>\n"
                    f"🕐 {now_str}"
                )
                send_telegram(msg)

        except Exception as e:
            print(f"[ERROR] {e}")
            try:
                send_telegram(f"⚠️ Bot error: <code>{e}</code>")
            except:
                pass

        time.sleep(LOOP_SLEEP)


if __name__ == "__main__":
    run()
