import calendar
import uuid
import json, base64, os, google, openpyxl
from django.shortcuts import render, get_object_or_404

from django.contrib.auth.decorators import login_required

from django.http import HttpResponseForbidden, JsonResponse, HttpResponse

from django.views.decorators.csrf import csrf_exempt

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.urls import reverse

from django.conf import settings
from google.cloud import vision
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.contrib import messages
from django.shortcuts import redirect

from .models import SesiUjian, Pelajar, DokumenUjian, JawabanUjian, Soal, Kelas, MataKuliah, ParameterRubrik, PasswordResetRequest, ActivityLog
from accounts.models import CustomUser
# from .models import CustomUser

from .services.nlp_utils import hitung_skor_semantik, validasi_logika
from .services.vision_utils import proses_scan_kertas
from .services.ocr_google import ekstrak_teks_dari_gambar
from .services.ocr_parser import pisahkan_jawaban_per_soal

DEFAULT_RESET_PASSWORD = 'sitompel123'


def catat_aktivitas(request, action, target='', description=''):
    user = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
    ActivityLog.objects.create(
        user=user,
        action=action,
        target=target[:180],
        description=description or target or action,
    )


def nilai_jawaban_otomatis(jawaban):
    daftar_parameter = jawaban.soal.parameter_jawaban.all()

    if not jawaban.teks_ocr_final:
        jawaban.skor_ai = 0.0
        jawaban.skor_akhir = 0.0
        jawaban.catatan_rag = "Jawaban kosong atau OCR belum berhasil membaca jawaban untuk soal ini."
    elif daftar_parameter.exists():
        persentase_kemiripan = hitung_skor_semantik(jawaban.teks_ocr_final, daftar_parameter)
        skor_validasi, catatan_rag = validasi_logika(
            pertanyaan=jawaban.soal.pertanyaan,
            teks_jawaban=jawaban.teks_ocr_final,
            parameter_rubrik=daftar_parameter,
            skor_sbert_mentah=persentase_kemiripan
        )
        skor_kalkulasi = skor_validasi * jawaban.soal.bobot_maksimal
        jawaban.skor_ai = round(skor_kalkulasi, 2)
        jawaban.skor_akhir = jawaban.skor_ai
        jawaban.catatan_rag = catatan_rag
    else:
        jawaban.skor_ai = 0.0
        jawaban.skor_akhir = 0.0
        jawaban.catatan_rag = "Gagal menilai: Parameter rubrik belum ditentukan oleh pengajar."

    jawaban.save(update_fields=['skor_ai', 'skor_akhir', 'catatan_rag'])
    return jawaban

def landing_page(request):
    return render(request, 'core/landing.html')

@login_required
def pengajar_dashboard(request):
    if request.user.role != 'PENGAJAR':
        return redirect('admin_dashboard') 
        
    today = timezone.localdate()
    try:
        calendar_year = int(request.GET.get('year', today.year))
        calendar_month = int(request.GET.get('month', today.month))
        if not 1 <= calendar_month <= 12:
            raise ValueError
    except ValueError:
        calendar_year = today.year
        calendar_month = today.month

    if calendar_month == 1:
        prev_year, prev_month = calendar_year - 1, 12
    else:
        prev_year, prev_month = calendar_year, calendar_month - 1

    if calendar_month == 12:
        next_year, next_month = calendar_year + 1, 1
    else:
        next_year, next_month = calendar_year, calendar_month + 1

    month_start = timezone.datetime(calendar_year, calendar_month, 1, tzinfo=timezone.get_current_timezone())
    _, last_day = calendar.monthrange(calendar_year, calendar_month)
    month_end = timezone.datetime(calendar_year, calendar_month, last_day, 23, 59, 59, tzinfo=timezone.get_current_timezone())

    kelas_diajar = request.user.kelas_diajar.prefetch_related('sesi_ujian').all()
    sesi_ujian_bulan_ini = SesiUjian.objects.select_related('kelas__mata_kuliah').filter(
        kelas__pengajar=request.user,
        tanggal_ujian__range=(month_start, month_end)
    ).order_by('tanggal_ujian').distinct()

    ujian_by_day = {}
    for sesi in sesi_ujian_bulan_ini:
        ujian_by_day.setdefault(timezone.localtime(sesi.tanggal_ujian).day, []).append(sesi)

    calendar_weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(calendar_year, calendar_month):
        calendar_weeks.append([
            {
                'day': day,
                'is_today': day == today.day and calendar_month == today.month and calendar_year == today.year,
                'exam_count': len(ujian_by_day.get(day, [])) if day else 0,
                'exams': ujian_by_day.get(day, []),
            }
            for day in week
        ])
    
    context = {
        'kelas_diajar': kelas_diajar,
        'server_time': timezone.localtime(),
        'calendar_weeks': calendar_weeks,
        'calendar_month_name': calendar.month_name[calendar_month],
        'calendar_year': calendar_year,
        'prev_calendar_url': f"{reverse('pengajar_dashboard')}?month={prev_month}&year={prev_year}",
        'next_calendar_url': f"{reverse('pengajar_dashboard')}?month={next_month}&year={next_year}",
    }
    return render(request, 'core/pengajar_dashboard.html', context)

