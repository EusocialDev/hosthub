from django.contrib import admin
from .models import Call, Account, Location, PhoneNumber

admin.site.register(Account)
admin.site.register(Location)
admin.site.register(PhoneNumber)
admin.site.register(Call)

# Register your models here.
