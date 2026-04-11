from django.contrib import admin
from .models import Vendor, VendorEarning, AppCommission
admin.site.register(Vendor)
admin.site.register(VendorEarning)
admin.site.register(AppCommission)