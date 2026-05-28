import os
import time
import requests
from datetime import datetime, timezone

# ─── CONFIG ────────────────────────────────────────────────────────────────────
SYMBOL        = "BTCUSDT"
INTERVAL      = "30m"
FAST          = 12
SLOW          = 26
SIGNAL_P      = 9
CANDLE_SEC    = 30 * 60
WARN_BEFORE   = 60
LOOP_SLEEP    = 15

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


def fetch_candles(limit=120):
    url = (
        f"https://fapi.binance.com/fapi/v1/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit={limit}"
    )
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


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
    print(f"[START] MACD 4-State Alert Bot — {SYMBOL} {INTERVAL} via Binance Futures")
    send_telegram(
        f"🤖 <b>MACD Alert Bot aktif</b>\n"
        f"Pair: <code>{SYMBOL}</code> | TF: <code>30 menit</code>\n"
        f"Sumber: <code>Binance Futures</code>\n\n"
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
            candles = fetch_candles()

            # Binance format: [openTime, open, high, low, close, vol, closeTime, ...]
            closes      = [float(c[4]) for c in candles]
            open_times  = [int(c[0]) for c in candles]
            close_times = [int(c[6]) for c in candles]

            macd_data = calc_macd(closes)

            # Butuh minimal 3 nilai MACD
            if len(macd_data) < 3:
                print("[WARN] Data MACD belum cukup, skip...")
                time.sleep(LOOP_SLEEP)
                continue

            cur  = macd_data[-1]   # candle forming (belum close)
            prev = macd_data[-2]   # candle closed sebelumnya
            pp   = macd_data[-3]   # 2 candle lalu

            cur_state  = get_hist_state(cur["histogram"],  prev["histogram"])
            prev_state = get_hist_state(prev["histogram"], pp["histogram"])

            # Gunakan candle terakhir langsung dari raw data Binance
            # candles[-1] = candle forming sekarang
            forming_open_ms  = open_times[-1]
            forming_close_ms = close_times[-1]

            now_ms        = int(time.time() * 1000)
            secs_to_close = max(0, (forming_close_ms - now_ms) // 1000)

            state_changed = (cur_state != prev_state)
            btc_price     = closes[-1]
            now_str       = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

            print(
                f"[{now_str}] {cur_state} | prev={prev_state} | "
                f"changed={state_changed} | close_in={secs_to_close}s"
            )

            meaning = TRANSITION_MEANING.get((prev_state, cur_state), "Perubahan state")
            from_e  = STATE_EMOJI[prev_state]
            to_e    = STATE_EMOJI[cur_state]

            # ── WARNING ───────────────────────────────────────────────────────
            if (
                state_changed
                and 0 < secs_to_close <= WARN_BEFORE
                and forming_open_ms != last_warned_candle
            ):
                last_warned_candle = forming_open_ms
                msg = (
                    f"⚠️ <b>WARNING — {secs_to_close}s Sebelum Close</b>\n\n"
                    f"{from_e} <b>{STATE_LABEL[prev_state]}</b>\n"
                    f"        ↓\n"
                    f"{to_e} <b>{STATE_LABEL[cur_state]}</b>\n\n"
                    f"💡 <i>{meaning}</i>\n\n"
                    f"📊 MACD: <code>{fmt(cur['macd'])}</code>\n"
                    f"📉 Histogram: <code>{fmt(cur['histogram'])}</code>\n"
                    f"💰 BTC: <code>${btc_price:,.2f}</code>\n"
                    f"⏱ Close dalam: <b>{secs_to_close} detik</b>\n"
                    f"🕐 {now_str}\n\n"
                    f"<i>Belum confirmed — tunggu candle close</i>"
                )
                send_telegram(msg)

            # ── CONFIRMED ─────────────────────────────────────────────────────
            if (
                state_changed
                and secs_to_close <= 5
                and forming_open_ms != last_confirmed_candle
            ):
                last_confirmed_candle = forming_open_ms
                msg = (
                    f"✅ <b>CONFIRMED — Candle 30M Closed</b>\n\n"
                    f"{from_e} <b>{STATE_LABEL[prev_state]}</b>\n"
                    f"        ↓\n"
                    f"{to_e} <b>{STATE_LABEL[cur_state]}</b>\n\n"
                    f"💡 <i>{meaning}</i>\n\n"
                    f"📊 MACD: <code>{fmt(cur['macd'])}</code>\n"
                    f"📈 Signal: <code>{fmt(cur['signal'])}</code>\n"
                    f"📉 Histogram: <code>{fmt(cur['histogram'])}</code>\n"
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
