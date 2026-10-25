"""AI-Based Student Performance Tracking System
DBMS Mini-Project (TAE-2) - Python + SQLite + Tkinter

Demonstrates:
  * Database design  - 4 tables, primary keys, foreign keys, ON DELETE
    CASCADE, UNIQUE and CHECK constraints, an index, a view and a trigger
  * Database connectivity through Python's built-in `sqlite3` module
  * Insert / Update / Delete / Retrieve (CRUD) operations
  * A JOIN report that pulls data from all four tables
  * A small AI model (ridge linear regression written in pure Python,
    no external library needed) that predicts a student's final score
    and flags the risk level
"""
from contextlib import closing
import datetime
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

DB_FILE = "performance.db"

# ---------------------------------------------------------------
# 1. DATABASE DESIGN  (4 tables with primary & foreign keys)
# ---------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    student_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    roll_no        TEXT UNIQUE NOT NULL,
    email          TEXT UNIQUE NOT NULL,
    branch         TEXT,
    semester       INTEGER,
    attendance_pct REAL CHECK (attendance_pct IS NULL
                               OR (attendance_pct >= 0 AND attendance_pct <= 100)),
    study_hours    REAL CHECK (study_hours IS NULL OR study_hours >= 0)
);

CREATE TABLE IF NOT EXISTS courses (
    course_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT UNIQUE NOT NULL,
    course_name TEXT NOT NULL,
    credits     INTEGER CHECK (credits IS NULL OR credits > 0)
);

