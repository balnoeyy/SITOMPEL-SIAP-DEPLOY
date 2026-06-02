from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy

class SitompelLoginView(LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return reverse_lazy('admin_dashboard') 
        elif user.role == 'PENGAJAR':
            return reverse_lazy('pengajar_dashboard') 
        
        return reverse_lazy('home')