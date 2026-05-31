from django.urls import path

from . import views

app_name = "discovery"

urlpatterns = [
    path("<slug:slug>/", views.program_detail, name="program_detail"),
]
