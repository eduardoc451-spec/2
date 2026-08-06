FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cria a pasta .streamlit e injeta a variavel de ambiente no arquivo secrets.toml
CMD mkdir -p /app/.streamlit && \
    echo "$SECRETS_TOML" > /app/.streamlit/secrets.toml && \
    streamlit run main.py --server.port=8501 --server.address=0.0.0.0
