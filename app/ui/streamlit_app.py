"""本地演示界面。历史页只展示检查点摘要，不是 LangGraph Studio。"""

from __future__ import annotations

import streamlit as st

from app.authz import DEPARTMENT_LABELS, LIBRARY_LABELS
from app.ui.api_client import (
    ApiError,
    api_base_url,
    bind_token,
    compare_artifacts,
    create_project,
    download_artifact,
    fork_run,
    get_run,
    index_document,
    list_artifacts,
    list_checkpoints,
    list_documents,
    list_events,
    list_projects,
    list_runs,
    login_user,
    register_user,
    resume_run,
    review,
    search_evidence,
    start_run,
    upload_document,
)


def main() -> None:
    st.set_page_config(page_title="EnterprisePlan AI", layout="wide")
    bind_token(st.session_state.get("token"))
    st.sidebar.title("EnterprisePlan AI")
    st.sidebar.caption(f"API：{api_base_url()}")
    if not st.session_state.get("token"):
        try:
            _account()
        except ApiError as exc:
            st.error(f"{exc}（HTTP {exc.status_code}）")
        except Exception as exc:
            st.error(f"无法连接 API：{type(exc).__name__}")
        return
    user = st.session_state.get("user") or {}
    st.sidebar.caption(
        f"{user.get('username', '')} · {DEPARTMENT_LABELS.get(user.get('department', ''), '')}"
    )
    st.sidebar.caption("审核记录仍使用本地演示身份，不是生产身份认证。")
    if st.sidebar.button("退出登录"):
        st.session_state.clear()
        bind_token(None)
        st.rerun()
    page = st.sidebar.radio(
        "页面",
        ["项目工作台", "知识库", "人工审核", "执行历史", "产物与版本"],
    )
    pages = {
        "项目工作台": _workspace,
        "知识库": _knowledge,
        "人工审核": _review,
        "执行历史": _history,
        "产物与版本": _artifacts,
    }
    try:
        pages[page]()
    except ApiError as exc:
        if exc.status_code == 401:
            st.session_state.pop("token", None)
            st.session_state.pop("user", None)
            bind_token(None)
        st.error(f"{exc}（HTTP {exc.status_code}）")
    except Exception as exc:
        st.error(f"无法连接 API：{type(exc).__name__}")


def _account() -> None:
    st.header("登录")
    st.caption("创建用户时必须选择部门。登录后只能查看本部门和公共资料库。")
    login_tab, register_tab = st.tabs(["登录", "创建用户"])
    with login_tab:
        with st.form("login"):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录")
        if submitted:
            result = login_user(username, password)
            _store_session(result)
    with register_tab:
        with st.form("register"):
            username = st.text_input("新用户名")
            password = st.text_input("密码", type="password")
            department = st.selectbox(
                "部门",
                list(DEPARTMENT_LABELS),
                format_func=lambda key: DEPARTMENT_LABELS[key],
            )
            submitted = st.form_submit_button("创建并登录")
        if submitted:
            result = register_user(username, password, department)
            _store_session(result)


def _store_session(result: dict) -> None:
    st.session_state["token"] = result["token"]
    st.session_state["user"] = result["user"]
    bind_token(result["token"])
    st.rerun()


def _workspace() -> None:
    st.header("项目工作台")
    st.caption("创建项目并启动生成。节点进度来自轮询，不是实时推送。")
    with st.form("create_project"):
        name = st.text_input("项目名称")
        objective = st.text_area("目标")
        background = st.text_area("背景")
        constraints = st.text_area("约束")
        start = st.text_input("计划开始日期", value="2026-01-01")
        end = st.text_input("计划结束日期", value="2026-06-30")
        submitted = st.form_submit_button("创建项目")
    if submitted:
        created = create_project(
            {
                "name": name.strip(),
                "objective": objective.strip(),
                "background": background.strip(),
                "constraints": constraints.strip(),
                "plan_start_date": start.strip() or None,
                "plan_end_date": end.strip() or None,
            }
        )
        st.session_state["project_id"] = created["id"]
        st.success(f"已创建项目 {created['id']}")

    project_id = _select_project()
    if project_id is None:
        return
    request_text = st.text_area("本次生成要求", value="请编制实施方案")
    deliverables = st.text_input("交付物，用顿号分隔", value="项目书、任务计划")
    if st.button("启动生成"):
        items = [item.strip() for item in deliverables.split("、") if item.strip()]
        run = start_run(project_id, request_text, items)
        st.session_state["run_id"] = run["id"]
        st.success(f"运行 {run['id']}，状态 {run['status']}")
    _show_run_progress()


