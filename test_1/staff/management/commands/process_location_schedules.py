from django.core.management.base import BaseCommand
from staff.services.location_hours import process_due_location_schedules

class Command(BaseCommand):
    help = "Processes location schedule transition and syncs Bland Pathways"

    def handle(self, *args, **options):
        process_due_location_schedules()
        self.stdout.write(self.style.SUCCESS("Successfully processed location schedules."))