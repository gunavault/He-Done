# Bot notifikasi T-Rex Discord

Bot Python yang otomatis tag satu role di satu channel teks **setiap hari**. Menggunakan WIB (`Asia/Jakarta`) meskipun timezone server UTC. Jadwal default aktif saat bot dijalankan. Gunakan `/trex index:3.1 waktu:11:20` untuk mengganti timer index berdasarkan waktu T-Rex terakhir muncul. `/trex` tanpa opsi tetap menampilkan spawn terdekat.

## Index yang tersedia

Index **3.1, 3.2, 4.1, dan 4.3** dapat dipilih melalui opsi `index` pada `/trex`. Index 4.1 dan 4.3 belum memiliki jam default: isi waktu terakhir muncul agar timer dan pengingatnya aktif. Rumus waktunya sama, yaitu 6 jam 40 menit–7 jam setelah kemunculan terakhir. Setiap index memiliki timer tersendiri yang tersimpan setelah restart dan berulang setiap hari sampai diperbarui.

```text
/trex index:4.3 waktu:08:20
/trex index:4.1 waktu:08:30
```

Jam di atas hanya contoh; masukkan waktu aktual dalam WIB. `/jadwal` menampilkan semua slot harian aktif dan menandai index yang belum diisi. Tidak perlu mengubah `.env` atau membuat database baru untuk kedua index tambahan.

## Update timer lewat Discord

```text
/trex index:3.1 waktu:11:20
/trex index:3.2 waktu:12:47
/trex
/jadwal
```

Pada slash command Discord, pilih opsi `index` dan `waktu`; gunakan `:` seperti contoh, bukan mengetik `index=...` sebagai teks pesan biasa.

- `waktu` adalah **waktu terakhir T-Rex muncul**, bukan jam pengingat atau jam spawn berikutnya.
- Perkiraan spawn berikutnya adalah **waktu + 6 jam 40 menit sampai waktu + 7 jam**, dengan pengingat dihitung dari awal jendela.
- `/trex index:3.1 waktu:11:20` menghasilkan jendela **18:00–18:20 WIB**, pengingat **17:30, 17:45, 17:55, 18:00**.
- Update menjadi `waktu:11:30` mengganti jendela menjadi **18:10–18:30 WIB**, pengingat **17:40, 17:55, 18:05, 18:10**.
- Update hanya mengganti index yang dipilih. Seluruh jadwal default/hasil update sebelumnya untuk index itu diganti dengan **satu jendela harian baru**. Index lainnya tidak berubah. Jadi sesudah update 3.1 ke `11:20`, slot tetap 3.1 pukul 11:20 tidak lagi mengirim notifikasi; jendela barunya adalah 18:00–18:20.
- Jendela hasil update berulang setiap hari pada jam yang sama sampai diubah lagi. Bot tidak menghitung siklus berikutnya dari perkiraan secara otomatis; perbarui `waktu` saat melihat kemunculan aktual agar waktunya akurat.
- Timer tersimpan di SQLite, bertahan setelah restart, dan tidak ditimpa konfigurasi jam default di `.env`.
- Update memerlukan **Manage Server**; `/trex` tanpa opsi dan `/jadwal` bisa digunakan anggota biasa. Konfirmasi update privat dan tidak tag role. Pengingat terjadwal tetap tag role di channel tujuan.
- Tanggal default adalah hari ini WIB. Jika catatan berasal dari kemarin, isi `tanggal:2026-10-30`, misalnya `/trex index:3.1 waktu:23:20 tanggal:2026-10-30`. Hasilnya 31-10-2026 06:00–06:20 WIB. Waktu terakhir muncul yang masih di masa depan ditolak.
- Bila input sudah menghasilkan jendela yang seluruhnya lewat hari ini, bot menampilkan jadwal berulang berikutnya besok. Pengingat yang sudah lewat tidak dikirim sekaligus; tetap mengikuti tenggang 60 detik pada bagian batasan di bawah.
- `/trex` juga menampilkan jendela hasil update yang sedang berlangsung sampai waktu akhirnya, lalu memilih jadwal berikutnya.

## Jadwal harian default (sebelum index diperbarui)

| Index | H-30 menit | H-15 menit | H-5 menit | Saat spawn |
| --- | --- | --- | --- | --- |
| 3.1 | 10:50 | 11:05 | 11:15 | 11:20 |
| 3.2 | 12:17 | 12:32 | 12:42 | 12:47 |
| 3.1 | 17:30 | 17:45 | 17:55 | 18:00 |
| 3.2 | 18:57 | 19:12 | 19:22 | 19:27 |

**Semua jam di atas WIB.** Tabel juga menampilkan referensi H-5 dan saat spawn; konfigurasi default sekarang hanya H-30/H-15. Untuk empat slot default ada 8 pesan per hari. Setelah kedua index awal diperbarui menjadi satu jendela per index, ada 4 pesan per hari (belum termasuk index tambahan yang diaktifkan). Jam 11:20 dan 12:47 adalah waktu spawn tambahan, bukan waktu pencatatan awal. Bot hanya mengikuti jadwal yang dikonfigurasi, tanpa membaca keadaan game.

