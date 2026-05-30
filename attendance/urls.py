from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.program_list, name="program_list"),
    path("new/", views.program_new, name="program_new"),
    path("<slug:slug>/", views.program_detail, name="program_detail"),
    path("<slug:slug>/preview/", views.program_preview, name="program_preview"),
    path("<slug:slug>/publish/", views.program_publish, name="program_publish"),
]
