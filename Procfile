web: python manage.py collectstatic --noinput && python manage.py migrate && daphne -b 0.0.0.0 -p $PORT ecommerce.asgi:application --proxy-headers
