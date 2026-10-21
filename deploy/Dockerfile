FROM python:3.11-slim-trixie@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce
WORKDIR /app
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
COPY vendor/openeo-python-driver vendor/openeo-python-driver
RUN pip install --no-cache-dir -r requirements.lock
RUN pip install --no-cache-dir setuptools==84.2.1 && pip check
COPY gee gee
COPY examples examples
COPY deploy/sync.yaml /app/deploy/sync.yaml
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
USER 1000:1000
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "60", "gee.app:create_app()"]
