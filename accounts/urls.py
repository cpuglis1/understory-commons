from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("magic/<str:token>/", views.magic_login, name="magic_login"),
]
