from django.urls import path
from . import views

app_name = 'staff'

urlpatterns = [
    path('', views.worker_list_view, name='worker_list'),
    path("create/", views.worker_create_view, name="worker_create"),
    path("<int:access_id>/edit/", views.worker_edit_view, name="worker_edit"),
]