CREATE TABLE IF NOT EXISTS marks (
    mark_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     INTEGER NOT NULL,
    course_id      INTEGER NOT NULL,
    internal_marks REAL CHECK (internal_marks IS NULL OR internal_marks >= 0),
    external_marks REAL CHECK (external_marks IS NULL OR external_marks >= 0),
    total          REAL,
    grade          TEXT CHECK (grade IN ('S','A','B','C','D','E','F')),
    UNIQUE (student_id, course_id),
    FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
    FOREIGN KEY (course_id)  REFERENCES courses(course_id)  ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS predictions (
    prediction_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      INTEGER NOT NULL,
    attendance_pct  REAL,
    study_hours     REAL,
    avg_marks       REAL,
    predicted_score REAL,
    risk_level      TEXT CHECK (risk_level IN ('Low','Medium','High')),
    model_info      TEXT,
    created_on      TEXT,
    FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_marks_student    ON marks(student_id);
CREATE INDEX IF NOT EXISTS idx_predict_student  ON predictions(student_id);

-- View: one consolidated performance row per student
CREATE VIEW IF NOT EXISTS v_student_performance AS
SELECT s.student_id,
       s.name,
       s.roll_no,
       s.branch,
       s.semester,
       s.attendance_pct,
       s.study_hours,
       COUNT(m.mark_id)               AS subjects,
       ROUND(AVG(m.internal_marks),2) AS avg_internal,
       ROUND(AVG(m.total),2)          AS avg_total,
       ROUND(MIN(m.total),2)          AS lowest_total,
       ROUND(MAX(m.total),2)          AS highest_total
FROM students s
LEFT JOIN marks m ON m.student_id = s.student_id
GROUP BY s.student_id;

-- Trigger: keeps total & grade correct even for raw SQL inserts
CREATE TRIGGER IF NOT EXISTS trg_marks_grade
AFTER INSERT ON marks
WHEN NEW.total IS NULL
BEGIN
    UPDATE marks
       SET total = COALESCE(NEW.internal_marks,0) + COALESCE(NEW.external_marks,0),
           grade = CASE
                       WHEN COALESCE(NEW.internal_marks,0) + COALESCE(NEW.external_marks,0) >= 90 THEN 'S'
                       WHEN COALESCE(NEW.internal_marks,0) + COALESCE(NEW.external_marks,0) >= 80 THEN 'A'
                       WHEN COALESCE(NEW.internal_marks,0) + COALESCE(NEW.external_marks,0) >= 70 THEN 'B'
                       WHEN COALESCE(NEW.internal_marks,0) + COALESCE(NEW.external_marks,0) >= 60 THEN 'C'
                       WHEN COALESCE(NEW.internal_marks,0) + COALESCE(NEW.external_marks,0) >= 50 THEN 'D'
                       WHEN COALESCE(NEW.internal_marks,0) + COALESCE(NEW.external_marks,0) >= 40 THEN 'E'
                       ELSE 'F'
                   END
     WHERE mark_id = NEW.mark_id AND total IS NULL;
END;
"""

# table -> (primary key, [editable columns], [computed columns shown in the grid])
TABLES = {
    "students": ("student_id",
                 ["name", "roll_no", "email", "branch", "semester",
                  "attendance_pct", "study_hours"], []),
    "courses": ("course_id",
                ["course_code", "course_name", "credits"], []),
    "marks": ("mark_id",
              ["student_id", "course_id", "internal_marks", "external_marks"],
              ["total", "grade"]),
    "predictions": ("prediction_id",
                    ["student_id", "attendance_pct", "study_hours"],
                    ["avg_marks", "predicted_score", "risk_level", "created_on"]),
}

INT_COLS = {"student_id", "course_id", "semester", "credits"}
FLOAT_COLS = {"attendance_pct", "study_hours", "internal_marks", "external_marks"}


# ---------------------------------------------------------------
# 2. DATABASE CONNECTIVITY
# ---------------------------------------------------------------
def connect():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON")   # required for ON DELETE CASCADE
    return conn


def db_execute(query, params=()):
    """Run INSERT / UPDATE / DELETE and return the new rowid."""
    with closing(connect()) as conn:
        cur = conn.execute(query, params)
        conn.commit()
        return cur.lastrowid


def db_query(query, params=()):
    """Run SELECT and return all rows."""
    with closing(connect()) as conn:
        return conn.execute(query, params).fetchall()


def init_db():
    with closing(connect()) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


# ---------------------------------------------------------------
# 3. CRUD OPERATIONS
# ---------------------------------------------------------------
def compute_total_grade(internal, external):
    total = round(float(internal or 0) + float(external or 0), 2)
    if total >= 90:
        grade = "S"
    elif total >= 80:
        grade = "A"
    elif total >= 70:
        grade = "B"
    elif total >= 60:
        grade = "C"
    elif total >= 50:
        grade = "D"
    elif total >= 40:
        grade = "E"
    else:
        grade = "F"
    return total, grade


def insert_row(table, values):
    pk, cols, extra = TABLES[table]
    cols, values = list(cols), list(values)

    if table == "marks":
        total, grade = compute_total_grade(values[2], values[3])
        cols += ["total", "grade"]
        values += [total, grade]
    elif table == "predictions":
        f = predict_fields(values[0], values[1], values[2])
        values[1], values[2] = f["attendance_pct"], f["study_hours"]
        cols += ["avg_marks", "predicted_score", "risk_level", "model_info", "created_on"]
        values += [f["avg_marks"], f["predicted_score"], f["risk_level"],
                   f["model_info"], f["created_on"]]

    q = "INSERT INTO {} ({}) VALUES ({})".format(
        table, ",".join(cols), ",".join("?" * len(cols)))
    return db_execute(q, values)


def update_row(table, pk_value, values):
    pk, cols, extra = TABLES[table]
    cols, values = list(cols), list(values)

    if table == "marks":
        total, grade = compute_total_grade(values[2], values[3])
        cols += ["total", "grade"]
        values += [total, grade]

    q = "UPDATE {} SET {} WHERE {}=?".format(
        table, ",".join(c + "=?" for c in cols), pk)
    db_execute(q, values + [pk_value])


def delete_row(table, pk_value):
    pk, _, _ = TABLES[table]
    db_execute("DELETE FROM {} WHERE {}=?".format(table, pk), (pk_value,))


def fetch_rows(table, search=""):
    pk, cols, extra = TABLES[table]
    shown = [pk] + list(cols) + list(extra)
    q = "SELECT {} FROM {}".format(",".join(shown), table)
    params = []
    if search:
        q += " WHERE " + " OR ".join("CAST({} AS TEXT) LIKE ?".format(c) for c in shown)
        params = ["%{}%".format(search)] * len(shown)
    return db_query(q + " ORDER BY {}".format(pk), params)


def fetch_performance_report():
    """JOIN query across all four tables (latest prediction per student)."""
    q = """
    SELECT p.prediction_id, s.roll_no, s.name, c.course_code,
           m.internal_marks, m.external_marks, m.total, m.grade,
           s.attendance_pct, p.risk_level, p.predicted_score
    FROM predictions p
    JOIN students  s ON p.student_id = s.student_id
    JOIN marks     m ON m.student_id = s.student_id
    JOIN courses   c ON m.course_id  = c.course_id
    WHERE p.prediction_id IN (SELECT MAX(prediction_id)
                              FROM predictions GROUP BY student_id)
    ORDER BY s.roll_no, c.course_code
    """
    return db_query(q)


# ---------------------------------------------------------------
# 4. AI MODEL  (ridge linear regression, pure Python)
# ---------------------------------------------------------------
MODEL_VERSION = "ridge-linreg-v1"
DEFAULT_WEIGHTS = [10.0, 0.55, 1.20, 0.35]   # intercept, attendance, study hrs, avg internal
_MODEL_CACHE = {}


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _solve(matrix, vector):
    """Gauss-Jordan elimination with partial pivoting."""
    n = len(vector)
    a = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        pv = a[col][col]
        for r in range(n):
            if r != col and abs(a[r][col]) > 1e-15:
                f = a[r][col] / pv
                for c in range(col, n + 1):
                    a[r][c] -= f * a[col][c]
    return [a[i][n] / a[i][i] for i in range(n)]


def _fit_ridge(X, y, lam=1.0):
    k = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) + (lam if (i == j and i > 0) else 0.0)
          for j in range(k)] for i in range(k)]
    b = [sum(r[i] * t for r, t in zip(X, y)) for i in range(k)]
    return _solve(A, b)


def training_samples():
    rows = db_query("""
        SELECT attendance_pct, study_hours, avg_internal, avg_total
        FROM v_student_performance
        WHERE attendance_pct IS NOT NULL
          AND study_hours    IS NOT NULL
          AND avg_internal   IS NOT NULL
          AND avg_total      IS NOT NULL
    """)
    return [([1.0, float(r[0]), float(r[1]), float(r[2])], float(r[3])) for r in rows]


def train_model(force=False):
    """Fit the model on the data currently in the database."""
    if _MODEL_CACHE and not force:
        return _MODEL_CACHE

    data = training_samples()
    weights, samples, r2, mae = list(DEFAULT_WEIGHTS), 0, None, None

    if len(data) >= 5:
        X = [d[0] for d in data]
        y = [d[1] for d in data]
        w = _fit_ridge(X, y)
        if w:
            weights, samples = w, len(data)
            preds = [_dot(w, x) for x in X]
            mae = sum(abs(p - t) for p, t in zip(preds, y)) / len(y)
            mean_y = sum(y) / len(y)
            ss_tot = sum((t - mean_y) ** 2 for t in y)
            ss_res = sum((p - t) ** 2 for p, t in zip(preds, y))
            r2 = (1 - ss_res / ss_tot) if ss_tot else None

    _MODEL_CACHE.clear()
    _MODEL_CACHE.update({"weights": weights, "samples": samples, "r2": r2, "mae": mae})
    return _MODEL_CACHE


def risk_level(score, attendance):
    if score < 50 or attendance < 60:
        return "High"
    if score < 65 or attendance < 75:
        return "Medium"
    return "Low"


def predict_fields(student_id, attendance=None, study_hours=None):
    """Run the trained model for one student."""
    row = db_query("""SELECT attendance_pct, study_hours, avg_internal
                      FROM v_student_performance WHERE student_id=?""", (student_id,))
    if not row:
        raise ValueError("Student ID {} does not exist.".format(student_id))

    model = train_model()
    att = row[0][0] if attendance in (None, "") else attendance
    hrs = row[0][1] if study_hours in (None, "") else study_hours
    avg_int = row[0][2] or 0.0
    att = 0.0 if att is None else float(att)
    hrs = 0.0 if hrs is None else float(hrs)

    score = _dot(model["weights"], [1.0, att, hrs, float(avg_int)])
    score = max(0.0, min(100.0, score))

    info = "{} | samples={} | R2={}".format(
        MODEL_VERSION, model["samples"],
        "n/a" if model["r2"] is None else "{:.2f}".format(model["r2"]))

    return {"attendance_pct": round(att, 2),
            "study_hours": round(hrs, 2),
            "avg_marks": round(float(avg_int), 2),
            "predicted_score": round(score, 2),
            "risk_level": risk_level(score, att),
            "model_info": info,
            "created_on": datetime.date.today().isoformat()}


# ---------------------------------------------------------------
# 5. DEMO DATA  (optional, for your presentation)
# ---------------------------------------------------------------
DEMO_STUDENTS = [
    ("Aarav Sharma",   "1RV21CS001", "aarav.sharma@example.edu",  "CSE", 5, 92.5, 14.0),
    ("Diya Patel",     "1RV21CS002", "diya.patel@example.edu",    "CSE", 5, 88.0, 11.0),
    ("Rohan Verma",    "1RV21CS003", "rohan.verma@example.edu",   "ISE", 5, 64.0,  5.0),
    ("Ananya Rao",     "1RV21CS004", "ananya.rao@example.edu",    "CSE", 5, 78.5,  9.0),
    ("Kabir Nair",     "1RV21CS005", "kabir.nair@example.edu",    "ECE", 3, 55.0,  3.0),
    ("Meera Iyer",     "1RV21CS006", "meera.iyer@example.edu",    "ISE", 3, 95.0, 16.0),
    ("Aditya Kulkarni","1RV21CS007", "aditya.kulkarni@example.edu","CSE", 5, 71.0,  7.0),
    ("Sneha Deshpande","1RV21CS008", "sneha.deshpande@example.edu","ECE", 3, 83.0, 10.0),
]

DEMO_COURSES = [
    ("CS501", "Database Management Systems", 4),
    ("CS502", "Operating Systems", 4),
    ("CS503", "Design and Analysis of Algorithms", 4),
    ("CS504", "Computer Networks", 3),
    ("CS505", "Machine Learning Fundamentals", 3),
]

# roll_no -> [(course_id, internal (out of 50), external (out of 50))]
DEMO_MARKS = {
    "1RV21CS001": [(1, 46, 44), (2, 42, 40), (3, 44, 45), (4, 38, 36), (5, 40, 42)],
    "1RV21CS002": [(1, 44, 40), (2, 40, 38), (3, 42, 41), (4, 36, 34), (5, 38, 39)],
    "1RV21CS003": [(1, 26, 18), (2, 24, 15), (3, 28, 20), (4, 22, 14)],
    "1RV21CS004": [(1, 36, 32), (2, 34, 30), (3, 38, 35), (4, 32, 28), (5, 35, 33)],
    "1RV21CS005": [(1, 20, 12), (2, 22, 10), (3, 18, 14), (4, 24, 16)],
    "1RV21CS006": [(1, 48, 47), (2, 46, 45), (3, 47, 46), (4, 44, 43), (5, 45, 44)],
    "1RV21CS007": [(1, 32, 26), (2, 30, 24), (3, 33, 28), (4, 28, 22), (5, 31, 27)],
    "1RV21CS008": [(1, 40, 36), (2, 38, 34), (3, 41, 37), (4, 36, 32), (5, 39, 35)],
}


def load_demo_data():
    """Insert the sample students / courses / marks (safe to call twice)."""
    if db_query("SELECT COUNT(*) FROM students")[0][0] > 0:
        return 0, "Sample data already present - nothing inserted."

    for row in DEMO_STUDENTS:
        db_execute("""INSERT INTO students
                      (name, roll_no, email, branch, semester, attendance_pct, study_hours)
                      VALUES (?,?,?,?,?,?,?)""", row)
    for row in DEMO_COURSES:
        db_execute("""INSERT INTO courses (course_code, course_name, credits)
                      VALUES (?,?,?)""", row)

    ids = {r[0]: r[1] for r in db_query("SELECT roll_no, student_id FROM students")}
    count = 0
    for roll, items in DEMO_MARKS.items():
        for cid, internal, external in items:
            # total and grade are filled in by the database trigger
            db_execute("""INSERT INTO marks (student_id, course_id, internal_marks, external_marks)
                          VALUES (?,?,?,?)""", (ids[roll], cid, internal, external))
            count += 1

    train_model(force=True)
    return count, "Inserted {} students, {} courses and {} marks. AI model retrained.".format(
        len(DEMO_STUDENTS), len(DEMO_COURSES), count)


# ---------------------------------------------------------------
# 6. GUI  (styled Tkinter)
# ---------------------------------------------------------------
BG = "#F4F6F9"
PRIMARY = "#1F4E79"
GREEN = "#2E8B57"
BLUE = "#2F6FB5"
RED = "#C0392B"
GRAY = "#6B7280"
PURPLE = "#7D3C98"
TEAL = "#117A65"
STRIPE = "#EEF3F9"


def make_button(parent, text, color, cmd):
    return tk.Button(parent, text=text, command=cmd, bg=color, fg="white",
                     activebackground=color, activeforeground="white",
                     relief="flat", bd=0, padx=16, pady=6, cursor="hand2",
                     font=("Segoe UI", 10, "bold"))


def setup_style(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    root.configure(bg=BG)
    s.configure("TFrame", background=BG)
    s.configure("TLabel", background=BG, font=("Segoe UI", 10))
    s.configure("TLabelframe", background=BG)
    s.configure("TLabelframe.Label", background=BG, foreground=PRIMARY,
                font=("Segoe UI", 10, "bold"))
    s.configure("TNotebook", background=BG, borderwidth=0)
    s.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=(14, 6))
    s.map("TNotebook.Tab",
          background=[("selected", PRIMARY)], foreground=[("selected", "white")])
    s.configure("Treeview", rowheight=26, font=("Segoe UI", 10),
                background="white", fieldbackground="white")
    s.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"),
                background=PRIMARY, foreground="white")
    s.map("Treeview.Heading", background=[("active", PRIMARY)])
    s.map("Treeview", background=[("selected", "#CFE3F7")],
          foreground=[("selected", "black")])


def fill_tree(tree, rows):
    tree.delete(*tree.get_children())
    tree.tag_configure("odd", background=STRIPE)
    for n, r in enumerate(rows):
        values = ["" if v is None else v for v in r]
        tree.insert("", "end", values=values, tags=("odd",) if n % 2 else ())


def clean_values(cols, raw):
    """Convert GUI text into proper Python types and validate numbers."""
    out = []
    for col, text in zip(cols, raw):
        text = (text or "").strip()
        if col in INT_COLS:
            if text == "":
                out.append(None)
            else:
                try:
                    out.append(int(float(text)))
                except ValueError:
                    raise ValueError("{} must be a whole number.".format(
                        col.replace("_", " ").title()))
        elif col in FLOAT_COLS:
            if text == "":
                out.append(None)
            else:
                try:
                    out.append(float(text))
                except ValueError:
                    raise ValueError("{} must be a number.".format(
                        col.replace("_", " ").title()))
        else:
            out.append(text)
    return out


def friendly_error(msg):
    if "UNIQUE constraint failed" in msg:
        return msg + "\n\nEach record needs a unique value (roll no, email or course code)."
    if "FOREIGN KEY constraint failed" in msg:
        return msg + "\n\nUse a valid ID from the parent table (add Students and Courses first)."
    if "CHECK constraint failed" in msg:
        return msg + "\n\nA value is outside the allowed range (e.g. attendance must be 0-100)."
    return msg


class TablePage(ttk.Frame):
    def __init__(self, parent, table, tools=None):
        super().__init__(parent)
        self.table = table
        self.pk, self.cols, self.extra = TABLES[table]
        self.selected_id = None

        form = ttk.LabelFrame(self, text="  {} Details  ".format(table.title()))
        form.pack(fill="x", padx=12, pady=10)
        self.entries = {}
        for i, col in enumerate(self.cols):
            ttk.Label(form, text=col.replace("_", " ").title()).grid(
                row=i // 2, column=(i % 2) * 2, padx=8, pady=6, sticky="e")
            e = ttk.Entry(form, width=28, font=("Segoe UI", 10))
            e.grid(row=i // 2, column=(i % 2) * 2 + 1, padx=8, pady=6)
            self.entries[col] = e

        btns = ttk.Frame(self)
        btns.pack(pady=4)
        self.tools_frame = btns
        for text, color, cmd in [("Insert", GREEN, self.on_insert),
                                 ("Update", BLUE, self.on_update),
                                 ("Delete", RED, self.on_delete),
                                 ("Clear", GRAY, self.clear)]:
            make_button(btns, text, color, cmd).pack(side="left", padx=6)
        for text, color, method in (tools or []):
            make_button(btns, text, color, getattr(self, method)).pack(side="left", padx=6)

        sbar = ttk.Frame(self)
        sbar.pack(fill="x", padx=12, pady=(8, 0))
        ttk.Label(sbar, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        se = ttk.Entry(sbar, textvariable=self.search_var, width=34,
                       font=("Segoe UI", 10))
        se.pack(side="left", padx=6)
        se.bind("<KeyRelease>", lambda e: self.refresh())

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=12, pady=10)
        shown = [self.pk] + list(self.cols) + list(self.extra)
        self.tree = ttk.Treeview(wrap, columns=shown, show="headings", height=11)
        for c in shown:
            self.tree.heading(c, text=c.replace("_", " ").title())
            self.tree.column(c, width=115, anchor="w")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.refresh()

    # ----- helpers -------------------------------------------------
    def values(self):
        return clean_values(self.cols, [self.entries[c].get() for c in self.cols])

    def on_insert(self):
        try:
            vals = self.values()
        except ValueError as e:
            return messagebox.showwarning("Invalid input", str(e))
        if vals[0] in (None, ""):
            return messagebox.showwarning(
                "Missing", "Please fill {} first.".format(
                    self.cols[0].replace("_", " ").title()))
        try:
            insert_row(self.table, vals)
            messagebox.showinfo("Success", "Record inserted.")
            self.clear()
            self.refresh()
        except ValueError as e:
            messagebox.showerror("Cannot predict", str(e))
        except sqlite3.Error as e:
            messagebox.showerror("Database error", friendly_error(str(e)))

    def on_update(self):
        if self.selected_id is None:
            return messagebox.showwarning("Select", "Select a row to update.")
        try:
            vals = self.values()
        except ValueError as e:
            return messagebox.showwarning("Invalid input", str(e))
        try:
            update_row(self.table, self.selected_id, vals)
            messagebox.showinfo("Success", "Record updated.")
            self.clear()
            self.refresh()
        except sqlite3.Error as e:
            messagebox.showerror("Database error", friendly_error(str(e)))

    def on_delete(self):
        if self.selected_id is None:
            return messagebox.showwarning("Select", "Select a row to delete.")
        if messagebox.askyesno("Confirm", "Delete this record?"):
            try:
                delete_row(self.table, self.selected_id)
                self.clear()
                self.refresh()
            except sqlite3.Error as e:
                messagebox.showerror("Database error", friendly_error(str(e)))

    def on_select(self, _):
        sel = self.tree.selection()
        if not sel:
            return
        row = self.tree.item(sel[0])["values"]
        self.selected_id = row[0]
        for col, val in zip(self.cols, row[1:]):
            self.entries[col].delete(0, "end")
            self.entries[col].insert(0, "" if val is None else str(val))

    def clear(self):
        self.selected_id = None
        for e in self.entries.values():
            e.delete(0, "end")

    def refresh(self):
        fill_tree(self.tree, fetch_rows(self.table, self.search_var.get().strip()))


class PredictionPage(TablePage):
    """Predictions tab plus the AI model controls."""

    def __init__(self, parent):
        super().__init__(parent, "predictions",
                         tools=[("Train AI Model", PURPLE, "on_train"),
                                ("Predict All Students", TEAL, "on_predict_all")])
        self.status = tk.StringVar()
        ttk.Label(self.tools_frame, textvariable=self.status,
                  foreground=PRIMARY).pack(side="left", padx=10)
        self.update_status()

    def update_status(self):
        m = train_model()
        txt = "AI model: {}  |  trained on {} student(s)".format(
            MODEL_VERSION, m["samples"])
        if m["r2"] is not None:
            txt += "  |  R2 = {:.2f}  |  MAE = {:.2f}".format(m["r2"], m["mae"])
        else:
            txt += "  |  default weights (needs 5+ students with marks)"
        self.status.set(txt)

    def on_train(self):
        m = train_model(force=True)
        self.update_status()
        if m["samples"]:
            messagebox.showinfo(
                "AI model trained",
                "Model {} fitted on {} students.\nR2 = {:.2f}\nMAE = {:.2f} marks".format(
                    MODEL_VERSION, m["samples"], m["r2"] or 0, m["mae"] or 0))
        else:
            messagebox.showwarning(
                "Not enough data",
                "Add at least 5 students with marks, then train again.")

    def on_predict_all(self):
        ids = [r[0] for r in db_query("SELECT student_id FROM students ORDER BY student_id")]
        if not ids:
            return messagebox.showwarning("No students", "Add students first.")
        count = 0
        for sid in ids:
            try:
                # keep one fresh prediction per student instead of piling up duplicates
                db_execute("DELETE FROM predictions WHERE student_id=?", (sid,))
                insert_row("predictions", [sid, None, None])
                count += 1
            except (sqlite3.Error, ValueError) as e:
                messagebox.showerror("Prediction failed", str(e))
                break
        self.refresh()
        messagebox.showinfo("AI prediction complete",
                            "{} student(s) scored and risk-classified.\n"
                            "Open the Performance Report tab to see the JOIN view.".format(count))


class ReportPage(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        bar = ttk.Frame(self)
        bar.pack(pady=10)
        make_button(bar, "Refresh Report", BLUE, self.refresh).pack(side="left", padx=6)
        make_button(bar, "Load Demo Data", TEAL, self.on_demo).pack(side="left", padx=6)
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, foreground=PRIMARY).pack()

        cols = ("ID", "Roll No", "Student", "Course", "Internal", "External",
                "Total", "Grade", "Att %", "Risk", "Predicted")
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=12, pady=8)
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", height=16)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=115, anchor="w")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.refresh()

    def on_demo(self):
        added, msg = load_demo_data()
        self.refresh()
        messagebox.showinfo("Demo data", msg)

    def refresh(self):
        rows = fetch_performance_report()
        fill_tree(self.tree, rows)
        self.status.set(
            "JOIN of predictions + students + marks + courses   |   {} row(s)".format(len(rows))
            if rows else
            "No predictions yet - load demo data or add records, then run the AI model.")


def build_ui(root):
    setup_style(root)

    header = tk.Frame(root, bg=PRIMARY)
    header.pack(fill="x")
    tk.Label(header, text="AI-Based Student Performance Tracking System",
             bg=PRIMARY, fg="white", font=("Segoe UI", 17, "bold")
             ).pack(anchor="w", padx=18, pady=(12, 0))
    tk.Label(header, text="DBMS Mini-Project  |  Python + SQLite  |  AI score & risk prediction",
             bg=PRIMARY, fg="#BBD3EC", font=("Segoe UI", 10)
             ).pack(anchor="w", padx=18, pady=(0, 12))

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=8, pady=8)
    for t in TABLES:
        page = PredictionPage(nb) if t == "predictions" else TablePage(nb, t)
        nb.add(page, text=t.title())
    nb.add(ReportPage(nb), text="Performance Report")
    nb.bind("<<NotebookTabChanged>>",
            lambda e: nb.nametowidget(nb.select()).refresh())
    return nb


def main():
    init_db()
    root = tk.Tk()
    root.title("AI-Based Student Performance Tracking System")
    root.geometry("1080x700")
    root.minsize(940, 600)
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
