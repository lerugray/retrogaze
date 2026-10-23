FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    libjpeg62-turbo-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY src/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY frontend/ ./frontend/
COPY scripts/minify.py ./scripts/minify.py

RUN python scripts/minify.py

RUN useradd -r -u 1001 appuser
USER appuser

EXPOSE 8642

CMD ["sh", "-c", "cd src && python -m uvicorn retrogaze.api:app --host 0.0.0.0 --port ${PORT}"]
