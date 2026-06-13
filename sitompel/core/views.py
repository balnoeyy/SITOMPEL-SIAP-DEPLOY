import json, base64, os, google, openpyxl
from django.shortcuts import render, get_object_or_404

from django.contrib.auth.decorators import login_required

from django.http import HttpResponseForbidden, JsonResponse, HttpResponse

from django.views.decorators.csrf import csrf_exempt

from django.db.models import Count

from django.conf import settings
from google.cloud import vision
from django.core.files.base import ContentFile
from django.contrib import messages
from django.shortcuts import redirect

from .models import SesiUjian, Pelajar, DokumenUjian, JawabanUjian, Soal, Kelas, MataKuliah
# from .models import CustomUser

from .services.nlp_utils import hitung_skor_semantik, validasi_logika
from .services.vision_utils import proses_scan_kertas
from .services.ocr_google import ekstrak_teks_dari_gambar

@login_required
def pengajar_dashboard(request):
    if request.user.role != 'PENGAJAR':
        return redirect('/admin/') 
        
    # user = CustomUser.objects.get(id=request.user.id)
    kelas_diajar = request.user.kelas_diajar.prefetch_related('sesi_ujian').all()
    
    context = {
        # 'user': user,
        'kelas_diajar': kelas_diajar,
    }
    return render(request, 'core/pengajar_dashboard.html', context)

@login_required
def admin_dashboard(request):
    if getattr(request.user, 'role', '') != 'ADMIN':
        messages.error(request, "Akses ditolak. Halaman ini khusus untuk Admin.")
        return redirect('pengajar_dashboard')

    total_pelajar = Pelajar.objects.count()
    total_kelas = Kelas.objects.count()
    total_mk = MataKuliah.objects.count()
    
    sesi_ujian_terbaru = SesiUjian.objects.select_related('kelas__mata_kuliah').order_by('-tanggal_ujian')[:5]

    context = {
        'total_pelajar': total_pelajar,
        'total_kelas': total_kelas,
        'total_mk': total_mk,
        'sesi_ujian_terbaru': sesi_ujian_terbaru,
    }
    return render(request, 'core/admin_dashboard.html', context)

@login_required
def capture_lembar_ujian(request, sesi_id):
    if request.user.role != 'PENGAJAR':
        return JsonResponse({'error': 'Akses ditolak'}, status=403)
        
    sesi = get_object_or_404(SesiUjian, id=sesi_id)

    daftar_pelajar = sesi.kelas.daftar_pelajar.all()
    
    context = {
        'sesi': sesi,
        'daftar_pelajar': daftar_pelajar,
    }
    return render(request, 'core/capture_webcam.html', context)

def proses_ocr_vision(image_path):
    """
    Fungsi helper untuk mengirim gambar ke Google Vision API.
    Menggunakan document_text_detection khusus untuk membaca paragraf/tulisan tangan.
    """
    client = vision.ImageAnnotatorClient()
    
    with open(image_path, "rb") as image_file:
        content = image_file.read()
        
    image = vision.Image(content=content)
    
    response = client.document_text_detection(image=image)
    
    if response.error.message:
        raise Exception(f"Vision API Error: {response.error.message}")
        
    if response.full_text_annotation:
        return response.full_text_annotation.text
    return ""

@login_required
def api_upload_capture(request, sesi_id):
    sesi = get_object_or_404(SesiUjian, id=sesi_id)
    
    if request.method == 'POST':
        pelajar_id = request.POST.get('pelajar_id')
        image_b64 = request.POST.get('image_base64') # Mengambil Base64 dari JS
        
        if not pelajar_id or not image_b64:
            messages.error(request, "Gagal mengambil data gambar dari kamera.")
            return redirect('capture_ujian', sesi_id=sesi.id)
            
        pelajar = get_object_or_404(Pelajar, id=pelajar_id)
        
        # PROSES DEKODE BASE64 JADI FILE FISIK
        format_gambar, imgstr = image_b64.split(';base64,') 
        ext = format_gambar.split('/')[-1] 
        data_gambar = ContentFile(base64.b64decode(imgstr), name=f'scan_mhs_{pelajar.nim}.{ext}')
        
        dokumen = DokumenUjian.objects.create(
            sesi_ujian=sesi,
            pelajar=pelajar,
            file_gambar=data_gambar
        )
        
        path_gambar_absolut = dokumen.file_gambar.path
        try:
            teks_hasil_ocr = ekstrak_teks_dari_gambar(path_gambar_absolut)

            print("================= HASIL OCR ====================")
            print(teks_hasil_ocr)
            print("================================================")
        except Exception as e:
            teks_hasil_ocr = ""
            messages.warning(request, f"Google Vision API Gagal: {str(e)}")
            
        for soal in sesi.daftar_soal.all():
            JawabanUjian.objects.create(
                dokumen=dokumen,
                soal=soal,
                teks_ocr_mentah=teks_hasil_ocr,
                teks_ocr_final=teks_hasil_ocr,
            )
            
        return redirect('review_jawaban', dokumen_id=dokumen.id)
        
    return redirect('pengajar_dashboard')

