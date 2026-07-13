# ============================================================
# Advanced CRM - Task Manager (Projects + Monthly Targets + Cleanup)
# ============================================================

import streamlit as st
from supabase import create_client
from datetime import date, timedelta
import pandas as pd
import plotly.express as px
import json
import csv
import io
import re
from zoneinfo import ZoneInfo


# ---------------- PAGE & CLIENT ----------------
st.set_page_config(page_title="Advanced CRM - Task Manager", page_icon="📋", layout="wide")

# TIP: Move these to Streamlit secrets in production
# Store these values in .streamlit/secrets.toml in production.
SUPABASE_URL = st.secrets.get(
    "SUPABASE_URL",
    "https://fijvjhbhxdbinqdiiytq.supabase.co",
)
SUPABASE_KEY = st.secrets.get(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZpanZqaGJoeGRiaW5xZGlpeXRxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTc5MTU5OTksImV4cCI6MjA3MzQ5MTk5OX0.aR5Sl9Z9wnCMQhRwHJ6dEXwAWTnxn-yxDqomL9KEHag",
)

@st.cache_resource
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = get_supabase_client()

try:
    _rerun = st.rerun
except AttributeError:
    _rerun = st.experimental_rerun


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
def df_show(df: pd.DataFrame):
    st.dataframe(df, width="stretch")

def _to_datestr(d):
    return d if isinstance(d, str) else d.strftime("%Y-%m-%d")

def _date_to_ymd(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def _link(url: str) -> str:
    if not url:
        return ""
    return f"[{url}]({url})"

def _status_from_progress(done: int, total: int, fallback: str = "Pending") -> str:
    if total <= 0:
        return fallback
    if done <= 0:
        return "Pending"
    if done >= total:
        return "Done"
    return "Half"

def _now_utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)

def chunk_list(items, size=500):
    for i in range(0, len(items), size):
        yield items[i:i + size]

def month_start(d: date) -> date:
    return date(d.year, d.month, 1)

def month_range(year: int, month: int):
    start_dt = date(year, month, 1)
    if month == 12:
        end_dt = date(year + 1, 1, 1)
    else:
        end_dt = date(year, month + 1, 1)
    return start_dt, end_dt

def year_range(year: int):
    return date(year, 1, 1), date(year + 1, 1, 1)

