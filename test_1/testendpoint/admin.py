from django.contrib import admin
from .models import Call, Account, Location, PhoneNumber, UserAccess, BusinessHour
from .forms import UserAccessAdminForm

admin.site.register(Account)
admin.site.register(Location)
admin.site.register(PhoneNumber)
admin.site.register(Call)

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

