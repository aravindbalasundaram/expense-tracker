docker run -d \
  --name expense-tracker \
  -p 50000:5000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/templates:/app/templates \
  -e FLASK_APP=app.py \
  -e FLASK_ENV=production \
  --restart unless-stopped \
  expensetracker
