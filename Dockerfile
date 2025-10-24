# ===============================
# Flask Expense Tracker Dockerfile
# ===============================

# Use lightweight Python base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir flask gunicorn

# Expose app port
EXPOSE 5000

# Environment variables
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1

# Create the database folder if needed
RUN mkdir -p /app && touch /app/expenses.db

# Command to run Gunicorn server
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]