@login_required
def admin_dashboard(request):
    if getattr(request.user, 'role', '') != 'ADMIN':
        messages.error(request, "Akses ditolak. Halaman ini khusus untuk Admin.")
        return redirect('pengajar_dashboard')

    today = timezone.localdate()
    try:
        calendar_year = int(request.GET.get('year', today.year))
        calendar_month = int(request.GET.get('month', today.month))
        if not 1 <= calendar_month <= 12:
            raise ValueError
    except ValueError:
        calendar_year = today.year
        calendar_month = today.month

    if calendar_month == 1:
        prev_year, prev_month = calendar_year - 1, 12
    else:
        prev_year, prev_month = calendar_year, calendar_month - 1

    if calendar_month == 12:
        next_year, next_month = calendar_year + 1, 1
    else:
        next_year, next_month = calendar_year, calendar_month + 1

    month_start = timezone.datetime(calendar_year, calendar_month, 1, tzinfo=timezone.get_current_timezone())
    _, last_day = calendar.monthrange(calendar_year, calendar_month)
    month_end = timezone.datetime(calendar_year, calendar_month, last_day, 23, 59, 59, tzinfo=timezone.get_current_timezone())

    total_pelajar = Pelajar.objects.count()
    total_pengajar = CustomUser.objects.filter(role='PENGAJAR').count()
    total_kelas = Kelas.objects.count()
    total_mk = MataKuliah.objects.count()
    pending_reset_requests = PasswordResetRequest.objects.select_related('user').filter(status='PENDING')
    
    sesi_ujian_bulan_ini = SesiUjian.objects.select_related('kelas__mata_kuliah').filter(
        tanggal_ujian__range=(month_start, month_end)
    ).order_by('tanggal_ujian')

    ujian_by_day = {}
    for sesi in sesi_ujian_bulan_ini:
        ujian_by_day.setdefault(timezone.localtime(sesi.tanggal_ujian).day, []).append(sesi)

    calendar_weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(calendar_year, calendar_month):
        calendar_weeks.append([
            {
                'day': day,
                'is_today': day == today.day and calendar_month == today.month and calendar_year == today.year,
                'exam_count': len(ujian_by_day.get(day, [])) if day else 0,
                'exams': ujian_by_day.get(day, []),
            }
            for day in week
        ])

    context = {
        'total_pelajar': total_pelajar,
        'total_pengajar': total_pengajar,
        'total_kelas': total_kelas,
        'total_mk': total_mk,
        'pending_reset_requests': pending_reset_requests,
        'server_time': timezone.localtime(),
        'calendar_weeks': calendar_weeks,
        'calendar_month_name': calendar.month_name[calendar_month],
        'calendar_month': calendar_month,
        'calendar_year': calendar_year,
        'prev_calendar_url': f"{reverse('admin_dashboard')}?month={prev_month}&year={prev_year}",
        'next_calendar_url': f"{reverse('admin_dashboard')}?month={next_month}&year={next_year}",
        'sesi_ujian_bulan_ini': sesi_ujian_bulan_ini,
    }
    return render(request, 'core/admin_dashboard.html', context)

@login_required
def daftar_kelas(request):
    if request.user.role != 'PENGAJAR':
        return redirect('admin_dashboard')

    kelas_diajar = request.user.kelas_diajar.prefetch_related('sesi_ujian', 'daftar_pelajar').all()
    return render(request, 'core/daftar_kelas.html', {'kelas_diajar': kelas_diajar})

@login_required
def detail_kelas(request, kelas_id):
    kelas = get_object_or_404(
        Kelas.objects.prefetch_related('pengajar', 'daftar_pelajar', 'sesi_ujian__daftar_soal'),
        id=kelas_id
    )

    if request.user.role != 'PENGAJAR' or not kelas.pengajar.filter(id=request.user.id).exists():
        messages.error(request, "Anda tidak memiliki akses ke kelas ini.")
        return redirect('pengajar_dashboard')

    context = {
        'kelas': kelas,
        'daftar_pelajar': kelas.daftar_pelajar.all(),
        'daftar_sesi': kelas.sesi_ujian.all().order_by('-tanggal_ujian'),
    }
    return render(request, 'core/detail_kelas.html', context)

@login_required
def arsip_kelas(request):
    if request.user.role != 'PENGAJAR':
        return redirect('admin_dashboard')

    sesi_terakhir = SesiUjian.objects.select_related('kelas__mata_kuliah').prefetch_related(
        'dokumen_terkumpul',
        'kelas__daftar_pelajar'
    ).filter(
        kelas__pengajar=request.user
    ).annotate(
        total_peserta_scan=Count('dokumen_terkumpul__pelajar', distinct=True)
    ).order_by('-tanggal_ujian')[:10]

    return render(request, 'core/arsip_kelas.html', {'sesi_terakhir': sesi_terakhir})

