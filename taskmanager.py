# ---------------- IMPORTS ----------------
import streamlit as st
from supabase import create_client
from datetime import date, datetime, timedelta
import pandas as pd
import plotly.express as px
import json

# ---------------- PAGE & CLIENT ----------------
st.set_page_config(page_title="Advanced CRM - Task Manager", page_icon="📋", layout="wide")

SUPABASE_URL = "https://fijvjhbhxdbinqdiiytq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZpanZqaGJoeGRiaW5xZGlpeXRxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTc5MTU5OTksImV4cCI6MjA3MzQ5MTk5OX0.aR5Sl9Z9wnCMQhRwHJ6dEXwAWTnxn-yxDqomL9KEHag"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Compatibility helper for Streamlit rerun across versions
try:
    _rerun = st.rerun          # New API
except AttributeError:
    _rerun = st.experimental_rerun  # Old API

# ---------------- DEFAULT TASK TYPES ----------------
DEFAULT_TASK_TYPES = [
    "Forum Submission", "SBM", "Social Bookmarking", "Web 2.0/Profile Creation",
    "Podcast", "Classified Ads", "Forum Posting", "Q&A / Quora Submission",
    "Blog Submission", "Mini blog/article submission", "Tier-2 Backlinks",
    "Image Submission", "Blog SEO", "Document Sharing/PDF Sharing",
    "Infographic Submission / Business listings", "Guest Posting",
    "Competitor Backlinks", "Indexed Blogs (Wordpress, Blogger, Weebly)",
    "Social Signals", "On-page Blog", "Create Lost Backlinks"
]

# ---------------- UTIL ----------------
def _to_datestr(d):
    return d if isinstance(d, str) else d.strftime("%Y-%m-%d")

def _link(url: str) -> str:
    if not url:
        return ""
    return f"[{url}]({url})"

def _status_from_progress(done: int, total: int, fallback: str = "Pending") -> str:
    if total <= 0: return fallback
    if done <= 0: return "Pending"
    if done >= total: return "Done"
    return "Half"

def _now_utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


# ---------------- AUTH HELPERS (demo only) ----------------
def add_user(username, password, role):
    supabase.table("users").insert({"username": username, "password": password, "role": role}).execute()

def update_user(old_username, new_username, new_role):
    supabase.table("users").update({"username": new_username, "role": new_role}).eq("username", old_username).execute()

def delete_users(usernames):
    for username in usernames:
        supabase.table("users").delete().eq("username", username).execute()

def login_user(username, password):
    response = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
    return response.data[0] if response.data else None

def get_all_users():
    return supabase.table("users").select("*").execute().data

# ---------------- TASK TYPE HELPERS ----------------
def get_all_task_types():
    response = supabase.table("task_types").select("*").execute()
    if not response.data:
        for t in DEFAULT_TASK_TYPES:
            supabase.table("task_types").insert({"task_name": t}).execute()
        response = supabase.table("task_types").select("*").execute()
    return [t['task_name'] for t in response.data]

def add_task_type(task_name):
    supabase.table("task_types").insert({"task_name": task_name}).execute()

def delete_task_types(task_names, safe=True):
    if not task_names:
        return []
    skipped = []
    for name in task_names:
        if safe:
            used = supabase.table("tasks").select("id").eq("task", name).limit(1).execute()
            if getattr(used, "data", None) and len(used.data) > 0:
                skipped.append(name)
                continue
        supabase.table("task_types").delete().eq("task_name", name).execute()
    return skipped

# ---------------- TASK HELPERS ----------------
def assign_task_with_details(users, tasks_with_qty, date_val, deadline, remarks="", details_list=None):
    date_str = _to_datestr(date_val)
    deadline_str = _to_datestr(deadline)
    details_list = details_list or []

    for user in users:
        for task_name, qty in tasks_with_qty.items():
            payload = {
                "assigned_to": user,
                "task": task_name,
                "status": "Pending",
                "date": date_str,
                "deadline": deadline_str,
                "quantity": int(qty),
                "quantity_done": 0,
                "remarks": remarks,
                "updated_at": _now_utc().isoformat()  # keep fresh if column exists
            }

            ins = supabase.table("tasks").insert(payload).execute()

            task_id = None
            if getattr(ins, "data", None):
                try:
                    task_id = ins.data[0]["id"]
                except (IndexError, KeyError, TypeError):
                    task_id = None

            if task_id is None:
                lookup = (
                    supabase.table("tasks")
                    .select("id")
                    .eq("assigned_to", user)
                    .eq("task", task_name)
                    .eq("date", date_str)
                    .eq("deadline", deadline_str)
                    .order("id", desc=True)
                    .limit(1)
                    .execute()
                )
                if getattr(lookup, "data", None):
                    task_id = lookup.data[0]["id"]

            if not task_id:  # couldn’t resolve; skip attaching details
                continue

            if details_list:
                child_rows = []
                for d in details_list:
                    if not any([d.get("title"), d.get("url"), d.get("keywords"), d.get("description")]):
                        continue
                    child_rows.append({
                        "task_id": task_id,
                        "title": (d.get("title") or "").strip() or None,
                        "url": (d.get("url") or "").strip() or None,
                        "keywords": (d.get("keywords") or "").strip() or None,
                        "description": (d.get("description") or "").strip() or None
                    })
                if child_rows:
                    supabase.table("task_details").insert(child_rows).execute()

