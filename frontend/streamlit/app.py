import streamlit as st
import os
import json
import requests

st.set_page_config(page_title="Jira Bug Solver", page_icon="🛠️")

st.title("Jira Bug Solver Dashboard")
st.markdown("Step 1: Clone locally (no Docker auto-heal). Step 2: Fetch Jira incidents and run the bug-solving pipeline.")


def _coerce_description(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []

        def walk(node):
            if isinstance(node, dict):
                text = node.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
                for child in node.values():
                    walk(child)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(value)
        if parts:
            return "\n".join(parts)
        return json.dumps(value, indent=2, default=str)
    return str(value)


if "tickets" not in st.session_state:
    st.session_state.tickets = []
if "pipeline_logs" not in st.session_state:
    st.session_state.pipeline_logs = ""
if "pipeline_report" not in st.session_state:
    st.session_state.pipeline_report = None
if "pipeline_meta" not in st.session_state:
    st.session_state.pipeline_meta = {}
if "clone_ready" not in st.session_state:
    st.session_state.clone_ready = False
if "clone_result" not in st.session_state:
    st.session_state.clone_result = {}


backend_base_url = st.text_input("Backend API Base URL", value="http://127.0.0.1:8000")

st.subheader("Step 1 — Clone Repository (Required)")
repo_url = st.text_input("GitHub Repo URL", placeholder="https://github.com/OWNER/REPO.git")
repo_id = st.text_input("Local Folder Name", placeholder="shopstack-platform_testing")
ref = st.text_input("Branch/Tag/Commit (Ref)", value="main")

default_path = "C:/data/repos" if os.name == "nt" else "/data/repos"
local_storage = st.text_input("Local Storage Location", value=default_path)
st.caption("Docker auto-heal is disabled for this flow so clone completes first and incidents can be shown immediately.")

if st.button("Clone Repository", type="primary"):
    if not repo_id or not local_storage or not backend_base_url:
        st.error("Please fill in Repo ID, Local Storage Location, and Backend API Base URL.")
    else:
        payload = {
            "repoUrl": repo_url,
            "repoId": repo_id,
            "ref": ref if ref else "main",
            "localStorageLocation": local_storage,
            "autoRunDocker": False,
        }

        clone_status = st.empty()
        clone_status.info("Calling backend clone agent...")

        try:
            endpoint = f"{backend_base_url.rstrip('/')}/agent/clone-repo"
            response = requests.post(endpoint, json=payload, timeout=300)

            if response.ok:
                result = response.json()
                if result.get("status") == "ok":
                    st.session_state.clone_ready = True
                    st.session_state.clone_result = result
                    clone_status.success(
                        f"Repository {result.get('operation')} at {result.get('localPath')} (commit {result.get('commitSha')})."
                    )
                else:
                    st.session_state.clone_ready = False
                    st.session_state.clone_result = {}
                    clone_status.empty()
                    st.error(f"Clone agent returned an error: {result}")
            else:
                st.session_state.clone_ready = False
                st.session_state.clone_result = {}
                clone_status.empty()
                st.error("Backend clone endpoint returned an error.")
                try:
                    st.json(response.json())
                except Exception:
                    st.code(response.text, language="log")

        except Exception as e:
            st.session_state.clone_ready = False
            st.session_state.clone_result = {}
            clone_status.empty()
            st.error(f"Failed to call backend clone agent: {str(e)}")

if st.session_state.clone_ready:
    clone_result = st.session_state.clone_result
    st.success(
        f"Clone complete. Local path: {clone_result.get('localPath')} | Checked out: {clone_result.get('checkedOutRef', clone_result.get('ref'))}"
    )
else:
    st.info("Clone the repository first. Jira incidents and pipeline controls will appear after a successful clone.")
    st.stop()

st.divider()
st.subheader("Step 2 — Incidents (Jira) and Bug-Solving Flow")

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("Fetch Jira Tickets", use_container_width=True):
        try:
            resp = requests.get(f"{backend_base_url.rstrip('/')}/tickets", timeout=60)
            if not resp.ok:
                st.error(f"Failed to fetch tickets (status {resp.status_code})")
            else:
                st.session_state.tickets = resp.json() or []
                st.success(f"Fetched {len(st.session_state.tickets)} ticket(s) from Jira")
        except Exception as exc:
            st.error(f"Failed to fetch Jira tickets: {exc}")

with col2:
    run_pipeline_clicked = st.button("Solve all the bugs", type="primary", use_container_width=True)

st.subheader("Jira Tickets")
if st.session_state.tickets:
    summary_rows = [
        {
            "Key": t.get("jira_key"),
            "Summary": t.get("summary"),
            "Priority": t.get("priority"),
            "Status": t.get("status"),
        }
        for t in st.session_state.tickets
    ]
    st.dataframe(summary_rows, use_container_width=True)

    for ticket in st.session_state.tickets:
        title = f"{ticket.get('jira_key', 'UNKNOWN')} — {ticket.get('summary', 'No summary')}"
        with st.expander(title):
            st.markdown(f"**Priority:** {ticket.get('priority', 'N/A')}  ")
            st.markdown(f"**Status:** {ticket.get('status', 'N/A')}  ")
            description = _coerce_description(ticket.get("description"))
            st.markdown("**Description:**")
            st.code(description or "No description", language="markdown")
else:
    st.info("No Jira tickets loaded yet. Click **Fetch Jira Tickets**.")

st.subheader("Pipeline Logs")
log_box = st.empty()
status_box = st.empty()

if run_pipeline_clicked:
    endpoint = f"{backend_base_url.rstrip('/')}/pipeline/solve-all-bugs"
    logs: list[str] = []
    status_box.info("Running `test_pipeline.py` on backend...")
    try:
        with requests.post(endpoint, stream=True, timeout=7200) as response:
            if not response.ok:
                status_box.empty()
                st.error(f"Pipeline run failed to start (status {response.status_code})")
                try:
                    st.json(response.json())
                except Exception:
                    st.code(response.text, language="log")
            else:
                for raw_line in response.iter_lines(decode_unicode=True):
                    if raw_line is None:
                        continue
                    line = str(raw_line).rstrip("\r")
                    logs.append(line)
                    if len(logs) % 5 == 0:
                        log_box.code("\n".join(logs), language="log")

                st.session_state.pipeline_logs = "\n".join(logs)
                log_box.code(st.session_state.pipeline_logs or "No logs produced.", language="log")

                last_run_resp = requests.get(f"{backend_base_url.rstrip('/')}/pipeline/last-run", timeout=60)
                if last_run_resp.ok:
                    payload = last_run_resp.json() or {}
                    st.session_state.pipeline_meta = payload
                    st.session_state.pipeline_report = payload.get("report")

                    exit_code = payload.get("exitCode")
                    if exit_code == 0:
                        status_box.success("Pipeline completed successfully.")
                    else:
                        status_box.warning(f"Pipeline finished with exit code {exit_code}.")
                else:
                    status_box.warning("Pipeline finished, but failed to fetch last run report.")
    except Exception as exc:
        status_box.empty()
        st.error(f"Failed while streaming pipeline logs: {exc}")

if st.session_state.pipeline_logs and not run_pipeline_clicked:
    log_box.code(st.session_state.pipeline_logs, language="log")

st.subheader("Detailed Report")
report = st.session_state.pipeline_report
if report:
    summary = report.get("summary") or {}
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Requested", summary.get("requested", 0))
    s2.metric("Processed", summary.get("processed", 0))
    s3.metric("Successful", summary.get("successful", 0))
    s4.metric("Halted", "Yes" if summary.get("halted") else "No")

    if summary.get("halt_reason"):
        st.warning(f"Halt reason: {summary.get('halt_reason')}")

    for item in report.get("tickets", []):
        key = item.get("ticket_key", "UNKNOWN")
        status = item.get("status", "unknown")
        with st.expander(f"{key} | status={status}"):
            st.markdown(f"**Success:** {item.get('success')}  ")
            st.markdown(f"**Attempts:** {item.get('attempt_count')}  ")
            if item.get("error"):
                st.markdown(f"**Error:** `{item.get('error')}`")
            if item.get("edit_reason"):
                st.markdown(f"**Reason for edit:** {item.get('edit_reason')}")

            edited_files = item.get("edited_files") or []
            if edited_files:
                st.markdown("**Files edited:**")
                for path in edited_files:
                    st.code(path, language="text")

            where_edited = item.get("where_was_edited") or []
            if where_edited:
                st.markdown("**Where edits were applied (diff artifacts):**")
                for path in where_edited:
                    st.code(path, language="text")

            edit_details = item.get("edit_details") or []
            if edit_details:
                st.markdown("**Edit details:**")
                st.dataframe(edit_details, use_container_width=True)

            tests = item.get("tests") or {}
            st.markdown("**Test results:**")
            st.markdown(f"- Passed: `{tests.get('passed')}`")
            st.markdown(f"- Selected tests: `{tests.get('selected_tests')}`")
            st.markdown(f"- Failed tests: `{tests.get('failed_tests')}`")
            st.markdown(f"- Test plan source: `{tests.get('test_plan_source')}`")
            if tests.get("failure_reason"):
                st.markdown("- Failure reason:")
                st.code(str(tests.get("failure_reason")), language="log")
else:
    st.info("No report available yet. Run **Solve all the bugs** to generate one.")
