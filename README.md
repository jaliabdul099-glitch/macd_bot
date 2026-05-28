# MACD Alert Bot — BTCUSDT 30M → Telegram

Bot ini jalan 24/7 di Railway dan kirim notifikasi Telegram otomatis
saat MACD histogram berubah warna di timeframe 30 menit.

---

## STEP 1 — Buat Bot Telegram

1. Buka Telegram, cari **@BotFather**
2. Kirim: `/newbot`
3. Ikuti instruksi → catat **BOT TOKEN** (format: `123456:ABCdef...`)
4. Cari **@userinfobot** di Telegram → kirim sembarang pesan → catat **Chat ID** kamu

---

## STEP 2 — Upload ke GitHub

1. Buat akun di https://github.com (kalau belum)
2. Klik **New Repository** → nama: `macd-bot` → Public → Create
3. Upload 4 file ini: `bot.py`, `requirements.txt`, `Procfile`, `README.md`

---

## STEP 3 — Deploy ke Railway

1. Buka https://railway.app → Login with GitHub
2. Klik **New Project** → **Deploy from GitHub repo** → pilih `macd-bot`
3. Setelah project terbuat, klik tab **Variables** → tambah:

   | Key | Value |
   |-----|-------|
   | `TELEGRAM_TOKEN` | token dari BotFather |
   | `TELEGRAM_CHAT_ID` | chat ID kamu |

4. Klik tab **Settings** → pastikan **Start Command** kosong (Procfile sudah handle)
5. Klik **Deploy** → tunggu 1-2 menit

---

## STEP 4 — Cek Bot Jalan

- Di Railway → tab **Logs** → harusnya muncul `[START] MACD Alert Bot`
- Di Telegram kamu harusnya masuk pesan: "🤖 MACD Alert Bot aktif"

---

## Alert yang Dikirim

### ⚠️ WARNING (60 detik sebelum candle close)
Dikirim jika histogram sudah berubah warna sebelum candle tutup.
Ini sinyal awal — belum confirmed.

### ✅ CONFIRMED (saat candle close)
Dikirim saat candle 30m benar-benar close dan warna histogram berubah.
Ini sinyal yang sudah dikonfirmasi.

---

## Biaya Railway
- Free tier: $5 kredit/bulan → cukup untuk bot ringan ini (~$0.50/bulan)
- Tidak perlu kartu kredit untuk mulai

---

## Ubah Pengaturan (opsional)
Edit di `bot.py` baris paling atas:
- `WARN_BEFORE = 60` → ganti ke `120` untuk warning 2 menit
- `LOOP_SLEEP = 15`  → interval cek (detik), jangan < 10