@login_required
def kelola_rubrik(request, sesi_id):
    sesi = get_object_or_404(
        SesiUjian.objects.select_related('kelas__mata_kuliah').prefetch_related('daftar_soal__parameter_jawaban'),
        id=sesi_id
    )

    if request.user.role != 'PENGAJAR' or not sesi.kelas.pengajar.filter(id=request.user.id).exists():
        messages.error(request, "Anda tidak memiliki akses untuk mengelola rubrik ujian ini.")
        return redirect('pengajar_dashboard')

    if request.method == 'POST':
        for soal in sesi.daftar_soal.all():
            daftar_rubrik = [
                teks.strip()
                for teks in request.POST.getlist(f'rubrik_{soal.id}[]')
                if teks.strip()
            ]

            if daftar_rubrik:
                soal.parameter_jawaban.all().delete()
                bobot_parameter = soal.bobot_maksimal / len(daftar_rubrik) if soal.bobot_maksimal else 1
                for teks_rubrik in daftar_rubrik:
                    ParameterRubrik.objects.create(
                        soal=soal,
                        deskripsi_jawaban=teks_rubrik,
                        bobot_parameter=bobot_parameter
                    )

        catat_aktivitas(
            request,
            'Update Rubrik',
            sesi.nama_ujian,
            f"Rubrik sesi {sesi.nama_ujian} untuk kelas {sesi.kelas.nama_kelas} diperbarui."
        )
        messages.success(request, "Rubrik penilaian berhasil disimpan.")
        return redirect('detail_kelas', kelas_id=sesi.kelas.id)

    return render(request, 'core/kelola_rubrik.html', {'sesi': sesi})

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
        pages_json = request.POST.get('image_base64_pages', '')
        image_b64 = request.POST.get('image_base64') # Fallback untuk format lama.
        
        if pages_json:
            try:
                image_pages = [page for page in json.loads(pages_json) if page]
            except json.JSONDecodeError:
                image_pages = []
        else:
            image_pages = [image_b64] if image_b64 else []

        if not pelajar_id or not image_pages:
            messages.error(request, "Gagal mengambil data gambar dari kamera.")
            return redirect('capture_ujian', sesi_id=sesi.id)
            
        pelajar = get_object_or_404(Pelajar, id=pelajar_id)
        
        # PROSES DEKODE BASE64 JADI FILE FISIK
        format_gambar, imgstr = image_pages[0].split(';base64,') 
        ext = format_gambar.split('/')[-1] 
        data_gambar = ContentFile(base64.b64decode(imgstr), name=f'scan_mhs_{pelajar.nim}.{ext}')
        
        dokumen = DokumenUjian.objects.create(
            sesi_ujian=sesi,
            pelajar=pelajar,
            file_gambar=data_gambar
        )

        daftar_soal = list(sesi.daftar_soal.all())
        gabungan_ocr_mentah = []
        gabungan_jawaban_per_soal = {soal.nomor_soal: '' for soal in daftar_soal}
        total_ocr_berhasil = 0

        for index, page_b64 in enumerate(image_pages, start=1):
            try:
                if index == 1:
                    path_gambar_absolut = dokumen.file_gambar.path
                else:
                    format_page, imgstr_page = page_b64.split(';base64,')
                    ext_page = format_page.split('/')[-1]
                    saved_name = default_storage.save(
                        f"lembar_ujian_raw/tambahan_live_{pelajar.nim}_{uuid.uuid4().hex}.{ext_page}",
                        ContentFile(base64.b64decode(imgstr_page))
                    )
                    path_gambar_absolut = default_storage.path(saved_name)

                teks_halaman = ekstrak_teks_dari_gambar(path_gambar_absolut)
                gabungan_ocr_mentah.append(f"--- HALAMAN {index} ---\n{teks_halaman}")
                jawaban_halaman = pisahkan_jawaban_per_soal(teks_halaman, daftar_soal)
                for nomor_soal, teks_jawaban in jawaban_halaman.items():
                    teks_jawaban = (teks_jawaban or '').strip()
                    if teks_jawaban:
                        gabungan_jawaban_per_soal[nomor_soal] = (
                            f"{gabungan_jawaban_per_soal.get(nomor_soal, '').strip()}\n\n{teks_jawaban}"
                        ).strip()
                if teks_halaman.strip():
                    total_ocr_berhasil += 1
            except Exception as e:
                gabungan_ocr_mentah.append(f"--- HALAMAN {index} GAGAL OCR ---\n{str(e)}")
                messages.error(request, f"OCR halaman {index} gagal: {str(e)}")

        teks_hasil_ocr = "\n\n".join(gabungan_ocr_mentah).strip()
        if total_ocr_berhasil:
            messages.success(request, f"OCR berhasil membaca {total_ocr_berhasil} dari {len(image_pages)} jepretan.")
        else:
            messages.warning(request, "OCR berjalan, tetapi tidak menemukan teks. Coba ulang scan dengan pencahayaan lebih terang dan posisi kertas lebih dekat.")

        if teks_hasil_ocr.strip() and not any(gabungan_jawaban_per_soal.values()) and len(daftar_soal) > 1:
            messages.warning(request, "OCR berhasil membaca teks, tetapi sistem belum menemukan penanda nomor soal. Pastikan jawaban ditulis dengan format 1., 2., 3., dan seterusnya.")

        for soal in daftar_soal:
            JawabanUjian.objects.create(
                dokumen=dokumen,
                soal=soal,
                teks_ocr_mentah=teks_hasil_ocr,
                teks_ocr_final=gabungan_jawaban_per_soal.get(soal.nomor_soal, ''),
            )

        catat_aktivitas(
            request,
            'Scan OCR',
            f"{pelajar.nim} - {sesi.nama_ujian}",
            f"Upload {len(image_pages)} jepretan live dan OCR untuk {pelajar.nama_pelajar} pada sesi {sesi.nama_ujian}."
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
        if request.POST.get('action') == 'rerun_ocr':
            try:
                teks_hasil_ocr = ekstrak_teks_dari_gambar(dokumen.file_gambar.path)
                daftar_soal = [jawaban.soal for jawaban in jawaban_list]
                jawaban_per_soal = pisahkan_jawaban_per_soal(teks_hasil_ocr, daftar_soal)
                for jawaban in jawaban_list:
                    teks_jawaban = jawaban_per_soal.get(jawaban.soal.nomor_soal, '')
                    jawaban.teks_ocr_mentah = teks_hasil_ocr
                    jawaban.teks_ocr_final = teks_jawaban
                    jawaban.save(update_fields=['teks_ocr_mentah', 'teks_ocr_final'])

                if teks_hasil_ocr.strip():
                    messages.success(request, "OCR ulang berhasil membaca teks dari gambar.")
                    if not any(jawaban_per_soal.values()) and len(daftar_soal) > 1:
                        messages.warning(request, "OCR ulang membaca teks, tetapi belum menemukan penanda nomor soal. Gunakan format 1., 2., 3., dan seterusnya pada lembar jawaban.")
                else:
                    messages.warning(request, "OCR ulang berjalan, tetapi tidak menemukan teks pada gambar.")
                catat_aktivitas(
                    request,
                    'OCR Ulang',
                    f"{dokumen.pelajar.nim} - {dokumen.sesi_ujian.nama_ujian}",
                    f"OCR ulang dijalankan untuk {dokumen.pelajar.nama_pelajar} pada sesi {dokumen.sesi_ujian.nama_ujian}."
                )
            except Exception as e:
                messages.error(request, f"OCR ulang gagal: {str(e)}")

            return redirect('review_jawaban', dokumen_id=dokumen.id)

        # Logika untuk menyimpan perubahan teks (typo) dari dosen 
        for jawaban in jawaban_list:
            teks_baru = request.POST.get(f'jawaban_{jawaban.id}', '')
            
            # Update teks final yang siap dinilai oleh AI
            jawaban.teks_ocr_final = teks_baru.strip()
            jawaban.save(update_fields=['teks_ocr_final'])
            nilai_jawaban_otomatis(jawaban)
                
        messages.success(request, f"Sukses: Jawaban {dokumen.pelajar.nama_pelajar} telah dinilai secara otomatis.")
        catat_aktivitas(
            request,
            'Review & Nilai Jawaban',
            f"{dokumen.pelajar.nim} - {dokumen.sesi_ujian.nama_ujian}",
            f"Jawaban {dokumen.pelajar.nama_pelajar} direview dan dinilai otomatis."
        )
        return redirect('lihat_hasil_ujian', sesi_id=dokumen.sesi_ujian.id)
      
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
        
    # Ambil hanya scan terbaru per siswa agar hasil tidak numpuk jika siswa discan ulang.
    semua_dokumen = sesi.dokumen_terkumpul.select_related('pelajar').prefetch_related(
        'jawaban_detail__soal__parameter_jawaban'
    ).order_by('pelajar_id', '-tanggal_unggah')
    dokumen_terbaru_per_pelajar = {}
    for dokumen in semua_dokumen:
        dokumen_terbaru_per_pelajar.setdefault(dokumen.pelajar_id, dokumen)

    dokumen_terkumpul = sorted(
        dokumen_terbaru_per_pelajar.values(),
        key=lambda dokumen: dokumen.pelajar.nim
    )
    
    # Logika Form POST untuk menyimpan nilai Override dari dosen
    if request.method == 'POST':
        if request.POST.get('action') == 'score_all':
            total_dinilai = 0
            for dokumen in dokumen_terkumpul:
                for jawaban in dokumen.jawaban_detail.all():
                    nilai_jawaban_otomatis(jawaban)
                    total_dinilai += 1

            messages.success(request, f"Penilaian AI selesai untuk {total_dinilai} jawaban.")
            catat_aktivitas(
                request,
                'Penilaian AI Massal',
                sesi.nama_ujian,
                f"Penilaian AI dijalankan untuk {total_dinilai} jawaban pada sesi {sesi.nama_ujian}."
            )
            return redirect('lihat_hasil_ujian', sesi_id=sesi.id)

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
        catat_aktivitas(
            request,
            'Update Nilai Manual',
            sesi.nama_ujian,
            f"Penyesuaian nilai manual disimpan untuk sesi {sesi.nama_ujian}."
        )
        return redirect('lihat_hasil_ujian', sesi_id=sesi.id)

    for dokumen in dokumen_terkumpul:
        jawaban_doc = list(dokumen.jawaban_detail.all())
        for jawaban in jawaban_doc:
            if jawaban.skor_akhir is None:
                nilai_jawaban_otomatis(jawaban)
        dokumen.skor_ai_total = sum((jawaban.skor_ai or 0) for jawaban in jawaban_doc)
        dokumen.skor_akhir_total = sum((jawaban.skor_akhir or 0) for jawaban in jawaban_doc)
        dokumen.sudah_dinilai = bool(jawaban_doc) and all(jawaban.skor_akhir is not None for jawaban in jawaban_doc)

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
    semua_dokumen = sesi.dokumen_terkumpul.select_related('pelajar').prefetch_related('jawaban_detail').order_by('pelajar_id', '-tanggal_unggah')
    dokumen_terbaru_per_pelajar = {}
    for dokumen in semua_dokumen:
        dokumen_terbaru_per_pelajar.setdefault(dokumen.pelajar_id, dokumen)

    dokumen_terkumpul = sorted(
        dokumen_terbaru_per_pelajar.values(),
        key=lambda dokumen: dokumen.pelajar.nim
    )
    
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
    catat_aktivitas(
        request,
        'Export Nilai',
        sesi.nama_ujian,
        f"Rekap nilai sesi {sesi.nama_ujian} diunduh ke Excel."
    )
    return response

@login_required
def manajemen_mahasiswa(request):
    if getattr(request.user, 'role', '') != 'ADMIN':
        messages.error(request, "Akses ilegal ditolak oleh sistem.")
        return redirect('pengajar_dashboard')

    if request.method == 'POST':
        action = request.POST.get('action', 'create_pelajar')
        nim = request.POST.get('nim', '').strip()
        nama = request.POST.get('nama_pelajar', '').strip()

        if action == 'update_pelajar':
            pelajar = get_object_or_404(Pelajar, id=request.POST.get('pelajar_id'))
            if not nim or not nama:
                messages.error(request, "NIM dan nama mahasiswa wajib diisi.")
            elif Pelajar.objects.exclude(id=pelajar.id).filter(nim=nim).exists():
                messages.error(request, f"Gagal: Mahasiswa dengan NIM {nim} sudah ada di pangkalan data.")
            else:
                pelajar.nim = nim
                pelajar.nama_pelajar = nama
                pelajar.save(update_fields=['nim', 'nama_pelajar'])
                catat_aktivitas(
                    request,
                    'Update Mahasiswa',
                    nim,
                    f"Data mahasiswa {nama} ({nim}) diperbarui."
                )
                messages.success(request, f"Data mahasiswa {nama} berhasil diperbarui.")
                return redirect('manajemen_mahasiswa')

        elif action == 'delete_pelajar':
            pelajar = get_object_or_404(Pelajar, id=request.POST.get('pelajar_id'))
            nama_pelajar = pelajar.nama_pelajar
            nim = pelajar.nim
            pelajar.delete()
            catat_aktivitas(
                request,
                'Hapus Mahasiswa',
                nim,
                f"Data mahasiswa {nama_pelajar} ({nim}) dihapus."
            )
            messages.success(request, f"Data mahasiswa {nama_pelajar} berhasil dihapus.")
            return redirect('manajemen_mahasiswa')

        elif nim and nama:
            if Pelajar.objects.filter(nim=nim).exists():
                messages.error(request, f"Gagal: Mahasiswa dengan NIM {nim} sudah ada di pangkalan data.")
            else:
                # Simpan data mahasiswa baru ke PostgreSQL
                Pelajar.objects.create(nim=nim, nama_pelajar=nama)
                catat_aktivitas(
                    request,
                    'Tambah Mahasiswa',
                    nim,
                    f"Mahasiswa {nama} ({nim}) ditambahkan."
                )
                messages.success(request, f"Sukses: Mahasiswa bernama {nama} ({nim}) berhasil didaftarkan.")
                return redirect('manajemen_mahasiswa')
        else:
            messages.error(request, "NIM dan nama mahasiswa wajib diisi.")

    # Logika menampilkan data (GET): Ambil semua data mahasiswa, urutkan berdasarkan NIM terbaru
    daftar_mahasiswa = Pelajar.objects.all().order_by('-id')

    context = {
        'daftar_mahasiswa': daftar_mahasiswa,
    }
    return render(request, 'core/manajemen_mahasiswa.html', context)

@login_required
def manajemen_mata_kuliah(request):
    if getattr(request.user, 'role', '') != 'ADMIN':
        messages.error(request, "Akses ilegal ditolak oleh sistem.")
        return redirect('pengajar_dashboard')

    if request.method == 'POST':
        action = request.POST.get('action', 'create_mata_kuliah')

        if action in ['create_mata_kuliah', 'update_mata_kuliah']:
            mata_kuliah = None
            if action == 'update_mata_kuliah':
                mata_kuliah = get_object_or_404(MataKuliah, id=request.POST.get('mata_kuliah_id'))

            kode_mk = request.POST.get('kode_mk', '').strip().upper()
            nama_mk = request.POST.get('nama_mk', '').strip()
            sks = request.POST.get('sks', '').strip()
            if not kode_mk or not nama_mk or not sks:
                messages.error(request, "Kode, nama mata kuliah, dan SKS wajib diisi.")
            elif MataKuliah.objects.exclude(id=getattr(mata_kuliah, 'id', None)).filter(kode_mk=kode_mk).exists():
                messages.error(request, f"Kode mata kuliah {kode_mk} sudah digunakan.")
            else:
                try:
                    sks_int = int(sks)
                    if sks_int <= 0:
                        raise ValueError
                except ValueError:
                    messages.error(request, "SKS harus berupa angka positif.")
                else:
                    if mata_kuliah:
                        mata_kuliah.kode_mk = kode_mk
                        mata_kuliah.nama_mk = nama_mk
                        mata_kuliah.sks = sks_int
                        mata_kuliah.save(update_fields=['kode_mk', 'nama_mk', 'sks'])
                        log_action = 'Update Mata Kuliah'
                        pesan = f"Mata kuliah {kode_mk} berhasil diperbarui."
                    else:
                        mata_kuliah = MataKuliah.objects.create(kode_mk=kode_mk, nama_mk=nama_mk, sks=sks_int)
                        log_action = 'Tambah Mata Kuliah'
                        pesan = f"Mata kuliah {kode_mk} berhasil ditambahkan."
                    catat_aktivitas(
                        request,
                        log_action,
                        kode_mk,
                        f"Mata kuliah {kode_mk} - {nama_mk} disimpan."
                    )
                    messages.success(request, pesan)
                    return redirect('manajemen_mata_kuliah')

            return redirect('manajemen_mata_kuliah')

        if action == 'delete_mata_kuliah':
            mata_kuliah = get_object_or_404(MataKuliah, id=request.POST.get('mata_kuliah_id'))
            kode_mk = mata_kuliah.kode_mk
            nama_mk = mata_kuliah.nama_mk
            mata_kuliah.delete()
            catat_aktivitas(
                request,
                'Hapus Mata Kuliah',
                kode_mk,
                f"Mata kuliah {kode_mk} - {nama_mk} beserta data terkait dihapus."
            )
            messages.success(request, f"Mata kuliah {kode_mk} beserta kelas dan sesi terkait berhasil dihapus.")
            return redirect('manajemen_mata_kuliah')

    daftar_mata_kuliah = MataKuliah.objects.order_by('kode_mk')
    return render(request, 'core/manajemen_mata_kuliah.html', {'daftar_mata_kuliah': daftar_mata_kuliah})


@login_required
def manajemen_sesi_ujian(request):
    if getattr(request.user, 'role', '') != 'ADMIN':
        messages.error(request, "Akses ilegal ditolak oleh sistem.")
        return redirect('pengajar_dashboard')

    if request.method == 'POST':
        action = request.POST.get('action', 'create_sesi_setup')

        if action == 'update_kelas':
            kelas = get_object_or_404(Kelas, id=request.POST.get('kelas_id'))
            nama_kelas = request.POST.get('nama_kelas', '').strip().upper()
            pengajar_ids = request.POST.getlist('pengajar_ids')
            pelajar_ids = request.POST.getlist('pelajar_ids')

            if not nama_kelas:
                messages.error(request, "Kode kelas wajib diisi.")
            elif not pengajar_ids:
                messages.error(request, "Pilih minimal satu pengajar pemeriksa.")
            elif not pelajar_ids:
                messages.error(request, "Pilih minimal satu mahasiswa untuk kelas ini.")
            else:
                kelas.nama_kelas = nama_kelas
                kelas.save(update_fields=['nama_kelas'])
                kelas.pengajar.set(CustomUser.objects.filter(id__in=pengajar_ids, role='PENGAJAR'))
                kelas.daftar_pelajar.set(Pelajar.objects.filter(id__in=pelajar_ids))
                catat_aktivitas(
                    request,
                    'Update Kelas',
                    f"{kelas.mata_kuliah.kode_mk} - {nama_kelas}",
                    f"Kelas {nama_kelas} untuk {kelas.mata_kuliah.kode_mk} diperbarui beserta assign pengajar/mahasiswa."
                )
                messages.success(request, f"Kelas {nama_kelas} berhasil diperbarui.")
            return redirect('manajemen_sesi_ujian')

        if action == 'update_sesi':
            sesi = get_object_or_404(SesiUjian.objects.prefetch_related('daftar_soal__parameter_jawaban'), id=request.POST.get('sesi_id'))
            nama_ujian = request.POST.get('nama_ujian', '').strip()
            tanggal_ujian_raw = request.POST.get('tanggal_ujian', '').strip()
            tanggal_ujian = parse_datetime(tanggal_ujian_raw)

            if not nama_ujian or not tanggal_ujian_raw:
                messages.error(request, "Nama ujian dan tanggal ujian wajib diisi.")
                return redirect('manajemen_sesi_ujian')
            if not tanggal_ujian:
                messages.error(request, "Format tanggal ujian tidak valid.")
                return redirect('manajemen_sesi_ujian')

            if timezone.is_naive(tanggal_ujian):
                tanggal_ujian = timezone.make_aware(tanggal_ujian, timezone.get_current_timezone())

            sesi.nama_ujian = nama_ujian
            sesi.tanggal_ujian = tanggal_ujian
            sesi.save(update_fields=['nama_ujian', 'tanggal_ujian'])

            for soal in sesi.daftar_soal.all():
                pertanyaan = request.POST.get(f'soal_pertanyaan_{soal.id}', '').strip()
                bobot = request.POST.get(f'soal_bobot_{soal.id}', '').strip()
                rubrik = request.POST.get(f'soal_rubrik_{soal.id}', '').strip()
                if not pertanyaan or not bobot:
                    continue
                try:
                    bobot_float = float(bobot)
                except ValueError:
                    messages.error(request, f"Bobot soal nomor {soal.nomor_soal} harus berupa angka.")
                    return redirect('manajemen_sesi_ujian')

                soal.pertanyaan = pertanyaan
                soal.bobot_maksimal = bobot_float
                soal.save(update_fields=['pertanyaan', 'bobot_maksimal'])
                soal.parameter_jawaban.all().delete()
                if rubrik:
                    ParameterRubrik.objects.create(
                        soal=soal,
                        deskripsi_jawaban=rubrik,
                        bobot_parameter=bobot_float
                    )

            messages.success(request, f"Sesi {nama_ujian} berhasil diperbarui.")
            catat_aktivitas(
                request,
                'Update Sesi Ujian',
                nama_ujian,
                f"Sesi ujian {nama_ujian} untuk kelas {sesi.kelas.nama_kelas} diperbarui."
            )
            return redirect('manajemen_sesi_ujian')

        if action == 'delete_sesi':
            sesi = get_object_or_404(SesiUjian, id=request.POST.get('sesi_id'))
            nama_ujian = sesi.nama_ujian
            nama_kelas = sesi.kelas.nama_kelas
            sesi.delete()
            catat_aktivitas(
                request,
                'Hapus Sesi Ujian',
                nama_ujian,
                f"Sesi ujian {nama_ujian} untuk kelas {nama_kelas} dihapus."
            )
            messages.success(request, f"Sesi ujian {nama_ujian} berhasil dihapus.")
            return redirect('manajemen_sesi_ujian')

        mata_kuliah_id = request.POST.get('mata_kuliah_id')
        mata_kuliah = get_object_or_404(MataKuliah, id=mata_kuliah_id) if mata_kuliah_id else None
        nama_kelas = request.POST.get('nama_kelas', '').strip().upper()
        jumlah_mahasiswa = request.POST.get('jumlah_mahasiswa', '').strip()
        nama_ujian = request.POST.get('nama_ujian', '').strip()
        tanggal_ujian_raw = request.POST.get('tanggal_ujian', '').strip()
        pengajar_ids = request.POST.getlist('pengajar_ids')
        pelajar_ids = request.POST.getlist('pelajar_ids')
        pertanyaan_list = request.POST.getlist('soal_pertanyaan[]')
        bobot_list = request.POST.getlist('soal_bobot[]')
        rubrik_list = request.POST.getlist('soal_rubrik[]')

        tanggal_ujian = parse_datetime(tanggal_ujian_raw)
        daftar_soal = [
            (pertanyaan.strip(), bobot.strip(), rubrik.strip())
            for pertanyaan, bobot, rubrik in zip(pertanyaan_list, bobot_list, rubrik_list)
            if pertanyaan.strip() and bobot.strip()
        ]

        if not all([mata_kuliah, nama_kelas, nama_ujian, tanggal_ujian_raw]):
            messages.error(request, "Mata kuliah, kelas, dan sesi ujian wajib diisi.")
        elif not tanggal_ujian:
            messages.error(request, "Format tanggal ujian tidak valid.")
        elif not pengajar_ids:
            messages.error(request, "Pilih minimal satu pengajar pemeriksa.")
        elif not pelajar_ids:
            messages.error(request, "Pilih minimal satu mahasiswa untuk kelas ini.")
        elif not daftar_soal:
            messages.error(request, "Isi minimal satu soal untuk sesi ujian.")
        else:
            try:
                jumlah_mahasiswa_int = int(jumlah_mahasiswa) if jumlah_mahasiswa else len(pelajar_ids)
                if jumlah_mahasiswa_int <= 0:
                    raise ValueError
            except ValueError:
                messages.error(request, "Jumlah mahasiswa harus berupa angka positif.")
            else:
                if jumlah_mahasiswa_int != len(pelajar_ids):
                    messages.error(request, "Jumlah mahasiswa harus sama dengan mahasiswa yang dipilih.")
                else:
                    try:
                        with transaction.atomic():
                            kelas, created = Kelas.objects.get_or_create(
                                mata_kuliah=mata_kuliah,
                                nama_kelas=nama_kelas
                            )
                            kelas.pengajar.set(CustomUser.objects.filter(id__in=pengajar_ids, role='PENGAJAR'))
                            kelas.daftar_pelajar.set(Pelajar.objects.filter(id__in=pelajar_ids))

                            if timezone.is_naive(tanggal_ujian):
                                tanggal_ujian = timezone.make_aware(tanggal_ujian, timezone.get_current_timezone())

                            sesi = SesiUjian.objects.create(
                                kelas=kelas,
                                nama_ujian=nama_ujian,
                                tanggal_ujian=tanggal_ujian,
                            )

                            for nomor, (pertanyaan, bobot, rubrik) in enumerate(daftar_soal, start=1):
                                soal = Soal.objects.create(
                                    sesi_ujian=sesi,
                                    nomor_soal=nomor,
                                    pertanyaan=pertanyaan,
                                    bobot_maksimal=float(bobot)
                                )
                                if rubrik:
                                    ParameterRubrik.objects.create(
                                        soal=soal,
                                        deskripsi_jawaban=rubrik,
                                        bobot_parameter=float(bobot)
                                    )

                        status_kelas = "dibuat" if created else "diperbarui"
                        catat_aktivitas(
                            request,
                            'Setup Akademik',
                            f"{mata_kuliah.kode_mk} - {nama_kelas}",
                            f"Sesi {nama_ujian} untuk {mata_kuliah.kode_mk} kelas {nama_kelas} dengan {len(daftar_soal)} soal disimpan."
                        )
                        messages.success(request, f"Sesi ujian {nama_ujian} berhasil disimpan. Kelas {status_kelas}.")
                        return redirect('manajemen_sesi_ujian')
                    except ValueError:
                        messages.error(request, "Bobot soal harus berupa angka.")

    daftar_mata_kuliah = MataKuliah.objects.prefetch_related(
        'daftar_kelas__pengajar',
        'daftar_kelas__daftar_pelajar',
        'daftar_kelas__sesi_ujian__daftar_soal',
    ).order_by('kode_mk')
    context = {
        'daftar_mata_kuliah': daftar_mata_kuliah,
        'daftar_pengajar': CustomUser.objects.filter(role='PENGAJAR', is_active=True).order_by('username'),
        'daftar_mahasiswa': Pelajar.objects.all().order_by('nim'),
    }
    return render(request, 'core/manajemen_sesi_ujian.html', context)

@login_required
def manajemen_pengajar(request):
    if getattr(request.user, 'role', '') != 'ADMIN':
        messages.error(request, "Akses ilegal ditolak oleh sistem.")
        return redirect('pengajar_dashboard')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_user':
            username = request.POST.get('username', '').strip()
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()
            role = request.POST.get('role', 'PENGAJAR')
            create_login = request.POST.get('create_login') == 'on'
            password = request.POST.get('password', '')
            password_confirm = request.POST.get('password_confirm', '')

            if role not in dict(CustomUser.ROLE_CHOICES):
                messages.error(request, "Role akun tidak valid.")
            elif not username:
                messages.error(request, "Kode/username pengajar wajib diisi.")
            elif create_login and not password:
                messages.error(request, "Password wajib diisi jika akses login dibuat.")
            elif create_login and password != password_confirm:
                messages.error(request, "Konfirmasi password tidak sama.")
            elif CustomUser.objects.filter(username=username).exists():
                messages.error(request, f"Username {username} sudah digunakan.")
            else:
                user = CustomUser.objects.create_user(
                    username=username,
                    password=password if create_login else None,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    role=role,
                    is_staff=(role == 'ADMIN'),
                    is_superuser=False,
                )
                if not create_login:
                    user.set_unusable_password()
                    user.save(update_fields=['password'])

                akses = "dengan akses login" if create_login else "tanpa akses login"
                catat_aktivitas(
                    request,
                    'Tambah Akun/Pengajar',
                    username,
                    f"{username} dibuat sebagai {role} {akses}."
                )
                messages.success(request, f"Data {username} berhasil dibuat sebagai {role} {akses}.")
                return redirect('manajemen_pengajar')

        elif action == 'update_role':
            user_id = request.POST.get('user_id')
            role = request.POST.get('role')
            user = get_object_or_404(CustomUser, id=user_id)

            if role not in dict(CustomUser.ROLE_CHOICES):
                messages.error(request, "Role akun tidak valid.")
            elif user.id == request.user.id and role != 'ADMIN':
                messages.error(request, "Anda tidak bisa menurunkan role akun admin yang sedang dipakai.")
            else:
                user.role = role
                user.is_staff = role == 'ADMIN'
                user.save(update_fields=['role', 'is_staff'])
                catat_aktivitas(
                    request,
                    'Update Role Akun',
                    user.username,
                    f"Role {user.username} diubah menjadi {role}."
                )
                messages.success(request, f"Role {user.username} berhasil diubah menjadi {role}.")
                return redirect('manajemen_pengajar')

        elif action == 'update_credentials':
            user_id = request.POST.get('user_id')
            user = get_object_or_404(CustomUser, id=user_id)
            username = request.POST.get('username', '').strip()
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()
            password = request.POST.get('password', '')

            if not username:
                messages.error(request, "Username tidak boleh kosong.")
            elif CustomUser.objects.exclude(id=user.id).filter(username=username).exists():
                messages.error(request, f"Username {username} sudah digunakan akun lain.")
            else:
                user.username = username
                user.first_name = first_name
                user.last_name = last_name
                user.email = email
                update_fields = ['username', 'first_name', 'last_name', 'email']

                if password:
                    user.set_password(password)
                    update_fields.append('password')

                user.save(update_fields=update_fields)
                catat_aktivitas(
                    request,
                    'Update Kredensial Akun',
                    user.username,
                    f"Kredensial akun {user.username} diperbarui."
                )
                messages.success(request, f"Kredensial akun {user.username} berhasil diperbarui.")
                return redirect('manajemen_pengajar')

        elif action == 'update_account':
            user_id = request.POST.get('user_id')
            user = get_object_or_404(CustomUser, id=user_id)
            username = request.POST.get('username', '').strip()
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()
            role = request.POST.get('role')
            password = request.POST.get('password', '')
            create_login = request.POST.get('create_login') == 'on'

            if not username:
                messages.error(request, "Username tidak boleh kosong.")
            elif role not in dict(CustomUser.ROLE_CHOICES):
                messages.error(request, "Role akun tidak valid.")
            elif CustomUser.objects.exclude(id=user.id).filter(username=username).exists():
                messages.error(request, f"Username {username} sudah digunakan akun lain.")
            elif user.id == request.user.id and role != 'ADMIN':
                messages.error(request, "Anda tidak bisa menurunkan role akun admin yang sedang dipakai.")
            elif not user.has_usable_password() and create_login and not password:
                messages.error(request, "Isi password untuk membuat akses login pengajar.")
            else:
                user.username = username
                user.first_name = first_name
                user.last_name = last_name
                user.email = email
                user.role = role
                user.is_staff = role == 'ADMIN'
                update_fields = ['username', 'first_name', 'last_name', 'email', 'role', 'is_staff']

                if password:
                    user.set_password(password)
                    update_fields.append('password')

                user.save(update_fields=update_fields)
                catat_aktivitas(
                    request,
                    'Update Akun/Pengajar',
                    user.username,
                    f"Akun/data pengajar {user.username} diperbarui."
                )
                messages.success(request, f"Akun {user.username} berhasil diperbarui.")
                return redirect('manajemen_pengajar')

        elif action == 'toggle_active':
            user_id = request.POST.get('user_id')
            user = get_object_or_404(CustomUser, id=user_id)

            if user.id == request.user.id:
                messages.error(request, "Anda tidak bisa menonaktifkan akun yang sedang dipakai.")
            else:
                user.is_active = not user.is_active
                user.save(update_fields=['is_active'])
                status = "diaktifkan" if user.is_active else "dinonaktifkan"
                catat_aktivitas(
                    request,
                    'Ubah Status Akun',
                    user.username,
                    f"Akun {user.username} {status}."
                )
                messages.success(request, f"Akun {user.username} berhasil {status}.")
                return redirect('manajemen_pengajar')

        elif action == 'delete_account':
            user_id = request.POST.get('user_id')
            user = get_object_or_404(CustomUser, id=user_id)

            if user.id == request.user.id:
                messages.error(request, "Anda tidak bisa menghapus akun yang sedang dipakai.")
            else:
                username = user.username
                user.delete()
                catat_aktivitas(
                    request,
                    'Hapus Akun/Pengajar',
                    username,
                    f"Akun/data pengajar {username} dihapus."
                )
                messages.success(request, f"Akun/data pengajar {username} berhasil dihapus.")
                return redirect('manajemen_pengajar')

        elif action == 'reset_password_request':
            request_id = request.POST.get('request_id')
            reset_request = get_object_or_404(
                PasswordResetRequest.objects.select_related('user'),
                id=request_id,
                status='PENDING'
            )

            reset_request.user.set_password(DEFAULT_RESET_PASSWORD)
            reset_request.user.save(update_fields=['password'])
            reset_request.status = 'RESOLVED'
            reset_request.resolved_at = timezone.now()
            reset_request.resolved_by = request.user
            reset_request.save(update_fields=['status', 'resolved_at', 'resolved_by'])
            catat_aktivitas(
                request,
                'Reset Password',
                reset_request.user.username,
                f"Password {reset_request.user.username} direset ke default."
            )
            messages.success(
                request,
                f"Password {reset_request.user.username} berhasil direset ke {DEFAULT_RESET_PASSWORD}."
            )
            return redirect('manajemen_pengajar')

    daftar_akun = CustomUser.objects.exclude(
        role='PENGAJAR',
        password__startswith='!'
    ).order_by('role', 'username')
    daftar_pengajar = CustomUser.objects.filter(role='PENGAJAR').order_by('username')
    pending_reset_requests = PasswordResetRequest.objects.select_related('user').filter(status='PENDING')
    context = {
        'daftar_akun': daftar_akun,
        'daftar_pengajar': daftar_pengajar,
        'role_choices': CustomUser.ROLE_CHOICES,
        'pending_reset_requests': pending_reset_requests,
        'default_reset_password': DEFAULT_RESET_PASSWORD,
    }
    return render(request, 'core/manajemen_akun.html', context)

@login_required
def log_aktivitas(request):
    if getattr(request.user, 'role', '') != 'ADMIN':
        messages.error(request, "Akses ilegal ditolak oleh sistem.")
        return redirect('pengajar_dashboard')

    list_data = [
        {
            'kolom_1': timezone.localtime(log.created_at).strftime('%d %b %Y %H:%M'),
            'kolom_2': log.user.username if log.user else 'Sistem',
            'kolom_3': f"{log.action} - {log.description}",
        }
        for log in ActivityLog.objects.select_related('user').all()[:100]
    ]
    return render(request, 'core/admin_data_list.html', {
        'judul': 'Log Aktivitas',
        'deskripsi': 'Aktivitas terbaru yang tercatat dari panel administrasi.',
        'ikon': 'fa-clipboard-list',
        'header': ['Waktu', 'User', 'Aktivitas'],
        'list_data': list_data,
    })
