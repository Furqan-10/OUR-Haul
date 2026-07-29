# HaulCheck API.
#
# A container rather than a platform buildpack, so the same image runs on
# Render, Railway, Fly, or any VPS. Being unable to move hosts is the problem
# this migration exists to solve; a vendor buildpack would recreate it.
FROM python:3.12-slim

# reportlab and pillow render the PDF audit packs. They need these system image
# libraries at *runtime*, not only to build, so they cannot be dropped after
# pip install.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: this layer stays cached unless requirements.txt changes,
# so an application edit does not reinstall everything.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# A compromised dependency should not be able to rewrite the application it was
# installed alongside.
RUN useradd --create-home --shell /usr/sbin/nologin haulcheck \
    && chown -R haulcheck:haulcheck /app
USER haulcheck

EXPOSE 8000

# The host assigns the port. Binding a fixed one makes the platform health check
# fail with no useful error, and 0.0.0.0 is required -- a process bound to
# localhost is unreachable from outside the container.
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
