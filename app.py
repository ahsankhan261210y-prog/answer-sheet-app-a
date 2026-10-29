import os
import sqlite3
import difflib
import textwrap
from datetime import datetime
from io import BytesIO

import streamlit as st
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


# ---------------- CONFIGURATION ----------------

st.set_page_config(
    page_title="Answer Sheet Checking",
    page_icon="📘",
    layout="wide"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# On cloud hosting, set ANSWER_DB_PATH to a permanent folder.
DB_PATH = os.environ.get("ANSWER_DB_PATH", os.path.join(BASE_DIR, "answer_sheet.db"))


def get_secret(name, default):
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name, default)


TEACHER_USERNAME = get_secret("TEACHER_USERNAME", "teacher")
TEACHER_PASSWORD = get_secret("TEACHER_PASSWORD", "teacher123")

# Students must not see the model answer.
PUBLIC_COLUMNS = [
    "id", "student_name", "roll_number", "exam_name", "subject",
    "max_marks", "similarity", "suggested_marks", "final_marks",
    "teacher_feedback", "created_at",
]


# ---------------- DESIGN ----------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,500;8..60,700&display=swap');

:root {
    --ink: #1c2b4a;
    --ink-soft: #55607a;
    --paper: #f4f6fa;
    --line: #d9deea;
    --pen: #c7312b;
    --tick: #2f7d57;
    --wait: #b7791f;
}

html, body, [class*="css"], .stApp {
    font-family: 'Source Sans 3', sans-serif;
    color: var(--ink);
}
.stApp { background: var(--paper); }

h1, h2, h3, .serif {
    font-family: 'Source Serif 4', serif !important;
    color: var(--ink);
    letter-spacing: -0.01em;
}
h1 { font-weight: 700 !important; }

