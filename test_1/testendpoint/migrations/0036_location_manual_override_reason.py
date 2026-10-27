from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("testendpoint", "0035_call_recovery_sms_sent_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="location",
            name="manual_override_reason",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
