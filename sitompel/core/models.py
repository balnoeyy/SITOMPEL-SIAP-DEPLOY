from django.db import models
from django.conf import settings
import uuid

class MataKuliah(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kode_mk = models.CharField(max_length=20, unique=True)
    nama_mk = models.CharField(max_length=100)
    sks = models.IntegerField()

    def __str__(self):
        return f"{self.kode_mk} - {self.nama_mk}"

class Kelas(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mata_kuliah = models.ForeignKey(MataKuliah, on_delete=models.CASCADE, related_name='daftar_kelas')
    nama_kelas = models.CharField(max_length=10) # Contoh: LA83, LB83
    
    # Relasi Many-to-Many ke AkunUser (Pengajar). 
    # limit_choices_to memastikan hanya akun dengan role PENGAJAR yang bisa dipilih.
    pengajar = models.ManyToManyField(
        settings.AUTH_USER_MODEL, 
        limit_choices_to={'role': 'PENGAJAR'},
        related_name='kelas_diajar'
    )

    def __str__(self):
        return f"{self.mata_kuliah.kode_mk} | Kelas {self.nama_kelas}"

class Pelajar(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nim = models.CharField(max_length=20, unique=True)
    nama_pelajar = models.CharField(max_length=150)
    
    # Relasi Many-to-Many ke Kelas
    kelas = models.ManyToManyField(Kelas, related_name='daftar_pelajar')

    def __str__(self):
        return f"{self.nim} - {self.nama_pelajar}"

class SesiUjian(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kelas = models.ForeignKey(Kelas, on_delete=models.CASCADE, related_name='sesi_ujian')
    nama_ujian = models.CharField(max_length=100) # Contoh: UTS Ganjil 2026
    tanggal_ujian = models.DateTimeField()
    
    # Implementasi kompromi kita: dokumen_rubrik bersifat opsional (null=True, blank=True)
    # Jika diisi, RAG akan mengambil konteks dari sini. Jika kosong, RAG pakai ParameterRubrik.
    dokumen_rubrik = models.FileField(upload_to='rubrik_materi/', null=True, blank=True)

    def __str__(self):
        return f"{self.nama_ujian} - {self.kelas.nama_kelas}"

class Soal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sesi_ujian = models.ForeignKey(SesiUjian, on_delete=models.CASCADE, related_name='daftar_soal')
    nomor_soal = models.IntegerField()
    pertanyaan = models.TextField()
    bobot_maksimal = models.FloatField()

    class Meta:
        ordering = ['nomor_soal'] 

    def __str__(self):
        return f"Soal No {self.nomor_soal} - {self.sesi_ujian.nama_ujian}"

class ParameterRubrik(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    soal = models.ForeignKey(Soal, on_delete=models.CASCADE, related_name='parameter_jawaban')
    deskripsi_jawaban = models.TextField(help_text="Variasi argumen jawaban yang benar untuk acuan SBERT")
    bobot_parameter = models.FloatField()

    def __str__(self):
        return f"Parameter Soal {self.soal.nomor_soal}"

class DokumenUjian(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sesi_ujian = models.ForeignKey(SesiUjian, on_delete=models.CASCADE, related_name='dokumen_terkumpul')
    pelajar = models.ForeignKey(Pelajar, on_delete=models.CASCADE, related_name='dokumen_ujian')
    file_gambar = models.ImageField(upload_to='lembar_ujian_raw/')
    tanggal_unggah = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Lembar {self.pelajar.nama_pelajar} - {self.sesi_ujian.nama_ujian}"

class JawabanUjian(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dokumen = models.ForeignKey(DokumenUjian, on_delete=models.CASCADE, related_name='jawaban_detail')
    soal = models.ForeignKey(Soal, on_delete=models.CASCADE)
    
    # Teks Hasil Ekstraksi
    teks_ocr_mentah = models.TextField(blank=True, null=True)
    teks_ocr_final = models.TextField(blank=True, null=True, help_text="Teks setelah direview pengajar")
    
    # Hasil Evaluasi AI
    skor_ai = models.FloatField(null=True, blank=True)
    catatan_rag = models.TextField(blank=True, null=True)
    
    # Keputusan Akhir Pengajar
    is_overridden = models.BooleanField(default=False)
    skor_akhir = models.FloatField(null=True, blank=True)
    catatan_pengajar = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Jawaban No {self.soal.nomor_soal} - {self.dokumen.pelajar.nim}"