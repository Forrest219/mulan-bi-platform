# Python 3.11 slim + Node 20 (for @tableau/mcp-server subprocess)
FROM python:3.11-slim

WORKDIR /app

# Install Node.js 20 via nodesource
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Node dependencies (@tableau/mcp-server binary)
COPY package*.json ./
RUN npm ci --omit=dev

COPY . .

EXPOSE 3928

CMD ["python", "main.py"]
