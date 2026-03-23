# Dev server: listen on all interfaces so other devices on the LAN can reach the app.
# (Docker web/ops services already pass --host 0.0.0.0 / gunicorn -b 0.0.0.0.)
FLASK_APP=app:create_app
FLASK_RUN_HOST=0.0.0.0
FLASK_RUN_PORT=5000
