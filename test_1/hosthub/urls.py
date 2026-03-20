from django.contrib import admin
from django.urls import path
from . import views

app_name = 'hosthub'

urlpatterns =[
    path("", views.hosthub_view, name='hosthub_dashboard'),
    path("calls/<int:call_id>/mark-handled/", views.mark_call_handled, name='mark_call_handled'),
    path("api/check-new-calls/", views.check_new_calls, name='hosthub_check_new_calls'),
    path("api/new-calls-boolean/", views.new_calls_for_pill, name='hosthub_new_calls_for_pill'),
    path("api/bland/live-calls/", views.bland_live_calls, name='hosthub_bland_live_calls'),
    path("api/bland/transfer-call/", views.bland_transfer_call, name="bland_transfer_call"),
    
]