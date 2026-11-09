from django.urls import path

from . import views


app_name = "owner_agent"

urlpatterns = [
    path(
        "gohighlevel/owner-agent/<str:token>/",
        views.owner_agent_inbound_webhook,
        name="owner_agent_inbound_webhook",
    ),
]