section[data-testid="stSidebar"] {
    background: var(--ink);
}
section[data-testid="stSidebar"] * { color: #e8ecf5 !important; }
section[data-testid="stSidebar"] .stRadio label {
    padding: 6px 4px;
}

/* Page heading with ruled-line feel */
.page-head { border-bottom: 2px solid var(--ink); padding-bottom: 10px; margin-bottom: 22px; }
.page-head p { color: var(--ink-soft); margin: 4px 0 0 0; font-size: 1.02rem; }

/* Counter strip (not cards) */
.counter-strip {
    display: flex; flex-wrap: wrap; gap: 0;
    border: 1px solid var(--line); border-radius: 6px; background: #fff;
    margin-bottom: 26px;
}
.counter { flex: 1 1 160px; padding: 16px 20px; border-right: 1px solid var(--line); }
.counter:last-child { border-right: none; }
.counter .n { font-family: 'Source Serif 4', serif; font-size: 2rem; font-weight: 700; line-height: 1.1; }
.counter .l { color: var(--ink-soft); font-size: 0.92rem; }
.counter.alert .n { color: var(--pen); }

/* Teacher's red-pen score: the one memorable element */
.result-sheet {
    display: flex; flex-wrap: wrap; gap: 28px; align-items: center;
    background: #fff; border: 1px solid var(--line); border-radius: 6px;
    padding: 24px 28px; margin: 12px 0 18px 0;
    background-image: repeating-linear-gradient(transparent, transparent 31px, #e9edf5 32px);
}
.pen-score {
    width: 150px; height: 130px; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    border: 3px solid var(--pen);
    border-radius: 52% 48% 50% 50% / 48% 53% 47% 52%;
    transform: rotate(-4deg); color: var(--pen);
    background: rgba(255,255,255,0.85);
}
.pen-score .num { font-family: 'Source Serif 4', serif; font-size: 2.6rem; font-weight: 700; line-height: 1; }
.pen-score .max { font-size: 1rem; border-top: 2px solid var(--pen); margin-top: 4px; padding-top: 2px; }
.sheet-meta { flex: 1 1 260px; background: rgba(255,255,255,0.9); padding: 8px 12px; border-radius: 4px; }
.sheet-meta .name { font-family: 'Source Serif 4', serif; font-size: 1.35rem; font-weight: 700; }
.sheet-meta .sub { color: var(--ink-soft); }
.sheet-meta .row { margin-top: 6px; }

.badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.85rem; font-weight: 600; border: 1px solid; }
.badge.ok { color: var(--tick); border-color: var(--tick); }
.badge.wait { color: var(--wait); border-color: var(--wait); }

.note {
    border-left: 4px solid var(--wait); background: #fff; padding: 10px 14px;
    color: var(--ink-soft); border-radius: 0 4px 4px 0; margin: 8px 0 16px 0;
}

/* Inputs & buttons */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
    background: var(--ink); color: #fff; border: none; border-radius: 4px;
    font-weight: 600; padding: 0.55rem 1.2rem;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
    background: #2b3f6b; color: #fff;
}
.stButton > button:focus-visible, .stFormSubmitButton > button:focus-visible {
    outline: 3px solid var(--pen); outline-offset: 2px;
}
div[data-testid="stForm"] { background: #fff; border: 1px solid var(--line); border-radius: 6px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def page_head(title, subtitle=""):
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(
        f'<div class="page-head"><h1 style="margin:0">{title}</h1>{sub}</div>',
        unsafe_allow_html=True
    )


def show_df(df):
    # Works on both newer and older Streamlit versions.
    try:
        st.dataframe(df, width="stretch", hide_index=True)
    except TypeError:
        st.dataframe(df, use_container_width=True, hide_index=True)


def public_view(rows):
    df = pd.DataFrame(rows)
    cols = [c for c in PUBLIC_COLUMNS if c in df.columns]
    return df[cols]


def fmt(n):
    return f"{n:g}" if n is not None else "-"


# ---------------- DATABASE ----------------

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS answer_sheet_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            roll_number TEXT NOT NULL,
            exam_name TEXT NOT NULL,
            subject TEXT NOT NULL,
            question TEXT NOT NULL,
            model_answer TEXT NOT NULL,
            student_answer TEXT NOT NULL,
            max_marks REAL NOT NULL,
            similarity REAL NOT NULL,
            suggested_marks REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS answer_sheet_rechecks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            result_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            teacher_comment TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            reviewed_at TEXT DEFAULT '',
            FOREIGN KEY (result_id)
                REFERENCES answer_sheet_results(id)
        )
    """)

    result_columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(answer_sheet_results)"
        ).fetchall()
    }

    if "final_marks" not in result_columns:
        conn.execute("""
            ALTER TABLE answer_sheet_results
            ADD COLUMN final_marks REAL DEFAULT NULL
        """)

    if "teacher_feedback" not in result_columns:
        conn.execute("""
            ALTER TABLE answer_sheet_results
            ADD COLUMN teacher_feedback TEXT DEFAULT ''
        """)

    conn.commit()
    conn.close()


def get_results():
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM answer_sheet_results
        ORDER BY id DESC
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_result_by_id(result_id):
    conn = get_connection()
    row = conn.execute("""
        SELECT * FROM answer_sheet_results
        WHERE id = ?
    """, (result_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_results_by_roll(roll_number):
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM answer_sheet_results
        WHERE LOWER(roll_number) = LOWER(?)
        ORDER BY id DESC
    """, (roll_number,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_result(data):
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO answer_sheet_results (
            student_name, roll_number, exam_name, subject,
            question, model_answer, student_answer, max_marks,
            similarity, suggested_marks, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["student_name"],
        data["roll_number"],
        data["exam_name"],
        data["subject"],
        data["question"],
        data["model_answer"],
        data["student_answer"],
        data["max_marks"],
        data["similarity"],
        data["suggested_marks"],
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    result_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return result_id


def get_rechecks():
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            r.id AS request_id,
            r.result_id,
            r.reason,
            r.status,
            r.teacher_comment,
            r.created_at AS request_date,
            r.reviewed_at,
            a.student_name,
            a.roll_number,
            a.subject,
            a.exam_name,
            a.suggested_marks,
            a.final_marks,
            a.max_marks
        FROM answer_sheet_rechecks r
        LEFT JOIN answer_sheet_results a
            ON r.result_id = a.id
        ORDER BY r.id DESC
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_recheck(result_id, reason):
    conn = get_connection()
    existing = conn.execute("""
        SELECT id FROM answer_sheet_results
        WHERE id = ?
    """, (result_id,)).fetchone()

    if existing is None:
        conn.close()
        raise ValueError("Result not found.")

    conn.execute("""
        INSERT INTO answer_sheet_rechecks (
            result_id, reason, status, teacher_comment,
            created_at, reviewed_at
        )
        VALUES (?, ?, 'Pending', '', ?, '')
    """, (
        result_id,
        reason,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()


def update_recheck(request_id, status, comment):
    conn = get_connection()
    conn.execute("""
        UPDATE answer_sheet_rechecks
        SET status = ?, teacher_comment = ?, reviewed_at = ?
        WHERE id = ?
    """, (
        status,
        comment,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        request_id
    ))
    conn.commit()
    conn.close()


def update_final_marks(result_id, final_marks, teacher_feedback):
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT max_marks FROM answer_sheet_results
            WHERE id = ?
        """, (result_id,)).fetchone()

        if row is None:
            raise ValueError("Result not found.")

        if not 0 <= final_marks <= row["max_marks"]:
            raise ValueError(
                f"Final marks must be between 0 and {row['max_marks']}."
            )

        conn.execute("""
            UPDATE answer_sheet_results
            SET final_marks = ?, teacher_feedback = ?
            WHERE id = ?
        """, (final_marks, teacher_feedback, result_id))

        conn.commit()
    finally:
        conn.close()


def delete_results(result_ids):
    """Deletes the selected results and their recheck requests."""
    if not result_ids:
        return
    conn = get_connection()
    try:
        marks = ",".join("?" for _ in result_ids)
        conn.execute(
            f"DELETE FROM answer_sheet_rechecks WHERE result_id IN ({marks})",
            list(result_ids)
        )
        conn.execute(
            f"DELETE FROM answer_sheet_results WHERE id IN ({marks})",
            list(result_ids)
        )
        conn.commit()
    finally:
        conn.close()


def delete_all_data():
    """Deletes all data and restarts IDs from 1."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM answer_sheet_rechecks")
        conn.execute("DELETE FROM answer_sheet_results")
        conn.execute(
            "DELETE FROM sqlite_sequence WHERE name IN "
            "('answer_sheet_results', 'answer_sheet_rechecks')"
        )
        conn.commit()
    finally:
        conn.close()


# ---------------- ANSWER CHECKING ----------------

def calculate_similarity(model_answer, student_answer):
    model = " ".join(model_answer.lower().split())
    student = " ".join(student_answer.lower().split())

    if not model or not student:
        return 0.0

    return round(
        difflib.SequenceMatcher(None, model, student).ratio() * 100,
        2
    )


def calculate_marks(similarity, max_marks):
    return round(max(0, min(max_marks, max_marks * similarity / 100)), 2)


# ---------------- PDF REPORT ----------------

def create_pdf(result):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_width, page_height = A4

    pdf.setTitle(f"Answer Sheet Result {result['id']}")

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(45, page_height - 50, "Answer Sheet Checking Report")

    pdf.setFont("Helvetica", 9)
    pdf.drawString(45, page_height - 70, "AI-assisted evaluation - teacher review recommended")
    pdf.line(45, page_height - 82, page_width - 45, page_height - 82)

    final_marks = result.get("final_marks")
    teacher_feedback = result.get("teacher_feedback") or ""

    fields = [
        ("Result ID", result["id"]),
        ("Student Name", result["student_name"]),
        ("Roll Number", result["roll_number"]),
        ("Exam", result["exam_name"]),
        ("Subject", result["subject"]),
        ("Question", result["question"]),
        ("Maximum Marks", result["max_marks"]),
        ("Text Similarity", f"{result['similarity']}%"),
        ("Suggested Marks", result["suggested_marks"]),
        (
            "Teacher Final Marks",
            final_marks if final_marks is not None else "Not reviewed yet"
        ),
        ("Teacher Feedback", teacher_feedback or "No feedback"),
        ("Date", result["created_at"])
    ]

    y = page_height - 110

    for label, value in fields:
        lines = textwrap.wrap(str(value), width=70) or [""]

        if y - 14 * len(lines) < 60:
            pdf.showPage()
            y = page_height - 55

        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(45, y, label + ":")
        pdf.setFont("Helvetica", 10)

        for line in lines:
            pdf.drawString(170, y, line)
            y -= 14

        y -= 9

    pdf.setFont("Helvetica-Oblique", 8)
    pdf.drawString(
        45, 35,
        "Similarity is a text-matching estimate, not a guarantee of answer correctness."
    )

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()


# ---------------- RESULT DISPLAY ----------------

def render_result_sheet(result, show_answers=False):
    """Red-pen style result display. Reads from the DB, so it survives
    reruns and page reloads."""
    final_marks = result.get("final_marks")
    reviewed = final_marks is not None
    shown = final_marks if reviewed else result["suggested_marks"]
    badge = (
        '<span class="badge ok">Teacher reviewed</span>'
        if reviewed else
        '<span class="badge wait">Awaiting teacher review</span>'
    )
    label = "Final marks" if reviewed else "Suggested marks"

    st.markdown(f"""
    <div class="result-sheet">
        <div class="pen-score">
            <div class="num">{fmt(shown)}</div>
            <div class="max">{fmt(result['max_marks'])}</div>
        </div>
        <div class="sheet-meta">
            <div class="name">{result['student_name']}</div>
            <div class="sub">Roll {result['roll_number']} &nbsp;|&nbsp; {result['subject']} &nbsp;|&nbsp; {result['exam_name']}</div>
            <div class="row">{label} &nbsp; {badge}</div>
            <div class="row">Text similarity: <b>{result['similarity']}%</b> &nbsp;|&nbsp; Result ID: <b>{result['id']}</b></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if result.get("teacher_feedback"):
        st.markdown(f"**Teacher feedback:** {result['teacher_feedback']}")

    if show_answers:
        with st.expander("View question and answers"):
            st.markdown(f"**Question:** {result['question']}")
            st.markdown(f"**Model answer:** {result['model_answer']}")
            st.markdown(f"**Student answer:** {result['student_answer']}")


# ---------------- INITIALIZE APP ----------------

initialize_database()

if "teacher_logged_in" not in st.session_state:
    st.session_state.teacher_logged_in = False


# ---------------- SIDEBAR ----------------

st.sidebar.markdown("## 📘 Answer Sheet\nChecking System")

page = st.sidebar.radio(
    "Page",
    [
        "Home",
        "Check Answers",
        "Saved Results",
        "Student Result Search",
        "Rechecking Request",
        "Teacher Panel"
    ],
    label_visibility="collapsed"
)

st.sidebar.divider()
st.sidebar.caption("Checking and rechecking, in one place.")
st.sidebar.caption(f"DB: {DB_PATH} | rows: {len(get_results())}")


# ---------------- HOME ----------------

if page == "Home":
    page_head(
        "Answer Sheet Checking",
        "Compare a student's answer with the model answer, save the result, "
        "and request a teacher recheck when needed."
    )

    results = get_results()
    rechecks = get_rechecks()

    total_results = len(results)
    total_students = len(set(
        (r["roll_number"] or "").strip().lower() for r in results
    ))
    pending_requests = sum(1 for r in rechecks if r["status"] == "Pending")
    reviewed_results = sum(1 for r in results if r.get("final_marks") is not None)

    st.markdown(f"""
    <div class="counter-strip">
        <div class="counter"><div class="n">{total_results}</div><div class="l">Saved results</div></div>
        <div class="counter"><div class="n">{total_students}</div><div class="l">Students</div></div>
        <div class="counter {'alert' if pending_requests else ''}"><div class="n">{pending_requests}</div><div class="l">Pending rechecks</div></div>
        <div class="counter"><div class="n">{reviewed_results}</div><div class="l">Teacher reviewed</div></div>
    </div>
    """, unsafe_allow_html=True)

    if results:
        df = pd.DataFrame(results)

        st.subheader("Suggested marks")
        chart_df = df[["student_name", "suggested_marks"]].copy()
        chart_df["student_name"] = (
            chart_df["student_name"].astype(str)
            + " (ID "
            + df["id"].astype(str)
            + ")"
        )
        chart_df = chart_df.set_index("student_name")
        try:
            # Horizontal chart: naam seedhe likhe nazar aate hain.
            st.bar_chart(chart_df, color="#1c2b4a", horizontal=True)
        except TypeError:
            st.bar_chart(chart_df, color="#1c2b4a")

        st.subheader("Recent results")
        show_df(public_view(results[:10]))
    else:
        st.info("No results saved yet. Start from the Check Answers page.")


# ---------------- CHECK ANSWERS ----------------

elif page == "Check Answers":
    page_head("Check Answer", "Fill in the form. The result is saved and will still be here after a reload.")

    # The ?result=ID in the URL brings the result back after a reload.
    last_id = st.session_state.get("last_result_id")
    if last_id is None:
        try:
            last_id = int(st.query_params.get("result"))
        except (TypeError, ValueError):
            last_id = None

    with st.form("answer_check_form"):
        c1, c2 = st.columns(2)
        student_name = c1.text_input("Student Name")
        roll_number = c2.text_input("Roll Number")
        c3, c4 = st.columns(2)
        exam_name = c3.text_input("Exam Name")
        subject = c4.text_input("Subject")
        question = st.text_area("Question")
        a1, a2 = st.columns(2)
        model_answer = a1.text_area("Model Answer", height=170)
        student_answer = a2.text_area("Student Answer", height=170)
        max_marks = st.number_input(
            "Maximum Marks",
            min_value=1.0,
            max_value=1000.0,
            value=10.0,
            step=1.0
        )

        submitted = st.form_submit_button("Check and save result")

    if submitted:
        if not all([
            student_name.strip(),
            roll_number.strip(),
            exam_name.strip(),
            subject.strip(),
            question.strip(),
            model_answer.strip(),
            student_answer.strip()
        ]):
            st.error("Please fill in all fields and try again.")
        else:
            similarity = calculate_similarity(model_answer, student_answer)
            suggested_marks = calculate_marks(similarity, max_marks)

            last_id = save_result({
                "student_name": student_name.strip(),
                "roll_number": roll_number.strip(),
                "exam_name": exam_name.strip(),
                "subject": subject.strip(),
                "question": question.strip(),
                "model_answer": model_answer.strip(),
                "student_answer": student_answer.strip(),
                "max_marks": max_marks,
                "similarity": similarity,
                "suggested_marks": suggested_marks
            })
            st.session_state.last_result_id = last_id
            st.query_params["result"] = str(last_id)
            st.toast(f"Result {last_id} saved")

    # Rendered outside the form, so it does not disappear when the download
    # button is clicked or the page is reloaded.
    if last_id is not None:
        saved = get_result_by_id(last_id)
        if saved:
            st.subheader("Result")
            render_result_sheet(saved, show_answers=True)
            st.markdown(
                '<div class="note">This is only text similarity and does not fully understand '
                'meaning. A teacher should verify the marks.</div>',
                unsafe_allow_html=True
            )
            b1, b2 = st.columns([1, 1])
            b1.download_button(
                "Download result PDF",
                data=create_pdf(saved),
                file_name=f"result_{last_id}.pdf",
                mime="application/pdf",
                key=f"check_pdf_{last_id}"
            )
            if b2.button("Check a new answer"):
                st.session_state.pop("last_result_id", None)
                st.query_params.clear()
                st.rerun()
        else:
            st.session_state.pop("last_result_id", None)
            st.warning(
                "This result was not found in the database. If the app is hosted "
                "on the cloud, the database may have been reset."
            )


# ---------------- SAVED RESULTS ----------------

elif page == "Saved Results":
    page_head("Saved Results")

    results = get_results()

    if not results:
        st.info("No saved results yet.")
    else:
        show_df(public_view(results))

        selected_id = st.selectbox(
            "Select Result ID",
            [r["id"] for r in results]
        )
        selected = get_result_by_id(selected_id)

        if selected:
            render_result_sheet(selected)
            st.download_button(
                "Download PDF report",
                data=create_pdf(selected),
                file_name=f"result_{selected_id}.pdf",
                mime="application/pdf",
                key=f"pdf_{selected_id}"
            )


# ---------------- STUDENT RESULT SEARCH ----------------

elif page == "Student Result Search":
    page_head("Student Result Search", "Enter your Roll Number to view your result.")

    roll_search = st.text_input("Roll Number")

    if roll_search.strip():
        student_results = get_results_by_roll(roll_search.strip())

        if student_results:
            st.success(f"{len(student_results)} result(s) found.")
            show_df(public_view(student_results))

            selected_id = st.selectbox(
                "Select Result ID",
                [r["id"] for r in student_results],
                key="student_pdf_id"
            )
            selected = get_result_by_id(selected_id)
            render_result_sheet(selected)

            st.download_button(
                "Download my result PDF",
                data=create_pdf(selected),
                file_name=f"result_{selected_id}.pdf",
                mime="application/pdf",
                key=f"student_pdf_{selected_id}"
            )
        else:
            st.warning("No result found for this Roll Number.")


# ---------------- RECHECKING REQUEST ----------------

elif page == "Rechecking Request":
    page_head("Rechecking Request", "If you disagree with your marks, submit a request with your reason.")

    results = get_results()

    if not results:
        st.info("First save a result from the Check Answers page.")
    else:
        labels = {
            f"ID {r['id']} | {r['student_name']} | {r['subject']}": r["id"]
            for r in results
        }

        with st.form("recheck_form"):
            chosen = st.selectbox("Select result", list(labels.keys()))
            reason = st.text_area("Reason for rechecking")
            submitted = st.form_submit_button("Submit rechecking request")

        if submitted:
            if not reason.strip():
                st.error("Please enter a reason for rechecking.")
            else:
                try:
                    save_recheck(labels[chosen], reason.strip())
                    st.success("Recheck request submitted.")
                except ValueError as exc:
                    st.error(str(exc))

    st.subheader("Request status")

    requests = get_rechecks()
    if requests:
        show_df(pd.DataFrame(requests))
    else:
        st.info("No recheck requests yet.")


# ---------------- TEACHER PANEL ----------------

elif page == "Teacher Panel":
    page_head("Teacher Panel")

    if not st.session_state.teacher_logged_in:
        with st.form("teacher_login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            login = st.form_submit_button("Login")

        if login:
            if username == TEACHER_USERNAME and password == TEACHER_PASSWORD:
                st.session_state.teacher_logged_in = True
                st.rerun()
            else:
                st.error("Incorrect username or password.")

    else:
        if st.button("Logout"):
            st.session_state.teacher_logged_in = False
            st.rerun()

        st.subheader("Rechecking requests")

        requests = get_rechecks()

        if not requests:
            st.info("No recheck requests.")
        else:
            show_df(pd.DataFrame(requests))

            with st.form("review_request_form"):
                request_id = st.selectbox(
                    "Select Request ID",
                    [r["request_id"] for r in requests]
                )
                status = st.selectbox(
                    "Request Status",
                    ["Pending", "Approved", "Rejected", "Completed"]
                )
                comment = st.text_area("Teacher Comment")
                review_submit = st.form_submit_button("Save request review")

            if review_submit:
                update_recheck(request_id, status, comment.strip())
                st.success("Recheck request updated.")
                st.rerun()

        st.divider()
        st.subheader("Final marks")

        results = get_results()

        if not results:
            st.info("No results available yet.")
        else:
            result_options = {
                f"ID {r['id']} | {r['student_name']} | {r['subject']} | Roll {r['roll_number']}": r["id"]
                for r in results
            }

            with st.form("final_marks_form"):
                selected_label = st.selectbox(
                    "Select student result",
                    list(result_options.keys())
                )
                selected_id = result_options[selected_label]
                selected_result = get_result_by_id(selected_id)

                max_marks = float(selected_result["max_marks"])
                existing_final = selected_result.get("final_marks")
                existing_feedback = selected_result.get("teacher_feedback") or ""

                st.write(f"**Maximum marks:** {fmt(max_marks)}  |  **Suggested marks:** {fmt(selected_result['suggested_marks'])}")

                final_marks = st.number_input(
                    "Teacher Final Marks",
                    min_value=0.0,
                    max_value=max_marks,
                    value=(
                        float(existing_final)
                        if existing_final is not None
                        else float(selected_result["suggested_marks"])
                    ),
                    step=0.5
                )
                final_feedback = st.text_area(
                    "Teacher Feedback",
                    value=existing_feedback
                )

                save_final = st.form_submit_button("Save final marks")

            if save_final:
                try:
                    update_final_marks(selected_id, final_marks, final_feedback.strip())
                    st.success("Final marks and feedback saved.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        st.divider()
        st.subheader("All saved results")
        latest_results = get_results()

        if latest_results:
            show_df(pd.DataFrame(latest_results))

            st.subheader("Backup")
            st.caption("The database can reset on cloud hosting, so download a backup regularly.")
            st.download_button(
                "Download all results (CSV)",
                data=pd.DataFrame(latest_results).to_csv(index=False).encode("utf-8"),
                file_name="answer_sheet_results_backup.csv",
                mime="text/csv"
            )

        st.divider()
        st.subheader("Delete data")

        delete_source = get_results()

        if not delete_source:
            st.info("There is no data to delete.")
        else:
            delete_options = {
                f"ID {r['id']} | {r['student_name']} | {r['subject']} | Roll {r['roll_number']}": r["id"]
                for r in delete_source
            }

            with st.form("delete_selected_form"):
                chosen_labels = st.multiselect(
                    "Select the results to delete",
                    list(delete_options.keys())
                )
                confirm_selected = st.checkbox(
                    "Yes, I am sure. Their recheck requests will also be deleted."
                )
                delete_selected = st.form_submit_button("Delete selected results")

            if delete_selected:
                if not chosen_labels:
                    st.error("Select at least one result first.")
                elif not confirm_selected:
                    st.error("Tick the box to confirm before deleting.")
                else:
                    delete_results([delete_options[l] for l in chosen_labels])
                    st.session_state.pop("last_result_id", None)
                    st.query_params.clear()
                    st.rerun()

            with st.expander("Delete all data"):
                st.warning("This permanently deletes all results and recheck requests. Download the CSV backup above first.")
                with st.form("delete_all_form"):
                    typed = st.text_input("Type DELETE to confirm")
                    delete_all = st.form_submit_button("Delete all data now")

                if delete_all:
                    if typed.strip() == "DELETE":
                        delete_all_data()
                        st.session_state.pop("last_result_id", None)
                        st.query_params.clear()
                        st.rerun()
                    else:
                        st.error("Type exactly DELETE to confirm.")