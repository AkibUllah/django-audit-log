# Runs the example project; the library itself is installed from this checkout.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /src

COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY audit_log ./audit_log
RUN pip install . "djangorestframework>=3.14" "psycopg[binary]>=3.1" "gunicorn>=21.2" "whitenoise>=6.6"

COPY example /app
WORKDIR /app
RUN python manage.py collectstatic --noinput
RUN addgroup --system app && adduser --system --ingroup app app && chown -R app:app /app
USER app

EXPOSE 8000
# DJANGO_SEED_DEMO=true loads the demo shop (idempotent) so the audit trail is not empty on first open.
CMD ["sh", "-c", "python manage.py migrate --noinput && if [ \"$DJANGO_SEED_DEMO\" = \"true\" ]; then python manage.py seed_shop; fi && gunicorn example_project.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2"]
