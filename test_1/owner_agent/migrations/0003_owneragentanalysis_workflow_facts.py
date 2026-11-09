from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("owner_agent", "0002_owneragentassessment_commitment_reasons"),
    ]

    operations = [
        migrations.AddField(
            model_name="owneragentanalysis",
            name="workflow",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="owneragentanalysis",
            name="booking_link_sent",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="owneragentanalysis",
            name="kitchen_share_completed",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="owneragentanalysis",
            name="details_shared_with_manager",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="owneragentanalysis",
            name="manager_review_required",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="owneragentanalysis",
            name="customer_waiting_confirmation",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
