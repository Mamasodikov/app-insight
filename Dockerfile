FROM python:3.11-slim

# Install Node.js, whois, dig
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm whois dnsutils curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Node.js deps
COPY package.json .
RUN npm install --production 2>/dev/null || true

# Copy app
COPY . .

# HF Spaces expects port 7860
ENV PORT=7860
EXPOSE 7860

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
