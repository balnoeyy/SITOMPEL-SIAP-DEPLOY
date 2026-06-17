from django.urls import path
from . import views

urlpatterns = [
    path('pengajar/', views.pengajar_dashboard, name='pengajar_dashboard'),
    path('pengajar/kelas/', views.daftar_kelas, name='daftar_kelas'),
    path('pengajar/kelas/<uuid:kelas_id>/', views.detail_kelas, name='detail_kelas'),
    path('pengajar/arsip/', views.arsip_kelas, name='arsip_kelas'),
    path('pengajar/rubrik/<uuid:sesi_id>/', views.kelola_rubrik, name='kelola_rubrik'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),

    path('admin-dashboard/mahasiswa/', views.manajemen_mahasiswa, name='manajemen_mahasiswa'),
    path('admin-dashboard/mata-kuliah/', views.manajemen_mata_kuliah, name='manajemen_mata_kuliah'),
    path('admin-dashboard/sesi-ujian/', views.manajemen_sesi_ujian, name='manajemen_sesi_ujian'),
    path('admin-dashboard/pengajar/', views.manajemen_pengajar, name='manajemen_pengajar'),
    path('admin-dashboard/log-aktivitas/', views.log_aktivitas, name='log_aktivitas'),
    
    path('ujian/<uuid:sesi_id>/capture/', views.capture_lembar_ujian, name='capture_ujian'),
    
    path('api/upload-capture/<uuid:sesi_id>/', views.api_upload_capture, name='api_upload_capture'),

    path('ujian/review/<uuid:dokumen_id>/', views.review_jawaban, name='review_jawaban'),

    path('ujian/hasil/<uuid:sesi_id>/', views.lihat_hasil_ujian, name='lihat_hasil_ujian'),

    path('ujian/ekspor/<uuid:sesi_id>/', views.ekspor_nilai_excel, name='ekspor_nilai_excel'),
]
