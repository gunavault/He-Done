# Bot world boss dan raid Discord

Bot mengirim pengingat world boss dengan tag role berdasarkan **register satu kali**. Semua waktu memakai WIB (`Asia/Jakarta`), termasuk saat server memakai UTC. Tidak ada jadwal harian default dan tidak ada pengulangan setiap 24 jam.

## Register world boss

```text
/worldbossregister index:3.1 tempat:Volcano waktu:11:20
/worldbossregister index:8.5 tempat:Snowfield waktu:12:00
/worldbossregister
/jadwal
/jadwal halaman:2
```

Opsi index tersedia **1.1–8.5**, total 40 kombinasi. Ketik angka utama seperti `8.` untuk melihat 8.1–8.5. Saat mengupdate, isi `index`, `tempat`, dan `waktu` bersama. `tempat` dipilih dari Volcano, Snowfield, Tundra, Swamp, Desert, atau Tropical. `waktu` adalah jam kemunculan aktual terakhir, bukan jam notifikasi.

Formula tetap **+6 jam 40 menit sampai +7 jam**. Contoh register 11:20 menghasilkan satu jendela **18:00–18:20 WIB pada tanggal yang dihitung**, dengan default pengingat H-30 17:30, H-15 17:45, dan H-0 18:00. Offset lain mengikuti REMINDER_MINUTES. Setelah 18:20 berlalu, jadwal menjadi tidak aktif dan tidak dibuat lagi untuk besok. Register lagi dengan waktu kemunculan baru untuk jadwal berikutnya. Tidak ada siklus 6 jam 40 menit otomatis.

Update pasangan **tempat + index** yang sama mengganti register sebelumnya. Volcano 3.1 dan Snowfield 3.1 memiliki timer terpisah; update Volcano 3.1 tidak mengubah Snowfield 3.1. Timer tersimpan setelah restart dengan tanggal/jam aslinya. Register lama yang sudah kedaluwarsa tetap tersimpan sebagai data, tetapi tidak mengirim pengingat lagi. `INDEX_31_TIMES` dan `INDEX_32_TIMES` dari env lama diabaikan, sehingga tidak ada jadwal tambahan tanpa register.

Tanggal default hari ini WIB. Untuk waktu kemunculan kemarin, isi `tanggal:YYYY-MM-DD`. Jika formula melintasi tengah malam, jadwal bisa jatuh besok dan tetap hanya sekali. Waktu kemunculan yang masih di masa depan ditolak. Jika jendela hasil perhitungan sudah seluruhnya lewat, bot memberitahu bahwa jendela sudah lewat, tanpa menggesernya ke besok. Pengingat yang terlewat mengikuti tenggang 60 detik, bukan dikirim sekaligus.

`/worldbossregister` tanpa opsi menampilkan spawn terdekat atau jendela yang masih aktif. Jika semua register sudah lewat, bot meminta register baru. `/jadwal` hanya menampilkan jendela yang aktif/akan datang, berhalaman bila perlu. Tempat tampil pada konfirmasi, jadwal, spawn terdekat, dan pesan pengingat.

## Izin edit timer

`ROLE_ID` menentukan role yang ditag pada notifikasi sekaligus role yang boleh memperbarui timer. ID role anggota harus sama persis; Manage Server/Administrator saja tidak menggantikan role tersebut. Role @everyone tidak boleh digunakan. Konfirmasi update bersifat privat. Anggota biasa tetap bisa melihat jadwal. `/tes` dan `/tesvoice` tetap memerlukan Manage Server.

## Pengumuman suara dari MP3

Bot kini memakai **10 rekaman MP3 dari pengguna**, tanpa sintesis TTS online. Pada H-30 dan H-15 bot masuk ke voice channel, memutar rekaman sesuai index, melanjutkan MP3 penutup `assets/outro.mp3`, lalu keluar. Pada H-0 bot memutar seruan komando tanpa penutup lalu keluar. `/tesvoice` memakai `test.mp3` dan MP3 penutup yang sama. Isi ucapan/RAWWRRRRR mengikuti rekaman asli; bot tidak menambahkan ucapan TTS lagi.

| Index | H-30 | H-15 |
| --- | --- | --- |
| 3.1 | `assets/voice/3_1_h30.mp3` | `assets/voice/3_1_h15.mp3` |
| 3.2 | `assets/voice/3_2_h30.mp3` | `assets/voice/3_2_h15.mp3` |
| 4.1 | `assets/voice/4_1_h30.mp3` | `assets/voice/4_1_h15.mp3` |
| 4.3 | `assets/voice/4_3_h30.mp3` | `assets/voice/4_3_h15.mp3` |
| Tes | `assets/voice/test.mp3` | — |

