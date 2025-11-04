# aqi/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("dashboard/", views.home, name="dashboard"),
    path("signup/", views.signup, name="signup"),
]
