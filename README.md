# Bot notifikasi T-Rex Discord

Bot Python yang otomatis tag satu role di satu channel teks **setiap hari**. Menggunakan WIB (`Asia/Jakarta`) meskipun timezone server UTC. Jadwal default aktif saat bot dijalankan. Gunakan `/trex i:3.1 w:11:20` untuk mengganti timer index berdasarkan waktu T-Rex terakhir muncul. `/trex` tanpa opsi tetap menampilkan spawn terdekat.

## Index yang tersedia

Index **3.1, 3.2, 4.1, dan 4.3** dapat dipilih melalui opsi `i` pada `/trex`. Index 4.1 dan 4.3 belum memiliki jam default: isi waktu terakhir muncul agar timer dan pengingatnya aktif. Rumus waktunya sama, yaitu 6 jam 40 menit–7 jam setelah kemunculan terakhir. Setiap index memiliki timer tersendiri yang tersimpan setelah restart dan berulang setiap hari sampai diperbarui.

```text
/trex i:4.3 w:08:20
/trex i:4.1 w:08:30
```

Jam di atas hanya contoh; masukkan waktu aktual dalam WIB. `/jadwal` menampilkan semua slot harian aktif dan menandai index yang belum diisi. Tidak perlu mengubah `.env` atau membuat database baru untuk kedua index tambahan.

## Update timer lewat Discord

```text
/trex i:3.1 w:11:20
/trex i:3.2 w:12:47
/trex
/jadwal
```

Pada slash command Discord, pilih opsi `i` dan `w`; gunakan `:` seperti contoh, bukan mengetik `i=...` sebagai teks pesan biasa.

- `w` adalah **waktu terakhir T-Rex muncul**, bukan jam pengingat atau jam spawn berikutnya.
- Perkiraan spawn berikutnya adalah **w + 6 jam 40 menit sampai w + 7 jam**, dengan pengingat dihitung dari awal jendela.
- `/trex i:3.1 w:11:20` menghasilkan jendela **18:00–18:20 WIB**, pengingat **17:30, 17:45, 17:55, 18:00**.
- Update menjadi `w:11:30` mengganti jendela menjadi **18:10–18:30 WIB**, pengingat **17:40, 17:55, 18:05, 18:10**.
- Update hanya mengganti index yang dipilih. Seluruh jadwal default/hasil update sebelumnya untuk index itu diganti dengan **satu jendela harian baru**. Index lainnya tidak berubah. Jadi sesudah update 3.1 ke `11:20`, slot tetap 3.1 pukul 11:20 tidak lagi mengirim notifikasi; jendela barunya adalah 18:00–18:20.
- Jendela hasil update berulang setiap hari pada jam yang sama sampai diubah lagi. Bot tidak menghitung siklus berikutnya dari perkiraan secara otomatis; perbarui `w` saat melihat kemunculan aktual agar waktunya akurat.
- Timer tersimpan di SQLite, bertahan setelah restart, dan tidak ditimpa konfigurasi jam default di `.env`.
- Update memerlukan **Manage Server**; `/trex` tanpa opsi dan `/jadwal` bisa digunakan anggota biasa. Konfirmasi update privat dan tidak tag role. Pengingat terjadwal tetap tag role di channel tujuan.
- Tanggal default adalah hari ini WIB. Jika catatan berasal dari kemarin, isi `tanggal:2026-10-30`, misalnya `/trex i:3.1 w:23:20 tanggal:2026-10-30`. Hasilnya 31-10-2026 06:00–06:20 WIB. Waktu terakhir muncul yang masih di masa depan ditolak.
- Bila input sudah menghasilkan jendela yang seluruhnya lewat hari ini, bot menampilkan jadwal berulang berikutnya besok. Pengingat yang sudah lewat tidak dikirim sekaligus; tetap mengikuti tenggang 60 detik pada bagian batasan di bawah.
- `/trex` juga menampilkan jendela hasil update yang sedang berlangsung sampai waktu akhirnya, lalu memilih jadwal berikutnya.

## Jadwal harian default (sebelum index diperbarui)

| Index | H-30 menit | H-15 menit | H-5 menit | Saat spawn |
| --- | --- | --- | --- | --- |
| 3.1 | 10:50 | 11:05 | 11:15 | 11:20 |
| 3.2 | 12:17 | 12:32 | 12:42 | 12:47 |
| 3.1 | 17:30 | 17:45 | 17:55 | 18:00 |
| 3.2 | 18:57 | 19:12 | 19:22 | 19:27 |

**Semua jam di atas WIB.** Sebelum ada update, default mengirim 16 pesan per hari, masing-masing dengan tag role. Setelah kedua index diperbarui, ada satu jendela per index dengan empat notifikasi (8 pesan per hari). Jam 11:20 dan 12:47 adalah waktu spawn tambahan, bukan waktu pencatatan awal. Bot hanya mengikuti jadwal yang dikonfigurasi, tanpa membaca keadaan game.

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

- `INDEX_31_TIMES` / `INDEX_32_TIMES`: daftar jam spawn harian dalam WIB, format HH:MM dipisah koma. Dipakai hanya untuk index yang belum diperbarui lewat `/trex`.
- `REMINDER_MINUTES`: menit sebelum spawn. `30,15,5,0` berarti H-30, H-15, H-5, dan saat spawn.
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
- `/trex i:3.1 w:11:20`: perbarui timer satu index. `i` dan `w` wajib diisi bersama; `tanggal` opsional. Memerlukan Manage Server.
- `/jadwal`: lihat jadwal berikutnya dan seluruh jam pengingat, memakai timer terbaru. Respons privat tanpa tag role.
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

Tes memeriksa jadwal default dan timer hasil update, pembatalan pengingat lama, isolasi antar-index, pengulangan harian, WIB pada server UTC, lintas tengah malam, validasi input/izin, restart, retry, pengingat kedaluwarsa, pembatasan mention role, pemilihan spawn terdekat, dan respons `/trex`. Pengiriman asli diuji dengan `/tes` setelah token/ID dipasang.

## Referensi

- https://discordpy.readthedocs.io/en/stable/ext/tasks/index.html
- https://discordpy.readthedocs.io/en/stable/api.html#discord.AllowedMentions
- https://discordpy.readthedocs.io/en/stable/interactions/api.html
