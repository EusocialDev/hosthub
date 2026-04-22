from django import forms
from django.core.exceptions import ValidationError

from .models import UserAccess

class UserAccessAdminForm(forms.ModelForm):
    pin = forms.CharField(
        required=False,
        max_length=4,
        widget=forms.PasswordInput(render_value=True),
        help_text="Enter a 4-Digit PIN",
        label="PIN",
    )
    confirm_pin = forms.CharField(
        required=False,
        max_length=4,
        widget=forms.PasswordInput(render_value=True),
        help_text="Confirm the 4-Digit PIN",
        label="Confirm PIN",
    )

    class Meta:
        model = UserAccess
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        pin = cleaned_data.get("pin")
        confirm_pin = cleaned_data.get("confirm_pin")

        if pin or confirm_pin:
            if not pin or not confirm_pin:
                raise ValidationError("Both PIN fields are required.")
            if pin != confirm_pin:
                raise ValidationError("PIN and Confirm PIN do not match.")
            if not pin.isdigit() or len(pin) != 4:
                raise ValidationError("PIN must be exactly 4 digits.")

        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        pin = self.cleaned_data.get("pin")

        if pin:
            instance.set_pin(pin)

        if commit:
            instance.save()
            self.save_m2m()

        return instance
    
class AccountLoginForm(forms.Form):
    username = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            "autocomplete":"username",
            "placeholder": "Account username",
        }),
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "autocomplete": "current-password",
            "placeholder": "Password",
        }),
    )