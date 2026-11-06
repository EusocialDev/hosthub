from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("owner_agent", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="owneragentassessment",
            name="reason",
            field=models.CharField(
                choices=[
                    ("hosthub_handled", "Handled in HostHub"),
                    ("silent_call", "No meaningful customer conversation"),
                    ("past_reservation", "Reservation date has passed"),
                    ("future_reservation", "Future reservation is unhandled"),
                    ("past_commitment", "Commitment date has passed"),
                    ("future_commitment", "Future commitment is unhandled"),
                    ("future_callback", "Future callback or commitment"),
                    ("insufficient_information", "Insufficient information"),
                ],
                max_length=40,
            ),
        ),
    ]
