# Bot Pengeluaran Telegram — Versi 2.4

Versi 2.4 menambahkan **pemasukan dan saldo**, serta **dompet/sumber pembayaran dan transfer antardompet**. Saldo dapat dilihat per dompet atau per bulan dan diunduh sebagai Excel arus kas. Semua fitur sebelumnya tetap tersedia: pengeluaran beberapa baris, kategori otomatis, favorit, tagihan, anggaran, rekap otomatis, edit dan Urungkan edit pengeluaran, pencarian, serta cadangan dan pemulihan. Program memakai Python dan SQLite, tanpa paket Python tambahan.

| Fitur baru | Buka dari bot |
| --- | --- |
| Catat pemasukan dengan konfirmasi | Catat → Pemasukan, atau `/pemasukan` |
| Saldo awal, pemasukan, pengeluaran, dan saldo akhir bulan | Saldo & dompet, atau `/saldo` |
| Kelola Tunai, Bank, DANA, atau sumber pembayaran lain | Pengaturan → Dompet & saldo awal, atau `/dompet` |
| Catat perpindahan uang tanpa menggandakan pengeluaran | Catat → Transfer, atau `/transfer` |
| Excel saldo per dompet dan buku kas | Saldo & dompet → Excel arus kas |

**Sudah memakai versi lama? Ikuti bagian pembaruan di bawah lebih dahulu agar konfigurasi dan catatanmu ikut terbawa.**

## Memperbarui versi lama

1. Hentikan bot lama dengan **Ctrl+C**. Salin seluruh folder lama sebagai cadangan.
2. Ekstrak ZIP versi 2.4 ke **folder baru**, misalnya `Documents\BotPengeluaranV24`.
3. Salin **`config.json` milikmu dari folder lama** ke folder baru, menggantikan konfigurasi contoh dalam paket. Token dan ID pengguna tidak perlu dibuat ulang.
4. Salin **folder `data` dari folder lama** ke folder baru. Pastikan `data\pengeluaran.db` terbawa. Jika lokasi database dalam konfigurasi berbeda, pertahankan lokasi tersebut atau salin database lalu sesuaikan konfigurasi.
5. Jalankan `JALANKAN_WINDOWS.bat` dari folder baru, lalu kirim **`/start`** ke bot.
6. Buka **Riwayat → Hari ini** atau **Laporan → Bulanan** dan cocokkan total dengan versi lama.
7. Buka **`/dompet`**. Catatan lama masuk ke dompet **Umum**. Atur saldo awal dan buat dompet lain sesuai kebutuhan sebelum mengandalkan angka saldo.

Pembaruan dari versi 2.3 mempertahankan catatan aktif/terhapus, riwayat edit, anggaran dan batas pemberitahuannya, kategori otomatis, favorit, tagihan, jadwal rekap dan status kiriman, pengingat, serta zona waktu. Struktur baru ditambahkan otomatis. **Nominal, tanggal, kategori, dan ID pengeluaran lama tetap sama.** Sumber pembayaran lama tidak ditebak: semuanya masuk ke **Umum**, lalu dapat dipindahkan lewat Edit → Dompet pembayaran. Template favorit/tagihan lama mengikuti dompet bawaan ketika dipakai. Tidak ada token atau variabel hosting baru yang perlu dibuat.

Saldo awal dompet **belum diatur** setelah pembaruan. Bot memakai Rp0 sementara untuk perhitungan dan memberi penanda **Saldo sementara**. Masukkan saldo sebelum seluruh transaksi yang tercatat di dompet tersebut; jangan langsung memasukkan saldo saat ini. Jika memang mulai dari nol, simpan angka `0`. Pemasukan dan transfer lama yang belum pernah dicatat perlu kamu tambahkan sendiri.

Jika berasal dari versi 2.2, kategori otomatis mulai dengan lima aturan awal untuk catatan baru; kategori lama tetap. Rekap terjadwal belum aktif sampai kamu mengaktifkannya. Favorit, anggaran kategori, dan tagihan awalnya kosong.

Jika berasal dari versi 2.1 atau lebih lama, anggaran lama menjadi nominal khusus pada bulan masing-masing. Riwayat edit mulai tersedia sejak memakai versi yang mendukungnya; perubahan lama tidak direkonstruksi.

Pada startup pertama, sebelum mengubah struktur versi lama, program menyimpan salinan `before-v2.4-....db` di folder cadangan. Tetap salin folder lama pada langkah pertama. Untuk kembali ke versi lama, gunakan kode dan database dari salinan sebelum pembaruan.

Untuk hosting, unggah seluruh kode terbaru, termasuk **`v24.py`, `storage_v24.py`, `excel_cash.py`**, modul versi sebelumnya, **kedua template dalam folder `assets`**, dan Dockerfile terbaru. Pertahankan Volume, `DB_PATH`, token, dan variabel lama. Jangan membuat Volume kosong sebagai pengganti Volume yang menyimpan datamu.

Jalankan **satu proses bot untuk satu token**. Jangan menjalankan versi lama dan versi baru bersamaan. Jangan menimpa konfigurasi milikmu dengan konfigurasi contoh yang masih kosong.

Catatan lama yang terlanjur berisi `makan siang 25000 bensin 50000 uang kas` tetap dipertahankan sebagaimana tersimpan. Untuk membetulkannya, hapus catatan tersebut melalui tombol, lalu kirim ulang pengeluarannya dengan satu pengeluaran per baris.

## Menu yang lebih mudah digunakan

Kirim `/start` atau `/menu`. Sapaan menampilkan `Halo! @username`. Jika akunmu tidak memiliki username, bot memakai nama Telegrammu.

Menu menampilkan zona waktu, tanggal dan jam saat dibuka, total pengeluaran hari ini, jumlah catatan, total pengeluaran bulan ini, serta saldo gabungan seluruh dompet. Pilihan zona waktu: **WIB, WITA, WIT**, melalui **Pengaturan → Zona waktu** atau `/zona`. Pilihan disimpan untuk setiap pengguna; bawaan awal adalah WIB. Lokasi pengguna tidak ditebak otomatis.

Jam diperbarui saat membuka menu atau menekan **Perbarui**. Angka pada pesan yang sudah dikirim tidak bergerak sendiri setiap detik. Tanggal pengeluaran otomatis memakai waktu pengiriman pesan dalam zona yang dipilih. Mengubah zona tidak menggeser tanggal catatan yang sudah tersimpan.

| Menu utama | Isi |
| --- | --- |
| Catat | Pengeluaran satu/beberapa baris, pemasukan, transfer, dompet, favorit, tagihan, kategori otomatis |
| Riwayat | Pengeluaran, pemasukan, transfer, edit, hapus/pulihkan; pencarian dan pilihan beberapa untuk pengeluaran |
| Laporan | Laporan pengeluaran, saldo & arus kas, Excel, perbandingan antarbulan, rekap otomatis |
| Anggaran | Batas bulanan dan per kategori, sisa, nominal khusus, anggaran otomatis |
| Saldo & dompet | Saldo per bulan, pemasukan, transfer, kelola dompet, Excel arus kas |
| Pengaturan | Dompet & saldo awal, pengingat, zona, kategori otomatis, rekap otomatis, tagihan, bantuan, bersihkan chat, cadangan khusus pemilik |
| Perbarui | Muat ulang jam dan ringkasan |

Tombol navigasi memperbarui pesan menu yang sama agar chat tidak cepat menumpuk. Daftar panjang dibagi enam catatan per halaman. Nomor tampilan menggunakan **1., 2., 3.**, tanpa tanda pagar. Nomor urut mengikuti daftar yang sedang dibuka; ID catatan tetap tersedia dalam rincian Excel.

## Dompet dan saldo awal

1. Buka **`/dompet`** atau **Pengaturan → Dompet & saldo awal**.
2. Pilih **Umum** untuk memakai dompet bawaan. Kamu dapat **Ganti nama** menjadi Tunai jika sesuai dengan sumber semua catatan di dalamnya. Mengganti nama mempertahankan transaksi dan saldo.
3. Tekan **Atur saldo awal**, kirim nominal atau `0`, periksa saldo hasil perhitungan, lalu **Ya, simpan**.
4. Gunakan **Tambah dompet** untuk membuat Bank, DANA, atau sumber lain; atur saldo awal setiap dompet baru.
5. Buka dompet yang paling sering digunakan, lalu **Jadikan dompet bawaan**. Pencatatan tanpa nama dompet memakai pilihan ini.

