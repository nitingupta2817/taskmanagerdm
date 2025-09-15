import streamlit as st
from supabase import create_client
from datetime import datetime

# ---------------- SUPABASE SETUP ----------------
SUPABASE_URL = "https://fijvjhbhxdbinqdiiytq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZpanZqaGJoeGRiaW5xZGlpeXRxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NzkxNTk5OSwiZXhwIjoyMDczNDkxOTk5fQ.8tZln8rHlB_OpDG4q_w3TeRTdJyPKQJr_OF-q7QlGz8"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- HELPER FUNCTIONS ----------------
def add_user(username, password, role):
    try:
        supabase.table("users").insert({
            "username": username,
            "password": password,
            "role": role
        }).execute()
    except:
        pass

def login_user(username, password):
    response = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
    data = response.data
    return data[0] if data else None

def assign_task(user, task):
    supabase.table("tasks").insert({
        "assigned_to": user,
        "task": task,
        "status": "Pending",
        "date": datetime.now().strftime("%Y-%m-%d")
    }).execute()

def get_user_tasks(user):
    response = supabase.table("tasks").select("*").eq("assigned_to", user).execute()
    return response.data

def update_task_status(task_id, status):
    supabase.table("tasks").update({"status": status}).eq("id", task_id).execute()

def get_all_tasks():
    response = supabase.table("tasks").select("*").execute()
    return response.data

def get_all_users():
    response = supabase.table("users").select("username").eq("role", "Team").execute()
    return [row["username"] for row in response.data]

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
            st.session_state.username = user["username"]
            st.session_state.role = user["role"]
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
            st.write(f"📌 Task ID: {t['id']} | User: {t['assigned_to']} | Task: {t['task']} | Status: {t['status']} | Date: {t['date']}")

    # --- TEAM PANEL ---
    else:
        st.subheader("My Tasks")
        tasks = get_user_tasks(st.session_state.username)

        # Track if any task updated
        task_updated_in_this_run = False

        for t in tasks:
            st.write(f"📌 {t['task']} - Status: {t['status']}")
            if t['status'] == "Pending":
                btn_key = f"done_{t['id']}"
                if st.button("Mark Done", key=btn_key):
                    update_task_status(t['id'], "Done")
                    task_updated_in_this_run = True

        # Safely rerun once after all updates
        if task_updated_in_this_run:
            st.success("Task Updated!")
            st.experimental_rerun()