def _knowledge() -> None:
    st.header("知识库")
    project_id = _select_project()
    uploaded = st.file_uploader("上传 PDF、DOCX 或 XLSX", type=["pdf", "docx", "xlsx"])
    library_choice = st.radio("上传到", ["本部门", "公共资料库"], horizontal=True)
    if uploaded is not None and st.button("上传"):
        library = "department" if library_choice == "本部门" else "public"
        document = upload_document(uploaded.name, uploaded.getvalue(), project_id, library)
        st.success(
            f"已登记 {document['filename']} 到 {LIBRARY_LABELS.get(document['library'], document['library'])}"
        )
    documents = list_documents(project_id)
    if documents:
        st.dataframe(
            [
                {
                    "id": item["id"],
                    "文件": item["filename"],
                    "资料库": LIBRARY_LABELS.get(item.get("library"), item.get("library")),
                    "类型": item["document_type"],
                    "版本": item["version_number"],
                    "有效性": item["validity_status"],
                    "索引": item["index_status"],
                    "chunk": item["chunk_count"],
                }
                for item in documents
            ],
            hide_index=True,
        )
        choice = st.selectbox("要索引的文档", [item["id"] for item in documents])
        if st.button("解析并索引"):
            result = index_document(choice)
            st.info(
                f"索引状态 {result['index_status']}，chunk {result['chunk_count']}，"
                f"embedding={result['embedding_provider']}"
            )
    query = st.text_input("试检索")
    if query.strip() and st.button("检索"):
        found = search_evidence(query.strip(), project_id)
        if found.get("embedding_mock"):
            st.warning("当前 embedding 是 mock，检索结果不能当作真实向量召回。")
        for item in found.get("items") or []:
            st.markdown(
                f"**{item.get('title')}** · 第 {item.get('page_number') or '—'} 页 · "
                f"{item.get('section') or '无章节'} · {item.get('verification_status')}"
            )
            st.text(item.get("quote") or "")


def _review() -> None:
    st.header("人工审核")
    st.caption("批准只会生成演示确认的 DOCX/XLSX，不会自动正式发布。")
    run_id = _select_run()
    if run_id is None:
        return
    payload = review(run_id)
    st.write(f"状态：{payload['status']} · 提示词版本：{payload.get('prompt_version')}")
    st.info(payload.get("demo_identity_notice"))
    st.subheader(payload.get("proposal_title") or "项目书")
    for section in payload.get("sections") or []:
        mark = "【待确认】" if section.get("needs_confirmation") else ""
        st.markdown(f"**{mark}{section.get('heading')}**")
        st.caption(f"引用：{', '.join(section.get('evidence_ids') or []) or '无'}")
    st.subheader("任务")
    st.dataframe(payload.get("tasks") or [], hide_index=True)
    st.subheader("审查问题")
    st.dataframe(payload.get("issues") or [], hide_index=True)
    st.subheader("证据")
    for item in payload.get("evidence") or []:
        st.markdown(
            f"`{item.get('evidence_id')}` {item.get('title')} · "
            f"第 {item.get('page_number') or '—'} 页 · {item.get('section') or '无章节'}"
        )
    decision = st.radio("决策", ["approve", "revise", "request_information", "select_option"])
    comment = st.text_area("意见")
    information = st.text_area("补充信息")
    selected = st.text_input("选项")
    if st.button("提交决策"):
        updated = resume_run(
            run_id,
            {
                "decision": decision,
                "comment": comment,
                "information": information,
                "selected_option": selected or None,
            },
        )
        st.success(f"恢复后状态：{updated['status']}")


