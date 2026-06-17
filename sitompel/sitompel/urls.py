from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from core.views import landing_page

urlpatterns = [
    path('', landing_page, name='home'),

    path('admin/', admin.site.urls),
    path('auth/', include('accounts.urls')),
    path('dashboard/', include('core.urls')), 
]

# Wajib ditambahkan agar gambar dari folder media bisa dirender di HTML saat tahap development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
