# FinTrace demo + metrics image: library, hosted-demo app, and its subset DB.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md requirements.txt ./
COPY src ./src
COPY demo ./demo
COPY scripts ./scripts

RUN pip install --no-cache-dir . -r requirements.txt

# The demo connects to "demo/demo.duckdb" relative to the working directory.
EXPOSE 8501 9091
CMD ["streamlit", "run", "demo/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