Contoh pesan pada 10:50 WIB:

```text
@T-Rex Hunter
🦖 T-Rex — Index 3.1 | H-30 menit
Jadwal spawn T-Rex: 11:20 WIB.
Tanggal spawn: 31-10-2026
```

## Pengumuman suara dari MP3

Bot kini memakai **9 rekaman MP3 dari pengguna**, tanpa sintesis TTS online. Pada H-30 dan H-15 bot masuk ke voice channel, memutar rekaman sesuai index, melanjutkan MP3 penutup `assets/outro.mp3`, lalu keluar. `/tesvoice` memakai `test.mp3` dan MP3 penutup yang sama. Isi ucapan/RAWWRRRRR mengikuti rekaman asli; bot tidak menambahkan ucapan TTS lagi.

| Index | H-30 | H-15 |
| --- | --- | --- |
| 3.1 | `assets/voice/3_1_h30.mp3` | `assets/voice/3_1_h15.mp3` |
| 3.2 | `assets/voice/3_2_h30.mp3` | `assets/voice/3_2_h15.mp3` |
| 4.1 | `assets/voice/4_1_h30.mp3` | `assets/voice/4_1_h15.mp3` |
| 4.3 | `assets/voice/4_3_h30.mp3` | `assets/voice/4_3_h15.mp3` |
| Tes | `assets/voice/test.mp3` | — |

Semua rekaman disalin dari unggahan pengguna tanpa mengubah audio. Nama file dinormalisasi agar pemilihannya konsisten.

### Aktifkan di Wispbyte

1. Perbarui seluruh kode, `requirements.txt`, dan **folder `assets/` lengkap**, termasuk `assets/voice/` serta `assets/outro.mp3`. Instalasi Git dapat memakai `git pull origin main` atau `AUTO_UPDATE=1` sebelum restart.
2. Pastikan dependencies terpasang dari `requirements.txt` dan `PY_FILE=bot.py`.
3. Isi `.env` atau variabel Startup aktif:

```ini
VOICE_CHANNEL_ID=ISI_ID_VOICE_CHANNEL
VOICE_AUDIO_DIR=assets/voice
VOICE_VOLUME=3.0
VOICE_OUTRO_PATH=assets/outro.mp3
REMINDER_MINUTES=30,15
```

Ganti ID dengan ID voice channel biasa di server yang sama. `CHANNEL_ID` tetap memakai ID channel **teks** untuk pesan bertag role. Kosongkan `VOICE_CHANNEL_ID` untuk mematikan suara. `TTS_VOICE` tidak lagi digunakan dan boleh dihapus.

4. Beri bot izin **View Channel, Connect, dan Speak**. Bot harus tidak di-server-mute. Tidak perlu Administrator.
5. Restart, masuk ke voice channel tujuan, lalu jalankan **`/tesvoice`** dengan akun Manage Server. Log startup menampilkan `mode=recorded_mp3`.

Default pengingat sekarang **H-30 dan H-15**. Jika `.env` atau Startup masih berisi `REMINDER_MINUTES=30,15,5,0`, ubah menjadi `30,15`; kode tidak menimpa environment aktif. Rekaman hanya tersedia untuk H-30/H-15. Jika offset lain sengaja dikonfigurasi, pesan teks tetap mengikuti offset itu, tetapi voice melewatinya.

### Tes rekaman H-30/H-15 langsung

Jalankan satu per satu saat berada di voice channel tujuan:

```text
/tesvoice index:3.1 menit:30
/tesvoice index:3.1 menit:15
```

Perintah langsung memutar `3_1_h30.mp3` atau `3_1_h15.mp3`, lalu MP3 penutup, dan bot keluar. Angka menit memilih jenis rekaman; bukan menunggu 30/15 menit. Jalankan tes kedua setelah tes pertama selesai. Timer spawn, status pengiriman terjadwal, dan notifikasi teks tidak berubah.

Tanpa opsi, `/tesvoice` tetap memutar `test.mp3`. Opsi index dan menit harus diisi bersama. Mendukung juga 3.2, 4.1, dan 4.3; memerlukan Manage Server dan voice aktif. Setelah memperbarui kode, restart bot agar opsi baru tersinkronisasi ke Discord.

### Volume pengumuman

`VOICE_VOLUME=3.0` adalah default baru untuk memperkuat rekaman, termasuk `test.mp3` dan MP3 penutup. `1.0` berarti amplitudo asli, `2.0` dua kali, dan `3.0` tiga kali. Nilai yang diterima 0.1–5.0; gunakan titik untuk desimal. FFmpeg memakai limiter puncak 0.95 agar penguatan tidak langsung memotong puncak sinyal. File MP3 asli tidak diubah.

Setelah memperbarui kode, isi/ubah `VOICE_VOLUME` pada `.env` atau Startup Wispbyte, restart bot, lalu jalankan `/tesvoice`. Pengaturan volume pengguna di Discord tetap ikut menentukan keras suara yang terdengar.

