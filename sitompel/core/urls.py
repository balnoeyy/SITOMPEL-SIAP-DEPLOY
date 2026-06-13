from django.urls import path
from . import views

urlpatterns = [
    path('pengajar/', views.pengajar_dashboard, name='pengajar_dashboard'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),

    path('admin-dashboard/mahasiswa/', views.manajemen_mahasiswa, name='manajemen_mahasiswa'),
    
    path('ujian/<uuid:sesi_id>/capture/', views.capture_lembar_ujian, name='capture_ujian'),
    
    path('api/upload-capture/<uuid:sesi_id>/', views.api_upload_capture, name='api_upload_capture'),

    path('ujian/review/<uuid:dokumen_id>/', views.review_jawaban, name='review_jawaban'),

    path('ujian/hasil/<uuid:sesi_id>/', views.lihat_hasil_ujian, name='lihat_hasil_ujian'),

    path('ujian/ekspor/<uuid:sesi_id>/', views.ekspor_nilai_excel, name='ekspor_nilai_excel'),
]