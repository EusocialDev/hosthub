from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("owner_agent", "0003_owneragentanalysis_workflow_facts"),
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
                    ("booking_link_sent", "Booking link was sent"),
                    (
                        "carryout_shared_with_kitchen",
                        "Carryout details were shared with the kitchen",
                    ),
                    ("incomplete_carryout", "Carryout was not completed"),
                    ("insufficient_information", "Insufficient information"),
                ],
                max_length=40,
            ),
        ),
    ]