### Audio, hosting, dan penanganan kegagalan

- Semua path relatif dihitung dari folder proyek. Upload manual Wispbyte harus menempatkan rekaman di `/home/container/assets/voice/` dan penutup di `/home/container/assets/outro.mp3`.
- Jika rekaman atau MP3 penutup hilang, bot mencatat nama/path file yang perlu diperbarui dan tidak masuk ke voice channel. Pesan teks tetap berjalan.
- Kosongkan `VOICE_OUTRO_PATH=` untuk menonaktifkan penutup; rekaman pengingat tetap diputar.
- `discord.py[voice]` menyediakan dukungan voice termasuk PyNaCl/DAVE; `imageio-ffmpeg` menyediakan FFmpeg pada platform wheel yang didukung. Jika binary tidak cocok, sediakan FFmpeg hosting dan isi `FFMPEG_PATH`.
- Bot tidak lagi memerlukan Edge TTS atau koneksi layanan sintesis. Hosting tetap perlu mendukung koneksi voice Discord termasuk UDP.
- Pengumuman diantrekan agar tidak tumpang tindih. Job yang sudah lewat tenggang 60 detik atau diganti lewat update timer dilewati sebelum pemutaran.
- Kegagalan voice tidak mengirim ulang pesan teks yang sudah berhasil. Voice dicoba ulang dengan jeda 15 detik selama masih dalam tenggang.
- Status pengiriman teks/voice tersimpan terpisah agar restart normal tidak mengulang pengumuman yang sudah selesai. Jika proses mati sesaat sebelum status tersimpan, pengulangan masih mungkin.
- Bot keluar sesudah seluruh audio selesai atau saat gagal; sesi voice lain tidak dipindah/diputus. Bot tidak merekam mikrofon/percakapan.

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
REMINDER_MINUTES=30,15
DB_PATH=data/trex.sqlite3
```

Angka ID di atas hanya contoh. Gunakan ID asli; role dan channel harus berada di server yang sama. Jangan menggunakan ID @everyone.

- `INDEX_31_TIMES` / `INDEX_32_TIMES`: daftar jam spawn harian dalam WIB, format HH:MM dipisah koma. Dipakai hanya untuk index yang belum diperbarui lewat `/trex`.
- `REMINDER_MINUTES`: menit sebelum awal jendela spawn. Default `30,15` berarti H-30 dan H-15.
- Jika hanya ingin tiga pengingat sebelum spawn, gunakan `REMINDER_MINUTES=30,15,5` (3 pesan per jendela spawn).
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

Versi ini menambahkan update timer ke jadwal harian. Variabel lama `SPAWN_MIN_MINUTES` / `SPAWN_MAX_MINUTES` tidak digunakan; interval perhitungan tetap 400–420 menit. Database lama otomatis mendapat tabel timer baru tanpa menghapus data sebelumnya.

### Wispbyte

Pada halaman Startup gunakan `PY_FILE=bot.py`, `REQUIREMENTS_FILE=requirements.txt`, dan `AUTO_UPDATE=1` jika proyek dipasang sebagai git checkout. Restart dari panel untuk menarik kode dan menyinkronkan opsi `/trex`. Jika instalasi tidak memiliki folder `.git`, perbarui file proyek dari GitHub sebelum restart. Jangan mengganti `.env` atau menghapus folder `data/` ketika memperbarui kode.

## Perintah Discord

- `/trex`: tampilkan spawn terdekat atau jendela aktif, tanggal WIB, dan sisa waktu. Respons publik tanpa tag role. Jika jadwal hari ini sudah lewat, memilih jadwal pertama besok. Sisa waktu dihitung saat dipanggil, bukan diperbarui terus-menerus.
- `/trex index:3.1 waktu:11:20`: perbarui timer satu index. `index` dan `waktu` wajib diisi bersama; `tanggal` opsional. Memerlukan Manage Server.
- `/jadwal`: lihat jadwal berikutnya dan seluruh jam pengingat, memakai timer terbaru. Respons privat tanpa tag role.
- `/tesvoice`: tes suara di voice channel yang dikonfigurasi, kemudian keluar. Memerlukan **Manage Server**.
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

Tes memeriksa jadwal default dan timer hasil update, pembatalan pengingat lama, isolasi antar-index, pengulangan harian, WIB pada server UTC, lintas tengah malam, validasi input/izin, restart, retry, pengingat kedaluwarsa, pembatasan mention role, pemilihan spawn terdekat, respons `/trex`, antrean suara, pembatalan timer, izin voice, dan pembersihan koneksi/audio saat gagal. Pengiriman asli diuji dengan `/tes` setelah token/ID dipasang.

## Referensi

- https://discordpy.readthedocs.io/en/stable/ext/tasks/index.html
- https://discordpy.readthedocs.io/en/stable/api.html#discord.AllowedMentions
- https://discordpy.readthedocs.io/en/stable/interactions/api.html
