from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from core.models import PasswordResetRequest, ActivityLog
from .models import CustomUser


def catat_aktivitas_akun(user, action, target='', description=''):
    ActivityLog.objects.create(
        user=user,
        action=action,
        target=target[:180],
        description=description or target or action,
    )

def login_view(request):
    if request.user.is_authenticated:
        if getattr(request.user, 'role', '') == 'PENGAJAR':
            return redirect('pengajar_dashboard') 
        else:
            return redirect('admin_dashboard') 

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            catat_aktivitas_akun(
                user,
                'Login',
                user.username,
                f"{user.username} login ke sistem."
            )
            
            if getattr(user, 'role', '') == 'PENGAJAR':
                return redirect('pengajar_dashboard')
            else:
                return redirect('admin_dashboard')
        else:
            messages.error(request, "Username atau password salah.")
    else:
        form = AuthenticationForm()

    return render(request, 'accounts/login.html', {'form': form})

def forgot_password_view(request):
    if request.user.is_authenticated:
        if getattr(request.user, 'role', '') == 'PENGAJAR':
            return redirect('pengajar_dashboard')
        return redirect('admin_dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        user = CustomUser.objects.filter(username=username, role='PENGAJAR', is_active=True).first()

        if user:
            existing_request = PasswordResetRequest.objects.filter(user=user, status='PENDING').first()
            if existing_request:
                messages.success(request, "Permintaan reset password Anda sudah masuk dan menunggu admin.")
            else:
                PasswordResetRequest.objects.create(user=user)
                catat_aktivitas_akun(
                    user,
                    'Request Reset Password',
                    user.username,
                    f"{user.username} mengajukan reset password."
                )
                messages.success(request, "Permintaan reset password berhasil dikirim ke admin.")
            return redirect('login')

        messages.error(request, "Akun pengajar aktif dengan username tersebut tidak ditemukan.")

    return render(request, 'accounts/forgot_password.html')

def logout_view(request):
    if request.user.is_authenticated:
        catat_aktivitas_akun(
            request.user,
            'Logout',
            request.user.username,
            f"{request.user.username} logout dari sistem."
        )
    logout(request)
    return redirect('login')
