# Django Starter Pack – Instructions

To start your Django backend for domain: __DOMAIN__

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Initialize your Django project in this folder (use "." to initialize here):
   ```bash
   django-admin startproject __PROJECT__ .
   ```

3. Update your Django `settings.py` to allow the domain and enable CORS/Hosts overrides:
   ```python
   ALLOWED_HOSTS = ["*"]  # Or specify: "__DOMAIN__", "127.0.0.1", "localhost"
   ```

4. Run the Django server:
   ```bash
   python manage.py runserver 127.0.0.1:8000
   ```
