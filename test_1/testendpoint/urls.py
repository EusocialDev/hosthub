from django.contrib import admin
from django.urls import path, include
from testendpoint import views, views_live
from .views_sse import sse_call_stream
from .views_live import get_transcript_turns


app_name = 'testendpoint'

urlpatterns = [
    path("login/", views.account_login_view, name="account_login"),
    path(
        "login/<slug:account_slug>/locations",
        views.location_picker_view,
        name='location_picker',
    ),

    path(
        "login/<slug:account_slug>/<slug:location_slug>",
        views.worker_login,
        name='location_login'
    ),
    path("logout/", views.worker_logout_view, name='logout'),
    path("account-logout/", views.account_logout_view, name="account_logout"),
    path("api/calls/<str:call_id>/live-transcript/", views.live_transcript_view, name='live_transcript'),
    path("api/calls/live-data/", views.live_calls_data_view, name='live_calls_data'),

    path('webhooks/bland/calls/<str:token>/', views.bland_calls_webhook, name='bland_calls_webhook'),

    # live UI polling endpoints 
    path("live/alerts/", views_live.live_alerts_poll, name='live_alerts_pool'),
    path("live/alerts/<int:alert_id>/resolve/", views_live.resolve_alert, name="resolve_alert"),
    
    # Live transcript endpoints
    path("sse/call/<str:call_id>/", sse_call_stream, name="sse_call_stream"),
    path("api/calls/<str:call_id>/turns/", get_transcript_turns, name="get_transcript_turns"),

    # Final transcript endpoint
    path("transcript/call/<str:call_id>/", views.get_final_transcripts, name="final_transcript_view"),
]

 