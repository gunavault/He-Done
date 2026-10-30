# Bot notifikasi T-Rex Discord

Bot Python untuk satu server, satu channel teks, dan satu role. Menggunakan slash command; tidak perlu Message Content Intent atau membaca pesan chat.

## Aturan yang diasumsikan

T-Rex diperkirakan muncul 6 jam 40 menit sampai 7 jam setelah waktu index dicatat. Ini diturunkan dari contoh, bukan aturan game yang sudah diverifikasi. Ubah SPAWN_MIN_MINUTES dan SPAWN_MAX_MINUTES jika berbeda.

| Index | Waktu catatan WIB | Jendela kemunculan WIB |
| --- | --- | --- |
| 3.1 | 11:20 | 18:00–18:20 |
| 3.2 | 12:47 | 19:27–19:47 |

Bot mengirim satu pesan dengan tag role di awal jendela. Bot memeriksa setiap 15 detik; pengiriman dapat terlambat akibat koneksi atau rate limit Discord. Bot tidak mengetahui spawn dari game secara otomatis: waktu perlu dicatat melalui `/trex` setiap siklus. Tidak ada pengulangan harian otomatis dan tidak ada jadwal yang diaktifkan sebelum kamu memasukkannya.

## 1. Buat dan undang bot

1. Buka https://discord.com/developers/applications dan buat New Application.
2. Buka halaman Bot, buat/reset token jika diperlukan. Simpan token di `.env` sendiri; jangan kirim token ke chat atau unggah ke Git.
3. Pada halaman instalasi/OAuth2 URL Generator, pilih scope `bot` dan `applications.commands`, lalu undang ke server.
4. Berikan izin **View Channel** dan **Send Messages** pada channel tujuan. Bot tidak memerlukan Administrator.
5. Agar role bisa ditag, aktifkan **Allow anyone to @mention this role** pada role tujuan. Alternatifnya, beri bot izin **Mention @everyone, @here, and All Roles** pada channel tujuan. Kode membatasi mention ke role yang diatur; @everyone tidak digunakan.
6. Di Discord, Settings → Advanced → aktifkan Developer Mode. Salin Server ID, Channel ID, serta Role ID melalui menu klik kanan.

## 2. Isi konfigurasi

Salin `.env.example` menjadi `.env`, lalu isi empat nilai pertama:

```ini
DISCORD_TOKEN=token_bot_discord
GUILD_ID=123456789012345678
CHANNEL_ID=234567890123456789
ROLE_ID=345678901234567890
SPAWN_MIN_MINUTES=400
SPAWN_MAX_MINUTES=420
DB_PATH=data/trex.sqlite3
```

Gunakan ID asli dari servermu; angka di atas hanya contoh. Jangan menggunakan ID @everyone. Role dan channel harus berada di server tersebut.

## 3. Jalankan dengan Python

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

Jika `.env` sudah diisi, lewati langkah salin agar tidak tertimpa. Python/venv harus terpasang; gunakan python3.11 atau python3.12 bila python3 bawaan Rocky masih 3.9.

## Alternatif: Docker Compose

Setelah mengisi `.env`:

```bash
docker compose up -d --build
docker compose logs -f
```

Data disimpan pada named volume `trex-data`. Jangan gunakan `docker compose down -v` jika ingin mempertahankan jadwal. Jalankan hanya **satu instance** untuk konfigurasi bot/database ini agar tidak mengirim ganda.

## 4. Gunakan di Discord

Admin atau anggota dengan izin **Manage Server** bisa mengatur jadwal. Anggota lain bisa melihat `/jadwal`. Perintah didaftarkan hanya pada GUILD_ID yang dipilih.

```text
/trex index:3.1 waktu:11:20
/trex index:3.2 waktu:12:47
/jadwal
/tes
/hapus index:3.1
```

Parameter `waktu` merupakan waktu catatan awal, bukan waktu notifikasi. Default tanggal adalah hari ini WIB. Jika catatan berasal dari kemarin, isi tanggal secara eksplisit:

```text
/trex index:3.1 waktu:23:20 tanggal:2026-10-30
```

Contoh itu menghasilkan jendela 31-10-2026 06:00–06:20 WIB. Waktu catatan yang masih di masa depan atau jendela yang seluruhnya sudah lewat ditolak. Memasukkan index yang sama akan mengganti jadwal lama, termasuk status terkirimnya. Jangan masukkan ulang catatan yang sama setelah terkirim kecuali memang ingin notifikasi baru.

`/trex` hanya memberi konfirmasi privat; pesan publik bertag role dikirim pada awal jendela. `/tes` **langsung** mengirim pesan uji publik dan tag role. Untuk contoh 3.1, pesannya:

```text
@T-Rex Hunter
🦖 T-Rex — Index 3.1
Waktu index dicatat: 30-10-2026 11:20 WIB
T-Rex diperkirakan muncul antara 30-10-2026 18:00–30-10-2026 18:20 WIB.
```

## Restart, kendala, dan batasan

- Komputer/server harus menyala, proses bot berjalan, dan tersambung ke internet saat pengiriman.
- Jadwal dan status terkirim disimpan di SQLite. Setelah restart, jadwal pending dikirim bila masih berada dalam jendela; jika seluruh jendela lewat, jadwal ditandai kedaluwarsa tanpa mengirim pesan basi.
- Bila pengiriman gagal, bot mencoba lagi setiap pemeriksaan selama jendela masih aktif. Periksa log bila izin/channel/role salah.
- Bila proses mati sesaat setelah Discord menerima pesan tetapi sebelum status tersimpan, atau respons pengiriman hilang di jaringan, notifikasi dapat terkirim ulang. Implementasi ini tidak menjamin exactly-once delivery.
- Tag role tidak menjamin push notification pada perangkat setiap anggota; pengaturan notifikasi Discord milik anggota tetap berlaku.
- Perintah tidak muncul: pastikan bot sudah diundang dengan scope yang sesuai, GUILD_ID benar, dan sinkronisasi perintah berhasil pada log. Restart aplikasi Discord bila perlu.
- Saat mengganti GUILD_ID, hapus bot/integrasi atau perintah lama dari server sebelumnya jika tidak dibutuhkan; perintah pada server lama tetap ditolak oleh kode.

## Pemeriksaan lokal

```bash
python -m unittest -v test_schedule.py
```

Tes mencakup perhitungan dua contoh, pergantian hari, validasi input, penolakan jadwal lewat, serta persistensi/penggantian/penghapusan jadwal. Pengiriman Discord perlu diuji dengan `/tes` setelah token dan ID dipasang.

## Referensi

- https://discordpy.readthedocs.io/en/stable/ext/tasks/index.html
- https://discordpy.readthedocs.io/en/stable/api.html#discord.AllowedMentions
- https://discordpy.readthedocs.io/en/stable/interactions/api.html
