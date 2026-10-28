FROM python:3.11-slim

# Evita criação de arquivos .pyc e força flush imediato de stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependências do sistema operacional necessárias (ffmpeg e bibliotecas gráficas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    curl \
    tesseract-ocr \
    tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

# Define o prefixo canônico do tessdata no Debian/Ubuntu
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
ENV HOST=0.0.0.0
ENV PORT=8000

# Copia e instala as dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código da aplicação e arquivos de configuração
COPY . .

# Expõe a porta 8000 para acesso à API e Interface Web
EXPOSE 8000

# Executa o ponto de entrada oficial documentado
CMD ["python", "-m", "src.main"]