H-0 semua index memakai `assets/voice/spawn.mp3` (seruan komando dari unggahan pengguna), **tanpa MP3 penutup**. `/tesvoice index:3.1 menit:0` langsung memutarnya lalu bot keluar. H-0 mengacu ke awal jendela perkiraan, bukan deteksi spawn dalam game.

Semua rekaman disalin dari unggahan pengguna tanpa mengubah audio. Nama file dinormalisasi agar pemilihannya konsisten.

### Aktifkan di Wispbyte

1. Perbarui seluruh kode, `requirements.txt`, dan **folder `assets/` lengkap**, termasuk `assets/voice/` serta `assets/outro.mp3`. Instalasi Git dapat memakai `git pull origin main` atau `AUTO_UPDATE=1` sebelum restart.
2. Pastikan dependencies terpasang dari `requirements.txt` dan `PY_FILE=bot.py`.
3. Isi `.env` atau variabel Startup aktif:

```ini
VOICE_CHANNEL_ID=ISI_ID_VOICE_CHANNEL
VOICE_AUDIO_DIR=assets/voice
VOICE_VOLUME=5.0
VOICE_OUTRO_PATH=assets/outro.mp3
REMINDER_MINUTES=30,15,0
```

Ganti ID dengan ID voice channel biasa di server yang sama. `CHANNEL_ID` tetap memakai ID channel **teks** untuk pesan bertag role. Kosongkan `VOICE_CHANNEL_ID` untuk mematikan suara. `TTS_VOICE` tidak lagi digunakan dan boleh dihapus.

4. Beri bot izin **View Channel, Connect, dan Speak**. Bot harus tidak di-server-mute. Tidak perlu Administrator.
5. Restart, masuk ke voice channel tujuan, lalu jalankan **`/tesvoice`** dengan akun Manage Server. Log startup menampilkan `mode=recorded_mp3`.

Default pengingat sekarang **H-30, H-15, dan H-0**. Ubah environment aktif menjadi `REMINDER_MINUTES=30,15,0` untuk mengaktifkan pengumuman tepat pada awal perkiraan spawn; kode tidak menimpa environment aktif. Untuk tetap memakai pengingat teks H-5/H-3/H-1, gunakan `REMINDER_MINUTES=30,15,5,3,1,0`. Rekaman tersedia untuk H-30/H-15/H-0; offset lain hanya mengirim teks dan tag role.

### Tes rekaman H-30/H-15/H-0 langsung

Jalankan satu per satu saat berada di voice channel tujuan:

```text
/tesvoice index:3.1 menit:30
/tesvoice index:3.1 menit:15
/tesvoice index:3.1 menit:0
```

Perintah langsung memutar `3_1_h30.mp3` atau `3_1_h15.mp3`, lalu MP3 penutup, dan bot keluar. Angka menit memilih jenis rekaman; bukan menunggu 30/15 menit. Jalankan tes kedua setelah tes pertama selesai. Timer spawn, status pengiriman terjadwal, dan notifikasi teks tidak berubah.

Tanpa opsi, `/tesvoice` tetap memutar `test.mp3`. Opsi index dan menit harus diisi bersama. Mendukung juga 3.2, 4.1, dan 4.3; memerlukan Manage Server dan voice aktif. Setelah memperbarui kode, restart bot agar opsi baru tersinkronisasi ke Discord.

### Volume pengumuman