def get_user_tasks(user):
    return supabase.table("tasks").select("*").eq("assigned_to", user).order("date").execute().data

def get_all_tasks():
    return supabase.table("tasks").select("*").order("date").execute().data

def update_task(task_id, task=None, assigned_to=None, status=None, remarks=None, quantity=None,
                date_val=None, deadline=None, title=None, url=None, keywords=None, description=None,
                quantity_done=None):
    update_data = {"updated_at": _now_utc().isoformat()}
    if task: update_data["task"] = task
    if assigned_to: update_data["assigned_to"] = assigned_to
    if status: update_data["status"] = status
    if remarks is not None: update_data["remarks"] = remarks
    if quantity is not None: update_data["quantity"] = int(quantity)
    if date_val: update_data["date"] = _to_datestr(date_val)
    if deadline: update_data["deadline"] = _to_datestr(deadline)
    if title is not None: update_data["title"] = title
    if url is not None: update_data["url"] = url
    if keywords is not None: update_data["keywords"] = keywords
    if description is not None: update_data["description"] = description
    if quantity_done is not None:
        update_data["quantity_done"] = int(max(0, quantity_done))

    supabase.table("tasks").update(update_data).eq("id", task_id).execute()

def delete_tasks(task_ids):
    for tid in task_ids:
        supabase.table("tasks").delete().eq("id", tid).execute()

# ---------------- TASK DETAILS HELPERS ----------------
def get_task_details(task_id):
    return supabase.table("task_details").select("*").eq("task_id", task_id).order("id").execute().data

def add_task_detail_row(task_id, title=None, url=None, keywords=None, description=None):
    payload = {"task_id": task_id, "title": title or None, "url": url or None, "keywords": keywords or None, "description": description or None}
    supabase.table("task_details").insert(payload).execute()

def delete_task_detail_rows(detail_ids):
    if not detail_ids: return
    for did in detail_ids:
        supabase.table("task_details").delete().eq("id", did).execute()

def get_task_details_bulk(task_ids):
    if not task_ids: return []
    return (
        supabase.table("task_details")
        .select("*")
        .in_("task_id", task_ids)
        .order("task_id").order("id")
        .execute()
    ).data

# ---------------- TO-DO HELPERS ----------------
def add_todo(date_val, title, notes, created_by, status="Pending"):
    payload = {
        "date": _to_datestr(date_val),
        "title": title.strip(),
        "notes": (notes or "").strip(),
        "status": status,
        "created_by": created_by,
        "updated_at": _now_utc().isoformat()
    }
    supabase.table("todos").insert(payload).execute()

def get_todos(from_date=None, to_date=None, status=None, created_by=None):
    q = supabase.table("todos").select("*").order("date").order("id")
    if from_date: q = q.gte("date", _to_datestr(from_date))
    if to_date:   q = q.lte("date", _to_datestr(to_date))
    if status and status in ("Pending","Done"): q = q.eq("status", status)
    if created_by: q = q.eq("created_by", created_by)
    return q.execute().data

def update_todo(todo_id, title=None, notes=None, status=None, date_val=None):
    data = {"updated_at": _now_utc().isoformat()}
    if title is not None: data["title"] = title.strip()
    if notes is not None: data["notes"] = (notes or "").strip()
    if status in ("Pending","Done"): data["status"] = status
    if date_val is not None: data["date"] = _to_datestr(date_val)
    supabase.table("todos").update(data).eq("id", todo_id).execute()

def delete_todos(todo_ids):
    for tid in todo_ids:
        supabase.table("todos").delete().eq("id", tid).execute()

# ---------------- DESKTOP NOTIFICATIONS ----------------
def show_browser_notifications(messages):
    """
    messages: list of {"title": "...", "body": "..."}
    Uses the Browser Notification API via a tiny HTML/JS payload.
    """
    if not messages: return
    payload = {
        "messages": messages
    }
    html = f"""
    <script>
      const data = {json.dumps(payload)};
      (async () => {{
        if (!("Notification" in window)) return;
        let perm = Notification.permission;
        try {{
          if (perm !== "granted") perm = await Notification.requestPermission();
        }} catch (e) {{}}
        if (perm === "granted") {{
          data.messages.forEach((m, i) => {{
            setTimeout(() => new Notification(m.title, {{ body: m.body }}), i * 400);
          }});
        }}
      }})();
    </script>
    """
    # Height 0 keeps it invisible
    st.components.v1.html(html, height=0)