@login_required
def review_jawaban(request, dokumen_id):
    """
    Menampilkan antarmuka Split-Screen untuk validasi Human-in-the-Loop.
    """
    dokumen = get_object_or_404(DokumenUjian, id=dokumen_id)

    # Cek user Pengajar terdaftar untuk akses kelas atau tidak
    if not dokumen.sesi_ujian.kelas.pengajar.filter(id=request.user.id).exists():
        messages.error(request, "Keamanan Sistem: Anda tidak memiliki hak akses untuk memeriksa dokumen kelas ini!")
        return redirect('pengajar_dashboard')
    
    jawaban_list = dokumen.jawaban_detail.all().order_by('soal__nomor_soal')
    
    if request.method == 'POST':
        # Logika untuk menyimpan perubahan teks (typo) dari dosen 
        for jawaban in jawaban_list:
            teks_baru = request.POST.get(f'jawaban_{jawaban.id}')
            
            if teks_baru:
                # Update teks final yang siap dinilai oleh AI
                jawaban.teks_ocr_final = teks_baru.strip()
                
                # Ambil semua parameter rubrik yang terikat dengan soal ini
                daftar_parameter = jawaban.soal.parameter_jawaban.all()
                
                if daftar_parameter.exists():
                    # 1. Jalankan SBERT untuk mendapatkan kedekatan semantik mentah
                    persentase_kemiripan = hitung_skor_semantik(jawaban.teks_ocr_final, daftar_parameter)
                    
                    # 2. Jalankan RAG (Gemini) untuk memvalidasi konteks logikanya
                    skor_validasi, catatan_rag = validasi_logika(
                        pertanyaan=jawaban.soal.pertanyaan,
                        teks_jawaban=jawaban.teks_ocr_final,
                        parameter_rubrik=daftar_parameter,
                        skor_sbert_mentah=persentase_kemiripan
                    )
                    
                    # 3. Kalkulasi skor akhir (0.0 - 1.0) dikali bobot maksimal soal
                    skor_kalkulasi = skor_validasi * jawaban.soal.bobot_maksimal
                    
                    # 4. Simpan ke database
                    jawaban.skor_ai = round(skor_kalkulasi, 2)
                    jawaban.skor_akhir = jawaban.skor_ai
                    jawaban.catatan_rag = catatan_rag
                else:
                    jawaban.skor_ai = 0.0
                    jawaban.skor_akhir = 0.0
                    jawaban.catatan_rag = "Gagal menilai: Parameter rubrik belum ditentukan oleh pengajar."
                
                jawaban.save()
                
        messages.success(request, f"Sukses: Jawaban {dokumen.pelajar.nama_pelajar} telah dinilai secara otomatis.")
        return redirect('pengajar_dashboard')
      
    context = {
        'dokumen': dokumen,
        'jawaban_list': jawaban_list,
    }
    return render(request, 'core/review_split.html', context)

