from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.home, name="home"),
    path("programs/", views.program_list, name="program_list"),
    path("programs/new/", views.program_new, name="program_new"),
    path("programs/<slug:slug>/", views.program_detail, name="program_detail"),
    path("programs/<slug:slug>/setup/", views.program_setup, name="program_setup"),
    path("programs/<slug:slug>/log/", views.attendance_log, name="attendance_log"),
    path(
        "programs/<slug:slug>/log/add/",
        views.session_add_participant,
        name="session_add_participant",
    ),
    path("programs/<slug:slug>/log/wrap/", views.session_wrap, name="session_wrap"),
    path("programs/<slug:slug>/preview/", views.program_preview, name="program_preview"),
    path("programs/<slug:slug>/publish/", views.program_publish, name="program_publish"),
]
