from flask import Flask, render_template, request, redirect, url_for, session, send_file
import sqlite3
from datetime import datetime
import io, csv

app = Flask(__name__)
app.secret_key = "supersecretkey"

DB_PATH = "data/expenses.db"

# ---------------------------
# Database setup
# ---------------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )""")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        category TEXT NOT NULL,
        amount REAL NOT NULL,
        description TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )""")
    conn.commit()
    conn.close()

init_db()

# ---------------------------
# Auth routes
# ---------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password)).fetchone()
        conn.close()
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("index"))
        else:
            return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            conn.commit()
            conn.close()
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            conn.close()
            return render_template("register.html", error="Username already exists!")
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------------------
# Expenses CRUD
# ---------------------------
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))

    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    selected_category = request.args.get("category", "").strip()

    conn = get_db_connection()

    # ---- Build expense query ----
    query = "SELECT * FROM expenses WHERE user_id=?"
    params = [session["user_id"]]

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    if selected_category:
        query += " AND category = ?"
        params.append(selected_category)

    query += " ORDER BY date DESC"
    expenses = conn.execute(query, params).fetchall()

    # ---- Compute totals (same filters) ----
    sum_query = """
        SELECT 
            SUM(CASE WHEN type='Credit' THEN amount ELSE 0 END) AS income,
            SUM(CASE WHEN type='Expense' THEN amount ELSE 0 END) AS spending
        FROM expenses
        WHERE user_id=?
    """
    sum_params = [session["user_id"]]
    if start_date:
        sum_query += " AND date >= ?"
        sum_params.append(start_date)
    if end_date:
        sum_query += " AND date <= ?"
        sum_params.append(end_date)
    if selected_category:
        sum_query += " AND category = ?"
        sum_params.append(selected_category)

    totals = conn.execute(sum_query, sum_params).fetchone()

    # ---- Fetch categories for dropdown ----
    categories = conn.execute(
        "SELECT DISTINCT category FROM expenses WHERE user_id=? ORDER BY category ASC",
        (session["user_id"],)
    ).fetchall()
    categories = [c["category"] for c in categories]

    conn.close()

    # ---- Calculate summary ----
    income = totals["income"] or 0
    spending = totals["spending"] or 0
    balance = income - spending

    return render_template(
        "index.html",
        expenses=expenses,
        income=income,
        spending=spending,
        balance=balance,
        start_date=start_date,
        end_date=end_date,
        categories=categories,
        selected_category=selected_category
    )


@app.route("/add", methods=["GET", "POST"])
def add_expense():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        type = request.form["type"] # New field for type of expense
        category = request.form["category"].strip()
        amount = float(request.form["amount"])
        description = request.form["description"].strip()
        date = request.form.get("date") or datetime.now().strftime("%Y-%m-%d")

        conn = get_db_connection()
        conn.execute("INSERT INTO expenses (user_id, date, category, amount, description, type) VALUES (?, ?, ?, ?, ?, ?)",
                     (session["user_id"], date, category, amount, description, type))
        conn.commit()
        conn.close()
        return redirect(url_for("index"))
    return render_template("add.html")

@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_expense(id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    expense = conn.execute("SELECT * FROM expenses WHERE id=? AND user_id=?", (id, session["user_id"])).fetchone()
    if not expense:
        conn.close()
        return "Expense not found", 404
    if request.method == "POST":
        type = request.form["type"] # New field for type of expense
        date = request.form.get("date") or expense["date"]
        category = request.form["category"]
        amount = float(request.form["amount"])
        description = request.form["description"]
        conn.execute("UPDATE expenses SET date=?, category=?, amount=?, description=?, type=? WHERE id=?",
                     (date, category, amount, description, type, id))
        conn.commit()
        conn.close()
        return redirect(url_for("index"))
    conn.close()
    return render_template("edit.html", expense=expense)

@app.route("/delete/<int:id>")
def delete_expense(id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    conn.execute("DELETE FROM expenses WHERE id=? AND user_id=?", (id, session["user_id"]))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))

# ---------------------------
# Dashboard - Charts
# ---------------------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    
    # Monthly income and expenses
    monthly = conn.execute("""
        SELECT strftime('%Y-%m', date) AS month,
               SUM(CASE WHEN type='Credit' THEN amount ELSE 0 END) AS income,
               SUM(CASE WHEN type='Expense' THEN amount ELSE 0 END) AS spending
        FROM expenses 
        WHERE user_id=? 
        GROUP BY month 
        ORDER BY month
    """, (session["user_id"],)).fetchall()

    # Category-wise totals (both credit and expense)
    category_data = conn.execute("""
        SELECT category,
               SUM(CASE WHEN type='Credit' THEN amount ELSE 0 END) AS income,
               SUM(CASE WHEN type='Expense' THEN amount ELSE 0 END) AS spending
        FROM expenses 
        WHERE user_id=?
        GROUP BY category 
        ORDER BY (income + spending) DESC
    """, (session["user_id"],)).fetchall()
    
    conn.close()

    # Prepare data for charts
    months = [m["month"] for m in monthly]
    income_totals = [m["income"] for m in monthly]
    expense_totals = [m["spending"] for m in monthly]

    categories = [c["category"] for c in category_data]
    category_income = [c["income"] for c in category_data]
    category_expense = [c["spending"] for c in category_data]

    # ✅ Pass correct variable names to template
    return render_template(
        "dashboard.html",
        months=months,
        income_totals=income_totals,
        expense_totals=expense_totals,
        categories=categories,
        category_income=category_income,
        category_expense=category_expense
    )



# ---------------------------
# CSV Export
# ---------------------------
@app.route("/export")
def export_csv():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    expenses = conn.execute("SELECT * FROM expenses WHERE user_id=?", (session["user_id"],)).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Type", "Category", "Amount", "Description"])
    for e in expenses:
        writer.writerow([e["date"], e["type"], e["category"], e["amount"], e["description"]])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype="text/csv", as_attachment=True, download_name="expenses.csv")

# ---------------------------
# CSV Import    
@app.route("/import", methods=["GET", "POST"])
def import_csv():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        file = request.files["file"]
        if not file:
            return redirect(url_for("index"))
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.reader(stream)
        next(csv_input)  # Skip header row
        conn = get_db_connection()
        for row in csv_input:
            date, category, amount, description = row
            conn.execute("INSERT INTO expenses (user_id, type, date, category, amount, description) VALUES (?, ?, ?, ?, ?, ?)",
                         (session["user_id"], 'type', date, category, float(amount), description))
        conn.commit()
        conn.close()
        return redirect(url_for("index"))
    return render_template("import.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