`VOICE_VOLUME=5.0` adalah default baru untuk memperkuat rekaman, termasuk `test.mp3` dan MP3 penutup. `1.0` berarti amplitudo asli, `2.0` dua kali, `3.0` tiga kali, dan `5.0` lima kali. Nilai yang diterima 0.1–5.0; gunakan titik untuk desimal. FFmpeg memakai limiter puncak 0.95 agar penguatan tidak langsung memotong puncak sinyal. File MP3 asli tidak diubah.

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
REMINDER_MINUTES=30,15,0
DB_PATH=data/trex.sqlite3
```

Angka ID di atas hanya contoh. Gunakan ID asli; role dan channel harus berada di server yang sama. Jangan menggunakan ID @everyone.

- `INDEX_31_TIMES` / `INDEX_32_TIMES`: variabel lama yang diabaikan. Semua jadwal berasal dari register satu kali.
- `REMINDER_MINUTES`: menit sebelum awal jendela spawn. Default `30,15,0` berarti H-30, H-15, dan saat awal perkiraan spawn.
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

Jika sebelumnya menjalankan Python langsung, hentikan proses lama, lalu jalankan `python bot.py` kembali dari environment yang sama. Jangan menimpa `.env`; atur `REMINDER_MINUTES` seperti contoh di atas. Jadwal hanya aktif setelah register; variabel INDEX_31_TIMES/INDEX_32_TIMES tidak digunakan.

Versi ini memakai timer sekali per register. Variabel lama `SPAWN_MIN_MINUTES` / `SPAWN_MAX_MINUTES` tidak digunakan; interval perhitungan tetap 400–420 menit. Versi tempat + index membuat tabel timer baru dan mereset timer format lama satu kali; data poin, raid, dan redeem tidak dihapus.

### Wispbyte

Pada halaman Startup gunakan `PY_FILE=bot.py`, `REQUIREMENTS_FILE=requirements.txt`, dan `AUTO_UPDATE=1` jika proyek dipasang sebagai git checkout. Restart dari panel untuk menarik kode dan menyinkronkan opsi `/worldbossregister`. Jika instalasi tidak memiliki folder `.git`, perbarui file proyek dari GitHub sebelum restart. Jangan mengganti `.env` atau menghapus folder `data/` ketika memperbarui kode.

## Perintah Discord

- `/worldbossregister`: tampilkan spawn terdekat atau jendela aktif, tanggal WIB, dan sisa waktu. Respons publik tanpa tag role. Jika tidak ada jadwal aktif, meminta register baru tanpa mengulang jadwal lama. Sisa waktu dihitung saat dipanggil, bukan diperbarui terus-menerus.
- `/worldbossregister index:3.1 tempat:Volcano waktu:11:20`: perbarui timer satu pasangan tempat + index. `index`, `tempat`, dan `waktu` wajib diisi bersama; `tanggal` opsional. Hanya anggota dengan role sesuai `ROLE_ID` yang dapat mengedit.
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

Tes memeriksa register satu kali, tidak adanya jadwal default, pembatalan pengingat lama, isolasi antar-index, tidak berulang setelah restart, WIB pada server UTC, lintas tengah malam, validasi input/izin, restart, retry, pengingat kedaluwarsa, pembatasan mention role, pemilihan spawn terdekat, respons `/worldbossregister`, antrean suara, pembatalan timer, izin voice, dan pembersihan koneksi/audio saat gagal. Pengiriman asli diuji dengan `/tes` setelah token/ID dipasang.

## Raid manual: T-Rex, Rift, Savage

Fitur raid terpisah dari timer T-Rex: semua event pendaftaran dibuat manual dan tidak berulang otomatis. `/worldbossregister` tetap untuk timer; `/worldbossraid` untuk pendaftaran. Event raid tidak menjadwalkan voice/pengingat tambahan.

### Pengaturan Wispbyte

1. Buat channel teks `#pendaftaran-raid` di server dan salin ID-nya. Bot tidak otomatis membuat channel.
2. Buat/pilih role leader. Anggota dengan role ini boleh membuat dan mengelola event. Pembuat event juga menjadi leader event tersebut.
3. Tambahkan variabel berikut di `.env` atau Startup yang aktif:

```env
RAID_CHANNEL_ID=ISI_ID_CHANNEL_PENDAFTARAN_RAID
RAID_COMMAND_CHANNEL_ID=ISI_ID_CHANNEL_PENDAFTARAN_RAID
RAID_LEADER_ROLE_ID=ISI_ID_ROLE_LEADER
```

`RAID_CHANNEL_ID` adalah tujuan kartu event dan tombol. `RAID_COMMAND_CHANNEL_ID` adalah tempat leader menjalankan perintah pembuatan event; boleh berbeda jika ingin channel notifikasi terpisah. Jika kosong, channel perintah mengikuti channel kartu, dan channel kartu mengikuti `CHANNEL_ID`. Role leader kosong mengikuti `ROLE_ID`; role `@everyone` tidak dianggap role leader. Pembuat event atau pemegang role leader dapat mengelola event. Izin Manage Server saja tidak menggantikan role leader.

