from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages

def login_view(request):
    if request.user.is_authenticated:
        if getattr(request.user, 'role', '') == 'PENGAJAR':
            return redirect('pengajar_dashboard') 
        else:
            return redirect('/admin/') 

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            
            if getattr(user, 'role', '') == 'PENGAJAR':
                return redirect('pengajar_dashboard')
            else:
                return redirect('admin_dashboard')
        else:
            messages.error(request, "Username atau password salah.")
    else:
        form = AuthenticationForm()

    return render(request, 'accounts/login.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('login')