def _history() -> None:
    st.header("执行历史")
    st.caption("这里只列出运行、线程、分支、节点事件和检查点摘要，不是图形化 LangGraph Studio。")
    st.caption("从检查点继续会重新执行后续节点，模型输出不保证逐字一致。检查点目前不会自动清理。")
    run_id = _select_run()
    if run_id is None:
        return
    current = get_run(run_id)
    st.write(
        {
            "run_id": current["id"],
            "thread_id": current["thread_id"],
            "parent_run_id": current.get("parent_run_id"),
            "parent_checkpoint_id": current.get("parent_checkpoint_id"),
            "branch_label": current.get("branch_label"),
            "status": current["status"],
        }
    )
    st.subheader("节点事件")
    st.dataframe(list_events(run_id), hide_index=True)
    checkpoints = list_checkpoints(run_id)
    st.subheader("检查点摘要")
    st.dataframe(checkpoints, hide_index=True)
    if not checkpoints:
        return
    checkpoint_id = st.selectbox("用于分叉的检查点", [item["checkpoint_id"] for item in checkpoints])
    label = st.text_input("分支名称", value="修订分支")
    request_text = st.text_input("可选的新要求")
    constraints = st.text_input("可选的新约束")
    if st.button("从该检查点创建分支"):
        child = fork_run(
            run_id,
            {
                "checkpoint_id": checkpoint_id,
                "branch_label": label,
                "user_request": request_text or None,
                "constraints": constraints or None,
            },
        )
        st.session_state["run_id"] = child["id"]
        st.success(f"新分支 {child['id']}，thread {child['thread_id']}")


def _artifacts() -> None:
    st.header("产物与版本")
    st.caption("差异展示是文本级 unified diff，不是语义级版本比较。")
    project_id = _select_project()
    if project_id is None:
        return
    artifacts = list_artifacts(project_id)
    if not artifacts:
        st.info("还没有产物。批准运行后会生成草稿快照、DOCX 和 XLSX。")
        return
    st.dataframe(
        [
            {
                "id": item["id"],
                "类型": item["artifact_type"],
                "版本": item["version_number"],
                "父版本": item.get("parent_version_id"),
                "审核状态": item["review_status"],
                "sha256": item["sha256"],
                "摘要": item["summary"],
                "运行": item["run_id"],
            }
            for item in artifacts
        ],
        hide_index=True,
    )
    selected = st.selectbox("下载", [item["id"] for item in artifacts])
    chosen = next(item for item in artifacts if item["id"] == selected)
    st.download_button(
        "下载文件",
        data=download_artifact(selected),
        file_name=f"{chosen['artifact_type']}_v{chosen['version_number']}",
    )
    left, right = st.columns(2)
    left_id = left.selectbox("比较左侧", [item["id"] for item in artifacts], key="diff_left")
    right_id = right.selectbox("比较右侧", [item["id"] for item in artifacts], key="diff_right")
    if st.button("查看文本差异"):
        result = compare_artifacts(left_id, right_id)
        st.caption(result["note"])
        st.code(result["diff"] or "两边的提取文本相同。", language="diff")


def _select_project() -> str | None:
    projects = list_projects()
    if not projects:
        st.info("还没有项目。")
        return None
    labels = {f"{item['name']} ({item['id']})": item["id"] for item in projects}
    current = st.session_state.get("project_id")
    options = list(labels)
    index = 0
    for position, label in enumerate(options):
        if labels[label] == current:
            index = position
    selected = st.selectbox("项目", options, index=index)
    project_id = labels[selected]
    st.session_state["project_id"] = project_id
    return project_id


def _select_run() -> str | None:
    project_id = _select_project()
    if project_id is None:
        return None
    runs = list_runs(project_id)
    if not runs:
        st.info("这个项目还没有运行。")
        return None
    labels = {
        f"{item['status']} · {item.get('branch_label') or '主运行'} · {item['id']}": item["id"] for item in runs
    }
    current = st.session_state.get("run_id")
    options = list(labels)
    index = 0
    for position, label in enumerate(options):
        if labels[label] == current:
            index = position
    selected = st.selectbox("运行", options, index=index)
    run_id = labels[selected]
    st.session_state["run_id"] = run_id
    return run_id


def _show_run_progress() -> None:
    run_id = st.session_state.get("run_id")
    if not run_id:
        return
    if st.button("刷新状态"):
        current = get_run(run_id)
        st.write(f"状态：{current['status']} · thread：{current['thread_id']}")
        st.dataframe(list_events(run_id), hide_index=True)


if __name__ == "__main__":
    main()