4. Beri bot View Channel, Send Messages, dan Embed Links pada channel kartu; izinkan anggota melihat channel dan memakai Application Commands. Kartu pertama menandai role `ROLE_ID` yang sudah dipakai notifikasi T-Rex. Pastikan role tersebut mentionable atau bot diizinkan mention role itu. Perubahan daftar tidak mengirim ping lagi.
5. Perbarui kode termasuk **`raids.py` dan `raid_store.py`**, lalu restart. Tidak ada dependency baru. Dockerfile sudah menyertakan kedua modul baru. Pertahankan `.env`, `DB_PATH`, dan folder `data/`; tabel raid ditambahkan tanpa mengganti timer/receipt lama. Cadangkan database saat bot berhenti sebelum update.

### Perintah

```text
/worldbossraid jam:18:00 tempat:Gurun index:3.1
/rift jam:20:00 tempat:Pantai
/savage jam:21:00 tempat:Savana
/rift jam:00:10 tempat:Pantai tanggal:2026-11-03
/raid
/raid event:1
/leaderboard
/leaderboard halaman:2
```

Semua jam WIB. Tanggal default hari ini, dan jam yang sudah lewat ditolak (menit berjalan masih boleh). Untuk besok isi tanggal secara eksplisit. Pilih jam/tanggal mendatang saat mencoba contoh di atas. `/raid` menampilkan 10 event terbaru; `event` adalah nomor pada judul kartu, bukan ID pesan Discord. `/raid event:<nomor>` juga bisa digunakan jika kartu di channel gagal diperbarui atau terhapus.

### Alur sederhana

Kartu hanya menampilkan **Menunggu diterima**, **Hadir**, dan **Tidak Hadir**.

- **Daftar:** masuk Menunggu diterima. Belum mendapat poin. Klik berulang tidak menggandakan entri; peserta berstatus Hadir tetap Hadir.
- **Tidak Hadir:** menyatakan tidak ikut/membatalkan pendaftaran. Jika sebelumnya Hadir, poin event ini langsung ditarik. Bisa Daftar lagi, tetapi perlu diterima ulang.
- **Kelola — Leader:** panel privat dengan menu peserta, **Hadir**, dan **Tidak Hadir**. Ada navigasi halaman untuk lebih dari 25 peserta.
- **Hadir:** langsung mengubah status menjadi Hadir dan menambah poin sesuai jenis raid: **World Boss/T-Rex 40**, **War di Savage 50**, **Rift 35**, tanpa menunggu jam event atau Selesaikan Event. Satu peserta hanya mendapat satu pemberian poin per event, termasuk jika tombol ditekan berulang.
- Leader dapat menandai peserta **Tidak Hadir** untuk membatalkan penerimaan dan menarik poin. Peserta perlu memilih Daftar lagi sebelum diterima ulang.
- **Selesaikan Event:** menutup perubahan daftar dan mempertahankan poin yang sudah tercatat, tanpa memberi poin tambahan. Tersedia mulai jam event. Ada konfirmasi sebelum penutupan; periksa daftar dahulu.
- **Batalkan Event:** menutup event dan menarik semua poin event ini, tanpa memengaruhi poin dari event lain.

Leader tidak mendapat poin otomatis karena membuat event. Leader/role pengelola dipercaya menentukan peserta diterima, termasuk dirinya sendiri jika mendaftar. Tidak ada tombol Absen atau Sahkan Hadir. Penutupan final pada versi awal: belum ada fitur buka ulang/koreksi poin setelah event ditutup.

### Poin kontribusi administrator

`/addpoint` hanya bisa dipakai anggota yang memiliki izin **Administrator** bawaan pada server Discord yang dikonfigurasi. Tidak memerlukan role khusus atau env tambahan. Manage Server saja, role leader, atau menjadi pembuat event tidak cukup. Hak pengelolaan raid tetap mengikuti leader event/RAID_LEADER_ROLE_ID.

```text
/addpoint user:@C.Ago point:5 detail:Membantu material guild
/leaderboard
```

`user` memilih satu anggota server (bukan bot), `point` bilangan bulat positif 1–1000000, dan `detail` wajib 1–500 karakter setelah spasi tepi dibuang. Perintah dapat dijalankan di channel mana pun pada server yang dikonfigurasi. Respons pemberian poin dikirim **publik pada channel tempat perintah dijalankan**, dengan mention role `ROLE_ID` seperti notifikasi T-Rex. Semua anggota yang punya akses ke channel itu dapat melihatnya. Pastikan role mentionable atau bot punya izin mention role, sama seperti konfigurasi pengingat T-Rex. Teks detail tidak dapat memicu ping tambahan. Perubahan ini berlaku untuk pesan `/addpoint` baru; pesan privat lama tidak berubah. ID kontribusi, penerima, jumlah poin, detail, pemberi, waktu, dan ID interaksi Discord disimpan di tabel `raid_contributions`. Tidak ada fitur ubah/hapus kontribusi pada versi ini.

