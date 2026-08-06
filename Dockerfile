FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# Cria a pasta e grava o secrets.toml de forma limpa e segura
CMD ["sh", "-c", "mkdir -p .streamlit && printf '[default]\nDATABASE_URL = \"%s\"\n' \"$DATABASE_URL\" > .streamlit/secrets.toml && streamlit run main.py --server.port=8501 --server.address=0.0.0.0"]
