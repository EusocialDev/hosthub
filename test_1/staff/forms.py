from django import forms
from django.contrib.auth.models import User

from .models import UserProfile
from testendpoint.models import UserAccess, Location


class WorkerForm(forms.Form):
    display_name = forms.CharField(max_length=255, required=True)
    role = forms.ChoiceField(choices=UserAccess.ROLE_CHOICES, required=True)
    locations = forms.ModelMultipleChoiceField(
        queryset=Location.objects.none(),
        required=False,
    )
    pin = forms.CharField(
        max_length=4, 
        min_length=4,
        required=True,
        widget=forms.PasswordInput(attrs={
            "max_length":"4",
            "inputmode": "numeric",
            "pattern": "[0-9]*",
        })
        )
    confirm_pin = forms.CharField(
        max_length=4, 
        min_length=4,
        required=True,
        widget=forms.PasswordInput(attrs={
            "max_length":"4",
            "inputmode": "numeric",
            "pattern": "[0-9]*",
        })
        )
    is_active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, manager_access=None, editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.manager_access = manager_access
        self.editing = editing

        if manager_access is not None:
            if manager_access.role == "owner":
                allowed_locations = Location.objects.filter(
                    account=manager_access.account,
                    is_active=True,
                ).order_by("name")
            else:
                allowed_locations = manager_access.locations.filter(
                    is_active=True,
                ).order_by("name")

            self.fields["locations"].queryset = allowed_locations

            if manager_access.role != "owner":
                self.fields["role"].choices = [
                    choice for choice in UserAccess.ROLE_CHOICES
                    if choice[0] == "host"
                ]

    def clean_display_name(self):
        value = self.cleaned_data["display_name"].strip()
        if not value:
            raise forms.ValidationError("Display name is required.")
        return value

    def clean_pin(self):
        pin = self.cleaned_data.get("pin", "").strip()

        if pin and (not pin.isdigit() or len(pin) != 4):
            raise forms.ValidationError("PIN must be a 4-digit number.")
        return pin

    def clean(self):
        cleaned_data = super().clean()
        pin = cleaned_data.get("pin", "").strip()
        confirm_pin = cleaned_data.get("confirm_pin", "").strip()
        locations = cleaned_data.get("locations")
        role = cleaned_data.get("role")

        if not self.editing and not pin:
            self.add_error("pin", "PIN is required for new workers.")

        if pin and pin != confirm_pin:
            self.add_error("confirm_pin", "PIN and confirm PIN do not match.")

        if self.manager_access:
            allowed_ids = set(self.fields["locations"].queryset.values_list("id", flat=True))
            chosen_ids = set(loc.id for loc in locations) if locations else set()

            if not chosen_ids:
                self.add_error("locations", "At least one location must be selected.")

            if not chosen_ids.issubset(allowed_ids):
                self.add_error("locations", "You can only assign allowed locations.")

            if self.manager_access.role != "owner" and role != "host":
                self.add_error("role", "You can only create hosts.")

        return cleaned_data