Satu `/addpoint` = satu contribution, berapa pun poinnya. Contoh Hadir pada satu World Boss/T-Rex (40), satu War di Savage (50), dan satu Rift (35), ditambah satu `/addpoint` 5 poin:

> 1. **@C. Ago** — **130 poin** · 3 event, 1 contribution

Anggota yang hanya punya poin kontribusi tetap masuk leaderboard dengan 0 event. Poin kontribusi tidak ditarik jika peserta memilih Tidak Hadir atau suatu raid dibatalkan. Pengiriman ulang interaksi Discord yang sama tidak menggandakan pemberian; menjalankan perintah baru adalah kontribusi baru.

Setelah update, restart agar perintah baru tersinkronisasi. Data timer, raid, dan poin sebelumnya tetap dipertahankan.

### Mengurangi poin anggota

```text
/remove user:@anggota point:10 detail:Alasan pengurangan
```

Hanya pemilik izin **Administrator** server yang bisa menjalankan, sama seperti `/addpoint`. Isi jumlah positif 1–1000000 dan alasan wajib 1–500 karakter. Bot mengurangi total poin anggota sebanyak jumlah tersebut; saldo dapat menjadi negatif. Hasil diumumkan publik pada channel perintah dengan mention `ROLE_ID`, sama seperti pengumuman kontribusi.

Pengurangan disimpan terpisah di `raid_deductions`, termasuk penerima, jumlah, alasan, administrator pemberi, waktu, dan ID interaksi. Jumlah event dan contribution tetap. `/point` menampilkan rincian Pengurangan dan total bersih; leaderboard juga memakai total bersih. Pengiriman ulang interaksi yang sama tidak mengurangi dua kali. Alasan tidak memicu ping tambahan. Wipe dari console mereset pengurangan sekaligus poin event/kontribusi sehingga total benar-benar kembali nol; riwayat tetap disimpan untuk audit.

### Cek poin per anggota

```text
/point
/point user:@C.Ago
```

`/point` tanpa opsi menampilkan poin sendiri. Isi `user` untuk melihat satu anggota lain pada server yang sama. Semua anggota bisa memakai perintah ini, tanpa izin Administrator. Hasil hanya terlihat oleh pemanggil: total poin, jumlah event beserta poin event, dan jumlah contribution beserta poin kontribusi. Anggota yang belum mendapat poin ditampilkan sebagai 0. Ringkasan memakai data yang sama dengan leaderboard dan tidak mengubah poin.

### Reset poin hanya dari Console Wispbyte

Tidak ada slash command Discord untuk wipe, tidak memerlukan role atau env owner. Hak Administrator Discord tidak memberi akses reset. Operator yang dapat mengakses console hosting bisa menjalankannya; batasi akses panel Wispbyte sesuai kebutuhan.

Setelah update kode termasuk `console_commands.py`, restart bot. Tunggu log `Console aktif`, lalu ketik langsung di input **Console Wispbyte** saat proses bot berjalan (tanpa `/`):

```text
wipepoint HAPUS SEMUA POIN
```

Frasa `HAPUS SEMUA POIN` adalah konfirmasi wajib dan harus sama persis. `wipepoint` saja hanya menampilkan petunjuk, tidak menghapus data. Perintah ini mereset **semua poin event dan kontribusi seluruh anggota pada GUILD_ID aktif**, termasuk jumlah event/contribution yang dihitung oleh leaderboard dan `/point`. Bukan perintah shell, dan jangan dikirim ke chat Discord.

Timer T-Rex, daftar peserta, pesan event, dan detail historis kontribusi tetap disimpan. Riwayat reset disimpan untuk audit. Poin event lama yang direset tidak dipulihkan saat restart atau klik Hadir lagi pada peserta/event yang sama. Peserta baru yang belum memiliki poin pada event itu dan event baru tetap bisa mendapat poin. Kontribusi baru setelah reset juga dihitung normal. Reset tidak dapat dibatalkan lewat bot; buat cadangan database saat bot berhenti jika perlu pemulihan.

