FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY monitor.py .

# 每日早上9點（香港時間 UTC+8 = UTC 01:00）執行
# 用 supercronic 做 cron
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://github.com/aptible/supercronic/releases/download/v0.2.29/supercronic-linux-amd64 \
    -o /usr/local/bin/supercronic && \
    chmod +x /usr/local/bin/supercronic

# 每日01:00 UTC = 09:00 HKT
RUN echo "0 1 * * * python /app/monitor.py >> /proc/1/fd/1 2>&1" > /app/crontab

CMD ["supercronic", "/app/crontab"]
