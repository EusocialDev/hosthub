from django.contrib import admin
from .models import Call, Account, Location, PhoneNumber, UserAccess, BusinessHour
from .forms import UserAccessAdminForm
from django import forms


admin.site.register(Location)
admin.site.register(PhoneNumber)
admin.site.register(Call)

class AccountAdminForm(forms.ModelForm):
    login_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label="Account Login Password",
        help_text="Enter a new account login password. Leave blank to keep the current password.",
    )

    class Meta:
        model = Account
        fields = "__all__"

    def save(self, commit=True):
        account = super().save(commit=False)
        raw_password = self.cleaned_data.get("login_password")

        if raw_password:
            account.set_login_password(raw_password)

        if commit:
            account.save()
            self.save_m2m()

        return account


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    form = AccountAdminForm

    list_display = (
        "name",
        "slug",
        "is_active",
        "login_username",
        "daily_report_email_enabled",
        "daily_report_email",
    )

    search_fields = (
        "name",
        "slug",
        "login_username",
        "daily_report_email",
    )

    list_filter = (
        "is_active",
        "daily_report_email_enabled",
    )

    readonly_fields = (
        "login_password_hash",
    )


@admin.register(UserAccess)
class UserAccessAdmin(admin.ModelAdmin):
    form = UserAccessAdminForm

    fields = ("user", "account", "role", "locations", "pin", "confirm_pin", "is_active")

    readonly_fields = ()


    list_display = ("user", "account", "role", "is_active", "created_at")
    list_filter = ("account", "role", "is_active")
    filter_horizontal = ("locations",)

@admin.register(BusinessHour)
class BusinessHourAdmin(admin.ModelAdmin):
    list_display = ("location", "day_of_week", "open_time", "close_time")

