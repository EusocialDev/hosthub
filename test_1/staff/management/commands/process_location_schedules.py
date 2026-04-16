from django.core.management.base import BaseCommand
from staff.services.location_hours import process_due_location_schedules, reconcile_location_bland_state

class Command(BaseCommand):
    help = "Processes location schedule transition and syncs Bland Pathways"

    def handle(self, *args, **options):
        process_due_location_schedules()
        reconcile_location_bland_state()
        self.stdout.write(self.style.SUCCESS("Successfully processed location schedules."))