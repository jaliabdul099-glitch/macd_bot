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


def fetch_candles(limit=120):
    """Ambil candle dari Binance Futures. Sudah urutan lama → baru."""
    url = (
        f"https://fapi.binance.com/fapi/v1/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit={limit}"
    )
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()
    # format tiap candle: [openTime, open, high, low, close, vol, closeTime, ...]


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
    """
    Ambil data dan hitung state histogram.
    Selalu ambil candle fresh dari Binance.

    candles[-1] = candle yang SEDANG forming (belum close)
    candles[-2] = candle terakhir yang sudah CLOSED
    candles[-3] = candle sebelumnya (closed)

    State WARNING  → bandingkan candle[-1] forming vs candle[-2] closed
    State CONFIRMED → bandingkan candle[-2] closed vs candle[-3] closed
    """
    candles = fetch_candles(limit=120)
    closes  = [float(c[4]) for c in candles]

    macd = calc_macd(closes)
    if len(macd) < 3:
        raise ValueError("Data MACD tidak cukup")

    # Untuk WARNING: state candle forming sekarang
    warn_cur_state  = get_hist_state(macd[-1]["histogram"], macd[-2]["histogram"])
    warn_prev_state = get_hist_state(macd[-2]["histogram"], macd[-3]["histogram"])

    # Untuk CONFIRMED: state candle yang baru saja closed (candles[-2])
    conf_cur_state  = get_hist_state(macd[-2]["histogram"], macd[-3]["histogram"])
    conf_prev_state = get_hist_state(macd[-3]["histogram"], macd[-4]["histogram"])

    btc_price = closes[-1]

    return {
        "warn_cur":  warn_cur_state,
        "warn_prev": warn_prev_state,
        "conf_cur":  conf_cur_state,
        "conf_prev": conf_prev_state,
        "macd_val":  macd[-2]["macd"],
        "signal_val":macd[-2]["signal"],
        "hist_val":  macd[-2]["histogram"],
        "hist_forming": macd[-1]["histogram"],
        "btc":       btc_price,
    }


def fmt(v: float) -> str:
    return f"{'+' if v >= 0 else ''}{v:.4f}"


def wait_until_second(target_second: int):
    """
    Tunggu sampai detik ke-target_second dari menit sekarang.
    Contoh: target_second=0 → tunggu sampai detik :00 menit berikutnya
    """
    while True:
        now = datetime.now(timezone.utc)
        if now.second == target_second:
            return
        time.sleep(0.5)


def seconds_until(target_minute: int, target_second: int = 0) -> float:
    """Hitung detik sampai menit target (dalam jam yang sama)."""
    now = datetime.now(timezone.utc)
    target_sec_of_hour = target_minute * 60 + target_second
    current_sec_of_hour = now.minute * 60 + now.second
    diff = target_sec_of_hour - current_sec_of_hour
    if diff <= 0:
        diff += 3600  # jam berikutnya
    return diff


def run():
    print(f"[START] MACD Alert Bot — {SYMBOL} 30M | Binance Futures")
    send_telegram(
        f"🤖 <b>MACD Alert Bot aktif</b>\n"
        f"Pair: <code>{SYMBOL}</code> | TF: <code>30 menit</code>\n"
        f"Sumber: <code>Binance Futures</code>\n\n"
        f"🟢 Hijau Tua → Bullish menguat\n"
        f"🟩 Hijau Muda → Bullish melemah\n"
        f"🔴 Merah Tua → Bearish menguat\n"
        f"🩷 Merah Muda → Bearish melemah\n\n"
        f"⚡ WARNING dikirim jam XX:29 & XX:59\n"
        f"✅ CONFIRMED dikirim jam XX:30 & XX:00"
    )

    while True:
        now = datetime.now(timezone.utc)
        m   = now.minute
        s   = now.second

        # ── ZONA WARNING: menit ke-29 atau ke-59, detik 0–10 ─────────────────
        if m in (29, 59) and s < 10:
            print(f"[{now.strftime('%H:%M:%S')}] ⚡ WARNING ZONE")
            try:
                data = get_macd_states()
                warn_changed = (data["warn_cur"] != data["warn_prev"])

                if warn_changed:
                    from_e = STATE_EMOJI[data["warn_prev"]]
                    to_e   = STATE_EMOJI[data["warn_cur"]]
                    meaning = TRANSITION_MEANING.get(
                        (data["warn_prev"], data["warn_cur"]), "Perubahan state"
                    )
                    msg = (
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
                    send_telegram(msg)
                else:
                    print(f"[WARN] Tidak ada perubahan state — tidak kirim alert")

            except Exception as e:
                print(f"[ERROR WARNING] {e}")

            # Tunggu sampai keluar dari menit 29/59
            time.sleep(55)
            continue

        # ── ZONA CONFIRMED: menit ke-0 atau ke-30, detik 5–15 ────────────────
        # Tunggu 5 detik setelah candle close biar data Binance sudah update
        if m in (0, 30) and 5 <= s <= 15:
            print(f"[{now.strftime('%H:%M:%S')}] ✅ CONFIRMED ZONE")
            try:
                data = get_macd_states()
                conf_changed = (data["conf_cur"] != data["conf_prev"])

                if conf_changed:
                    from_e = STATE_EMOJI[data["conf_prev"]]
                    to_e   = STATE_EMOJI[data["conf_cur"]]
                    meaning = TRANSITION_MEANING.get(
                        (data["conf_prev"], data["conf_cur"]), "Perubahan state"
                    )
                    msg = (
                        f"✅ <b>CONFIRMED — Candle 30M Closed</b>\n\n"
                        f"{from_e} <b>{STATE_LABEL[data['conf_prev']]}</b>\n"
                        f"        ↓\n"
                        f"{to_e} <b>{STATE_LABEL[data['conf_cur']]}</b>\n\n"
                        f"💡 <i>{meaning}</i>\n\n"
                        f"📊 MACD: <code>{fmt(data['macd_val'])}</code>\n"
                        f"📈 Signal: <code>{fmt(data['signal_val'])}</code>\n"
                        f"📉 Histogram: <code>{fmt(data['hist_val'])}</code>\n"
                        f"💰 BTC: <code>${data['btc']:,.2f}</code>\n"
                        f"🕐 {now.strftime('%H:%M:%S UTC')}"
                    )
                    send_telegram(msg)
                else:
                    print(f"[CONF] Tidak ada perubahan state — tidak kirim alert")

            except Exception as e:
                print(f"[ERROR CONFIRMED] {e}")

            # Tunggu sampai keluar dari zona ini
            time.sleep(50)
            continue

        # ── IDLE: hitung sisa waktu ke event berikutnya ───────────────────────
        # Event berikutnya: menit 29, 30, 59, atau 0
        candidates = []
        for target in (29, 30, 59, 0):
            diff = seconds_until(target)
            candidates.append((diff, target))
        candidates.sort()
        next_diff, next_min = candidates[0]

        # Tidur sampai 5 detik sebelum event berikutnya
        sleep_sec = max(1, next_diff - 5)
        print(
            f"[{now.strftime('%H:%M:%S')}] Idle — "
            f"event berikutnya menit :{next_min:02d} "
            f"(dalam {int(next_diff)}s) | tidur {int(sleep_sec)}s"
        )
        time.sleep(sleep_sec)


if __name__ == "__main__":
    run()
