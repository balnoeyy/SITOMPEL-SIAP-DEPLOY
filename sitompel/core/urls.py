from django.urls import path
from . import views

urlpatterns = [
    path('pengajar/', views.pengajar_dashboard, name='pengajar_dashboard'),
    path('admin/', views.admin_dashboard, name='admin_dashboard'),
]