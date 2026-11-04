FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py schedule.py voice_alerts.py raids.py raid_store.py console_commands.py redeem.py redeem_store.py salary.py salary_store.py ./
COPY assets/ ./assets/
CMD ["python", "bot.py"]
