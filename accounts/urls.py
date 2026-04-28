from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("magic/<str:token>/", views.magic_login, name="magic_login"),
    path("facilitators/new/", views.facilitator_new, name="facilitator_new"),
    path("facilitators/<uuid:pk>/", views.facilitator_detail, name="facilitator_detail"),
]
