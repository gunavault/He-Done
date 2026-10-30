# Bot notifikasi T-Rex Discord

Bot Python yang otomatis tag satu role di satu channel teks **setiap hari**. Menggunakan WIB (`Asia/Jakarta`) meskipun timezone server UTC. Jadwal langsung aktif saat bot dijalankan; tidak perlu memasukkan waktu lewat slash command.

## Jadwal harian

| Index | H-30 menit | H-15 menit | H-5 menit | Saat spawn |
| --- | --- | --- | --- | --- |
| 3.1 | 10:50 | 11:05 | 11:15 | 11:20 |
| 3.2 | 12:17 | 12:32 | 12:42 | 12:47 |
| 3.1 | 17:30 | 17:45 | 17:55 | 18:00 |
| 3.2 | 18:57 | 19:12 | 19:22 | 19:27 |

**Semua jam di atas WIB.** Default mengirim 16 pesan per hari, masing-masing dengan tag role. Jam 11:20 dan 12:47 adalah waktu spawn tambahan, bukan waktu pencatatan awal. Bot hanya mengikuti jadwal yang dikonfigurasi, tanpa membaca keadaan game.

Contoh pesan pada 10:50 WIB:

```text
@T-Rex Hunter
🦖 T-Rex — Index 3.1 | H-30 menit
Jadwal spawn T-Rex: 11:20 WIB.
Tanggal spawn: 31-10-2026
```

## 1. Buat dan undang bot

1. Buka https://discord.com/developers/applications dan buat New Application.
2. Pada halaman Bot, buat/reset token jika diperlukan. Simpan token sendiri di `.env`; jangan kirim ke chat atau unggah ke Git.
3. Pada halaman instalasi/OAuth2 URL Generator, pilih scope `bot` dan `applications.commands`, lalu undang ke server.
4. Berikan **View Channel** dan **Send Messages** pada channel tujuan. Bot tidak memerlukan Administrator.
5. Agar role bisa ditag, aktifkan **Allow anyone to @mention this role** pada role tujuan. Alternatifnya, beri bot izin **Mention @everyone, @here, and All Roles** pada channel itu. Kode hanya mengizinkan mention role yang dikonfigurasi.
6. Di Discord, Settings → Advanced → aktifkan Developer Mode. Klik kanan untuk menyalin Server ID, Channel ID, serta Role ID.

## 2. Konfigurasi

Salin `.env.example` menjadi `.env` **jika belum punya**, lalu isi empat nilai pertama:

```ini
DISCORD_TOKEN=token_bot_discord
GUILD_ID=123456789012345678
CHANNEL_ID=234567890123456789
ROLE_ID=345678901234567890
INDEX_31_TIMES=11:20,18:00
INDEX_32_TIMES=12:47,19:27
REMINDER_MINUTES=30,15,5,0
DB_PATH=data/trex.sqlite3
```

Angka ID di atas hanya contoh. Gunakan ID asli; role dan channel harus berada di server yang sama. Jangan menggunakan ID @everyone.

- `INDEX_31_TIMES` / `INDEX_32_TIMES`: daftar jam spawn harian dalam WIB, format HH:MM dipisah koma. Semua waktu dipicu setiap hari.
- `REMINDER_MINUTES`: menit sebelum spawn. `30,15,5,0` berarti H-30, H-15, H-5, dan saat spawn.
- Jika hanya ingin tiga pengingat sebelum spawn, gunakan `REMINDER_MINUTES=30,15,5` (12 pesan per hari).
- Restart bot setelah mengubah konfigurasi. Pada Docker Compose jalankan ulang `docker compose up -d --build` agar environment baru diterapkan.

## 3. Jalankan

Gunakan Python 3.11 atau lebih baru. Buka terminal di folder proyek.

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env sebelum menjalankan baris berikut
.\.venv\Scripts\python bot.py
```

Linux/Rocky:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env sebelum menjalankan baris berikut
.venv/bin/python bot.py
```

**Lewati langkah salin jika `.env` sudah diisi**, agar token dan ID tidak tertimpa. Bila Python bawaan Rocky masih 3.9, gunakan python3.11 atau python3.12.

