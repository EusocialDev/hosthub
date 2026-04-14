from django.test import TestCase
from .views import accessible_calls_for_user
from django.contrib.auth import get_user_model

from testendpoint.models import Call, UserAccess, Account, Location

User = get_user_model()

class CallAccessTests(TestCase):
    def setUp(self):
        # Account and Location set up

        self.account = Account.objects.create(
            name="Restaurant Group A",
            slug="restaurant-group-a",
            is_active=True,
        )

        self.location_a = Location.objects.create(
            account = self.account,
            name='Downtown',

            slug='downtown',
            is_active=True,
        )

        self.location_b = Location.objects.create(
            account = self.account,
            name='Uptown',
            slug='uptown',
            is_active=True,
        )

        # Another account and location for isolation testing
        self.other_account = Account.objects.create(
            name="Restaurant Group B",
            slug="restaurant-group-b",
            is_active=True,
        )

        self.other_location = Location.objects.create(
            account = self.other_account,
            name='Suburb',
            slug='suburb',
            is_active=True,
        )

        # Host Users 

        self.host_user = User.objects.create_user(
            username = "host1",
            password = "test12345",
        )

        self.host_access = UserAccess.objects.create(
            user=self.host_user,
            account=self.account,
            role='host',
            pin_hash='1234',
            is_active=True,
        )

        self.host_access.locations.add(self.location_a)
        
        # second host with no locations

        self.no_location_user = User.objects.create_user(
            username="host2",
            password="test12345",
        )

        self.no_location_access = UserAccess.objects.create(
            user = self.no_location_user,
            account = self.account,
            role='host',
            pin_hash='5678',
            is_active=True,
        )

        # Manager User with access to both locations
        self.manager_user = User.objects.create_user(
            username="manager1",
            password="test12345",
        )

        self.manager_access = UserAccess.objects.create(
            user=self.manager_user,
            account=self.account,
            role='manager',
            pin_hash='4321',
            is_active=True,
        )

        self.manager_access.locations.add(self.location_a, self.location_b)

        # Calls the host should and should not see

        self.call_a = Call.objects.create(
            account = self.account,
            location=self.location_a,
            bland_call_id="call_001",
            from_number="+1234567890",
            to_number="+0987654321",
            display_category = 'reservation',
            host_status = 'needs_action',
        )

        self.call_b = Call.objects.create(
            account = self.account,
            location=self.location_b,
            bland_call_id="call_002",
            from_number="+1234567890",
            to_number="+0987654321",
            display_category='carryout',
            host_status='needs_action',
        )

        # Call from another tenant entirely
        self.other_account_call = Call.objects.create(
            account = self.other_account,
            location=self.other_location,
            bland_call_id="call_003",
            from_number="+1234567890",
            to_number="+0987654321",
            display_category='reservation',
            host_status='needs_action',
        )

    def test_host_only_sees_calls_from_assigned_location(self):
        calls = accessible_calls_for_user(self.host_user)

        self.assertIn(self.call_a, calls)
        self.assertNotIn(self.call_b, calls)
        self.assertNotIn(self.other_account_call, calls)
        self.assertEqual(calls.count(),1)

    def test_host_with_no_locations_sees_no_calls(self):
        calls = accessible_calls_for_user(self.no_location_user)

        self.assertEqual(calls.count(),0)


    def test_manager_sees_calls_from_all_locations(self):
        calls = accessible_calls_for_user(self.manager_user)

        self.assertIn(self.call_a, calls)
        self.assertIn(self.call_b, calls)
        self.assertNotIn(self.other_account_call, calls)
        self.assertEqual(calls.count(),2)

    def test_inactive_user_sees_no_calls(self):
        self.host_access.is_active = False
        self.host_access.save()

        calls = accessible_calls_for_user(self.host_user)
        self.assertEqual(calls.count(),0)

    # def test_inactive_location_is_excluded(self):
        self.location_a.is_active = False
        self.location_a.save()

        calls = accessible_calls_for_user(self.host_user)
        self.assertNotIn(self.call_a, calls)

        