Jika hosting tidak menyediakan stdin untuk proses bot, startup mencatat `Input console tidak tersedia`; fitur wipe tidak aktif di lingkungan itu. Jalur stdin telah diuji menggunakan pipe lokal, tetapi penerusan input pada panel Wispbyte perlu dicoba setelah deployment.

### Data dan restart

`raid_events`, `raid_participants`, `raid_points`, dan `raid_audit` disimpan pada database `DB_PATH` yang sama. Poin disimpan per event dan Discord user ID, bukan nama, sehingga perubahan nickname tidak mengubah total. Ledger membatasi satu pemberian poin per anggota per event, dengan bobot menurut jenis raid. Perubahan status beserta penambahan/penarikan poin dilakukan dalam satu transaksi. Saat update dari versi lama, Hadir disahkan menjadi Hadir; Ditolak/Tidak datang menjadi Tidak Hadir. Peserta Hadir pada event terbuka/selesai dihitung ulang sesuai bobot World Boss/T-Rex 40, War di Savage 50, Rift 35, tanpa menggandakan jumlah event. Catatan poin yang sudah di-wipe dikecualikan agar tidak muncul lagi. Event batal tidak mendapat poin. `/leaderboard` menghitung total poin semua jenis raid dan kontribusi manual untuk server ini, 10 anggota per halaman. Jumlah event hanya menghitung poin raid; jumlah contribution hanya menghitung transaksi `/addpoint`.

Tombol event terbuka dipulihkan dari database ketika startup. Bot harus online untuk memproses klik; saat offline Discord akan menampilkan kegagalan interaksi. Setelah bot aktif, coba klik kembali. Event tertutup tetap dapat dilihat dengan `/raid`, tetapi tidak menerima perubahan. Jika perubahan kartu gagal akibat izin/jaringan, data tetap tersimpan dan respons mengarahkan ke `/raid event:<nomor>`.

### Mencoba versi awal

1. Gunakan channel uji dan role leader milikmu, lalu buat `/rift` dengan jam WIB beberapa menit ke depan.
2. Dari akun peserta, coba **Daftar**, lalu **Tidak Hadir**, lalu **Daftar** lagi.
3. Leader membuka Kelola, memilih peserta, dan klik Hadir. `/leaderboard` langsung bertambah 35 poin. Klik Hadir lagi untuk memastikan poin tetap 35.
4. Restart bot selagi event terbuka dan coba tombol/panel lagi.
5. Coba Tidak Hadir untuk menarik poin, lalu Daftar dan Hadir ulang. Setelah jam event, Selesaikan Event dan konfirmasi: total poin tetap sama, tidak bertambah lagi.
6. Untuk membersihkan poin event uji yang masih terbuka, gunakan Batalkan Event. Reset seluruh poin server tersedia hanya melalui console hosting seperti dijelaskan di bawah.

Tes otomatis mencakup tiga status, poin langsung saat ditandai Hadir, penarikan poin, upgrade data lama, pemulihan setelah restart, izin lintas role/server, pembatalan, leaderboard, isolasi data timer lama, dan klik berulang tanpa poin ganda. Pengujian Discord langsung memerlukan bot berjalan dengan konfigurasi server milikmu.

## Katalog redeem dan penyerahan barang

Katalog awal diisi **sekali untuk server ini** pada startup setelah update:

| Item | Harga tukar |
|---|---:|
| Senjata Tarbo | 200 poin |
| Senjata Iguana | 200 poin |
| Senjata Amarga | 300 poin |
| Senjata T-Rex | 500 poin |
| Armor Brachi / RedIguana | 200 poin |
| Kepala (helm) Brachi / RedIguana | 100 poin |
| Sarung tangan | 80 poin |
| Sepatu | 80 poin |

Sarung tangan/sepatu termasuk katalog awal dan dapat dihapus jika tidak diperlukan. Tidak ada batas stok otomatis pada versi awal; Administrator perlu memastikan barang bisa disediakan. Bot mencatat penukaran, sedangkan barang game diserahkan manual.

### Untuk anggota

```text
/katalog
/katalog halaman:2
/redeem
/redeem item:1
/redeemhistory
```

