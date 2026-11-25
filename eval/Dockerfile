FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip "setuptools>=78.1.1" \
 && pip install --no-cache-dir -r requirements.txt
COPY *.py *.sh *.jsonl *.yaml ./eval/
WORKDIR /app/eval
USER 10001
CMD ["sh", "job_entry.sh"]
