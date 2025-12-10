FROM python:3.12-slim

WORKDIR /app

# OS dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Kopieer code
COPY CyNiT-tools/ ./CyNiT-tools/
COPY SP-YT/ ./SP-YT/

# Optioneel: als je een gezamenlijke requirements.txt hebt:
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# Minimale libs (pas aan naar jouw echte requirements)
RUN pip install --no-cache-dir flask cryptography pyjwt requests yt-dlp

# Poorten
EXPOSE 5000 5555

WORKDIR /app/CyNiT-tools
CMD ["python", "ctools.py"]