`/katalog` menampilkan kartu publik dengan tombol **Tukar Poin**. Anggota yang menekan tombol mendapat menu privat berisi saldo dan pilihan item. Pilih item lalu **Konfirmasi Redeem**; pilihan item mengganti menu yang sama, dan hasil penukaran mengganti konfirmasi agar tidak membuat banyak chat. `/redeem item:<nomor>` bisa langsung membuka konfirmasi. Nomor item ditampilkan di katalog; gunakan nomor aktual, jangan mengandalkan nomor contoh.

Satu konfirmasi = satu item, dengan poin dipotong langsung saat berhasil dan status **Menunggu penyerahan**. Saldo diperiksa ulang ketika konfirmasi; saldo yang kurang, item dihapus, atau harga berubah membatalkan proses tanpa biaya. Tombol Batal sebelum konfirmasi tidak memotong poin. Klik konfirmasi ganda tidak membuat penukaran ganda. Untuk meminta item kedua, jalankan redeem baru.

`/redeemhistory` menampilkan 10 penukaran milik sendiri per halaman, termasuk nomor penukaran, nama item, harga, dan status. Anggota menghubungi Administrator untuk penyerahan atau pembatalan setelah konfirmasi. Menu/konfirmasi privat berlaku 3 menit; setelah restart buka `/redeem` lagi. Kartu katalog publik tetap bisa membuka menu baru setelah restart.

### Untuk Administrator server

```text
/katalogadd nama:Senjata Baru harga:250
/katalogremove item:1
/redeemqueue
/redeemstatus id:1 status:Sudah diserahkan
/redeemstatus id:1 status:Batalkan dan kembalikan poin
```

Semua perintah pengelolaan memerlukan izin **Administrator** bawaan Discord. `katalogadd` menerima nama 1–100 karakter dan harga 1–1000000 poin. Nama aktif yang sama tidak bisa diduplikasi. `katalogremove` menghapus item dari katalog aktif tanpa menghapus riwayat/penukaran yang sudah tercatat. Untuk mengganti harga, hapus item lama lalu tambahkan kembali dengan harga baru; nomor item ikut berubah.

Kartu `/katalog` lama merupakan tampilan saat dikirim. Jalankan `/katalog` lagi untuk menampilkan daftar publik terbaru; tombol Tukar Poin pada kartu lama selalu membuka data aktif terbaru. Item yang telah dihapus tidak muncul kembali saat bot restart.

`/redeemqueue` menampilkan penukaran yang masih menunggu penyerahan. Pilih status dari dropdown `/redeemstatus`: **Sudah diserahkan** setelah barang diberikan, atau **Batalkan dan kembalikan poin** jika tidak dapat dipenuhi. Penyelesaian tidak memotong poin lagi. Pembatalan mengembalikan poin satu kali. Penukaran selesai/dibatalkan tidak bisa diubah lagi. Nomor `id` adalah nomor penukaran, bukan nomor item.

### Saldo, penyimpanan, dan update

Saldo `/point` dan leaderboard = poin event + kontribusi − pengurangan − harga redeem yang aktif/selesai. `/point` juga menampilkan **Redeem terpakai**. Jumlah event dan contribution tidak berkurang saat belanja; redeem tidak dihitung sebagai contribution.

Nama/harga disimpan pada setiap penukaran sehingga perubahan katalog tidak mengubah pembelian lama. Saldo dicek dan penukaran ditulis dalam satu transaksi SQLite; dua konfirmasi bersamaan tidak bisa memakai saldo yang sama melebihi saldo tersedia. Tabel katalog, audit, dan penukaran menggunakan `DB_PATH` yang sama dengan data bot lainnya.

Wipe dari console juga mereset pengeluaran redeem agar saldo kembali nol. Riwayat dan pesanan tetap tersimpan untuk penyerahan barang. Pembatalan pesanan yang biaya poinnya sudah di-wipe tidak mengembalikan poin lama; bot menampilkan pengembalian 0 poin. Pesanan baru setelah wipe memakai saldo baru secara normal.

Update seluruh kode termasuk **`redeem.py` dan `redeem_store.py`**, lalu restart untuk sinkronisasi slash command dan pengisian katalog awal. Tidak ada env/dependency baru. Pertahankan `.env`, `DB_PATH`, dan folder `data/`. Dockerfile sudah menyertakan modul baru.

Tes otomatis memeriksa katalog awal, perubahan katalog setelah restart, saldo/klik ganda, dua koneksi yang bertransaksi bersamaan, izin Administrator, privasi riwayat, pembatalan/refund, dan interaksi dengan wipe. Pemakaian langsung di Discord perlu diuji setelah bot di Wispbyte diperbarui.

