FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" "sqlalchemy>=2.0" "httpx>=0.27" "pydantic>=2.9" "python-dotenv>=1.0"
COPY gigsim /app/gigsim
ENV GIGSIM_DB_PATH=/data/gigsim.db
VOLUME ["/data"]
EXPOSE 8081
CMD ["uvicorn", "gigsim.app:app", "--host", "0.0.0.0", "--port", "8081"]
