from django.contrib import admin
from .models import Call, Account, Location, PhoneNumber, UserAccess

admin.site.register(Account)
admin.site.register(Location)
admin.site.register(PhoneNumber)
admin.site.register(Call)

@admin.register(UserAccess)
class UserAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "account", "role", "is_active")
    filter_horizontal = ("locations",)

# Register your models here.
