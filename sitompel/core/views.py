from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden

# Decorator ini memastikan hanya user yang sudah login yang bisa mengakses halaman ini
@login_required
def pengajar_dashboard(request):
    # Validasi role: Cegah Admin atau role lain masuk ke dashboard pengajar
    if request.user.role != 'PENGAJAR':
        return HttpResponseForbidden("Akses ditolak. Anda bukan pengajar.")
    
    # Render template dengan membawa context data jika diperlukan nanti
    return render(request, 'core/pengajar_dashboard.html')

@login_required
def admin_dashboard(request):
    # Validasi role: Cegah Pengajar masuk ke dashboard admin
    if request.user.role != 'ADMIN':
        return HttpResponseForbidden("Akses ditolak. Anda bukan administrator.")
    
    # Sementara kita pakai template dummy atau langsung pass ke HTML sederhana
    return render(request, 'core/admin_dashboard.html')