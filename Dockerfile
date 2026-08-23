FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PYTHONPATH=/app/app
ENV USAGE_HOST=0.0.0.0
ENV USAGE_PORT=8063

EXPOSE 8063

CMD ["sh", "-c", "uvicorn usage.main:app --host ${USAGE_HOST} --port ${USAGE_PORT}"]
