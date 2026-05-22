FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production

COPY requirements.txt pyproject.toml ./
COPY wasted_sun/ ./wasted_sun/
COPY translations/ ./translations/
COPY wsgi.py .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir . \
    && pybabel compile -d translations

EXPOSE 8080
CMD ["gunicorn", "wsgi:app", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "30", "--access-logfile", "-", "--error-logfile", "-", "--capture-output"]
