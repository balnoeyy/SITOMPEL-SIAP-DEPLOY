from django.urls import path
from .views import SitompelLoginView

urlpatterns = [
    path('login/', SitompelLoginView.as_view(), name='login'),
]