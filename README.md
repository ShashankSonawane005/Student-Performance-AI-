# AI-Based Student Performance Tracking System

**DBMS Mini-Project (TAE-2) - Python + SQLite + Tkinter**

Predicts a student's expected final score and classifies the risk level
using a small linear-regression model written in pure Python (no pip
packages required), then stores and reports the results through a
fully relational SQLite database.

## Features
- **4 tables**: `students`, `courses`, `marks`, `predictions`
  - Primary keys on every table
  - Foreign keys with `ON DELETE CASCADE`
  - `UNIQUE` (roll no, email, course code, student+course pair)
  - `CHECK` constraints (attendance 0-100, grade in S/A/B/C/D/E/F, risk in Low/Medium/High)
- **Indexes** on the foreign-key columns for faster joins
- **View** `v_student_performance` - consolidated average per student (SQL `GROUP BY` + aggregates)
- **Trigger** `trg_marks_grade` - computes `total` and `grade` automatically on insert
- **Database connectivity** with Python's built-in `sqlite3` (parameterised queries)
- **Insert / Update / Delete / View** for all 4 tables through the GUI
- **Live search** box on every table
- **AI model**: ridge linear regression that learns from the data in the database
  (`Train AI Model` button), predicts every student's final score and flags
  Low / Medium / High risk (`Predict All Students`)
- **JOIN report**: one row per student per course, combining
  `predictions + students + marks + courses` in a single `SELECT`

## Requirements
- Python 3.8 or newer
- Tkinter (bundled with the standard Windows/macOS Python installer).
  On Debian/Ubuntu: `sudo apt install python3-tk`
- No other packages - `sqlite3` is part of the standard library

## How to run
```
python app.py
```
`performance.db` is created automatically on the first run.

## Suggested demo order (for the viva)
1. Open the **Performance Report** tab and click **Load Demo Data**
   (8 students, 5 courses, 38 marks).
2. Go to **Predictions** and click **Train AI Model** - it prints the number of
   students used, R² and MAE.
3. Click **Predict All Students** - every student gets a predicted score and risk level.
4. Open **Performance Report** again - the four-table JOIN now shows
   marks, grade, attendance, predicted score and risk.
5. Show CRUD live: insert a new student in **Students**, edit a `marks` row in
   **Marks** (total and grade recompute instantly), delete a student and point
   out that their marks and predictions disappear too (CASCADE).

## Tables

| Table | Columns | Notes |
|---|---|---|
| `students` | student_id (PK), name, roll_no (UQ), email (UQ), branch, semester, attendance_pct, study_hours | students |
| `courses` | course_id (PK), course_code (UQ), course_name, credits | subjects |
| `marks` | mark_id (PK), student_id (FK), course_id (FK), internal_marks, external_marks, total, grade | UNIQUE(student_id, course_id); total+grade auto-filled |
| `predictions` | prediction_id (PK), student_id (FK), attendance_pct, study_hours, avg_marks, predicted_score, risk_level, model_info, created_on | output of the AI model |

## The AI part in one paragraph
`train_model()` reads the view `v_student_performance`, builds the design matrix
`[1, attendance_pct, study_hours, avg_internal]`, and solves the ridge
regression normal equations with Gauss-Jordan elimination implemented in pure
Python. Predictions are clipped to 0-100, and `risk_level()` turns the score and
attendance into Low / Medium / High. If the database has fewer than five
students with marks, the model falls back to sensible default weights so the
program never crashes.

## Error handling
- `UNIQUE`, `FOREIGN KEY` and `CHECK` violations are caught and shown as
  readable messages instead of tracebacks.
- Numeric fields are validated before the SQL is built.
- `foreign_keys` is switched on for every connection, so cascade deletes work.

## Files
- `app.py` - the complete application (schema, CRUD, AI model, GUI)
- `TAE_2_CODE.ipynb` - notebook version (also has an `ipywidgets` dashboard for Colab/Jupyter)
- `docs/index.html` - project website (can be published with GitHub Pages)
- `README.md` - this file

