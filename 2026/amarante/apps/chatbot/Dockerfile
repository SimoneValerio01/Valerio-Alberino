# uso questa versione per un'incompatibilità tra glibc e docker
FROM python:3.9-slim-bullseye

WORKDIR /app

RUN pip install --no-cache-dir flask==2.2.5

COPY chatbot.py /app/chatbot.py

EXPOSE 5000

CMD ["python3", "/app/chatbot.py"]