@login_required
def lihat_hasil_ujian(request, sesi_id):
    sesi = get_object_or_404(SesiUjian, id=sesi_id)
    
    # PROTEKSI KEAMANAN: Memastikan dosen yang login adalah pengajar di kelas ini
    if not sesi.kelas.pengajar.filter(id=request.user.id).exists():
        messages.error(request, "Keamanan Sistem: Anda tidak memiliki otoritas untuk melihat nilai kelas ini.")
        return redirect('pengajar_dashboard')
        
    # Mengambil semua dokumen ujian di sesi ini beserta detail jawabannya
    dokumen_terkumpul = sesi.dokumen_terkumpul.prefetch_related('jawaban_detail__soal').all()
    
    # Logika Form POST untuk menyimpan nilai Override dari dosen
    if request.method == 'POST':
        for dokumen in dokumen_terkumpul:
            for jawaban in dokumen.jawaban_detail.all():
                # Mengambil input nilai baru dari form HTML (jika dosen mengubahnya)
                input_skor_baru = request.POST.get(f'skor_akhir_{jawaban.id}')
                
                if input_skor_baru:
                    try:
                        skor_float = float(input_skor_baru)
                        # Cek apakah dosen benar-benar merubah nilainya dari tebakan awal AI
                        if skor_float != jawaban.skor_ai:
                            jawaban.skor_akhir = skor_float
                            jawaban.is_overridden = True
                            jawaban.catatan_pengajar = request.POST.get(f'catatan_{jawaban.id}', '')
                            jawaban.save()
                    except ValueError:
                        continue # Abaikan jika input bukan angka
                        
        messages.success(request, "Perubahan nilai manual berhasil disimpan.")
        return redirect('lihat_hasil_ujian', sesi_id=sesi.id)

    context = {
        'sesi': sesi,
        'dokumen_terkumpul': dokumen_terkumpul,
    }
    return render(request, 'core/hasil_penilaian.html', context)

@login_required
def ekspor_nilai_excel(request, sesi_id):
    sesi = get_object_or_404(SesiUjian, id=sesi_id)
    
    if not sesi.kelas.pengajar.filter(id=request.user.id).exists():
        messages.error(request, "Akses ditolak.")
        return redirect('pengajar_dashboard')

    # Membuat Workbook Excel baru
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rekap Nilai"

    # Menyusun Header Kolom
    headers = ['NIM', 'Nama Mahasiswa', 'Nilai Total (AI)', 'Nilai Total (Akhir)', 'Status Override']
    for col_num, header_title in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.value = header_title
        cell.font = openpyxl.styles.Font(bold=True)

    # Mengambil dan menyusun dataset
    dokumen_terkumpul = sesi.dokumen_terkumpul.prefetch_related('pelajar', 'jawaban_detail').all()
    
    for row_num, dokumen in enumerate(dokumen_terkumpul, 2):
        skor_ai_total = sum(j.skor_ai for j in dokumen.jawaban_detail.all())
        skor_akhir_total = sum(j.skor_akhir for j in dokumen.jawaban_detail.all())
        ada_override = any(j.is_overridden for j in dokumen.jawaban_detail.all())
        
        ws.cell(row=row_num, column=1, value=dokumen.pelajar.nim)
        ws.cell(row=row_num, column=2, value=dokumen.pelajar.nama_pelajar)
        ws.cell(row=row_num, column=3, value=skor_ai_total)
        ws.cell(row=row_num, column=4, value=skor_akhir_total)
        ws.cell(row=row_num, column=5, value="Disesuaikan" if ada_override else "Asli AI")

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename=Rekap_Nilai_{sesi.nama_ujian.replace(" ", "_")}.xlsx'
    
    wb.save(response)
    return response

@login_required
def manajemen_mahasiswa(request):
    if getattr(request.user, 'role', '') != 'ADMIN':
        messages.error(request, "Akses ilegal ditolak oleh sistem.")
        return redirect('pengajar_dashboard')

    if request.method == 'POST':
        nim = request.POST.get('nim', '').strip()
        nama = request.POST.get('nama_pelajar', '').strip()
        
        if nim and nama:
            if Pelajar.objects.filter(nim=nim).exists():
                messages.error(request, f"Gagal: Mahasiswa dengan NIM {nim} sudah ada di pangkalan data.")
            else:
                # Simpan data mahasiswa baru ke PostgreSQL
                Pelajar.objects.create(nim=nim, nama_pelajar=nama)
                messages.success(request, f"Sukses: Mahasiswa bernama {nama} ({nim}) berhasil didaftarkan.")
                return redirect('manajemen_mahasiswa')

    # Logika menampilkan data (GET): Ambil semua data mahasiswa, urutkan berdasarkan NIM terbaru
    daftar_mahasiswa = Pelajar.objects.all().order_by('-id')

    context = {
        'daftar_mahasiswa': daftar_mahasiswa,
    }
    return render(request, 'core/manajemen_mahasiswa.html', context)