**Saldo awal adalah saldo sebelum seluruh transaksi dompet yang tercatat di bot**, bukan saldo saat mengubah pengaturan. Contoh: hanya ada pengeluaran lama Rp300.000, tanpa pemasukan/transfer, dan saldo nyata kini Rp100.000; saldo awalnya Rp400.000. Saldo awal tidak memiliki tanggal dan tidak dihitung sebagai pemasukan. Mengaturnya lagi **mengganti** nominal awal, sehingga saldo historis ikut dihitung ulang.

Setiap dompet menghitung **saldo awal + pemasukan − pengeluaran + transfer masuk − transfer keluar** dari catatan aktif. Saldo yang belum lengkap dapat menjadi negatif; periksa saldo awal dan transaksi yang terlewat. Ini pembukuan manual, tanpa sambungan ke rekening bank atau e-wallet.

Nama dompet 1–32 karakter, tanpa tanda pemisah `|`, dan harus unik pada akunmu tanpa membedakan huruf besar/kecil. Maksimal 20 dompet termasuk Umum. Versi ini menyediakan tambah, ganti nama, saldo awal, dan pilihan bawaan; belum menyediakan penghapusan dompet. **Riwayat dompet** menampilkan pengeluaran, pemasukan, serta transfer masuk/keluar untuk membuka transaksi terkait.

## Pemasukan dan saldo

Buka **Catat → Pemasukan**, lalu kirim nominal dan keterangan. Bisa juga langsung:

```text
/pemasukan 2jt gaji | Gaji | Bank
/pemasukan 2026-09-20 500rb uang saku | Lainnya | Tunai
```

Nama dompet harus sudah dibuat. Kategori dan dompet boleh dikosongkan; kategori awal pemasukan adalah **Lainnya**, dan penerima mengikuti dompet bawaan. Satu pemasukan per pesan. Bot menampilkan tinjauan dengan tombol untuk mengubah nominal, tanggal, keterangan, kategori, dan dompet penerima. Catatan baru disimpan setelah **Ya, simpan**. Tanggal masa depan ditolak.

Kirim **`/saldo`** untuk bulan berjalan, atau **`/saldo 2026-09`** untuk bulan tertentu. Laporan menunjukkan saldo awal periode, pemasukan, pengeluaran, selisih pemasukan/pengeluaran, dan saldo akhir periode. Saldo awal periode sudah mencakup saldo awal dompet serta semua transaksi sebelum bulan tersebut. Saldo akhir memakai transaksi sampai akhir bulan; untuk bulan berjalan, hasilnya mengikuti data yang sudah dicatat.

**Riwayat → Pemasukan → pilih catatan** menyediakan **Edit transaksi**, **Hapus transaksi**, dan pemulihan catatan yang terhapus. Perubahan dikonfirmasi dahulu dan saldo dompet dihitung ulang. Fitur Riwayat edit/Urungkan edit, pencarian, dan pilihan beberapa tetap khusus pengeluaran; koreksi pemasukan dilakukan lewat Edit transaksi.

Saldo dan anggaran memiliki tujuan berbeda: saldo mengikuti uang masuk/keluar yang dicatat, sedangkan anggaran adalah batas pengeluaran. Pemasukan tidak menambah nominal anggaran atau mengurangi pemakaiannya.

## Transfer antardompet

1. Siapkan sedikitnya dua dompet melalui `/dompet`.
2. Buka **Catat → Transfer** atau **`/transfer`**.
3. Pilih dompet asal, lalu dompet tujuan yang berbeda.
4. Kirim nominal dan keterangan, misalnya `100rb top up DANA`; nominal saja juga diterima.
5. Periksa nominal, tanggal, asal, dan tujuan. Gunakan tombol untuk koreksi, lalu **Ya, simpan**.

Transfer mengurangi saldo asal dan menambah saldo tujuan dalam satu catatan. **Total saldo gabungan tetap sama**; transfer tidak dihitung sebagai pemasukan eksternal, pengeluaran, atau pemakaian anggaran. Catat biaya admin terpisah sebagai pengeluaran pada dompet yang membayarnya. Tombol hanya membukukan perpindahan uang yang kamu lakukan sendiri; tidak mengirim uang melalui bank/e-wallet.

Buka **Riwayat → Transfer** untuk edit, hapus, atau pulihkan dengan konfirmasi. Kedua sisi saldo ikut diperbarui bersama. Tanggal mengikuti zona pilihanmu dan boleh diubah ke tanggal sebelumnya. Konfirmasi yang ditekan berulang tidak menggandakan transaksi yang sama.

Draf pemasukan/transfer dan pengaturan dompet kedaluwarsa setelah 30 menit tanpa pembaruan. Tekan **Batal** atau `/batal` untuk meninggalkan draf; membuka menu/perintah lain juga mengakhirinya.

## Mencatat beberapa pengeluaran sekaligus

Kirim contoh ini sebagai **satu pesan dengan tiga baris**:

```text
50000 bensin
20000 makan
15000 minum
```

Bot menyimpan tiga catatan dengan total **Rp85.000**, lalu menampilkan rincian, total tanggal tersebut, dan total bulan. Maksimal 100 pengeluaran per pesan. Untuk membuat baris baru di Telegram Desktop, gunakan Shift+Enter jika Enter langsung mengirim pesan.

Tambahkan kategori setelah tanda `|` bila diperlukan:

```text
50rb bensin | Transportasi
20rb makan | Makanan
15rb minum | Makanan
```

Tanpa kategori tertulis, bot memakai **aturan kategori otomatis** jika aktif dan cocok; jika tidak ada kecocokan, kategori menjadi **Lainnya**. Kategori yang ditulis setelah `|` selalu diutamakan. Perbedaan huruf besar/kecil kategori dinormalisasi. Jika ada satu baris yang tidak valid, **seluruh isi pesan belum disimpan**. Bot menyebutkan nomor baris yang perlu diperbaiki; kirim ulang seluruh pesan setelah memperbaikinya.

Untuk memilih sumber pembayaran, tambahkan nama dompet sebagai kolom ketiga. Buat dompetnya melalui `/dompet` terlebih dahulu:

```text
50rb bensin | Transportasi | Tunai
20rb makan | Makanan | Bank
15rb minum | | DANA
```

Kolom kategori kosong pada baris terakhir tetap memakai kategori otomatis. Tanpa kolom dompet, pengeluaran memakai dompet bawaan. Jika ada nama dompet yang tidak ditemukan, **seluruh pesan belum dicatat**; buat/perbaiki dompet lalu kirim ulang. Rincian pengeluaran dan Excel mencantumkan dompet pembayaran.

| Penulisan nominal | Nilai |
| --- | --- |
| `15000`, `15.000`, `Rp15.000` | Rp15.000 |
| `15rb`, `15k` | Rp15.000 |
| `15,5rb` | Rp15.500 |
| `1,5jt` | Rp1.500.000 |

Titik adalah pemisah ribuan; koma untuk pecahan ribu/juta. Nilai harus rupiah bulat dan positif, maksimal Rp1.000.000.000.000 per catatan. Keterangan maksimal 160 karakter, kategori 32 karakter.

Untuk tanggal sebelumnya, tulis tanggal di awal baris:

```text
/catat 2026-09-19 15000 makan siang | Makanan
2026-09-20 50000 bensin | Transportasi
```

Tanggal memakai format **YYYY-MM-DD**. Jika mencatat beberapa tanggal, tulis tanggal pada setiap baris yang perlu dibedakan. Baris tanpa tanggal memakai tanggal pengiriman pesan. Tanggal masa depan ditolak.

## Kategori otomatis

Buka **Catat → Atur kategori otomatis** atau `/kategoriotomatis`. Saat fitur ini pertama tersedia untuk akunmu, aturan awalnya aktif:

| Kata dalam keterangan | Kategori |
| --- | --- |
| bensin, ojek, parkir | Transportasi |
| makan, minum | Makanan |

Contoh: `50000 bensin motor` masuk Transportasi. `50000 bensin motor | Kantor` tetap masuk Kantor karena kategori tertulis diutamakan. Aturan juga berlaku untuk input beberapa baris dan saat membuat template favorit/tagihan.

Tekan **Tambah aturan**, lalu kirim `kopi | Makanan`. Untuk mengubah atau menghapus, pilih aturan dari daftar. Kata/frasa maksimal 40 karakter; kategori maksimal 32 karakter; tersedia hingga 50 aturan per akun. Gunakan **Nonaktifkan/Aktifkan** untuk mengubah status tanpa menghapus aturan.