Alternatif Docker Compose, setelah `.env` diisi:

```bash
docker compose up -d --build
docker compose logs -f
```

Status pengiriman tersimpan pada named volume `trex-data`. Jangan menjalankan `docker compose down -v` jika ingin mempertahankan status. Jalankan hanya **satu instance** bot dengan database ini untuk mencegah pesan ganda.

## Update dari versi sebelumnya

```bash
git pull origin main
docker compose up -d --build
```

Jika sebelumnya menjalankan Python langsung, hentikan proses lama, lalu jalankan `python bot.py` kembali dari environment yang sama. Jangan menimpa `.env`; tambahkan `INDEX_31_TIMES`, `INDEX_32_TIMES`, dan `REMINDER_MINUTES` seperti contoh di atas. Jika tidak ditambahkan, default empat jadwal harian tetap digunakan.

Versi ini mengganti penjadwalan manual dengan jadwal harian otomatis. Variabel lama `SPAWN_MIN_MINUTES` / `SPAWN_MAX_MINUTES` tidak digunakan lagi. `/trex` dan `/hapus` dihapus saat sinkronisasi perintah; jadwal manual lama di database tidak dijalankan. Data lama tidak dihapus.

## Perintah Discord

- `/jadwal`: lihat jadwal harian dan seluruh jam pengingat. Respons privat, tidak tag role.
- `/tes`: langsung kirim pesan uji publik dan tag role ke channel tujuan. Memerlukan **Manage Server**.

Bot menggunakan slash command, tanpa Message Content Intent. Perintah hanya didaftarkan untuk GUILD_ID yang diatur.

## Ketepatan waktu, restart, dan kendala

- Bot harus tetap berjalan dan terhubung ke internet. Menyimpan kode di GitHub tidak menjalankan bot otomatis.
- Scheduler memeriksa setiap 5 detik, sehingga waktu pengiriman bisa bergeser beberapa detik. Koneksi dan rate limit Discord juga dapat menambah keterlambatan.
- Setelah berhasil dikirim, setiap pengingat dicatat di SQLite berdasarkan server, index, waktu spawn, dan offset. Restart normal tidak mengirim ulang pengingat yang sudah tercatat. Tanggal berikutnya mempunyai pengingat baru.
- Ada tenggang **60 detik** sejak waktu trigger untuk pengiriman/retry. Pengingat yang sudah lewat lebih lama dilewati agar H-30 tidak muncul saat sudah H-5. Jika bot mati sepanjang waktu pengingat, pesan tersebut terlewat; pengingat berikutnya tetap berjalan.
- Jika jam spawn dini hari diatur, pengingat sebelum tengah malam dikaitkan dengan tanggal spawn besok secara otomatis.
- Jika proses mati tepat setelah Discord menerima pesan namun sebelum status tersimpan, atau respons pengiriman hilang di jaringan, pesan dapat terkirim ulang. Implementasi ini tidak menjamin exactly-once delivery.
- Tag role tidak menjamin push notification pada perangkat setiap anggota karena pengaturan notifikasi Discord anggota tetap berlaku.
- Jika tidak terkirim, periksa log, ID, dan izin channel/role. Jika perintah tidak muncul, pastikan scope instalasi dan GUILD_ID benar serta sinkronisasi di log berhasil.

## Tes tanpa mengirim ke Discord

Setelah dependencies terpasang:

```bash
python -m unittest discover -p 'test_*.py' -v
```

Tes memeriksa 16 waktu trigger, pengulangan harian, WIB pada server UTC, lintas tengah malam, validasi konfigurasi, restart, retry, pengingat kedaluwarsa, dan pembatasan mention role. Pengiriman asli diuji dengan `/tes` setelah token/ID dipasang.

## Referensi

- https://discordpy.readthedocs.io/en/stable/ext/tasks/index.html
- https://discordpy.readthedocs.io/en/stable/api.html#discord.AllowedMentions
- https://discordpy.readthedocs.io/en/stable/interactions/api.html