def poll_for_new_done_events(init=False):
    """
    Poll tasks that are Done and notify Admins when a task has newly become Done.
    - Tracks last seen done IDs & timestamps in session_state.
    """
    if "done_seen_ids" not in st.session_state:
        st.session_state.done_seen_ids = set()
    if "done_last_check" not in st.session_state:
        st.session_state.done_last_check = _now_utc() - timedelta(minutes=10)

    # Fetch recently updated tasks (last 24h) to keep payload small
    since = (_now_utc() - timedelta(hours=24)).isoformat()
    try:
        # If updated_at column exists, filter; else fall back to status filter only
        q = supabase.table("tasks").select("*").eq("status", "Done").order("updated_at", desc=True)
        tasks = q.gte("updated_at", since).limit(500).execute().data
    except Exception:
        tasks = supabase.table("tasks").select("*").eq("status", "Done").order("id", desc=True).limit(500).execute().data

    new_msgs = []
    current_done_ids = set()
    for t in tasks or []:
        tid = int(t["id"])
        current_done_ids.add(tid)
        if init:
            # On first load, seed but don't notify old items
            continue
        if tid not in st.session_state.done_seen_ids:
            who = t.get("assigned_to", "User")
            task_name = t.get("task", "Task")
            new_msgs.append({
                "title": "Task Completed",
                "body": f"{who} marked '{task_name}' as Done (#{tid})."
            })

    # Update seen set
    st.session_state.done_seen_ids |= current_done_ids
    st.session_state.done_last_check = _now_utc()

    # Fire notifications if any
    if new_msgs:
        show_browser_notifications(new_msgs)

# ---------------- STATE ----------------
st.title("📋 Advanced CRM - Task Manager")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""
if "details_draft" not in st.session_state:
    st.session_state.details_draft = []