Pencocokan memakai kata atau frasa utuh tanpa membedakan huruf besar/kecil. `makan` cocok dengan `makan siang`, tetapi tidak dengan `makanan`. Jika beberapa aturan cocok, frasa terpanjang didahulukan; jika sama panjang, aturan yang dibuat lebih dahulu dipakai. Mengubah aturan **tidak mengubah kategori catatan lama** atau template yang sudah disimpan. Gunakan Edit atau Pilih beberapa untuk memperbaiki catatan lama.

## Pengeluaran favorit

1. Buka **Catat → Favorit → Tambah favorit**, atau `/favorit`.
2. Kirim nama singkat, misalnya `Bensin motor`.
3. Kirim satu pengeluaran tanpa tanggal, misalnya `50000 bensin | Transportasi`.
4. Periksa lalu tekan **Simpan**. Tahap ini hanya menyimpan template.
5. Saat ingin mencatat, pilih favorit lalu **Catat dari favorit**. Periksa nominal dan tanggal, lalu tekan **Ya, catat pengeluaran**.

Tanggal awal adalah hari ini dalam zona pilihanmu. Tombol **Ubah nominal**, **Ubah tanggal**, dan **Ubah dompet** hanya mengubah pencatatan tersebut; template tetap sama. Tanggal masa depan ditolak. Membuka favorit atau menekan Batal belum membuat pengeluaran. Untuk memakai favorit lagi, buka kembali dari daftar; tombol konfirmasi yang sama tidak menggandakan catatan.

Saat membuat/edit template, tulis dompet pada kolom ketiga jika ingin sumber tetap, misalnya `50000 bensin | Transportasi | Tunai`. Jika kolom itu tidak diisi, template mengikuti dompet bawaan **saat digunakan**. Dompet ditampilkan sebelum pengeluaran dikonfirmasi.

Tersedia **Edit template** dan **Hapus template**. Menghapus template mempertahankan seluruh pengeluaran yang sudah dicatat. Maksimal 30 favorit per akun. Draf kedaluwarsa setelah 30 menit tanpa pembaruan; tombol tinjauan lama perlu dibuka ulang jika nilainya sudah berubah.

## Melihat laporan dan menghapus pengeluaran

**Hari ini** menampilkan total, jumlah catatan, dan rincian bernomor. Gunakan tombol sebelumnya/berikutnya untuk daftar atau tanggal lain. **Bulan ini** memakai bulan kalender, misalnya 1–30 September. Rekap di chat menampilkan hingga enam kategori terbesar; semua kategori tersedia dalam Excel.

Untuk membetulkan pengeluaran:

1. Buka **Riwayat → Hapus**, atau kirim `/hapus`.
2. Pilih pengeluaran dari tombol daftar. Gunakan **Berikutnya** jika perlu.
3. Periksa keterangan, nominal, kategori, dan tanggal; tekan **Ya, hapus**.
4. Jika keliru, tekan **Urungkan**. Pengeluaran yang dihapus juga tersedia di menu **Riwayat → Pulihkan terhapus**.

Pengeluaran yang dihapus tidak dihitung dalam laporan dan Excel, tetapi dapat dipulihkan. Untuk koreksi data gunakan menu **Edit**. Tidak perlu mengetik nomor atau `/hapus 12 ya`. Mengedit atau menghapus pesan melalui Telegram sendiri tidak mengubah catatan dalam database.

## Edit pengeluaran lewat tombol

1. Buka **Riwayat → Edit** atau kirim `/edit`, lalu pilih catatan. Untuk menemukan catatan tertentu, gunakan **Cari & filter**.
2. Pilih **Nominal**, **Keterangan**, **Kategori**, **Tanggal**, atau **Dompet pembayaran**.
3. Kirim nilai baru. Nominal dapat ditulis `25000` atau `25rb`; tanggal memakai `YYYY-MM-DD` dan tidak boleh di masa depan.
4. Periksa draf yang menampilkan nilai sebelum dan sesudah. Kamu dapat mengubah beberapa kolom dalam draf yang sama.
5. Tekan **Simpan perubahan**. ID catatan tetap sama; saldo dompet, total harian/bulanan, anggaran, pencarian, dan ekspor Excel berikutnya langsung memakai data terbaru.

Tombol **Batal** atau `/batal` membuang draf. Membuka menu/perintah lain juga mengakhiri input yang sedang dibuka. Selama bot meminta nilai edit, pesan berikutnya dipakai untuk draf tersebut. Tekan **Catat** atau kirim `/catat` untuk kembali mencatat pengeluaran.

Draf tersimpan melewati restart, tetapi kedaluwarsa setelah 30 menit tanpa pembaruan. Input yang datang setelah kedaluwarsa tidak dicatat sebagai pengeluaran baru. Catatan yang telah berubah atau dihapus sejak draf dibuka perlu dimuat ulang sebelum diedit.

## Riwayat perubahan dan Urungkan edit

Buka **Riwayat → Riwayat edit**, atau `/riwayatedit`. Pilih perubahan untuk melihat **nilai sebelum/sesudah** dan waktunya dalam zona pilihanmu. Dari draf Edit tersedia tombol **Riwayat edit catatan ini**. Membukanya meninggalkan draf yang belum disimpan.

Setelah menyimpan edit, tekan **Urungkan edit → Ya, urungkan** untuk mengembalikan nilai sebelumnya. Tindakan ini juga dicatat dalam riwayat. Nominal, keterangan, kategori, tanggal, dan dompet dipulihkan bersama; saldo, laporan, Excel berikutnya, serta pemakaian anggaran dihitung dari data hasil pemulihan. Riwayat edit sebelum versi 2.4 belum menyimpan dompet; mengurungkan edit lama mempertahankan dompet catatan saat ini.

Urungkan tersedia untuk **satu edit terakhir pada catatan yang belum diubah, dihapus, atau dipulihkan lagi**. Edit lama tetap bisa dibaca, tetapi tidak menimpa perubahan yang lebih baru. Tidak tersedia rangkaian undo/redo. Setelah urungkan, gunakan Edit untuk koreksi berikutnya. Setiap akun hanya dapat membaca dan mengurungkan perubahannya sendiri.

## Pilih beberapa catatan sekaligus

1. Buka **Riwayat → Pilih beberapa**, atau `/pilih`. Untuk hasil tertentu, atur **Cari & filter**, lalu **Pilih beberapa hasil**.
2. Tekan catatan sampai bertanda centang. Pilihan tetap tersimpan saat pindah halaman. Tersedia **Pilih halaman ini** dan **Lepas semua**.
3. Pilih **Hapus terpilih**, atau **Ganti kategori** lalu kirim nama kategori baru.
4. Periksa daftar, jumlah, total, dan kategori baru jika ada. Belum ada data yang berubah pada tahap ini.
5. Tekan **Ya, lanjutkan** untuk menerapkan tindakan pada seluruh pilihan. **Kembali ke pilihan** atau **Batal** tidak menyimpan perubahan.

Maksimal **50 catatan per tindakan**. Jika satu catatan berubah atau dihapus setelah dipilih, seluruh tindakan ditolak; batalkan lalu pilih ulang. Draf pilihan kedaluwarsa setelah 30 menit tanpa pembaruan dan tersimpan melewati restart.

Hapus bersama hanya mengeluarkan catatan dari rekap; pulihkan kembali satu per satu melalui **Pulihkan terhapus**. Ganti kategori dicatat dalam riwayat edit untuk setiap catatan yang benar-benar berubah dan bisa diurungkan per catatan. Total nominal tidak berubah ketika hanya kategori diganti.

## Anggaran bulanan

Tekan **Anggaran → Atur nominal**, kemudian kirim `1500000` atau `1,5jt`. Bisa juga langsung `/anggaran 1,5jt`. Untuk bulan tertentu, gunakan `/anggaran 2026-09 1500000`.

Dengan anggaran Rp1.500.000 dan pemakaian Rp1.200.000, tampilan menunjukkan:

```text
Anggaran: Rp1.500.000
Terpakai: Rp1.200.000 (80,0%)
Sisa anggaran: Rp300.000
```

Anggaran muncul pada menu utama, laporan bulanan, dan menu Anggaran. Jika terlampaui, bot menampilkan jumlah kelebihannya. Anggaran disimpan **per akun dan per bulan**. Gunakan tombol bulan sebelumnya/berikutnya; **Salin anggaran bulan lalu** tersedia ketika bulan tujuan belum memiliki anggaran. Anggaran otomatis tersedia sebagai pilihan; tidak aktif sampai dikonfirmasi.

