FROM python:3.11-slim
WORKDIR /srv
COPY opspilot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY opspilot ./opspilot
CMD ["python", "-m", "opspilot.ingestion.collector"]
