# Runs the example project; the library itself is installed from this checkout.
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /src

COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY audit_log ./audit_log
RUN pip install . "djangorestframework>=3.14" "psycopg[binary]>=3.1" "gunicorn>=21.2"

COPY example /app
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn example_project.wsgi:application --bind 0.0.0.0:8000 --workers 2"]