Pemberitahuan ditambahkan pada balasan ketika pencatatan, edit, urungkan, pemulihan, atau pengaturan anggaran membuat pemakaian mencapai 80% atau 100%. Setiap batas diberitahukan sekali per bulan untuk nominal anggaran tersebut. Jika langsung melewati 100%, hanya pemberitahuan 100% yang muncul. Menghapus transaksi menurunkan pemakaian, tetapi tidak mengulang pemberitahuan yang sudah diberikan. Mengubah nominal anggaran memulai evaluasi batas yang baru.

## Anggaran otomatis setiap bulan

1. Atur nominal bulan yang sedang dibuka, misalnya **Rp1.500.000**.
2. Tekan **Gunakan anggaran ini setiap bulan**.
3. Bot menampilkan nominal dan bulan mulai. Tekan **Ya, gunakan**.

Nominal menjadi bawaan **mulai bulan kalender berikutnya**. Anggaran dibuat otomatis saat bulan berganti selama bot hidup; setelah offline, aturan yang sama diterapkan ketika bot kembali berjalan atau bulan tersebut dibuka. Contoh: aktifkan Rp1.500.000 pada September; Oktober dan bulan-bulan berikutnya memakai nominal itu.

Untuk pengecualian, buka bulan tertentu lalu **Atur nominal**, misalnya `/anggaran 2026-11 2jt`. November memakai Rp2.000.000, sementara bulan lain tetap mengikuti aturan. **Nominal khusus yang sudah tersimpan selalu diutamakan**, termasuk saat aturan otomatis diubah. Gunakan **Gunakan nominal otomatis bulan ini** untuk melepas pengecualian jika tersedia.

Untuk mengganti nominal rutin, atur nominal yang diinginkan lalu pilih **Gunakan anggaran ini setiap bulan** kembali. Perubahan berlaku mulai bulan berikutnya; anggaran bulan lama tetap dapat dibaca sesuai aturan yang berlaku saat itu. **Nonaktifkan mulai bulan depan** menghentikan anggaran otomatis berikutnya dan mempertahankan anggaran bulan berjalan serta semua nominal khusus.

Pemberitahuan 80%/100% tetap terpisah per akun dan bulan. Riwayat pemakaian bulan lama tidak dipindahkan ke bulan baru.

## Anggaran per kategori

1. Buka **Anggaran → Anggaran per kategori**, atau `/anggarankategori`.
2. Pilih bulan, lalu **Tambah kategori**.
3. Kirim nama kategori, misalnya `Makanan`, kemudian batasnya, misalnya `500rb`.
4. Pilih kategori dari daftar untuk melihat pemakaian, persentase, sisa/kelebihan, mengubah batas, atau menghapus batas dengan konfirmasi.

Pemakaian mengikuti kategori yang tersimpan pada catatan. Pemberitahuan muncul saat mencapai **80% atau 100%**; jika langsung melewati 100%, hanya batas 100% yang diberitahukan. Mencatat, edit, Urungkan edit, memulihkan, dan mengganti kategori beberapa catatan ikut memperbarui perhitungan. Setiap batas diberitahukan sekali untuk nominal kategori pada bulan tersebut. Mengubah nominal mengevaluasi ulang batas; menghapus pengeluaran tidak mengulang pemberitahuan lama.

Anggaran kategori dan anggaran total bulanan diperiksa **secara terpisah**. Jumlah seluruh batas kategori ditampilkan, tetapi tidak otomatis mengubah anggaran total. Kategori yang belum diberi batas tetap dapat dicatat.

Maksimal 50 batas kategori per akun per bulan. Tombol **Salin batas bulan lalu** mengisi kategori yang belum ada pada bulan tujuan dan mempertahankan nominal yang sudah diatur. Anggaran kategori belum mengikuti aturan anggaran total otomatis; gunakan tombol salin saat menyiapkan bulan berikutnya. Perintah `/anggarankategori 2026-10` membuka bulan tertentu.

## Pencarian dan filter

Buka **Riwayat → Cari & filter**, atau kirim `/cari bensin`. Pencarian kata mencocokkan bagian keterangan tanpa membedakan huruf besar/kecil.

- **Kata pencarian:** misalnya `bensin`. Kirim `-` untuk mengosongkan kata.
- **Kategori:** pilih dari kategori catatan milikmu, atau **Semua kategori**.
- **Rentang tanggal:** kirim `2026-09-01 2026-09-21`, atau satu bulan seperti `2026-09`. Tanggal awal dan akhir ikut dihitung.
- **Bulan ini**, **Semua tanggal**, dan **Reset pencarian** mempercepat pengaturan filter.

Ketiga filter digabung. Hasil menampilkan jumlah catatan dan **total seluruh hasil**, termasuk halaman berikutnya. Catatan yang dihapus dan milik akun lain tidak ikut muncul. Tombol setiap hasil membuka catatan untuk diedit.

`/cari` membuka filter terakhir, yang tersimpan melewati restart. `/cari kata` memulai pencarian kata baru pada semua kategori dan tanggal. Mengubah kata lewat tombol mempertahankan filter lain yang sedang dipakai.

## Pengingat harian opsional

1. Buka **Pengaturan → Pengingat**. Status awal adalah **Nonaktif** dengan contoh jam 21:00.
2. Tekan **Ubah jam**, kirim `21:00` atau jam pilihanmu dalam format 24 jam. Menyimpan jam mengaktifkan pengingat.
3. Gunakan tombol **Nonaktifkan/Aktifkan** kapan pun. Jam mengikuti zona waktu pilihanmu melalui `/zona`.

Perintah cepat: `/pengingat 21:00` untuk mengatur dan mengaktifkan, `/pengingat off` untuk mematikan. Menu menampilkan jadwal berikutnya. Jika jam yang dipilih sudah lewat hari ini, jadwal baru dimulai besok. Pengingat tetap dikirim setiap hari meskipun sudah ada catatan, agar kamu dapat memeriksa apakah ada yang terlewat.

**Program bot harus tetap hidup dan tersambung internet**, termasuk saat tidak ada chat masuk. Scheduler menjadi bagian program; tidak perlu layanan penjadwal tambahan. Pengiriman berlangsung sekitar jam pilihan, biasanya dalam satu siklus polling hingga sekitar 30 detik, dan bisa lebih lambat saat antrean atau koneksi sibuk.

Pengaturan dan keberhasilan pengiriman disimpan di database. Restart normal tidak mengirim ulang pengingat yang berhasil dikirim pada hari yang sama. Jika bot offline beberapa hari, pengingat hari-hari lama dilewati; pengingat hari ini dapat menyusul ketika bot aktif setelah jam jadwal. Gangguan koneksi tepat setelah Telegram menerima pesan masih dapat menyebabkan kiriman ulang. Jika bot diblokir, pengingat dinonaktifkan; aktifkan lagi setelah membuka akses bot.

## Rekap otomatis mingguan dan bulanan

Buka **Laporan → Rekap otomatis**, **Pengaturan → Rekap otomatis**, atau `/rekapotomatis`. Rekap mingguan dan bulanan **awalnya nonaktif**, dengan pengaturan terpisah:

| Rekap | Jadwal bawaan | Isi periode |
| --- | --- | --- |
| Mingguan | Senin, pukul 07:00 | Senin–Minggu sebelumnya |
| Bulanan | Tanggal 1, pukul 07:00 | Bulan kalender sebelumnya |

Pilih **Atur mingguan/bulanan**, tekan **Aktifkan**, lalu **Ubah jam** jika diperlukan. Jam memakai format `HH:MM` dan mengikuti WIB/WITA/WIT pilihanmu. Mengubah jam saja tidak mengaktifkan jadwal yang masih nonaktif. Hari Senin/tanggal 1 tetap; yang dapat diubah adalah jamnya.

Rekap berisi total pengeluaran, jumlah catatan, perbandingan dengan periode lengkap sebelumnya, dan tiga kategori terbesar. Jika total pembanding nol, persentase tidak dihitung. Tekan **Sertakan Excel** jika ingin menerima berkas Rekap dan Transaksi untuk periode yang sama, termasuk kolom dompet. Pilihan Excel awalnya mati. **Lihat contoh rekap terakhir** menghasilkan pratinjau berdasarkan data saat diminta tanpa mengaktifkan jadwal. Rekap terjadwal tetap berupa laporan pengeluaran; Excel arus kas tersedia secara manual dari `/saldo`.

