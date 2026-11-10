FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# One layer: update, upgrade existing packages, install OCR tools, clean up.
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip "setuptools>=78.1.1" \
 && pip install --no-cache-dir -r requirements.txt
RUN rm -f /usr/local/lib/python3.12/site-packages/pip/_vendor/bom.cdx.json
COPY pipeline ./pipeline
USER 10001
CMD ["python", "-m", "pipeline.run"]