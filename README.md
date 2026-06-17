# SITOMPEL

SITOMPEL adalah aplikasi Django untuk manajemen mata kuliah, sesi ujian, OCR lembar jawaban, scoring otomatis, dan rekapitulasi nilai.

## Setup lokal

1. Buat virtual environment Python.
2. Install dependency:

```bash
pip install -r requirements.txt
```

3. Salin `.env.example` menjadi `.env`, lalu isi konfigurasi database dan API key yang diperlukan.
4. Jalankan migrasi:

```bash
python sitompel/manage.py migrate
```

5. Jalankan server:

```bash
python sitompel/manage.py runserver
```

## Catatan keamanan

File kredensial seperti `.env`, `kredensial-gcp.json`, hasil scan OCR, file rubrik upload, cache Python, dan virtual environment tidak boleh masuk ke GitHub.