Rekap pertama dikirim pada jadwal setelah diaktifkan. Bot harus tetap berjalan; setelah offline, **hanya periode terjadwal terbaru yang menyusul**, bukan semua minggu/bulan yang terlewat. Pengiriman yang tertunda dapat menyusul meskipun menu sudah menunjukkan jadwal reguler berikutnya.

Rekap terjadwal merupakan salinan data ketika pengiriman disiapkan. Jika pesan berhasil tetapi Excel gagal, bot mencoba kembali lampiran yang sama; perubahan catatan berikutnya tersedia melalui laporan manual. Mematikan Excel membatalkan lampiran yang masih tertunda. Status pengiriman disimpan sehingga restart normal tidak mengirim ulang rekap yang telah selesai. Gangguan tepat setelah Telegram menerima kiriman dan sebelum status tersimpan masih dapat menyebabkan kiriman ulang. Jika Telegram menolak akses chat, jadwal dinonaktifkan; periksa akses lalu aktifkan lagi.

## Tagihan rutin

1. Buka **Catat → Tagihan rutin → Tambah tagihan**, atau `/tagihan`.
2. Kirim nama, misalnya `Internet rumah`, lalu satu pengeluaran seperti `300rb internet | Tagihan`.
3. Kirim tanggal bulanan berupa angka `1`–`31`, kemudian jam pengingat, misalnya `09:00`.
4. Periksa nama, nominal, kategori, jadwal, zona, dan periode mulai, lalu **Simpan**.
5. Ketika pengingat diterima, tekan **Sudah dibayar → Catat**, periksa nominal dan tanggal pembayaran, lalu **Ya, catat pengeluaran**.

Pengingat aktif setelah tagihan disimpan. Jika jadwal bulan ini sudah lewat saat dibuat, periode mulai adalah bulan berikutnya. Tanggal 29–31 mengikuti hari terakhir pada bulan yang lebih pendek; contoh tanggal 31 menjadi 28/29 Februari. Kamu dapat mengubah tagihan atau **Nonaktifkan/Aktifkan** dari rinciannya. Maksimal 30 tagihan per akun, termasuk yang nonaktif; edit tagihan yang tidak dipakai jika ingin mengganti kebutuhannya.

Pengingat dikirim sekali per tagihan per bulan setelah jadwal tiba. **Pengingat tidak membuat pengeluaran otomatis.** Pembayaran dicatat setelah kamu meninjau dan mengonfirmasi. Tanggal pengeluaran awal adalah tanggal pembayaran hari ini; kamu dapat mengganti nominal, tanggal, atau dompet sebelum menyimpan tanpa mengubah template tagihan. Laporan menghitung tanggal pengeluaran tersebut, sedangkan status pembayaran tetap terkait periode tagihan yang dipilih.

Template dapat memakai dompet tetap dengan kolom ketiga, misalnya `300rb internet | Tagihan | Bank`. Jika tidak ditulis, pembayaran mengikuti dompet bawaan saat akan dicatat. Periksa sumber pembayaran pada tinjauan konfirmasi.

Setiap periode tagihan hanya memiliki satu catatan pembayaran. Menekan tombol berulang tidak mencatat ulang. Jika catatan pembayarannya dihapus, rincian tagihan menyediakan **Pulihkan catatan pembayaran**; jika perlu koreksi, gunakan **Edit catatan pembayaran**. Mengedit template mempertahankan catatan pembayaran lama. Menonaktifkan tagihan menghentikan pengingat; rincian dan pencatatan manual tetap tersedia.

Setelah offline, pengingat bulan berjalan yang belum terkirim dapat menyusul; bulan lama tidak dikirim bertumpuk. Gunakan tombol **Periode sebelumnya/berikutnya** untuk memeriksa dan mencatat pembayaran periode lain. Restart normal tidak mengulang pengingat yang berhasil dikirim; gangguan tepat setelah pesan diterima Telegram masih dapat menyebabkan pengingat terkirim ulang, tetapi konfirmasi pembayaran tetap dilindungi dari pencatatan ganda.

## Perbandingan antarbulan

Buka **Laporan → Perbandingan bulan** atau kirim `/banding`. Untuk bulan tertentu, gunakan `/banding 2026-09`.

Bot menampilkan total kedua periode, selisih rupiah, persentase kenaikan/penurunan, serta tiga kategori terbesar pada masing-masing periode. Jika total periode sebelumnya nol, persentase tidak dihitung.

Untuk **bulan berjalan**, bawaan perbandingan memakai tanggal setara: misalnya 1–21 September melawan 1–21 Agustus. Jika bulan pembanding lebih pendek, rentangnya berhenti pada hari terakhir bulan tersebut. Tombol **Bandingkan bulan penuh** tersedia untuk melihat pembanding satu bulan penuh. Rentang tanggal selalu ditulis pada laporan. Bulan yang sudah lewat dibandingkan sebagai bulan kalender penuh.

Perubahan catatan, hapus, dan pemulihan ikut memperbarui hasil perbandingan berikutnya. Data setiap akun tetap terpisah.

## Ekspor Excel

Buka **Laporan → Ekspor Excel → pilih bulan → Unduh Excel**, atau kirim `/excel` untuk bulan berjalan. Dari laporan harian, tombol **Excel tanggal ini** mengunduh satu hari saja.

File berisi dua lembar:

- **Rekap:** total pengeluaran, jumlah transaksi, total setiap tanggal, dan total per kategori.
- **Transaksi:** ID catatan, tanggal, keterangan, kategori, nominal, dan dompet; tersedia filter dan judul kolom yang tetap terlihat saat menggulir.

Nominal tersimpan sebagai angka, tanggal sebagai tanggal Excel. Total menggunakan rumus dan ikut dihitung ulang jika nominal pada baris yang sudah ada diubah. Rekap adalah salinan data saat diunduh. Perubahan file Excel tidak dikirim kembali ke bot; unduh ulang untuk mendapatkan catatan terbaru. Jika menambah baris atau kategori baru langsung di Excel, rentang rumus dan daftar rekap perlu disesuaikan.

Format angka mengikuti pengaturan pemisah ribuan aplikasi Excelmu. Setiap pengguna hanya mengekspor datanya sendiri. Periode kosong tetap bisa diunduh dengan total nol.

### Excel arus kas

Buka **`/saldo` → pilih bulan → Excel arus kas**. Berkas terpisah ini berisi:

- **Arus kas:** saldo awal/akhir periode, pemasukan dan pengeluaran gabungan; rincian setiap dompet dengan transfer masuk/keluar serta status saldo awal.
- **Buku kas:** tanggal, jenis transaksi, dompet asal/penerima, keterangan, kategori, dan nominal. Transfer muncul satu kali dengan kedua dompetnya. ID berawalan `E` menandai pengeluaran, sedangkan `K` menandai pemasukan/transfer.

Rumus saldo per dompet mengambil nominal dari Buku kas, sehingga mengubah nominal pada baris yang ada menghitung ulang hasil. Transfer tetap tidak mengubah saldo gabungan. Saldo awal periode diisi dari seluruh riwayat sebelum bulan laporan; status **Belum diatur** menunjukkan saldo masih sementara. File tetap berupa laporan, tidak dapat diimpor sebagai cadangan bot. Menambah baris/dompet atau mengganti nama dompet di Excel memerlukan penyesuaian rentang dan nama yang dipakai rumus.

## Membersihkan chat dengan /clear

Kirim `/clear` atau buka **Pengaturan → Bersihkan chat**, lalu konfirmasi. Bot membersihkan pesan yang dikenali dalam chat tersebut dan berumur kurang dari 48 jam. Catatan pengeluaran, total, pengaturan zona waktu, serta daftar pemulihan **tetap tersimpan**.

