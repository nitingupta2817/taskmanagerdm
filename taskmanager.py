import streamlit as st
import sqlite3
from datetime import datetime

# ---------------- DB SETUP ----------------
conn = sqlite3.connect("crm.db", check_same_thread=False)
c = conn.cursor()

# Create tables
c.execute('''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT,
    role TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assigned_to TEXT,
    task TEXT,
    status TEXT,
    date TEXT
)''')

conn.commit()

# ---------------- HELPER FUNCTIONS ----------------
def add_user(username, password, role):
    try:
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                  (username, password, role))
        conn.commit()
    except:
        pass

def login_user(username, password):
    c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
    return c.fetchone()

def assign_task(user, task):
    c.execute("INSERT INTO tasks (assigned_to, task, status, date) VALUES (?, ?, ?, ?)",
              (user, task, "Pending", datetime.now().strftime("%Y-%m-%d")))
    conn.commit()

def get_user_tasks(user):
    c.execute("SELECT * FROM tasks WHERE assigned_to=?", (user,))
    return c.fetchall()

def update_task_status(task_id, status):
    c.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    conn.commit()

def get_all_tasks():
    c.execute("SELECT * FROM tasks")
    return c.fetchall()

def get_all_users():
    c.execute("SELECT username FROM users WHERE role='Team'")
    return [row[0] for row in c.fetchall()]

# ---------------- STREAMLIT APP ----------------
st.title("📋 Simple CRM - Task Manager")

# --- SESSION STATE INIT ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""

# --- MENU ---
if not st.session_state.logged_in:
    menu = ["Login", "Register"]
    choice = st.sidebar.selectbox("Menu", menu)
else:
    choice = "Dashboard"

# --- REGISTER ---
if choice == "Register":
    st.subheader("Create New Account")
    new_user = st.text_input("Username")
    new_pass = st.text_input("Password", type="password")
    role = st.selectbox("Role", ["Admin", "Team"])
    if st.button("Register"):
        add_user(new_user, new_pass, role)
        st.success("User registered successfully! Go to Login.")

# --- LOGIN ---
elif choice == "Login":
    st.subheader("Login to Your Account")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        user = login_user(username, password)
        if user:
            st.session_state.logged_in = True
            st.session_state.username = user[1]
            st.session_state.role = user[3]
            st.experimental_rerun()
        else:
            st.error("Invalid credentials")

# --- DASHBOARD ---
elif choice == "Dashboard":
    st.success(f"Welcome {st.session_state.username} ({st.session_state.role})")

    # LOGOUT BUTTON
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.role = ""
        st.experimental_rerun()

    # --- ADMIN PANEL ---
    if st.session_state.role == "Admin":
        st.subheader("Admin Panel")

        team_users = get_all_users()
        if team_users:
            task_user = st.selectbox("Select Team Member", team_users)
            task_options = ["SBM", "Article Submission", "Blog Submission", "Forum"]
            task_desc = st.selectbox("Select Task", task_options)

            if st.button("Assign Task"):
                assign_task(task_user, task_desc)
                st.success(f"Task '{task_desc}' assigned to {task_user}")
        else:
            st.warning("No team members found. Please register users first.")

        st.subheader("All Tasks")
        tasks = get_all_tasks()
        for t in tasks:
            st.write(f"📌 Task ID: {t[0]} | User: {t[1]} | Task: {t[2]} | Status: {t[3]} | Date: {t[4]}")

    # --- TEAM PANEL ---
    else:
        st.subheader("My Tasks")
        tasks = get_user_tasks(st.session_state.username)
        for t in tasks:
            st.write(f"📌 {t[2]} - Status: {t[3]}")
            if t[3] == "Pending":
                if st.button(f"Mark Done - Task {t[0]}"):
                    update_task_status(t[0], "Done")
                    st.success("Task Updated!")
                    st.experimental_rerun()