def _norm_task(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _targets_aliases(target_label: str, known_tasks_norm: dict) -> list[str]:
    """
    Goal:
    - If target_label is a group label like "Blog Submission/ Mini blog/article submission"
      or "Web 2.0/Profile Creation/ /podcast/CLASSIFIED ADS/Forum Posting"
      then count done units from ANY task contained inside it.
    - We do this by matching known task names as "whole-ish" substrings.
    """
    label_norm = _norm_task(target_label)

    matches = []
    for t_norm, t_original in known_tasks_norm.items():
        # Skip tiny strings to avoid accidental matches
        if len(t_norm) < 4:
            continue

        # Boundary-ish match: avoid partial word matches
        # Example: "blog" should not match "blog seo" unless blog itself is a task.
        patt = r"(?<![a-z0-9])" + re.escape(t_norm) + r"(?![a-z0-9])"
        if re.search(patt, label_norm):
            matches.append(t_original)

    # If nothing matched, treat as a single task label
    if not matches:
        return [target_label]

    # Deduplicate while preserving order
    seen = set()
    out = []
    for m in matches:
        k = _norm_task(m)
        if k not in seen:
            seen.add(k)
            out.append(m)
    return out


# ---------------- BULK PASTE PARSER (DETAILS) ----------------
def parse_bulk_details(text: str):
    """
    Supports:
      1) TSV paste: Title<TAB>URL<TAB>Keywords<TAB>Description
      2) CSV
      3) Pipe format: Title | URL | Keywords | Description
      4) Labeled blocks:
         Title: ...
         URL: ...
         Keywords: ...
         Description: ...
         (blank line separates entries)
    """
    if not text or not text.strip():
        return [], []

    raw = text.strip()

    label_re = re.compile(r"^(title|url|keywords|description)\s*:\s*(.*)$", re.I)
    lines = raw.splitlines()
    if any(label_re.match((l or "").strip() or "") for l in lines):
        rows = []
        cur = {"title": "", "url": "", "keywords": "", "description": ""}
        errors = []

        def flush():
            nonlocal cur
            if any(v.strip() for v in cur.values()):
                rows.append({
                    "title": cur["title"].strip(),
                    "url": cur["url"].strip(),
                    "keywords": cur["keywords"].strip(),
                    "description": cur["description"].strip()
                })
            cur = {"title": "", "url": "", "keywords": "", "description": ""}

        for ln in lines:
            s = (ln or "").strip()
            if not s:
                flush()
                continue

            m = label_re.match(s)
            if not m:
                cur["description"] = (cur["description"] + "\n" + s).strip()
                continue

            k = m.group(1).lower()
            v = m.group(2)
            cur[k] = (cur[k] + ("\n" if cur[k].strip() else "") + v).strip()

        flush()
        rows = [r for r in rows if any((r.get(k) or "").strip() for k in ("title", "url", "keywords", "description"))]
        return rows, errors

    sample_line = next((l for l in raw.splitlines() if l.strip()), "")
    delimiter = "\t" if "\t" in raw else None

    if delimiter is None:
        for d in ["|", ",", ";"]:
            if d in sample_line:
                delimiter = d
                break

    if delimiter is None:
        rows = [{"title": l.strip(), "url": "", "keywords": "", "description": ""} for l in raw.splitlines() if l.strip()]
        return rows, []

    f = io.StringIO(raw)
    reader = csv.reader(f, delimiter=delimiter)
    all_rows = [[(c or "").strip() for c in r] for r in reader if any(((c or "").strip() for c in r))]

    if not all_rows:
        return [], []

    header = [c.lower() for c in all_rows[0]]
    header_set = set(header)
    header_like = any(h in header_set for h in ["title", "url", "keywords", "description", "keyword", "link", "desc"])

    col_map = {"title": None, "url": None, "keywords": None, "description": None}

    if header_like:
        def idx(*names):
            for n in names:
                if n in header:
                    return header.index(n)
            return None

        col_map["title"] = idx("title")
        col_map["url"] = idx("url", "link")
        col_map["keywords"] = idx("keywords", "keyword")
        col_map["description"] = idx("description", "desc")
        data_rows = all_rows[1:]
    else:
        col_map["title"] = 0
        col_map["url"] = 1
        col_map["keywords"] = 2
        col_map["description"] = 3
        data_rows = all_rows

    rows = []
    errors = []

    for r in data_rows:
        def getv(key):
            j = col_map.get(key)
            if j is None:
                return ""
            return r[j].strip() if j < len(r) else ""

        row = {
            "title": getv("title"),
            "url": getv("url"),
            "keywords": getv("keywords"),
            "description": getv("description"),
        }
        if not any(v.strip() for v in row.values()):
            continue
        rows.append(row)

    return rows, errors


# ---------------- BULK PASTE PARSER (TARGETS) ----------------
def parse_bulk_targets(text: str):
    """
    Paste like:
    Task<TAB>Qty
    Task | Qty
    Task,Qty
    """
    rows = []
    if not text or not text.strip():
        return rows

    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in raw_lines:
        low = ln.lower()
        if low.startswith("task"):
            continue

        if "\t" in ln:
            a, b = ln.split("\t", 1)
        elif "|" in ln:
            a, b = ln.split("|", 1)
        elif "," in ln:
            a, b = ln.split(",", 1)
        else:
            parts = ln.split()
            if len(parts) < 2:
                continue
            a = " ".join(parts[:-1])
            b = parts[-1]

        task = (a or "").strip()
        qty_raw = (b or "").strip()
        if not task:
            continue

        try:
            qty = int(float(qty_raw)) if qty_raw else 0
        except Exception:
            qty = 0

        rows.append((task, qty))
    return rows


# ---------------- BULK CALLBACKS ----------------
def _clear_text_key(text_key: str):
    st.session_state[text_key] = ""

def _bulk_preview_to_state(text_key: str, out_key_prefix: str):
    text = st.session_state.get(text_key, "") or ""
    parsed, errs = parse_bulk_details(text)
    st.session_state[f"{out_key_prefix}_preview"] = parsed
    st.session_state[f"{out_key_prefix}_errs"] = errs

def _bulk_add_to_draft(text_key: str, out_key_prefix: str):
    text = st.session_state.get(text_key, "") or ""
    parsed, errs = parse_bulk_details(text)
    st.session_state[f"{out_key_prefix}_errs"] = errs
    st.session_state[f"{out_key_prefix}_added"] = len(parsed)

    if parsed:
        st.session_state.details_draft.extend(parsed)
        st.session_state[text_key] = ""

def _bulk_insert_into_task(task_id: int, text_key: str, out_key_prefix: str):
    text = st.session_state.get(text_key, "") or ""
    parsed, errs = parse_bulk_details(text)

    st.session_state[f"{out_key_prefix}_errs"] = errs
    st.session_state[f"{out_key_prefix}_added"] = 0

    if not parsed:
        return

    child_rows = []
    for d in parsed:
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
        for chunk in chunk_list(child_rows, 500):
            supabase.table("task_details").insert(chunk).execute()

    st.session_state[f"{out_key_prefix}_added"] = len(child_rows)
    st.session_state[text_key] = ""


# ---------------- AUTH HELPERS ----------------
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


# ---------------- PROJECT HELPERS ----------------
def get_all_projects():
    res = supabase.table("projects").select("*").order("project_name").execute()
    return [r["project_name"] for r in (res.data or [])]

def add_project(project_name: str):
    name = (project_name or "").strip()
    if not name:
        return
    supabase.table("projects").insert({"project_name": name}).execute()

def delete_projects(project_names, safe=True):
    if not project_names:
        return []
    skipped = []
    for name in project_names:
        name = (name or "").strip()
        if not name:
            continue

        if safe:
            used = supabase.table("tasks").select("id").eq("project", name).limit(1).execute()
            if getattr(used, "data", None) and len(used.data) > 0:
                skipped.append(name)
                continue

        supabase.table("projects").delete().eq("project_name", name).execute()
    return skipped


# ---------------- TASK TYPE HELPERS ----------------
def get_all_task_types():
    response = supabase.table("task_types").select("*").execute()
    if not response.data:
        for t in DEFAULT_TASK_TYPES:
            supabase.table("task_types").insert({"task_name": t}).execute()
        response = supabase.table("task_types").select("*").execute()
    return [t["task_name"] for t in response.data]

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


# ---------------- MONTHLY TARGET HELPERS ----------------
def upsert_monthly_target(project: str, month_dt: date, task: str, target_qty: int):
    payload = {
        "project": (project or "").strip(),
        "month": _to_datestr(month_start(month_dt)),
        "task": (task or "").strip(),
        "target_qty": int(target_qty),
        "updated_at": _now_utc().isoformat()
    }
    supabase.table("monthly_targets").upsert(payload, on_conflict="project,month,task").execute()

def get_monthly_targets(project: str, month_dt: date):
    m = _to_datestr(month_start(month_dt))
    return (
        supabase.table("monthly_targets")
        .select("*")
        .eq("project", project)
        .eq("month", m)
        .order("task")
        .execute()
        .data
    )


# ---------------- TASK HELPERS ----------------
def assign_task_with_details(project, users, tasks_with_qty, date_val, deadline, remarks="", details_list=None):
    date_str = _to_datestr(date_val)
    deadline_str = _to_datestr(deadline)
    details_list = details_list or []
    project = (project or "").strip() or None

    for user in users:
        for task_name, qty in tasks_with_qty.items():
            payload = {
                "project": project,
                "assigned_to": user,
                "task": task_name,
                "status": "Pending",
                "date": date_str,
                "deadline": deadline_str,
                "quantity": int(qty),
                "quantity_done": 0,
                "remarks": remarks,
                "updated_at": _now_utc().isoformat()
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

            if not task_id:
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
                    for chunk in chunk_list(child_rows, 500):
                        supabase.table("task_details").insert(chunk).execute()

def get_user_tasks(user):
    return supabase.table("tasks").select("*").eq("assigned_to", user).order("date").execute().data

def get_all_tasks():
    return supabase.table("tasks").select("*").order("date").execute().data

def update_task(task_id, task=None, assigned_to=None, status=None, remarks=None, quantity=None,
                date_val=None, deadline=None, project=None,
                title=None, url=None, keywords=None, description=None,
                quantity_done=None):
    update_data = {"updated_at": _now_utc().isoformat()}
    if project is not None:
        update_data["project"] = project
    if task:
        update_data["task"] = task
    if assigned_to:
        update_data["assigned_to"] = assigned_to
    if status:
        update_data["status"] = status
    if remarks is not None:
        update_data["remarks"] = remarks
    if quantity is not None:
        update_data["quantity"] = int(quantity)
    if date_val:
        update_data["date"] = _to_datestr(date_val)
    if deadline:
        update_data["deadline"] = _to_datestr(deadline)
    if title is not None:
        update_data["title"] = title
    if url is not None:
        update_data["url"] = url
    if keywords is not None:
        update_data["keywords"] = keywords
    if description is not None:
        update_data["description"] = description
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
    if not detail_ids:
        return
    for did in detail_ids:
        supabase.table("task_details").delete().eq("id", did).execute()


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
    if from_date:
        q = q.gte("date", _to_datestr(from_date))
    if to_date:
        q = q.lte("date", _to_datestr(to_date))
    if status and status in ("Pending", "Done"):
        q = q.eq("status", status)
    if created_by:
        q = q.eq("created_by", created_by)
    return q.execute().data

def update_todo(todo_id, title=None, notes=None, status=None, date_val=None):
    data = {"updated_at": _now_utc().isoformat()}
    if title is not None:
        data["title"] = title.strip()
    if notes is not None:
        data["notes"] = (notes or "").strip()
    if status in ("Pending", "Done"):
        data["status"] = status
    if date_val is not None:
        data["date"] = _to_datestr(date_val)
    supabase.table("todos").update(data).eq("id", todo_id).execute()

def delete_todos(todo_ids):
    for tid in todo_ids:
        supabase.table("todos").delete().eq("id", tid).execute()


# ---------------- CLEANUP HELPERS ----------------
def delete_tasks_by_range(start_dt: date, end_dt_exclusive: date, project: str = None):
    q = (
        supabase.table("tasks")
        .delete()
        .gte("date", _date_to_ymd(start_dt))
        .lt("date", _date_to_ymd(end_dt_exclusive))
    )
    if project and project != "All":
        q = q.eq("project", project)
    q.execute()

def delete_todos_by_range(start_dt: date, end_dt_exclusive: date, created_by: str = None):
    q = (
        supabase.table("todos")
        .delete()
        .gte("date", _date_to_ymd(start_dt))
        .lt("date", _date_to_ymd(end_dt_exclusive))
    )
    if created_by:
        q = q.eq("created_by", created_by)
    q.execute()

def delete_targets_by_range(start_month_dt: date, end_month_exclusive_dt: date, project: str = None):
    q = (
        supabase.table("monthly_targets")
        .delete()
        .gte("month", _date_to_ymd(month_start(start_month_dt)))
        .lt("month", _date_to_ymd(month_start(end_month_exclusive_dt)))
    )
    if project and project != "All":
        q = q.eq("project", project)
    q.execute()


# ---------------- DESKTOP NOTIFICATIONS ----------------
def show_browser_notifications(messages):
    # Temporarily disabled while diagnosing server crashes.
    return

def poll_for_new_done_events(init=False):
    if "done_seen_ids" not in st.session_state:
        st.session_state.done_seen_ids = set()

    since = (_now_utc() - timedelta(hours=24)).isoformat()
    try:
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
            continue
        if tid not in st.session_state.done_seen_ids:
            who = t.get("assigned_to", "User")
            task_name = t.get("task", "Task")
            new_msgs.append({"title": "Task Completed", "body": f"{who} marked '{task_name}' as Done (#{tid})."})

    st.session_state.done_seen_ids |= current_done_ids
    if new_msgs:
        show_browser_notifications(new_msgs)


# ---------------- DAILY SUMMARY (Date-wise, per team member) ----------------
IST = ZoneInfo("Asia/Kolkata")

def _now_ist():
    from datetime import datetime
    return datetime.now(IST)

def get_daily_task_summary(target_date: date):
    """
    For the given date, returns per-user counts of:
      - assigned: how many tasks were assigned on that date
      - closed: how many of those are marked Done
    """
    date_str = _date_to_ymd(target_date)
    rows = (
        supabase.table("tasks")
        .select("assigned_to, status")
        .eq("date", date_str)
        .execute()
        .data
    ) or []

    summary = {}
    for r in rows:
        user = r.get("assigned_to") or "Unassigned"
        summary.setdefault(user, {"assigned": 0, "closed": 0})
        summary[user]["assigned"] += 1
        if r.get("status") == "Done":
            summary[user]["closed"] += 1

    out = [
        {"user": u, "assigned": v["assigned"], "closed": v["closed"], "pending": v["assigned"] - v["closed"]}
        for u, v in summary.items()
    ]
    out.sort(key=lambda x: x["user"])
    return out

def build_summary_notification(target_date: date):
    rows = get_daily_task_summary(target_date)
    if not rows:
        return None
    date_label = target_date.strftime("%d %b %Y")
    lines = [f"{r['user']}: {r['closed']}/{r['assigned']} closed" for r in rows]
    body = "\n".join(lines)
    return {"title": f"Daily Task Summary - {date_label}", "body": body}

def maybe_auto_send_daily_summary():
    """
    Checks the current time in IST. Once it's 9:15 AM or later, sends the
    day's date-wise summary notification once (per browser session/day).
    Requires this tab to be open (with auto-refresh) around that time.
    """
    if st.session_state.get("auto_summary_enabled", True) is False:
        return

    now = _now_ist()
    today_str = now.strftime("%Y-%m-%d")

    if (now.hour, now.minute) < (9, 15):
        return

    if st.session_state.get("daily_summary_sent_for") == today_str:
        return

    msg = build_summary_notification(now.date())
    if msg:
        show_browser_notifications([msg])
    st.session_state["daily_summary_sent_for"] = today_str


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
        menu = [
            "User Management",
            "Task List Management",
            "Add New Task",
            "Task Management",
            "To-Do",
            "Reports",
            "Monthly Targets",
            "Data Cleanup",
            "Notifications",
        ]
    else:
        menu = ["My Tasks", "My To-Do"]

    choice = st.sidebar.selectbox("Menu", menu)

    if st.session_state.role == "Admin":
        # Automatic full-app refresh is intentionally disabled.
        # Streamlit already reruns after widget interactions, and an additional
        # timed rerun can interrupt database writes on Community Cloud.
        if "admin_polling_started" not in st.session_state:
            try:
                poll_for_new_done_events(init=True)
            except Exception:
                pass
            st.session_state.admin_polling_started = True

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
        st.subheader("Manage Task Types + Projects")
        tab1, tab2 = st.tabs(["Task Types", "Projects"])

        with tab1:
            task_types = get_all_task_types()
            col_a, col_b = st.columns([1, 1])
            with col_a:
                st.markdown("**Existing Task Types**")
                st.write(task_types)

                new_task_type = st.text_input("Add New Task Type", key="add_task_type_txt")
                if st.button("Add Task Type", key="add_task_type_btn"):
                    if new_task_type:
                        add_task_type(new_task_type.strip())
                        st.success(f"Added: {new_task_type}")
                        _rerun()
                    else:
                        st.warning("Enter a task type name.")

            with col_b:
                st.markdown("**Delete Task Types**")
                types_to_delete = st.multiselect("Select task types to delete", task_types, key="del_task_types_ms")
                safe_delete = st.checkbox("Prevent deletion if any task uses the type (recommended)", value=True, key="safe_del_task_types")

                if st.button("Delete Selected Types", key="del_task_types_btn"):
                    if not types_to_delete:
                        st.info("Select at least one type.")
                    else:
                        skipped = delete_task_types(types_to_delete, safe=safe_delete)
                        deleted = list(set(types_to_delete) - set(skipped))
                        if deleted:
                            st.success("Deleted: " + ", ".join(sorted(deleted)))
                        if skipped:
                            st.warning("Skipped (in use): " + ", ".join(sorted(skipped)))
                        _rerun()

        with tab2:
            try:
                projects = get_all_projects()
            except Exception:
                st.error("Projects table not found. Run the SQL at the top of this file in Supabase.")
                st.stop()

            col_a, col_b = st.columns([1, 1])
            with col_a:
                st.markdown("**Existing Projects**")
                st.write(projects)

                new_project = st.text_input("Add New Project", key="add_project_txt")
                if st.button("Add Project", key="add_project_btn"):
                    if new_project.strip():
                        add_project(new_project.strip())
                        st.success(f"Added: {new_project}")
                        _rerun()
                    else:
                        st.warning("Enter a project name.")

            with col_b:
                st.markdown("**Delete Projects**")
                proj_to_delete = st.multiselect("Select projects to delete", projects, key="del_projects_ms")
                safe_delete_p = st.checkbox("Prevent deletion if any task uses the project (recommended)", value=True, key="safe_del_projects")
                if st.button("Delete Selected Projects", key="del_projects_btn"):
                    if not proj_to_delete:
                        st.info("Select at least one project.")
                    else:
                        skipped = delete_projects(proj_to_delete, safe=safe_delete_p)
                        deleted = list(set(proj_to_delete) - set(skipped))
                        if deleted:
                            st.success("Deleted: " + ", ".join(sorted(deleted)))
                        if skipped:
                            st.warning("Skipped (in use): " + ", ".join(sorted(skipped)))
                        _rerun()

    # ---------- MONTHLY TARGETS (Admin) ----------
    elif choice == "Monthly Targets" and st.session_state.role == "Admin":
        st.subheader("Monthly Targets (Project-wise)")

        try:
            projects = get_all_projects()
        except Exception:
            st.error("Projects table not found. Run the SQL at the top of this file in Supabase.")
            st.stop()

        if not projects:
            st.info("Add at least 1 project in Task List Management → Projects.")
            st.stop()

        c1, c2 = st.columns([2, 1])
        with c1:
            project = st.selectbox("Project", projects, key="mt_project")
        with c2:
            picked_month = st.date_input("Month", value=date.today(), key="mt_month")

        task_types = get_all_task_types()

        st.markdown("### Add / Update Target (single)")
        a1, a2, a3 = st.columns([2, 1, 1])
        with a1:
            t_task = st.selectbox("Task", task_types, key="mt_task")
        with a2:
            t_qty = st.number_input("Target Qty", min_value=0, value=0, step=1, key="mt_qty")
        with a3:
            if st.button("Save Target", key="mt_save"):
                upsert_monthly_target(project, picked_month, t_task, int(t_qty))
                st.success("Saved.")
                _rerun()

        st.divider()
        st.markdown("### Bulk paste targets")
        st.caption("Paste like: Task<TAB>Qty OR Task | Qty OR Task,Qty")
        bulk_text = st.text_area("Paste here", height=180, key="mt_bulk")

        colx1, colx2 = st.columns([1, 1])
        with colx1:
            if st.button("Preview Bulk", key="mt_preview"):
                parsed = parse_bulk_targets(bulk_text)
                if not parsed:
                    st.info("No valid rows found.")
                else:
                    df_show(pd.DataFrame(parsed, columns=["Task", "Target Qty"]))

        with colx2:
            if st.button("Import Bulk Targets", key="mt_import"):
                parsed = parse_bulk_targets(bulk_text)
                if not parsed:
                    st.warning("No valid rows found.")
                else:
                    for task_name, qty in parsed:
                        upsert_monthly_target(project, picked_month, task_name, int(qty))
                    st.success(f"Imported {len(parsed)} targets.")
                    _rerun()

        st.divider()
        st.markdown("### Current Targets")
        existing = get_monthly_targets(project, picked_month)
        if not existing:
            st.info("No targets set for this month/project.")
        else:
            df_t = pd.DataFrame(existing)[["task", "target_qty"]].sort_values("task")
            df_show(df_t)

    # ---------- ADD NEW TASK (Admin) ----------
    elif choice == "Add New Task" and st.session_state.role == "Admin":
        st.subheader("Assign Tasks to Users")

        try:
            projects = get_all_projects()
        except Exception:
            st.error("Projects table not found. Run the SQL at the top of this file in Supabase.")
            st.stop()

        if not projects:
            st.info("First add projects in Task List Management → Projects.")
            st.stop()

        project = st.selectbox("Project", projects, key="assign_project")

        users = get_all_users()
        team_users = [u["username"] for u in users if u["role"] == "Team"]
        selected_users = st.multiselect("Select Team Members", team_users)

        task_types = get_all_task_types()
        selected_tasks = st.multiselect("Select Tasks", task_types)

        st.markdown("#### Quantities")
        tasks_with_qty = {}
        for task in selected_tasks:
            tasks_with_qty[task] = st.number_input(
                f"Quantity for '{task}'", min_value=1, value=1, key=f"qty_{task}"
            )

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

        st.markdown("#### Bulk paste (add many rows at once)")
        with st.expander("Paste bulk rows (Excel/Sheets/CSV/Pipe/Label format)"):
            st.caption(
                "Fastest: paste from Excel/Google Sheets (4 columns): Title, URL, Keywords, Description.\n\n"
                "Also works: Pipe and labeled blocks."
            )

            TEXT_KEY = "bulk_details_text_admin"
            OUT = "bulk_admin"

            st.text_area("Paste here", height=180, key=TEXT_KEY)

            c1, c2, c3 = st.columns([1, 1, 1])
            with c1:
                st.button("Preview parse", key="bulk_preview_admin", on_click=_bulk_preview_to_state, args=(TEXT_KEY, OUT))
            with c2:
                st.button("Add to draft", key="bulk_add_admin", on_click=_bulk_add_to_draft, args=(TEXT_KEY, OUT))
            with c3:
                st.button("Clear paste box", key="bulk_clear_admin", on_click=_clear_text_key, args=(TEXT_KEY,))

            errs = st.session_state.get(f"{OUT}_errs") or []
            if errs:
                st.warning("\n".join(errs))

            added = st.session_state.get(f"{OUT}_added")
            if isinstance(added, int) and added > 0:
                st.success(f"Added {added} rows to draft.")
                st.session_state[f"{OUT}_added"] = 0

            preview = st.session_state.get(f"{OUT}_preview") or []
            if preview:
                df_show(pd.DataFrame(preview))

        if st.session_state.details_draft:
            st.markdown("**Draft Details:**")
            draft_df = pd.DataFrame(st.session_state.details_draft)
            df_show(draft_df)

            idx_options = list(range(len(draft_df)))
            to_remove = st.multiselect(
                "Select rows to remove",
                options=idx_options,
                format_func=lambda i: f"{i+1}. {(draft_df.loc[i,'title'] or '(no title)')[:60]}",
                key="draft_remove_idx"
            )
            if st.button("Remove selected rows", key="draft_remove_btn"):
                keep = [r for j, r in enumerate(st.session_state.details_draft) if j not in set(to_remove)]
                st.session_state.details_draft = keep
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
            if st.button("Add Task", type="primary"):
                if not project:
                    st.warning("Select a project.")
                elif not selected_users:
                    st.warning("Select at least one team member.")
                elif not tasks_with_qty:
                    st.warning("Select at least one task.")
                else:
                    try:
                        assign_task_with_details(
                            project=project,
                            users=selected_users,
                            tasks_with_qty=tasks_with_qty,
                            date_val=date_val,
                            deadline=deadline,
                            remarks=remarks,
                            details_list=st.session_state.details_draft
                        )
                        st.session_state.details_draft = []
                        st.success("Tasks assigned successfully.")
                    except Exception as exc:
                        st.error(f"Task could not be saved: {exc}")

        with col_btn2:
            if st.button("Clear Details List"):
                st.session_state.details_draft = []
                st.info("Draft details cleared.")

    # ---------- TASK MANAGEMENT (Admin) ----------
    elif choice == "Task Management" and st.session_state.role == "Admin":
        st.subheader("View/Edit/Delete Assigned Tasks")

        tasks = get_all_tasks()
        if tasks:
            task_list = [
                f"{t['id']} | {t.get('project','')} | {t.get('task','')} | {t.get('assigned_to','')} | {t.get('status','')} | {t.get('date','')} | {t.get('deadline','')} | Qty:{t.get('quantity',1)} | Done:{t.get('quantity_done',0)}"
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

                    try:
                        projects = get_all_projects()
                    except Exception:
                        projects = []

                    task_types = get_all_task_types()
                    users = get_all_users()

                    new_project = st.selectbox("Project", projects if projects else ["--"], key="adm_edit_project")
                    new_task_name = st.selectbox("Task Name", task_types, key="adm_edit_task_name")
                    new_assigned_to = st.selectbox("Assigned To", [u["username"] for u in users if u["role"] == "Team"], key="adm_edit_assigned_to")
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
                            project=(new_project if new_project != "--" else None),
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

                    st.markdown("### Task Details")
                    if details_rows:
                        del_ids = []
                        for d in details_rows:
                            with st.expander(f"#{d['id']} • {d.get('title') or '(no title)'}"):
                                st.write(f"**URL:** {d.get('url','')}")
                                st.write(f"**Keywords:** {d.get('keywords','')}")
                                st.write(f"**Description:** {d.get('description','')}")
                                if st.checkbox(f"Mark for delete #{d['id']}", key=f"del_detail_{d['id']}"):
                                    del_ids.append(d["id"])
                        if st.button("Delete Selected Details"):
                            delete_task_detail_rows(del_ids)
                            st.success("Selected details deleted.")
                            _rerun()
                    else:
                        st.info("No details yet.")

                    st.markdown("#### Add a new detail row")
                    nd_title = st.text_input("Title", key="adm_new_detail_title")
                    nd_url = st.text_input("URL", key="adm_new_detail_url")
                    nd_keywords = st.text_input("Keywords (comma-separated)", key="adm_new_detail_keywords")
                    nd_description = st.text_area("Description", key="adm_new_detail_description")
                    if st.button("Add Detail Row"):
                        add_task_detail_row(task_id, nd_title, nd_url, nd_keywords, nd_description)
                        st.success("Detail row added.")
                        _rerun()

                    st.markdown("#### Bulk paste details into this task")
                    with st.expander("Bulk add to this task"):
                        TEXT_KEY = f"bulk_task_{task_id}"
                        OUT = f"bulk_task_out_{task_id}"

                        st.text_area("Paste here", height=160, key=TEXT_KEY)

                        cc1, cc2, cc3 = st.columns([1, 1, 1])
                        with cc1:
                            st.button("Preview parse", key=f"bulk_prev_{task_id}", on_click=_bulk_preview_to_state, args=(TEXT_KEY, OUT))
                        with cc2:
                            st.button("Insert into task", key=f"bulk_ins_{task_id}", on_click=_bulk_insert_into_task, args=(task_id, TEXT_KEY, OUT))
                        with cc3:
                            st.button("Clear paste box", key=f"bulk_clear_{task_id}", on_click=_clear_text_key, args=(TEXT_KEY,))

                        errs = st.session_state.get(f"{OUT}_errs") or []
                        if errs:
                            st.warning("\n".join(errs))

                        added = st.session_state.get(f"{OUT}_added")
                        if isinstance(added, int) and added > 0:
                            st.success(f"Inserted {added} rows into task #{task_id}.")
                            st.session_state[f"{OUT}_added"] = 0

                        preview = st.session_state.get(f"{OUT}_preview") or []
                        if preview:
                            df_show(pd.DataFrame(preview))
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
                    try:
                        add_todo(
                            todo_date,
                            title,
                            notes,
                            created_by=st.session_state.username,
                            status=status
                        )
                        st.success("To-Do added.")
                    except Exception as exc:
                        st.error(f"To-Do could not be saved: {exc}")

        st.divider()
        st.markdown("### Future Plan (Date-wise)")
        colf1, colf2, colf3 = st.columns([1, 1, 1])
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
            for dt_, g in df.sort_values(["date", "id"]).groupby(df["date"].dt.date):
                st.markdown(f"#### {dt_.strftime('%d %b %Y')}")
                for _, r in g.iterrows():
                    with st.expander(f"#{r['id']} • {r['title']} • {r['status']}"):
                        new_title = st.text_input("Title", value=r["title"], key=f"todo_title_{r['id']}")
                        new_notes = st.text_area("Notes", value=r.get("notes") or "", key=f"todo_notes_{r['id']}")
                        new_date = st.date_input("Date", value=r["date"].date(), key=f"todo_date_{r['id']}")
                        new_status = st.selectbox("Status", ["Pending", "Done"], index=(0 if r["status"] == "Pending" else 1), key=f"todo_status_{r['id']}")
                        c1, c2 = st.columns([1, 1])
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
        st.subheader("Task Reports (Project + Targets)")

        tasks = get_all_tasks()
        if not tasks:
            st.info("No tasks found.")
            st.stop()

        df = pd.DataFrame(tasks)
        for col in ["date", "deadline"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

        df["status"] = df.get("status", "Pending").fillna("Pending")
        df["quantity"] = df.get("quantity", 1).fillna(1).astype(int)
        df["quantity_done"] = df.get("quantity_done", 0).fillna(0).astype(int)
        df["remaining_units"] = (df["quantity"] - df["quantity_done"]).clip(lower=0).astype(int)

        users = get_all_users()
        user_filter = st.selectbox("Filter by User", ["All"] + [u["username"] for u in users])

        try:
            projects = get_all_projects()
            project_filter = st.selectbox("Filter by Project", ["All"] + projects)
        except Exception:
            project_filter = "All"
            st.info("Projects table not found. Project filter disabled.")

        col_f1, col_f2 = st.columns([1, 2])
        with col_f1:
            view_mode = st.radio("View", ["Date-wise", "Month-wise"], horizontal=True)

        filtered_df = df.copy()
        if user_filter != "All":
            filtered_df = filtered_df[filtered_df["assigned_to"] == user_filter]
        if project_filter != "All":
            filtered_df = filtered_df[filtered_df["project"].fillna("") == project_filter]

        picked_period = None
        with col_f2:
            if view_mode == "Date-wise":
                picked_date = st.date_input("Select Date", value=date.today(), key="admin_report_date")
                filtered_df = filtered_df[filtered_df["date"].dt.date == picked_date]
            else:
                valid = filtered_df[filtered_df["date"].notna()].copy()
                unique_months = sorted(valid["date"].dt.to_period("M").unique()) if not valid.empty else []
                if unique_months:
                    labels = [p.strftime("%B %Y") for p in unique_months]
                    picked_label = st.selectbox("Select Month", labels, index=len(labels) - 1)
                    picked_period = unique_months[labels.index(picked_label)]
                    filtered_df = filtered_df[filtered_df["date"].dt.to_period("M") == picked_period]
                else:
                    st.info("No month data available for selected filters.")
                    filtered_df = filtered_df.iloc[0:0]

        if filtered_df.empty:
            st.info("No data for the selected filters.")
            st.stop()

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Tasks", int(len(filtered_df)))
        c2.metric("Done", int((filtered_df["status"] == "Done").sum()))
        c3.metric("Half", int((filtered_df["status"] == "Half").sum()))
        c4.metric("Pending", int((filtered_df["status"] == "Pending").sum()))
        c5.metric("Units Done", int(filtered_df["quantity_done"].sum()))
        c6.metric("Units Pending", int(filtered_df["remaining_units"].sum()))

        st.divider()
        st.markdown("## Project Status Breakdown")

        by_user_task = (
            filtered_df.groupby(["assigned_to", "task"], as_index=False)[["quantity_done", "remaining_units", "quantity"]]
            .sum()
            .rename(columns={"quantity_done": "done_units", "remaining_units": "pending_units", "quantity": "assigned_units"})
        )
        st.markdown("### Task-wise units by user")
        df_show(by_user_task.sort_values(["assigned_to", "task"]))

        by_task = (
            filtered_df.groupby("task", as_index=False)[["quantity_done", "remaining_units", "quantity"]]
            .sum()
            .rename(columns={"quantity_done": "done_units", "remaining_units": "pending_units", "quantity": "assigned_units"})
        )
        st.markdown("### Task-wise totals (overall)")
        df_show(by_task.sort_values("pending_units", ascending=False))

        st.markdown("### Pending items (one by one)")
        pending_list = filtered_df[(filtered_df["remaining_units"] > 0) | (filtered_df["status"] != "Done")].copy()
        show_cols = ["id", "project", "task", "assigned_to", "status", "quantity", "quantity_done", "remaining_units", "date", "deadline", "remarks"]
        show_cols = [c for c in show_cols if c in pending_list.columns]
        df_show(pending_list[show_cols].sort_values(["deadline", "date", "id"], na_position="last"))

        # ---------------- TARGET vs ACHIEVED (FIXED FOR GROUP TARGETS) ----------------
        if view_mode == "Month-wise" and picked_period is not None and project_filter != "All":
            st.divider()
            st.markdown("## Target vs Achieved (Selected Project + Month)")

            month_dt = date(int(picked_period.year), int(picked_period.month), 1)
            targets = get_monthly_targets(project_filter, month_dt)
            tgt_df = pd.DataFrame(targets) if targets else pd.DataFrame(columns=["task", "target_qty"])

            # Actual done units by task (exact tasks from tasks table)
            actual_task_done = (
                filtered_df.groupby("task", as_index=False)[["quantity_done"]]
                .sum()
                .rename(columns={"quantity_done": "done_units"})
            )

            # Build a normalized lookup for actual
            actual_lookup = { _norm_task(r["task"]): int(r["done_units"]) for _, r in actual_task_done.iterrows() }

            # Known tasks (to detect group labels)
            task_types = get_all_task_types()
            known_tasks = set(task_types) | set(filtered_df["task"].dropna().unique().tolist())
            known_tasks_norm = { _norm_task(t): t for t in known_tasks }

            # If no targets, still show actual
            if tgt_df.empty:
                merged = actual_task_done.copy()
                merged["target_qty"] = 0
                merged["pending_to_target"] = 0
                df_show(merged.sort_values("done_units", ascending=False))
            else:
                rows = []
                for _, tr in tgt_df.iterrows():
                    label = tr.get("task") or ""
                    target_qty = int(tr.get("target_qty") or 0)

                    aliases = _targets_aliases(label, known_tasks_norm)

                    done_sum = 0
                    matched = []
                    for a in aliases:
                        k = _norm_task(a)
                        if k in actual_lookup:
                            done_sum += int(actual_lookup[k])
                            matched.append(a)

                    rows.append({
                        "task": label,
                        "target_qty": target_qty,
                        "done_units": int(done_sum),
                        "pending_to_target": int(max(0, target_qty - done_sum)),
                        "matched_tasks": ", ".join(matched) if matched else ""
                    })

                merged = pd.DataFrame(rows)
                t1, t2, t3 = st.columns(3)
                t1.metric("Target", int(merged["target_qty"].sum()))
                t2.metric("Done (counted into targets)", int(merged["done_units"].sum()))
                t3.metric("Pending to Target", int(merged["pending_to_target"].sum()))

                st.caption("Matched Tasks shows which actual task names were counted into each target row.")
                df_show(merged.sort_values("pending_to_target", ascending=False))

        st.divider()
        st.markdown("## Charts")
        agg_units = (
            filtered_df.groupby("assigned_to", as_index=False)[["quantity_done", "quantity"]]
            .sum()
            .rename(columns={"quantity_done": "completed_units", "quantity": "assigned_units"})
        )
        agg_units["remaining_units"] = (agg_units["assigned_units"] - agg_units["completed_units"]).clip(lower=0)
        agg_melt = agg_units.melt(
            id_vars="assigned_to",
            value_vars=["completed_units", "remaining_units"],
            var_name="Metric",
            value_name="Units"
        )
        fig = px.bar(agg_melt, x="assigned_to", y="Units", color="Metric", barmode="stack",
                     title="Completed vs Remaining Units by User")
        st.plotly_chart(fig, width="stretch")

        count_by_status = filtered_df.groupby("status", as_index=False)["id"].count().rename(columns={"id": "Tasks"})
        fig2 = px.bar(count_by_status, x="status", y="Tasks", title="Task Count by Status (Selected Period)")
        st.plotly_chart(fig2, width="stretch")

    # ---------- DATA CLEANUP (Admin) ----------
    elif choice == "Data Cleanup" and st.session_state.role == "Admin":
        st.subheader("Data Cleanup (Delete Old Data)")

        try:
            projects = get_all_projects()
            project_filter = st.selectbox("Project (optional)", ["All"] + projects, key="clean_project")
        except Exception:
            project_filter = "All"
            st.info("Projects table not found. Project filter disabled.")

        mode = st.radio("Delete Mode", ["Year-wise", "Month-wise", "Date-range wise"], horizontal=True)

        delete_tasks_opt = st.checkbox("Delete Tasks (includes details)", value=True)
        delete_targets_opt = st.checkbox("Delete Monthly Targets", value=False)
        delete_todos_opt = st.checkbox("Delete To-Dos", value=False)

        st.caption("Tasks will automatically remove task_details (ON DELETE CASCADE).")

        if mode == "Year-wise":
            yr = st.number_input("Year", min_value=2000, max_value=2100, value=date.today().year, step=1)
            start_dt, end_dt = year_range(int(yr))
            st.info(f"Range: {start_dt} → {end_dt} (end exclusive)")

        elif mode == "Month-wise":
            c1, c2 = st.columns(2)
            with c1:
                yr = st.number_input("Year", min_value=2000, max_value=2100, value=date.today().year, step=1, key="clean_year")
            with c2:
                mo = st.number_input("Month (1-12)", min_value=1, max_value=12, value=date.today().month, step=1, key="clean_month")
            start_dt, end_dt = month_range(int(yr), int(mo))
            st.info(f"Range: {start_dt} → {end_dt} (end exclusive)")

        else:
            c1, c2 = st.columns(2)
            with c1:
                start_dt = st.date_input("From date", value=date.today() - timedelta(days=30))
            with c2:
                end_dt = st.date_input("To date (inclusive)", value=date.today())
            end_dt = end_dt + timedelta(days=1)
            st.info(f"Range: {start_dt} → {end_dt} (end exclusive)")

        st.divider()
        st.markdown("### Confirm delete")
        st.warning("This will permanently delete data from Supabase.")
        confirm = st.text_input("Type DELETE to confirm", value="")

        if st.button("Delete Now"):
            if confirm.strip().upper() != "DELETE":
                st.error("Not confirmed. Type DELETE exactly.")
            else:
                if delete_tasks_opt:
                    delete_tasks_by_range(start_dt, end_dt, project=project_filter)
                if delete_targets_opt:
                    delete_targets_by_range(start_dt, end_dt, project=project_filter)
                if delete_todos_opt:
                    delete_todos_by_range(start_dt, end_dt, created_by=None)

                st.success("Deleted successfully.")
                _rerun()

    # ---------- NOTIFICATIONS (Admin) ----------
    elif choice == "Notifications" and st.session_state.role == "Admin":
        st.subheader("Notifications")

        st.markdown("### Automatic Daily Summary (9:15 AM)")
        st.checkbox(
            "Enable automatic desktop summary at 9:15 AM",
            value=st.session_state.get("auto_summary_enabled", True),
            key="auto_summary_enabled"
        )
        st.caption(
            "This tab needs to be open in your browser around 9:15 AM (IST) for the desktop "
            "notification to pop up — it refreshes itself quietly in the background to check the time."
        )

        st.divider()
        st.markdown("### Send It Manually")
        pick_date = st.date_input("Date", value=date.today(), key="notif_pick_date")

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("🔔 Show Desktop Notification Now"):
                msg = build_summary_notification(pick_date)
                if msg:
                    show_browser_notifications([msg])
                    st.success("Notification sent — check your browser/desktop.")
                else:
                    st.info("No tasks were assigned on that date.")
        with col2:
            if st.button("Refresh Table"):
                _rerun()

        st.divider()
        st.markdown(f"### Summary — {pick_date.strftime('%d %b %Y')}")
        rows = get_daily_task_summary(pick_date)
        if not rows:
            st.info("No tasks assigned on this date.")
        else:
            df_sum = pd.DataFrame(rows).rename(
                columns={"user": "Team Member", "assigned": "Assigned", "closed": "Closed", "pending": "Pending"}
            )
            df_show(df_sum[["Team Member", "Assigned", "Closed", "Pending"]].sort_values("Team Member"))

            t1, t2, t3 = st.columns(3)
            t1.metric("Total Assigned", int(df_sum["Assigned"].sum()))
            t2.metric("Total Closed", int(df_sum["Closed"].sum()))
            t3.metric("Total Pending", int(df_sum["Pending"].sum()))

    # ---------- MY TASKS (Team) ----------
    elif choice == "My Tasks" and st.session_state.role != "Admin":
        st.subheader("My Tasks")

        my_tasks = get_user_tasks(st.session_state.username)
        df = pd.DataFrame(my_tasks) if my_tasks else pd.DataFrame(columns=[
            "id", "project", "task", "status", "remarks", "quantity", "quantity_done", "date", "deadline",
            "title", "url", "keywords", "description"
        ])

        if df.empty:
            st.info("No tasks assigned yet.")
        else:
            for col in ["date", "deadline"]:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors="coerce")

            df["status"] = df["status"].fillna("Pending")
            df["quantity"] = df["quantity"].fillna(1).astype(int)
            df["quantity_done"] = df["quantity_done"].fillna(0).astype(int)

            pending_now = df[df["status"] != "Done"]
            if not pending_now.empty:
                st.sidebar.markdown("### Pending Tasks")
                for _, r in pending_now.sort_values(by=["deadline", "date", "id"]).iterrows():
                    label = f"#{r['id']} • {r.get('project','')} • {r.get('task','')}"
                    st.sidebar.markdown(f":red[{label}]")

            st.markdown("#### Filters")
            col_vm1, col_vm2 = st.columns([1, 1])
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
                fdf = fdf[fdf["status"] == status_filter]

            if fdf.empty:
                st.info("No tasks for the selected period.")
            else:
                for _, row in fdf.sort_values(by=["date", "deadline", "id"]).iterrows():
                    header = f"#{row['id']} • {row.get('project','')} • {row.get('task','(no task)')} • {row.get('status','')}"
                    with st.expander(header):
                        total_q = int(row.get("quantity", 1))
                        done_q = int(row.get("quantity_done", 0))
                        remain_q = max(0, total_q - done_q)

                        st.markdown(f"**Project:** {row.get('project','')}")
                        st.markdown(f"**Task:** {row.get('task','')}")
                        st.markdown(f"**Quantity Assigned:** {total_q}")
                        st.markdown(f"**Completed:** {done_q}")
                        st.markdown(f"**Remaining:** {remain_q}")
                        st.markdown(f"**Date:** {row['date'].date() if pd.notna(row['date']) else ''}")
                        st.markdown(f"**Deadline:** {row['deadline'].date() if pd.notna(row['deadline']) else ''}")
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
                            df_show(pd.DataFrame(table))
                        else:
                            st.info("No details attached to this task.")

                        st.markdown("---")
                        new_done = st.number_input(
                            "Update completed units",
                            min_value=0, max_value=total_q,
                            value=done_q, step=1,
                            key=f"done_{row['id']}"
                        )

                        suggested_status = _status_from_progress(int(new_done), int(total_q), row.get("status", "Pending"))
                        new_status = st.selectbox(
                            "Update Status", ["Pending", "Half", "Done"],
                            index=["Pending", "Half", "Done"].index(suggested_status),
                            key=f"status_{row['id']}"
                        )
                        new_remarks = st.text_area("Remarks", value=row.get("remarks") or "", key=f"remarks_{row['id']}")
                        if st.button("Save Update", key=f"save_{row['id']}"):
                            final_status = "Done" if new_done >= total_q else new_status
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
                    try:
                        add_todo(
                            todo_date,
                            title,
                            notes,
                            created_by=st.session_state.username,
                            status=status
                        )
                        st.success("To-Do added.")
                    except Exception as exc:
                        st.error(f"To-Do could not be saved: {exc}")

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
            for dt_, g in df.sort_values(["date", "id"]).groupby(df["date"].dt.date):
                st.markdown(f"#### {dt_.strftime('%d %b %Y')}")
                for _, r in g.iterrows():
                    with st.expander(f"#{r['id']} • {r['title']} • {r['status']}"):
                        new_title = st.text_input("Title", value=r["title"], key=f"mytodo_title_{r['id']}")
                        new_notes = st.text_area("Notes", value=r.get("notes") or "", key=f"mytodo_notes_{r['id']}")
                        new_date = st.date_input("Date", value=r["date"].date(), key=f"mytodo_date_{r['id']}")
                        new_status = st.selectbox("Status", ["Pending", "Done"], index=(0 if r["status"] == "Pending" else 1), key=f"mytodo_status_{r['id']}")
                        c1, c2 = st.columns([1, 1])
                        with c1:
                            if st.button("Save", key=f"mytodo_save_{r['id']}"):
                                update_todo(int(r["id"]), title=new_title, notes=new_notes, date_val=new_date, status=new_status)
                                st.success("Saved")
                                _rerun()
                        with c2:
                            if st.button("Delete", key=f"mytodo_del_{r['id']}"):
                                delete_todos([int(r["id"])])
                                st.success("Deleted")
                                _rerun()
