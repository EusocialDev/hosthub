from django.template.loader import render_to_string
from django.conf import settings
import requests
from .reports import build_daily_call_report


def send_daily_call_report(report_date=None):
    report = build_daily_call_report(report_date)

    html_content = render_to_string(
        "testendpoint/emails/daily_call_report.html",
        report
    )
    subject = f"Daily Call Report - {report['report_date']}"

    recipient = settings.RECIPIENT_EMAIL
    if not recipient:
        raise ValueError("RECIPIENT_EMAIL is not set")
    
    api_key = settings.RESEND_API_KEY
    if not api_key:
        raise ValueError("RESEND_API_KEY not set")

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "from": "reports@160maincarryout.com",
            "to": [recipient],
            "subject": subject,
            "html" : html_content,
            "text": f"Daily call report for {report["report_date"]}"
        },
        timeout=15
    )

    print("Resend status:", response.status_code)
    print("Resend body:", response.text)

    response.raise_for_status()
    return response.status_code


    

    