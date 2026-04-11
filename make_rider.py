from ecommerce.models import User
from rider.models import RiderProfile
from delivery.models import DeliveryZone

# Replace with the actual phone number of the person you want to make a rider
PHONE = '0558040216'

try:
    u = User.objects.get(phone=PHONE)
except User.DoesNotExist:
    print(f'No user with phone {PHONE}. Ask them to sign up first at /accounts/signup/')
    exit()

u.role = 'rider'
u.save()

zone = DeliveryZone.objects.first()
profile, created = RiderProfile.objects.get_or_create(
    rider=u,
    defaults={
        'commission_rate': 50,
        'is_verified': True,
        'status': 'available',
        'vehicle_type': 'Motorbike',
        'zone': zone,
    }
)

print('Done!' if created else 'Profile already exists.')
print('Name:', u.get_full_name() or u.phone)
print('Role:', u.role)
print('Rider URL: http://127.0.0.1:8000/rider/')