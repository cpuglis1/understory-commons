from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("programs/<uuid:pk>/", views.program_detail, name="program_detail"),
    path("sessions/<uuid:pk>/", views.session_detail, name="session_detail"),
    path("sessions/<uuid:pk>/attendance/", views.record_attendance, name="record_attendance"),
    path("sessions/<uuid:pk>/participants/", views.participant_create, name="participant_create"),
]
