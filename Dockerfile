FROM python:3.11-slim

WORKDIR /app

# Install fonts for Cyrillic support in PDF
RUN apt-get update && apt-get install -y \
    fonts-dejavu \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY data/ ./data/

CMD ["python", "-m", "src.main"]
