# aqi/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("dashboard/", views.home, name="dashboard"),
    path("signup/", views.signup, name="signup"),
    path("become-admin/", views.become_admin, name="become-admin"),
    path("admin-panel/", views.admin_panel, name="admin-panel"),
    path("after-login/", views.after_login, name="after-login"),

]
