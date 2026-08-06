FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# Cria o diretório .streamlit e escreve a chave DATABASE_URL exatamente como o Streamlit espera
CMD ["sh", "-c", "mkdir -p .streamlit && echo \"DATABASE_URL = \\\"$DATABASE_URL\\\"\" > .streamlit/secrets.toml && streamlit run main.py --server.port=8501 --server.address=0.0.0.0"]
