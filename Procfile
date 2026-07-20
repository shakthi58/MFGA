web: cd fitness_app && python manage.py migrate && python manage.py collectstatic --noinput && gunicorn fitness_app.wsgi:application --bind 0.0.0.0:$PORT
