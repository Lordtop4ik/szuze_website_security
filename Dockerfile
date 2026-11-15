FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py shop_api.py webapp.py .
COPY templates ./templates
COPY site ./site
ENV HOST=0.0.0.0 PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
RUN mkdir /app/data && chown 65532:65532 /app/data
USER 65532:65532
ENTRYPOINT ["python", "main.py"]
