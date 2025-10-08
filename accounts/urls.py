from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('profile/', views.profile, name='profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('change-password/', views.change_password, name='change_password'),
    path('apporteurs/', views.liste_apporteurs, name='liste_apporteurs'),
    path('apporteurs/nouveau/', views.nouveau_apporteur, name='nouveau_apporteur'),
    path('apporteurs/<int:pk>/', views.detail_apporteur, name='detail_apporteur'),
]