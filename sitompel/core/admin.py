from django.contrib import admin
from .models import MataKuliah, Kelas, Pelajar, SesiUjian, Soal, ParameterRubrik, DokumenUjian, JawabanUjian


# Mendaftarkan model agar bisa dikelola langsung oleh Superuser/Admin
# admin.site.register(CustomUser)
admin.site.register(MataKuliah)
admin.site.register(Kelas)
admin.site.register(Pelajar)
admin.site.register(SesiUjian)
admin.site.register(Soal)
admin.site.register(ParameterRubrik)
admin.site.register(DokumenUjian)
admin.site.register(JawabanUjian)