Telegram membatasi umur pesan yang dapat dihapus bot. Pesan lama atau balasan dari versi bot sebelumnya mungkin tidak dikenali. Untuk sisanya, gunakan **Hapus Riwayat/Clear History** pada Telegram. Bot tidak dapat membaca ulang seluruh riwayat chat. [Batas penghapusan resmi Telegram](https://core.telegram.org/bots/api#deletemessage).

## Daftar perintah

| Perintah | Hasil |
| --- | --- |
| `/start` atau `/menu` | Menu utama dan ringkasan |
| `/riwayat` | Catatan, koreksi, dan pilihan beberapa |
| `/laporan` | Laporan harian, bulanan, Excel, perbandingan, rekap otomatis |
| `/pengaturan` | Pengingat, zona, bantuan, dan pengelolaan bot |
| `/riwayatedit` | Riwayat nilai sebelum/sesudah dan Urungkan edit |
| `/pilih` | Pilih beberapa catatan untuk hapus/ganti kategori |
| `/cadangan` | Cadangan lengkap dan petunjuk pemulihan khusus pemilik |
| `/catat` | Contoh cara mencatat; bisa langsung diikuti isi pengeluaran |
| `/pemasukan` | Mulai pemasukan; boleh diikuti nominal dan keterangan, lalu konfirmasi |
| `/dompet` | Kelola sumber pembayaran, saldo awal, dompet bawaan, dan riwayat |
| `/saldo` atau `/saldo 2026-09` | Saldo serta arus kas bulan pilihan, dengan unduhan Excel |
| `/transfer` | Pilih asal/tujuan dan catat transfer antardompet dengan konfirmasi |
| `/kategoriotomatis` | Kelola aturan kata/frasa dan aktifkan/nonaktifkan kategori otomatis |
| `/favorit` | Buat dan gunakan template pengeluaran favorit |
| `/rekapotomatis` | Aktifkan rekap mingguan/bulanan, atur jam dan lampiran Excel |
| `/anggarankategori` | Lihat dan atur batas kategori pada bulan berjalan |
| `/anggarankategori 2026-10` | Batas kategori pada bulan tertentu |
| `/tagihan` | Kelola pengingat tagihan dan catat pembayarannya |
| `/hariini` | Rincian dan total hari ini |
| `/harian 2026-09-19` | Laporan satu tanggal |
| `/bulanini` | Rekap bulan berjalan |
| `/bulanan 2026-09` | Rekap bulan tertentu |
| `/excel` | File Excel bulan berjalan |
| `/excel 2026-09` | File Excel bulan tertentu |
| `/excel 2026-09-19` | File Excel satu tanggal |
| `/hapus` | Daftar pilihan pengeluaran untuk dihapus |
| `/pulihkan` | Daftar pilihan pengeluaran untuk dipulihkan |
| `/edit` | Pilih catatan untuk diedit melalui tombol |
| `/anggaran` | Lihat dan atur anggaran bulan berjalan |
| `/anggaran 1,5jt` | Simpan anggaran bulan berjalan |
| `/anggaran 2026-09 1500000` | Simpan anggaran bulan tertentu |
| `/cari bensin` | Cari keterangan, lalu atur kategori/tanggal lewat tombol |
| `/pengingat` | Buka pengaturan pengingat harian |
| `/pengingat 21:00` | Aktifkan pengingat pada jam pilihan |
| `/pengingat off` | Nonaktifkan pengingat |
| `/banding` | Perbandingan bulan berjalan dengan sebelumnya |
| `/banding 2026-09` | Perbandingan bulan tertentu dengan sebelumnya |
| `/batal` | Batalkan input atau draf edit |
| `/clear` | Konfirmasi pembersihan pesan chat |
| `/zona` | Pilih WIB, WITA, atau WIT |
| `/id` | ID Telegram pengirim sendiri |
| `/bantuan` | Panduan dalam chat |

Ganti tanggal/bulan contoh dengan periode yang diperlukan. Laporan manual tersedia kapan saja; kiriman rekap terjadwal perlu diaktifkan melalui `/rekapotomatis`. Pengingat harian tetap berfungsi sebagai ajakan mencatat.

## Memasang pertama kali di Windows

Lewati bagian ini jika kamu sudah menyalin konfigurasi dan data dari versi lama.

1. Ekstrak ZIP ke folder tetap. Jangan menjalankan program dari dalam ZIP.
2. Pasang **Python 3.10 atau lebih baru** dari [python.org](https://www.python.org/downloads/windows/). Aktifkan pilihan PATH jika tersedia. Peluncur akan mencari `py`, lalu `python`.
3. Buat bot melalui [@BotFather](https://t.me/BotFather): kirim `/newbot`, tentukan nama dan username berakhiran `bot`, lalu simpan token. [Panduan token Telegram](https://core.telegram.org/bots/tutorial#obtain-your-bot-token).
4. Buka `config.json` dengan Notepad. Ganti `ISI_TOKEN_DARI_BOTFATHER` dengan tokenmu. Pertahankan tanda petik. Biarkan `allowed_user_ids` berupa `[]` sementara.
5. Jalankan `JALANKAN_WINDOWS.bat`. Buka chat botmu dan kirim `/id`.
6. Hentikan bot dengan Ctrl+C. Masukkan ID angka milikmu dalam `allowed_user_ids`, misalnya `[123456789]`.
7. Simpan konfigurasi, jalankan ulang, lalu kirim `/start`.

Contoh konfigurasi; identitas di bawah hanya contoh:

```json
{
  "bot_token": "TOKEN_MILIKMU_DARI_BOTFATHER",
  "allowed_user_ids": [123456789],
  "owner_user_id": 123456789,
  "timezone": "WIB",
  "database": "data/pengeluaran.db"
}
```

Token cukup dimasukkan pada perangkatmu atau pengaturan hosting. Tidak perlu mengirimkannya dalam chat. Bot membaca konfigurasi saat mulai; mulai ulang setelah mengubahnya.

Hanya ID yang terdaftar dapat mengakses pengeluaran. `/id` tetap bisa dipakai untuk mengetahui ID sendiri. Gunakan ID pengguna berupa angka, bukan username atau ID bot. Untuk beberapa pengguna, isi `[123456789, 987654321]`; data tiap akun terpisah. Bot digunakan dalam chat pribadi.

Jika hanya satu ID diizinkan, ID tersebut otomatis menjadi pemilik bot. Jika beberapa ID diizinkan, isi `owner_user_id` dengan satu ID dari daftar itu (atau `OWNER_USER_ID` pada hosting). Pemilik dapat mengunduh cadangan **seluruh pengguna**; pengguna lain hanya mengakses catatannya sendiri. Jika pemilik belum ditetapkan pada bot dengan beberapa pengguna, cadangan harian tetap dibuat, tetapi tombol unduhan tidak tersedia.

## Hosting 24 jam: Railway

Bot di laptop hanya aktif selama program berjalan, internet tersedia, dan laptop tidak sleep. Agar tetap tersedia saat laptop mati, jalankan pada hosting dengan proses yang terus hidup dan penyimpanan database permanen.

Pilihan yang disiapkan dalam paket ini adalah **Railway Hobby**, dengan minimum **US$5 per bulan**, mencakup kredit pemakaian US$5. Jika pemakaian melewati kredit itu, selisihnya ditagihkan. Biaya rupiah mengikuti kurs dan metode pembayaran. Railway juga menyediakan paket gratis dengan batas pemakaian; periksa kecukupannya sebelum mengandalkan operasi terus menerus. Harga diperiksa 22 September 2026. [Harga Railway](https://railway.com/pricing).

File `Dockerfile` dan `railway.json` sudah disediakan. Hosting dan pembayaran belum diaktifkan dalam paket ini.

### Menyiapkan layanan

1. Buat repositori GitHub privat. Unggah **`bot.py`, `core.py`, `app.py`, `features.py`, `v22.py`, `storage_v22.py`, `v23.py`, `storage_v23.py`, `schedule_v23.py`, `v24.py`, `storage_v24.py`, `backups.py`, `cadangan.py`, `ui.py`, `excel_export.py`, `excel_cash.py`, folder `assets`, `Dockerfile`, dan `railway.json`** pada tingkat teratas repositori. Folder `assets` harus berisi `rekap-template.xlsx` dan `arus-kas-template.xlsx`. Sertakan `.gitignore` dan `.dockerignore`. Jangan unggah `config.json` milikmu, folder `data`, atau cadangan database. Jika mengunggah melalui browser, pilih file secara manual; `.gitignore` tidak menyaring unggahan browser.
2. Masuk ke Railway, buat proyek dari repositori GitHub tersebut, lalu pilih paket sesuai kebutuhan. Railway membaca Dockerfile. Jika proses awal berhenti karena token belum ada, lanjutkan pengaturan di bawah.
3. Buat **Volume**, hubungkan ke layanan bot, lalu pasang pada **`/data`**. Volume menyimpan database melewati restart/deploy. Jangan mengisi variabel sistem `RAILWAY_VOLUME_MOUNT_PATH` sendiri; Railway membuatnya saat Volume terpasang. [Panduan Volume](https://docs.railway.com/volumes).
4. Jika sudah memiliki catatan di laptop, **pindahkan database dahulu** sesuai bagian berikut, sebelum mengaktifkan token di hosting.
5. Buka **Variables** layanan, lalu masukkan pengaturan pada tabel di bawah.
6. Gunakan **satu replica**. Matikan **Serverless/App Sleeping** jika aktif. Bot perlu proses yang terus berjalan; konfigurasi paket memakai kebijakan restart **ALWAYS**. Tidak perlu domain publik, port HTTP, atau HTTP healthcheck karena bot memakai long polling. [Dockerfile](https://docs.railway.com/builds/dockerfiles), [konfigurasi Railway](https://docs.railway.com/config-as-code/reference), dan [Serverless](https://docs.railway.com/deployments/serverless).
7. Hentikan bot di laptop, lalu deploy/redeploy layanan Railway. Periksa log sampai muncul `Bot @... v2.4 aktif`.
8. Coba `/start`, periksa laporan, dan unduh `/excel`. Setelah berhasil, laptop boleh dimatikan. Aktifkan cadangan Volume dan pantau pemakaian layanan.

| Variable | Isi |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token bot yang sama dari BotFather |
| `ALLOWED_USER_IDS` | ID angka milikmu, misalnya `123456789`; beberapa ID dipisahkan koma, tanpa kurung siku |
| `OWNER_USER_ID` | ID pemilik untuk unduhan cadangan; wajib diisi jika ada beberapa pengguna dan ingin menu unduhan |
| `BOT_TIMEZONE` | `WIB`, `WITA`, atau `WIT` |
| `DB_PATH` | `/data/pengeluaran.db` |

Jika belum tahu ID, biarkan `ALLOWED_USER_IDS` kosong sementara, jalankan bot, kirim `/id`, lalu isi variabel dan redeploy. Bot menolak akses data sampai ID didaftarkan. Tanpa Volume yang benar, bot menghentikan startup di Railway agar data tidak tersimpan pada disk sementara.

Hosting dapat mengalami restart atau gangguan singkat; operasi 24 jam tidak berarti jaminan tanpa jeda. Jangan menjalankan token yang sama di laptop dan hosting secara bersamaan.

### Memindahkan catatan laptop ke Railway

Pindahkan file database, karena ekspor Excel tidak berfungsi sebagai impor kembali ke bot. Lakukan ini sebelum mulai mencatat di hosting.

1. Hentikan bot laptop dengan Ctrl+C, lalu cadangkan folder `data`. Pastikan bot hosting juga tidak sedang menjalankan `bot.py`; pada pemasangan baru, lakukan pemindahan sebelum mengisi token.
2. Pasang [Railway CLI](https://docs.railway.com/cli). Jika sudah memiliki Node.js, tersedia perintah `npm i -g @railway/cli`.
3. Buka terminal di folder bot yang berisi database. Jalankan `railway login`, kemudian `railway link`. Pilih proyek dan environment yang tepat, lalu `railway service` untuk memilih layanan bot.
4. Jalankan `railway volume files list /` untuk memeriksa Volume tujuan. Unggah database dengan perintah di bawah. Path `/pengeluaran.db` adalah lokasi relatif terhadap akar Volume; di dalam bot, lokasinya menjadi `/data/pengeluaran.db`.

```text
railway volume files upload ./data/pengeluaran.db /pengeluaran.db
```

Jika Volume sudah berisi `pengeluaran.db`, jangan menimpanya sebelum memastikan isinya dan membuat cadangan. Perintah di atas sengaja tidak memakai opsi overwrite. Gunakan `railway volume browse /` untuk mengelola file dan unduh database yang sudah ada dahulu jika perlu. [Referensi pengelolaan file Volume](https://docs.railway.com/cli/volume).

Setelah upload berhasil, lanjutkan pengisian variabel dan deploy. Periksa total historis di Telegram sebelum menambahkan catatan baru. Tetap simpan salinan database laptop sebagai cadangan awal.

## Cadangan otomatis dan pemulihan

Database berada di `data/pengeluaran.db` pada laptop atau lokasi `DB_PATH` pada hosting. Bot membuat snapshot SQLite saat hidup, sehingga catatan dapat terus digunakan selama pencadangan. `/clear` dan Hapus Riwayat Telegram tidak menghapus database.

**Jadwal otomatis:** sekitar pukul **03.00** dalam zona waktu pemilik bot, atau `BOT_TIMEZONE` jika pemilik belum ditetapkan. Pada startup pertama, cadangan langsung dibuat jika slot jadwal terbaru belum tersedia. Setelah offline, bot membuat cadangan untuk slot terbaru; hari-hari yang terlewat tidak bisa direkonstruksi. Waktu dapat bergeser selama koneksi/proses sibuk. Bot harus tetap berjalan.

**Lokasi dan retensi:** di folder `backups/<nama-database>` di samping database, misalnya `data/backups/pengeluaran/` pada laptop atau `/data/backups/pengeluaran/` pada hosting. Disimpan **14 cadangan harian terakhir** bernama `auto-YYYY-MM-DD.db`. Nama tanggal mengikuti slot jadwal 03.00; snapshot memuat data saat benar-benar dibuat. Cadangan manual dan sebelum pembaruan/pemulihan tidak dihapus otomatis. Kelola salinan manual yang sudah tidak diperlukan untuk menjaga ruang penyimpanan.

**Unduh:** pemilik membuka **Pengaturan → Cadangan & pemulihan → Buat & unduh cadangan**, atau `/cadangan`. Bot membuat file `.db` baru sebelum mengirimnya. Cadangan berisi data semua pengguna, termasuk pengeluaran aktif/terhapus dan riwayat editnya, **dompet, saldo awal, dompet bawaan, pemasukan dan transfer aktif/terhapus**, anggaran bulanan dan per kategori, aturan anggaran otomatis, aturan kategori, favorit beserta dompetnya, jadwal dan status pengiriman rekap, tagihan beserta dompet dan catatan pembayarannya, pengingat, serta zona. Token, ID pengguna yang diizinkan, dan konfigurasi hosting tetap berada dalam `config.json`/Variables; simpan pengaturan itu sendiri.

**Simpan juga salinan di luar hosting.** Cadangan otomatis berada pada penyimpanan yang sama dengan database; jika Volume dihapus, cadangan di sana ikut hilang. File cadangan tidak terenkripsi dan berisi data seluruh pengguna: unduh melalui akun pemilik lalu simpan secara pribadi. Excel hanya laporan periode tertentu dan tidak dapat dipakai untuk pemulihan.

Jika file melebihi batas unduhan bot (49 MiB), ambil file dari folder cadangan hosting. Jika cadangan harian gagal, bot mencoba lagi setelah lima menit dan menampilkan status pada menu Cadangan serta log. Pencatatan tidak sengaja dihentikan oleh kegagalan pencadangan.

### Pemulihan di Windows

1. Unduh cadangan `.db` yang ingin dipulihkan. Simpan di luar lokasi database aktif.
2. **Hentikan seluruh proses bot**, termasuk pada hosting jika sedang pindah. Jangan menghapus folder data.
3. Jalankan **`PULIHKAN_WINDOWS.bat`** dari folder versi 2.4. Masukkan lokasi file cadangan; path yang mengandung spasi diperbolehkan.
4. Program memeriksa format, integritas, struktur, dan data. Periksa ringkasan pengeluaran aktif/terhapus, perubahan, dompet, pemasukan, transfer, jumlah pengguna, ID bot, serta tujuan pemulihan.
5. Ketik **`PULIHKAN`** untuk mengganti data tujuan. Enter saja membatalkan. File tujuan belum diganti sebelum pemeriksaan dan konfirmasi berhasil.
6. Program membuat salinan database lama bernama `before-restore-....db`, kemudian mengganti database secara atomik. Jika database lama rusak, byte asli dan jurnalnya tetap disalin untuk pemeriksaan.
7. Jalankan bot kembali dengan token yang sama. Buka `/menu`, cocokkan laporan, anggaran, riwayat edit, serta saldo melalui `/dompet` dan `/saldo`.

Pemulihan **mengganti seluruh isi database**, bukan menggabungkan. Data setelah tanggal snapshot tidak ikut tersedia. Akun Telegram dan token bot tetap memakai konfigurasi tujuan. Jika database tujuan yang masih terbaca terikat pada bot lain, pemulihan ditolak. Saat pindah ke hosting kosong, gunakan token bot yang sama dengan sumber cadangan.

Seluruh data yang tercantum dalam isi cadangan dipulihkan. Draf input, pilihan yang belum dikonfirmasi, tanda terima pemrosesan chat, serta daftar pesan untuk `/clear` dibersihkan agar alur lama tidak hidup kembali. Status kiriman rekap, kaitan pembayaran tagihan, dan identitas pencatatan pemasukan/transfer **tetap dipertahankan sesuai waktu snapshot**, sehingga pekerjaan yang sudah selesai saat pencadangan tidak diulang. Aktivitas setelah snapshot tidak dapat dipulihkan dari cadangan tersebut. Buka menu baru; pesan lama tidak langsung dapat dibersihkan bot.

Pemulihan menerima database bot versi 1, 2, 2.1, 2.2, 2.3, atau 2.4 dengan struktur yang dikenal. Gunakan alat versi 2.4 untuk memulihkan cadangan versi 2.4; alat versi lama belum mengenali tabel fitur baru. Cadangan sebelum 2.4 menempatkan pengeluaran di Umum dengan saldo awal belum diatur. Excel, ZIP, file rusak, serta skema asing ditolak.

Jika ingin membatalkan pemulihan yang sudah selesai, hentikan bot lalu jalankan alat yang sama memakai file `before-restore-....db` yang sehat. Salinan mentah database rusak tetap memerlukan perbaikan SQLite sebelum dapat digunakan.

### Pemulihan melalui terminal atau hosting

Di folder program, setelah proses bot berhenti:

```text
python3 cadangan.py restore /lokasi/cadangan.db --database /data/pengeluaran.db
```

Periksa ringkasan lalu ketik `PULIHKAN`. Pada Windows, gunakan `py -3` menggantikan `python3`. Opsi `--database` memilih tujuan; jika tidak diisi, program mengikuti `DB_PATH` atau `database` dalam `config.json`. Alat pemulihan tidak memerlukan token. Bot versi 2.4 dan alat ini memakai kunci proses untuk mencegah database yang sama digunakan bersamaan; versi bot lama tetap harus dihentikan sendiri.

Untuk membuat cadangan manual lewat terminal saat bot berhenti:

```text
python3 cadangan.py backup --database /data/pengeluaran.db
```

**Railway:** jika tidak mempunyai terminal pemulihan pada Volume, pulihkan dan periksa cadangan di folder baru pada laptop terlebih dahulu. Setelah itu pindahkan database hasil pemulihan ke Volume dengan prosedur **Memindahkan catatan laptop ke Railway**. Hentikan deployment bot selama pemindahan, simpan salinan database hosting lama, lalu ganti `pengeluaran.db` melalui pengelola file Volume. Jika terdapat jurnal `pengeluaran.db-wal`, `-shm`, atau `-journal`, simpan bersama database lama dan jangan biarkan jurnal lama mendampingi file hasil pemulihan. Jangan menjalankan bot laptop dan hosting bersamaan. Setelah deploy, cocokkan total historis sebelum mencatat lagi.

Update Telegram yang belum diterima disimpan paling lama 24 jam. Jangan mengandalkan pesan yang dikirim ketika bot offline terlalu lama. [Dokumentasi update Telegram](https://core.telegram.org/bots/api#getting-updates). Pesan yang sama diproses ulang karena gangguan koneksi tidak menggandakan catatan, tetapi dua pesan terpisah yang kamu kirim sendiri tetap dicatat dua kali.

## Mengatasi kendala

| Kendala | Langkah |
| --- | --- |
| Python tidak ditemukan | Pasang Python 3.10+, lalu buka ulang peluncur BAT |
| Token belum diisi atau ditolak | Periksa token dari BotFather pada konfigurasi atau variable hosting |
| Akun belum diberi akses | Kirim `/id`, masukkan ID tersebut dalam daftar akses, lalu mulai ulang |
| Error 409 | Hentikan proses lain yang memakai token sama; jika pernah memakai webhook, lepaskan webhook pada layanan lama |
| Bot diam di laptop | Pastikan program berjalan, koneksi ada, dan laptop tidak sleep |
| Bot berhenti saat deploy | Periksa log; pastikan Volume `/data`, variabel, dan semua file program tersedia |
| Format Excel tidak ditemukan | Salin folder `assets` beserta `rekap-template.xlsx` dan `arus-kas-template.xlsx` dari paket terbaru |
| Saldo bertanda sementara | Atur saldo awal setiap dompet melalui `/dompet`; simpan `0` jika memang dimulai dari nol |
| Saldo negatif/tidak cocok | Periksa saldo sebelum seluruh catatan, pemasukan yang terlewat, dan dompet pengeluaran lama |
| Nama dompet tidak ditemukan | Buat dompet dahulu, atau samakan nama kolom ketiga dengan daftar `/dompet`, lalu kirim ulang |
| Transfer belum dapat dimulai | Buat sedikitnya dua dompet; asal dan tujuan harus berbeda |
| Jam terasa tidak sesuai | Buka `/zona`, pilih zona yang benar, kemudian tekan Perbarui |
| Pesan dianggap sebagai nilai edit/filter | Tekan Batal atau kirim `/batal`, lalu mulai pencatatan lagi |
| Pengingat belum muncul | Periksa status aktif, jadwal berikutnya, zona waktu, dan apakah proses bot tetap berjalan |
| Kategori tidak sesuai | Periksa aturan aktif dan kecocokan kata utuh; tulis kategori setelah tanda pemisah untuk menetapkannya sendiri |
| Rekap otomatis belum diterima | Aktifkan jadwal di `/rekapotomatis`; periksa zona, jadwal berikutnya, dan proses bot |
| Tagihan sudah pernah dicatat | Edit atau pulihkan catatan pembayaran dari rincian tagihan; satu periode memakai satu catatan |
| Modul program tidak ditemukan | Salin seluruh file versi 2.4, termasuk `v24.py`, `storage_v24.py`, `excel_cash.py`, dan pakai Dockerfile terbaru |
| Menu cadangan tidak muncul | Pastikan pemilik ditetapkan dalam `owner_user_id`/`OWNER_USER_ID` dan termasuk daftar ID diizinkan |
| Database sedang digunakan | Hentikan proses bot lain/pemulihan; jangan menghapus file kunci untuk memaksa akses |
| Pemulihan menolak file | Gunakan cadangan `.db` milik bot yang sama; periksa pesan kesalahan dan simpan database tujuan |
| Sebagian pesan tidak terhapus | Pesan lebih lama atau belum dikenali bot; gunakan Hapus Riwayat Telegram |
| Total berbeda setelah pindah | Pastikan memakai database dan akun Telegram yang sama; cocokkan periode laporan |
| Nominal lama tergabung dalam satu keterangan | Hapus catatan lama tersebut, lalu kirim ulang satu pengeluaran per baris |

## Menjalankan dari terminal dan pengujian

Windows: `py -3 bot.py`. Linux/macOS: `python3 bot.py`. Python minimum 3.10; tidak perlu `pip install`. Jalankan dari folder program. Konfigurasi environment mengalahkan nilai file konfigurasi jika keduanya diberikan.

Pengujian lokal tanpa token asli dan tanpa internet:

```text
python3 -m unittest -v test_bot.py test_features.py test_v22.py test_v23.py test_v24.py
```

Pada Windows gunakan `py -3 -m unittest -v test_bot.py test_features.py test_v22.py test_v23.py test_v24.py`.

**Validasi versi 2.4:** 168 pengujian otomatis lulus. Pengujian mencakup fitur lama serta saldo awal belum diatur/nol, pemasukan dengan konfirmasi, pemilihan dompet, transfer dua sisi, edit/hapus/pulihkan transaksi, perlindungan dari pencatatan ganda, privasi antar akun, tanggal dan restart, saldo lintas bulan, dompet favorit/tagihan, riwayat dan Urungkan edit pengeluaran, serta cadangan lengkap dan penolakan relasi dompet yang tidak valid. Migrasi dan pemulihan juga diperiksa menggunakan database yang dibuat oleh kode paket versi 2.3 asli, termasuk riwayat edit, favorit, tagihan, rekap terjadwal, dan anggaran.

Excel diperiksa secara lokal: nilai ekspor cocok dengan saldo database, rumus dihitung ulang setelah nominal pengeluaran/transfer diubah, dan kedua jenis laporan dirender untuk memeriksa tampilan. Transfer tetap mempertahankan total saldo gabungan.

Pengujian memakai database sementara dan simulasi respons Telegram. Koneksi ke bot Telegram milikmu, peluncur pada Windows, dan deployment Railway belum diuji langsung.

Isi utama paket: program Python, konfigurasi contoh, peluncur Windows, template Excel, konfigurasi hosting, panduan HTML/Markdown, dan pengujian. Buka `README.html` untuk membaca panduan ini di browser.
