# Na VPS: crie `.env` a partir de `env.example` e use:
#   docker run -d --env-file .env -p 8080:8080 deriv-bot
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "main.py"]