# ---------------- AUTH UI ----------------
if not st.session_state.logged_in:
    menu = ["Login", "Register"]
    choice = st.sidebar.selectbox("Menu", menu)

    if choice == "Register":
        st.subheader("Create New Account")
        new_user = st.text_input("Username")
        new_pass = st.text_input("Password", type="password")
        role = st.selectbox("Role", ["Admin", "Team"])
        if st.button("Register"):
            if not new_user or not new_pass:
                st.error("Username and password are required.")
            else:
                add_user(new_user, new_pass, role)
                st.success("User registered successfully! Go to Login.")

    elif choice == "Login":
        st.subheader("Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            user = login_user(username, password)
            if user:
                st.session_state.logged_in = True
                st.session_state.username = user["username"]
                st.session_state.role = user["role"]
                _rerun()
            else:
                st.error("Invalid credentials")

# ---------------- MAIN (ROLE-BASED) ----------------
else:
    st.sidebar.success(f"Logged in as {st.session_state.username} ({st.session_state.role})")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.role = ""
        _rerun()

    if st.session_state.role == "Admin":
        menu = ["User Management", "Task List Management", "Add New Task", "Task Management", "To-Do", "Reports"]
    else:
        menu = ["My Tasks", "My To-Do"]

    choice = st.sidebar.selectbox("Menu", menu)

    # Seed notification memory once per session to avoid spamming on first render
    if st.session_state.role == "Admin":
        poll_for_new_done_events(init=True)

    # ---------- USER MANAGEMENT (Admin) ----------
    if choice == "User Management" and st.session_state.role == "Admin":
        st.subheader("Manage Users")
        users = get_all_users()
        user_list = [f"{u['username']} ({u['role']})" for u in users]

        col1, col2 = st.columns(2)
        with col1:
            selected_users = st.multiselect("Select users to delete", user_list)
            if st.button("Delete Selected Users"):
                delete_users([u.split(" ")[0] for u in selected_users])
                st.success("Selected users deleted!")
                _rerun()

        with col2:
            edit_user_select = st.selectbox("Select a user to edit", ["--"] + user_list)
            if edit_user_select != "--":
                new_username = st.text_input("New Username")
                new_role = st.selectbox("New Role", ["Admin", "Team"])
                if st.button("Update User"):
                    old_username = edit_user_select.split(" ")[0]
                    update_user(old_username, new_username or old_username, new_role)
                    st.success("User updated!")
                    _rerun()

    # ---------- TASK LIST MANAGEMENT (Admin) ----------
    elif choice == "Task List Management" and st.session_state.role == "Admin":
        st.subheader("Manage Task Types")
        task_types = get_all_task_types()

        col_a, col_b = st.columns([1, 1])
        with col_a:
            st.markdown("**Existing Task Types**")
            st.write(task_types)

            new_task_type = st.text_input("Add New Task Type")
            if st.button("Add Task Type"):
                if new_task_type:
                    add_task_type(new_task_type.strip())
                    st.success(f"Task type '{new_task_type}' added!")
                    _rerun()
                else:
                    st.warning("Enter a task type name before adding.")

        with col_b:
            st.markdown("**Delete Task Types**")
            types_to_delete = st.multiselect("Select task types to delete", task_types)
            safe_delete = st.checkbox("Prevent deletion if any task uses the type (recommended)", value=True)

            if st.button("Delete Selected Types"):
                if not types_to_delete:
                    st.info("Select at least one type to delete.")
                else:
                    skipped = delete_task_types(types_to_delete, safe=safe_delete)
                    deleted = list(set(types_to_delete) - set(skipped))
                    if deleted: st.success("Deleted: " + ", ".join(sorted(deleted)))
                    if skipped:
                        st.warning(
                            "Skipped (in use): " + ", ".join(sorted(skipped)) +
                            (" — uncheck the safety box to force delete (not recommended)." if safe_delete else "")
                        )
                    _rerun()

    # ---------- ADD NEW TASK (Admin) ----------
    elif choice == "Add New Task" and st.session_state.role == "Admin":
        st.subheader("Assign Tasks to Users")

        users = get_all_users()
        team_users = [u['username'] for u in users if u['role']=="Team"]
        selected_users = st.multiselect("Select Team Members", team_users)

        task_types = get_all_task_types()
        selected_tasks = st.multiselect("Select Tasks", task_types)

        st.markdown("#### Quantities")
        tasks_with_qty = {}
        for task in selected_tasks:
            tasks_with_qty[task] = st.number_input(f"Quantity for '{task}'", min_value=1, value=1, key=f"qty_{task}")

        st.markdown("### Optional Task Details (visible to assignee) — add multiple rows")
        with st.form("detail_add_form"):
            colA, colB = st.columns([1, 1])
            with colA:
                d_title = st.text_input("Title", key="detail_title")
                d_url = st.text_input("URL", key="detail_url")
            with colB:
                d_keywords = st.text_input("Keywords (comma-separated)", key="detail_keywords")
                d_description = st.text_area("Description", key="detail_description")
            add_clicked = st.form_submit_button("Add Detail to List")
            if add_clicked:
                st.session_state.details_draft.append({
                    "title": d_title.strip(),
                    "url": d_url.strip(),
                    "keywords": d_keywords.strip(),
                    "description": d_description.strip()
                })
                st.success("Detail added to list.")

        if st.session_state.details_draft:
            st.markdown("**Draft Details:**")
            for i, d in enumerate(st.session_state.details_draft):
                with st.expander(f"Detail #{i+1}: {d.get('title') or '(no title)'}"):
                    st.write(f"**URL:** {d.get('url','')}")
                    st.write(f"**Keywords:** {d.get('keywords','')}")
                    st.write(f"**Description:** {d.get('description','')}")
                    if st.button("Remove this detail", key=f"remove_detail_{i}"):
                        st.session_state.details_draft.pop(i)
                        _rerun()

        st.divider()
        remarks = st.text_input("Remarks", "")
        colD, colE = st.columns(2)
        with colD:
            date_val = st.date_input("Task Date", value=date.today())
        with colE:
            deadline = st.date_input("Deadline", value=date.today())

        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            if st.button("Add Task"):
                if selected_users and tasks_with_qty:
                    assign_task_with_details(
                        selected_users,
                        tasks_with_qty,
                        _to_datestr(date_val),
                        _to_datestr(deadline),
                        remarks,
                        details_list=st.session_state.details_draft
                    )
                    st.success("Tasks assigned to selected users!")
                    st.session_state.details_draft = []
                else:
                    st.warning("Select at least one user and one task.")

        with col_btn2:
            if st.button("Clear Details List"):
                st.session_state.details_draft = []
                st.info("Draft details cleared.")

    # ---------- TASK MANAGEMENT (Admin) ----------
    elif choice == "Task Management" and st.session_state.role == "Admin":
        st.subheader("View/Edit/Delete Assigned Tasks")

        # Auto-poll every 15s to catch new Done events and notify
        st_autorefresh_key = "poll_tasks_done"
        st.experimental_memo.clear() if False else None  # placeholder to calm linters
        st_autorefresh = st.experimental_rerun if False else None  # placeholder

        # Use Streamlit native autorefresh if available
        try:
            st_autorefresh = st.experimental_singleton  # just to test attribute
            st_autorefresh = None
        except Exception:
            st_autorefresh = None
        try:
            # Streamlit provides st.runtime.legacy_caching? Avoid. Use built-in helper:
            from streamlit.runtime.scriptrunner import add_script_run_ctx  # noqa: F401
        except Exception:
            pass
        # Real refresh:
        try:
            st_autorefresh_func = st.experimental_rerun
        except Exception:
            st_autorefresh_func = None
        # Use the official helper:
        try:
            from streamlit_autorefresh import st_autorefresh as auto
            auto(interval=15000, key="auto_poll_done")
        except Exception:
            # Fallback: small manual interval prompt (no-op)
            pass

        # Poll + notify (non-initial)
        poll_for_new_done_events(init=False)

        tasks = get_all_tasks()
        if tasks:
            task_list = [
                f"{t['id']} | {t['task']} | {t['assigned_to']} | {t['status']} | {t.get('date','')} | {t.get('deadline','')} | Qty:{t.get('quantity',1)} | Done:{t.get('quantity_done',0)}"
                for t in tasks
            ]
            colL, colR = st.columns([1, 1])
            with colL:
                selected_tasks_to_delete = st.multiselect("Select tasks to delete", task_list, key="delete_tasks_list")
                if st.button("Delete Selected Tasks"):
                    delete_tasks([int(t.split("|")[0]) for t in selected_tasks_to_delete])
                    st.success("Selected tasks deleted!")
                    _rerun()

            with colR:
                edit_task_select = st.selectbox("Select task to edit", ["--"] + task_list, key="edit_task_select")
                if edit_task_select != "--":
                    task_id = int(edit_task_select.split("|")[0])
                    details_rows = get_task_details(task_id)

                    task_types = get_all_task_types()
                    users = get_all_users()
                    new_task_name = st.selectbox("Task Name", task_types, key="adm_edit_task_name")
                    new_assigned_to = st.selectbox("Assigned To", [u['username'] for u in users if u['role']=="Team"], key="adm_edit_assigned_to")
                    new_status = st.selectbox("Status", ["Pending", "Half", "Done"], key="adm_edit_status")
                    new_remarks = st.text_input("Remarks", key="adm_edit_remarks")
                    new_quantity = st.number_input("Quantity", min_value=1, value=1, key="adm_edit_qty")
                    new_quantity_done = st.number_input("Quantity Done", min_value=0, value=0, key="adm_edit_qty_done")
                    new_date_val = st.date_input("Date", key="adm_edit_date")
                    new_deadline = st.date_input("Deadline", key="adm_edit_deadline")

                    if st.button("Update Task"):
                        auto_status = _status_from_progress(int(new_quantity_done), int(new_quantity), new_status)
                        update_task(
                            task_id,
                            task=new_task_name,
                            assigned_to=new_assigned_to,
                            status=auto_status,
                            remarks=new_remarks,
                            quantity=new_quantity,
                            quantity_done=new_quantity_done,
                            date_val=_to_datestr(new_date_val),
                            deadline=_to_datestr(new_deadline)
                        )
                        st.success("Task updated!")
                        _rerun()

                    st.markdown("### Task Details (rows attached to this task)")
                    if details_rows:
                        del_ids = []
                        for d in details_rows:
                            with st.expander(f"#{d['id']} • {d.get('title') or '(no title)'}"):
                                st.write(f"**URL:** {d.get('url','')}")
                                st.write(f"**Keywords:** {d.get('keywords','')}")
                                st.write(f"**Description:** {d.get('description','')}")
                                if st.checkbox(f"Mark for delete #{d['id']}", key=f"del_detail_{d['id']}"):
                                    del_ids.append(d['id'])
                        if st.button("Delete Selected Details"):
                            delete_task_detail_rows(del_ids)
                            st.success("Selected details deleted.")
                            _rerun()
                    else:
                        st.info("No details yet.")

                    st.markdown("#### Add a new detail row to this task")
                    nd_title = st.text_input("Title", key="adm_new_detail_title")
                    nd_url = st.text_input("URL", key="adm_new_detail_url")
                    nd_keywords = st.text_input("Keywords (comma-separated)", key="adm_new_detail_keywords")
                    nd_description = st.text_area("Description", key="adm_new_detail_description")
                    if st.button("Add Detail Row"):
                        add_task_detail_row(task_id, nd_title, nd_url, nd_keywords, nd_description)
                        st.success("Detail row added.")
                        _rerun()
        else:
            st.info("No tasks found.")

    # ---------- TO-DO (Admin) ----------
    elif choice == "To-Do" and st.session_state.role == "Admin":
        st.subheader("Admin To-Do")

        with st.form("todo_add_form", clear_on_submit=True):
            col1, col2 = st.columns([2, 1])
            with col1:
                title = st.text_input("Title *")
                notes = st.text_area("Notes")
            with col2:
                todo_date = st.date_input("Date", value=date.today())
                status = st.selectbox("Status", ["Pending", "Done"], index=0)
            submitted = st.form_submit_button("Add To-Do")
            if submitted:
                if not title.strip():
                    st.error("Title is required.")
                else:
                    add_todo(todo_date, title, notes, created_by=st.session_state.username, status=status)
                    st.success("To-Do added.")

        st.divider()
        st.markdown("### Future Plan (Date-wise)")
        colf1, colf2, colf3 = st.columns([1,1,1])
        with colf1:
            from_dt = st.date_input("From", value=date.today())
        with colf2:
            to_dt = st.date_input("To", value=date.today() + timedelta(days=30))
        with colf3:
            filter_status = st.selectbox("Show", ["All", "Pending", "Done"], index=0)

        stat = None if filter_status == "All" else filter_status
        rows = get_todos(from_dt, to_dt, status=stat)

        if not rows:
            st.info("No to-dos in selected range.")
        else:
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            # Group by date
            for dt, g in df.sort_values(["date","id"]).groupby(df["date"].dt.date):
                st.markdown(f"#### {dt.strftime('%d %b %Y')}")
                for _, r in g.iterrows():
                    with st.expander(f"#{r['id']} • {r['title']} • {r['status']}"):
                        new_title = st.text_input("Title", value=r["title"], key=f"todo_title_{r['id']}")
                        new_notes = st.text_area("Notes", value=r.get("notes") or "", key=f"todo_notes_{r['id']}")
                        new_date = st.date_input("Date", value=r["date"].date(), key=f"todo_date_{r['id']}")
                        new_status = st.selectbox("Status", ["Pending","Done"], index=(0 if r['status']=="Pending" else 1), key=f"todo_status_{r['id']}")
                        c1, c2 = st.columns([1,1])
                        with c1:
                            if st.button("Save", key=f"todo_save_{r['id']}"):
                                update_todo(int(r["id"]), title=new_title, notes=new_notes, date_val=new_date, status=new_status)
                                st.success("Saved.")
                                _rerun()
                        with c2:
                            if st.button("Delete", key=f"todo_del_{r['id']}"):
                                delete_todos([int(r["id"])])
                                st.success("Deleted.")
                                _rerun()

    # ---------- REPORTS (Admin) ----------
    elif choice == "Reports" and st.session_state.role == "Admin":
        st.subheader("Task Reports")
        tasks = get_all_tasks()
        if tasks:
            df = pd.DataFrame(tasks)

            # normalize / derive
            for col in ["date", "deadline"]:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
            if "quantity_done" not in df.columns:
                df["quantity_done"] = 0
            if "quantity" not in df.columns:
                df["quantity"] = 1

            df["completed_units"] = df["quantity_done"].astype(int)
            df["assigned_units"]  = df["quantity"].astype(int)
            df["remaining_units"] = (df["assigned_units"] - df["completed_units"]).clip(lower=0).astype(int)
            df["status"] = df["status"].fillna("Pending")
            df["is_done"] = df["status"].eq("Done")
            df["needs_attention"] = (df["remaining_units"] > 0) | (~df["is_done"])

            user_filter = st.selectbox("Filter by User", ["All"] + [u['username'] for u in get_all_users()])

            col_f1, col_f2 = st.columns([1, 2])
            with col_f1:
                view_mode = st.radio("View", ["Date-wise", "Month-wise"], horizontal=True)

            filtered_df = df.copy()
            if user_filter != "All":
                filtered_df = filtered_df[filtered_df['assigned_to'] == user_filter]

            def _month_label(p):
                return p.strftime("%B %Y")

            if "date" in filtered_df.columns and not filtered_df.empty:
                valid_dates = filtered_df[filtered_df["date"].notna()].copy()
                unique_months = sorted(valid_dates["date"].dt.to_period("M").unique())
            else:
                unique_months = []

            with col_f2:
                if view_mode == "Date-wise":
                    picked_date = st.date_input("Select Date", value=date.today(), key="admin_report_date")
                    filtered_df = filtered_df[filtered_df["date"].dt.date == picked_date]
                else:
                    if unique_months:
                        month_labels = [_month_label(p) for p in unique_months]
                        default_idx = len(unique_months) - 1
                        picked_label = st.selectbox("Select Month", month_labels, index=default_idx)
                        picked_period = unique_months[month_labels.index(picked_label)]
                        filtered_df = filtered_df[filtered_df["date"].dt.to_period("M") == picked_period]
                    else:
                        st.info("No month data available.")
                        filtered_df = filtered_df.iloc[0:0]

            # Bring detail columns
            if not filtered_df.empty:
                task_ids = filtered_df["id"].astype(int).tolist()
                detail_rows = get_task_details_bulk(task_ids)

                titles_map, urls_map, keywords_map = {}, {}, {}
                for d in detail_rows or []:
                    tid = int(d.get("task_id"))
                    titles_map.setdefault(tid, []).append((d.get("title") or "").strip())
                    urls_map.setdefault(tid, []).append((d.get("url") or "").strip())
                    keywords_map.setdefault(tid, []).append((d.get("keywords") or "").strip())

                filtered_df["detail_titles"] = filtered_df["id"].map(lambda tid: "\n".join([t for t in titles_map.get(int(tid), []) if t]))
                filtered_df["detail_urls"] = filtered_df["id"].map(lambda tid: "\n".join([u for u in urls_map.get(int(tid), []) if u]))
                filtered_df["detail_keywords"] = filtered_df["id"].map(lambda tid: "\n".join([k for k in keywords_map.get(int(tid), []) if k]))

            # KPIs
            if not filtered_df.empty:
                total_assigned_tasks = len(filtered_df)
                total_done_tasks = int((filtered_df["status"] == "Done").sum())
                total_pending_tasks = int((filtered_df["status"] == "Pending").sum())
                total_half_tasks = int((filtered_df["status"] == "Half").sum())

                colk1, colk2, colk3, colk4 = st.columns(4)
                colk1.metric("Total Assigned Tasks", total_assigned_tasks)
                colk2.metric("Total Done Tasks", total_done_tasks)
                colk3.metric("Total Pending Tasks", total_pending_tasks)
                colk4.metric("Half (In Progress)", total_half_tasks)

                colu1, colu2, colu3, colu4 = st.columns(4)
                colu1.metric("Assigned Units", int(filtered_df["quantity"].sum()))
                colu2.metric("Completed Units", int(filtered_df["quantity_done"].sum()))
                colu3.metric("Remaining Units", int((filtered_df["quantity"] - filtered_df["quantity_done"]).clip(lower=0).sum()))
                colu4.metric("Needs Attention (tasks)", int(((filtered_df["quantity"] - filtered_df["quantity_done"]) > 0).sum()))
            else:
                st.info("No data for the selected filter.")

            display_cols = [
                "id","task","assigned_to","status",
                "quantity","quantity_done",
                "date","deadline","remarks",
                "detail_titles","detail_urls","detail_keywords"
            ]
            show_df = filtered_df[display_cols] if not filtered_df.empty else filtered_df

            def _row_style(row):
                remaining = int(row["quantity"]) - int(row["quantity_done"])
                if (remaining > 0) or (row["status"] != "Done"):
                    return ["background-color: #ffe6e6; color: #b00000"] * len(row)
                return [""] * len(row)

            st.markdown("#### Table")
            if show_df.empty:
                st.info("No data for the selected filter.")
            else:
                st.dataframe(show_df.style.apply(_row_style, axis=1), use_container_width=True)

            if not filtered_df.empty:
                agg_units = (
                    filtered_df
                    .groupby("assigned_to", as_index=False)[["quantity_done","quantity"]]
                    .sum()
                    .rename(columns={"quantity_done":"completed_units","quantity":"assigned_units"})
                )
                agg_units["remaining_units"] = (agg_units["assigned_units"] - agg_units["completed_units"]).clip(lower=0)
                agg_melt = agg_units.melt(id_vars="assigned_to", value_vars=["completed_units","remaining_units"],
                                          var_name="Metric", value_name="Units")
                fig = px.bar(agg_melt, x="assigned_to", y="Units", color="Metric", barmode="stack",
                             title="Completed vs Remaining Units by User")
                st.plotly_chart(fig, use_container_width=True)

                count_by_status = filtered_df.groupby("status", as_index=False)["id"].count().rename(columns={"id": "Tasks"})
                fig2 = px.bar(count_by_status, x="status", y="Tasks", title="Task Count by Status (Selected Period)")
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No tasks found.")

    # ---------- MY TASKS (Team) ----------
    elif choice == "My Tasks" and st.session_state.role != "Admin":
        st.subheader("My Tasks")

        my_tasks = get_user_tasks(st.session_state.username)
        df = pd.DataFrame(my_tasks) if my_tasks else pd.DataFrame(columns=[
            "id","task","status","remarks","quantity","quantity_done","date","deadline",
            "title","url","keywords","description"
        ])

        if df.empty:
            st.info("No tasks assigned yet.")
        else:
            for col in ["date", "deadline"]:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
            if "quantity_done" not in df.columns:
                df["quantity_done"] = 0
            if "quantity" not in df.columns:
                df["quantity"] = 1

            pending_now = df[df["status"].fillna("Pending") != "Done"]
            if not pending_now.empty:
                st.sidebar.markdown("### Pending Tasks")
                for _, r in pending_now.sort_values(by=["deadline","date","id"]).iterrows():
                    label = f"#{r['id']} • {r.get('task','')}"
                    st.sidebar.markdown(f":red[{label}]")

            st.markdown("#### Filters")
            col_vm1, col_vm2 = st.columns([1,1])
            with col_vm1:
                view_mode = st.radio("View by", ["Date", "Month"], horizontal=True)
            with col_vm2:
                status_filter = st.selectbox("Show", ["All", "Pending", "Half", "Done"], index=0)

            if view_mode == "Date":
                picked_date = st.date_input("Select Date", value=date.today(), key="team_view_date")
                fdf = df[df["date"].dt.date == picked_date]
            else:
                picked_month = st.date_input("Select Month", value=date.today(), key="team_view_month")
                fdf = df[df["date"].dt.month == picked_month.month]

            if status_filter != "All":
                fdf = fdf[fdf["status"].fillna("Pending") == status_filter]

            if fdf.empty:
                st.info("No tasks for the selected period.")
            else:
                for _, row in fdf.sort_values(by=["date", "deadline", "id"]).iterrows():
                    header = f"#{row['id']} • {row.get('task','(no task)')} • {row.get('status','')}"
                    with st.expander(header):
                        total_q = int(row.get("quantity", 1))
                        done_q  = int(row.get("quantity_done", 0))
                        remain_q = max(0, total_q - done_q)

                        st.markdown(f"**Task:** {row.get('task','')}")
                        st.markdown(f"**Quantity Assigned:** {total_q}")
                        st.markdown(f"**Completed:** {done_q}")
                        st.markdown(f"**Remaining:** {remain_q}")
                        st.markdown(f"**Date:** {row['date'].date() if pd.notna(row['date']) else ''}")
                        st.markdown(f"**Deadline:** {row['deadline'].date() if pd.notna(row['deadline']) else ''}")
                        st.markdown("---")

                        legacy_has_any = any([bool(row.get("title")), bool(row.get("url")), bool(row.get("keywords")), bool(row.get("description"))])
                        if legacy_has_any:
                            legacy_rows = [{
                                "Title": row.get("title") or "",
                                "URL": _link(row.get("url") or ""),
                                "Keywords": row.get("keywords") or "",
                                "Description": row.get("description") or ""
                            }]
                            st.markdown("**Task Info (legacy fields):**")
                            st.dataframe(pd.DataFrame(legacy_rows), use_container_width=True)
                            st.markdown("---")

                        details_rows = get_task_details(row["id"])
                        if details_rows:
                            table = []
                            for d in details_rows:
                                table.append({
                                    "Title": d.get("title") or "",
                                    "URL": _link(d.get("url") or ""),
                                    "Keywords": d.get("keywords") or "",
                                    "Description": d.get("description") or ""
                                })
                            st.markdown("**Assigned Details:**")
                            st.dataframe(pd.DataFrame(table), use_container_width=True)
                        else:
                            st.info("No details attached to this task.")

                        st.markdown("---")
                        max_qty = total_q
                        current_done = done_q
                        new_done = st.number_input("Update completed units", min_value=0, max_value=max_qty, value=current_done, step=1, key=f"done_{row['id']}")

                        suggested_status = _status_from_progress(int(new_done), int(max_qty), row.get("status","Pending"))
                        new_status = st.selectbox(
                            "Update Status", ["Pending", "Half", "Done"],
                            index=["Pending","Half","Done"].index(suggested_status if suggested_status in ["Pending","Half","Done"] else "Pending"),
                            key=f"status_{row['id']}"
                        )
                        new_remarks = st.text_area("Remarks", value=row.get("remarks") or "", key=f"remarks_{row['id']}")
                        if st.button("Save Update", key=f"save_{row['id']}"):
                            final_status = "Done" if new_done >= max_qty else new_status
                            update_task(row["id"], status=final_status, remarks=new_remarks, quantity_done=new_done)
                            st.success("Updated.")
                            _rerun()

    # ---------- MY TO-DO (Team) ----------
    elif choice == "My To-Do" and st.session_state.role != "Admin":
        st.subheader("My To-Do")

        with st.form("my_todo_add_form", clear_on_submit=True):
            col1, col2 = st.columns([2, 1])
            with col1:
                title = st.text_input("Title *")
                notes = st.text_area("Notes")
            with col2:
                todo_date = st.date_input("Date", value=date.today())
                status = st.selectbox("Status", ["Pending", "Done"], index=0)
            submitted = st.form_submit_button("Add To-Do")
            if submitted:
                if not title.strip():
                    st.error("Title is required.")
                else:
                    add_todo(todo_date, title, notes, created_by=st.session_state.username, status=status)
                    st.success("To-Do added.")

        st.divider()
        st.markdown("### Upcoming (Date-wise)")
        from_dt = st.date_input("From", value=date.today())
        to_dt = st.date_input("To", value=date.today() + timedelta(days=30))
        filter_status = st.selectbox("Show", ["All", "Pending", "Done"], index=0)

        stat = None if filter_status == "All" else filter_status
        rows = get_todos(from_dt, to_dt, status=stat, created_by=st.session_state.username)

        if not rows:
            st.info("No to-dos in selected range.")
        else:
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            for dt, g in df.sort_values(["date","id"]).groupby(df["date"].dt.date):
                st.markdown(f"#### {dt.strftime('%d %b %Y')}")
                for _, r in g.iterrows():
                    with st.expander(f"#{r['id']} • {r['title']} • {r['status']}"):
                        new_title = st.text_input("Title", value=r["title"], key=f"mytodo_title_{r['id']}")
                        new_notes = st.text_area("Notes", value=r.get("notes") or "", key=f"mytodo_notes_{r['id']}")
                        new_date = st.date_input("Date", value=r["date"].date(), key=f"mytodo_date_{r['id']}")
                        new_status = st.selectbox("Status", ["Pending","Done"], index=(0 if r['status']=="Pending" else 1), key=f"mytodo_status_{r['id']}")
                        c1, c2 = st.columns([1,1])
                        with c1:
                            if st.button("Save", key=f"mytodo_save_{r['id']}"):
                                update_todo(int(r["id"]), title=new_title, notes=new_notes, date_val=new_date, status=new_status)
                                st.success("Saved.")
                                _rerun()
                        with c2:
                            if st.button("Delete", key=f"mytodo_del_{r['id']}"):
                                delete_todos([int(r["id"])])
                                st.success("Deleted.")
                                _rerun()
