# Dockerfile
# Imagen compartida por backend, dashboard, llm_gateway y los 3 workers.
# Lo único que cambia entre ellos es el "command" en docker-compose.yml.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Sin CMD por defecto a propósito: cada servicio en docker-compose.yml
# especifica su propio "command".