## World boss register: index, tempat, waktu

```text
/worldbossregister index:1.1 tempat:Volcano waktu:11:20
/worldbossregister index:8.5 tempat:Snowfield waktu:12:00
/worldbossraid jam:18:00 tempat:Gurun index:8.5
/jadwal halaman:2
```

Format update timer adalah **index → tempat → waktu**, dengan tanggal opsional. `waktu` tetap waktu terakhir boss muncul, bukan langsung waktu spawn berikutnya. Rumus perkiraan berikut tetap +6 jam 40 menit sampai +7 jam, hanya untuk satu jendela dari register tersebut. Tanpa opsi, `/worldbossregister` tetap menampilkan jadwal terdekat. Update memerlukan role `ROLE_ID` seperti sebelumnya.

Index menerima 1.1–1.5, 2.1–2.5, sampai 8.1–8.5. Karena ada 40 kombinasi, menu memakai autocomplete maksimal 25 saran per pencarian: ketik angka utama seperti `8.` untuk melihat semua sub-index yang cocok. `/worldbossraid` memakai index yang sama. Memilih index baru tidak mengaktifkan jadwal sampai waktu terakhir muncul diisi.

Tempat wajib dipilih dari enam pulau dan disimpan bersama index sebagai satu pasangan unik per server. Tempat tampil pada konfirmasi, jadwal, spawn terdekat, dan pesan pengingat. Timer format lama direset satu kali saat pembaruan pertama ke versi tempat + index; isi register baru untuk mulai menjadwalkan kembali. `/jadwal` dibagi menjadi halaman jika daftar panjang agar semua index bisa dibaca.

Notifikasi teks berlaku untuk semua index. Rekaman H-30/H-15 tetap hanya untuk 3.1, 3.2, 4.1, dan 4.3; index lain tidak memakai rekaman bernama index lain. H-0 semua index memakai audio `spawn.mp3` yang sama tanpa penutup. Command `/tesvoice` tetap memilih empat index rekaman lama.

Perbarui seluruh kode termasuk **`bot.py`, `schedule.py`, `raids.py`, dan `voice_alerts.py`**, lalu restart. Migrasi membuat tabel worldboss_timers dengan ID unik dan pembatas unik server + tempat + index. Sesuai permintaan, timer lama di timer_overrides dikosongkan satu kali; poin, raid, dan riwayat redeem tidak dihapus. Register format baru tetap tersimpan pada restart berikutnya. Pertahankan `DB_PATH` dan folder `data/`.

## Timer per pulau dan index

```text
/worldbossregister index:3.1 tempat:Volcano waktu:11:20
/worldbossregister index:3.1 tempat:Snowfield waktu:12:00
```

Kedua register tersimpan bersama. Identitas jadwal adalah **server + tempat + index**, dengan ID database unik. Update pasangan yang sama mempertahankan ID-nya dan mengganti waktunya. Pilihan tempat tetap **Volcano, Snowfield, Tundra, Swamp, Desert, Tropical**; kapitalisasi dinormalisasi agar `volcano` dan `Volcano` tidak membuat dua timer. Setiap pulau mendukung 40 index (1.1–8.5).

Jadwal, notifikasi teks, dan pencatatan pengiriman voice membedakan pulau, termasuk bila dua pulau memiliki index dan waktu spawn persis sama. `/jadwal` menampilkan setiap pasangan aktif dan membagi hasil menjadi halaman. Formula tetap +6 jam 40 menit sampai +7 jam, sekali per register.

**Reset timer lama:** pada startup pertama setelah update ini, bot mengosongkan tabel timer format lama (`timer_overrides`). Ini sesuai permintaan untuk mulai dari register baru. Tidak perlu menjalankan wipe point atau menghapus database. Poin, riwayat kontribusi, pengurangan, redeem, dan data raid tetap ada. Reset migrasi hanya sekali; timer format baru tidak dihapus saat restart berikutnya. Setelah update, register kembali pasangan pulau + index yang ingin dipantau.

Perbarui `bot.py` dan `schedule.py` bersama, lalu restart untuk sinkronisasi pilihan tempat dan reset timer lama. Pertahankan file database yang sekarang.

## Referensi

- https://discordpy.readthedocs.io/en/stable/ext/tasks/index.html
- https://discordpy.readthedocs.io/en/stable/api.html#discord.AllowedMentions
- https://discordpy.readthedocs.io/en/stable/interactions/api.html
