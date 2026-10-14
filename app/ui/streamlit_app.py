"""计划书生成、审核和历史。资料库只负责上传，不进入生成表单。"""

from __future__ import annotations

import json

import httpx
import streamlit as st

from app.authz import DEPARTMENT_LABELS, LIBRARY_LABELS, PUBLIC_LIBRARY
from app.ui.api_client import (
    ApiError,
    api_base_url,
    bind_token,
    compare_artifacts,
    create_proposal,
    demo_login,
    download_artifact,
    get_run,
    health,
    index_document,
    list_artifacts,
    list_documents,
    list_events,
    list_projects,
    list_runs,
    login_user,
    resume_run,
    review,
    search_evidence,
    upload_document,
)

DECISIONS = (
    ("approve", "批准"),
    ("revise", "退回修订"),
    ("request_information", "补充信息"),
)
STATUS_LABELS = {
    "awaiting_review": "等待审核",
    "awaiting_information": "等待补充信息",
    "approved_pending_export": "已批准",
    "failed": "失败",
    "running": "执行中",
}
STAGE_LABELS = {
    "analyze_request": "整理需求",
    "check_missing_information": "检查缺项",
    "human_clarification": "等待补充",
    "retrieve_evidence": "检索材料",
    "assess_evidence": "整理证据",
    "generate_proposal": "撰写计划书",
    "generate_plan": "整理实施要点",
    "validate_plan": "规则校验",
    "audit_output": "质量审查",
    "revise_output": "定向修订",
    "human_approval": "人工审核",
    "fail": "失败",
}


def _download_bytes(artifact_id: str) -> bytes:
    payload = download_artifact(artifact_id)
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def main() -> None:
    st.set_page_config(page_title="EnterprisePlan AI", layout="wide")
    bind_token(st.session_state.get("token"))
    st.sidebar.title("EnterprisePlan AI")
    st.sidebar.caption("演示身份，不是生产认证。")
    if not st.session_state.get("token"):
        try:
            _entry()
        except ApiError as exc:
            st.error(f"{exc}（HTTP {exc.status_code}）")
        except httpx.HTTPError as exc:
            st.error(f"无法连接 API：{type(exc).__name__}")
        return
    user = st.session_state.get("user") or {}
    department = DEPARTMENT_LABELS.get(user.get("department", ""), "当前组")
    st.sidebar.caption(f"{user.get('username', '')} · {department} + 公共组")
    _mock_banner()
    if st.sidebar.button("退出"):
        st.session_state.clear()
        bind_token(None)
        st.rerun()
    page = st.sidebar.radio("页面", ["生成", "审核", "历史", "资料库"])
    try:
        if page == "生成":
            _generate(department)
        elif page == "审核":
            _review_page()
        elif page == "历史":
            _history()
        else:
            _library(department)
    except ApiError as exc:
        if exc.status_code == 401:
            st.session_state.pop("token", None)
            st.session_state.pop("user", None)
            bind_token(None)
        st.error(f"{exc}（HTTP {exc.status_code}）")
    except httpx.HTTPError as exc:
        st.error(f"无法连接 API：{type(exc).__name__}")
    except Exception as exc:  # noqa: BLE001 界面只显示异常类型，避免未处理错误中断页面
        st.error(f"页面处理失败：{exc}")


def _entry() -> None:
    st.header("进入演示")
    st.caption(f"API：{api_base_url()}。登录后只检索所选组和公共组的材料。")
    department = st.selectbox(
        "演示组",
        list(DEPARTMENT_LABELS),
        format_func=lambda key: DEPARTMENT_LABELS[key],
    )
    if st.button("进入", type="primary"):
        _store_session(demo_login(department))
    with st.expander("已有账号"):
        with st.form("login"):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录")
        if submitted:
            if not username.strip() or not password:
                st.warning("请填写用户名和密码。")
            else:
                _store_session(login_user(username, password))


def _store_session(result: dict) -> None:
    st.session_state["token"] = result["token"]
    st.session_state["user"] = result["user"]
    bind_token(result["token"])
    st.rerun()


def _mock_banner() -> None:
    try:
        payload = health()
    except (ApiError, httpx.HTTPError):
        st.sidebar.warning("健康检查失败")
        return
    if payload.get("mock_mode"):
        st.sidebar.warning("Mock 模式，不是真实模型输出")
    else:
        st.sidebar.caption(f"模型：{payload.get('llm_provider')}")


def _generate(department: str) -> None:
    st.header("生成计划书")
    st.caption(f"检索范围：{department} 与公共组。不需要选择资料范围，也不需要填写日期或交付物。")
    with st.form("proposal"):
        title = st.text_input("计划书标题")
        content = st.text_area("计划书大致内容", height=180)
        submitted = st.form_submit_button("生成", type="primary")
    if submitted:
        if not title.strip() or not content.strip():
            st.warning("请填写标题和大致内容。")
        else:
            with st.spinner("正在检索材料并生成计划书…"):
                created = create_proposal(title.strip(), content.strip())
            st.session_state["project_id"] = created["project_id"]
            st.session_state["run_id"] = created["run_id"]
            if created.get("mock_mode"):
                st.warning("这次结果来自 Mock 模式，不能当作真实模型输出。")
            st.success(f"已提交。当前状态：{_status_label(created.get('status') or '')}")
    run_id = st.session_state.get("run_id")
    if run_id:
        _progress(run_id)


def _progress(run_id: str) -> None:
    run = get_run(run_id)
    st.subheader(_status_label(run.get("status") or ""))
    if run.get("error_summary"):
        st.error(run["error_summary"])
    events = list_events(run_id)
    if events:
        st.caption(
            " → ".join(STAGE_LABELS.get(item["node_name"], item["node_name"]) for item in events)
        )
    status = run.get("status")
    if status in {"awaiting_review", "awaiting_information"}:
        st.info("草稿已停下，请到「审核」页处理。")
    elif status == "approved_pending_export":
        st.info("已批准。DOCX 在「历史」页下载。")


def _review_page() -> None:
    st.header("审核")
    run_id = _pick_run()
    if run_id is None:
        st.info("还没有可审核的计划书。先到「生成」页提交标题和大致内容。")
        return
    payload = review(run_id)
    status = payload.get("status") or ""
    st.subheader(f"{payload.get('proposal_title') or '计划书'} · {_status_label(status)}")
    st.caption(payload.get("demo_identity_notice"))
    unresolved = payload.get("unresolved_items") or []
    if unresolved:
        st.warning("待确认：" + "、".join(unresolved))
    gaps = payload.get("evidence_gaps") or []
    if gaps:
        st.caption("证据缺口：" + "、".join(str(item) for item in gaps))
    for section in payload.get("sections") or []:
        mark = "【待确认】" if section.get("needs_confirmation") else ""
        st.markdown(f"**{mark}{section.get('heading') or '未命名章节'}**")
        if section.get("body"):
            st.write(section["body"])
        evidence_ids = section.get("evidence_ids") or []
        if evidence_ids:
            st.caption("引用：" + "、".join(evidence_ids))
    issues = payload.get("issues") or []
    if issues:
        st.markdown("**审查问题**")
        st.dataframe(issues, hide_index=True)
    evidence = payload.get("evidence") or []
    if evidence:
        with st.expander(f"引用来源（{len(evidence)}）"):
            for item in evidence:
                st.markdown(
                    f"**{item.get('title') or '未命名来源'}** · "
                    f"第 {item.get('page_number') or '—'} 页 · {item.get('section') or '无章节'}"
                )
                if item.get("quote"):
                    st.text(item["quote"])
    if status in {"awaiting_review", "awaiting_information"}:
        _decision_form(run_id, status)


def _decision_form(run_id: str, status: str) -> None:
    st.markdown("**审核决定**")
    options = DECISIONS if status == "awaiting_review" else (("request_information", "补充信息"),)
    decision = st.radio(
        "决定",
        [code for code, _label in options],
        format_func=lambda code: dict(DECISIONS)[code],
        horizontal=True,
    )
    comment = ""
    information = ""
    if decision == "revise":
        comment = st.text_area("修改意见")
    elif decision == "request_information":
        information = st.text_area("补充信息")
    elif decision == "approve":
        comment = st.text_area("审核意见", placeholder="可选")
    if st.button("提交", type="primary"):
        if decision == "revise" and not comment.strip():
            st.warning("退回修订需要填写修改意见。")
            return
        if decision == "request_information" and not information.strip():
            st.warning("请填写要补充的内容。")
            return
        with st.spinner("正在继续…"):
            resume_run(
                run_id,
                {"decision": decision, "comment": comment, "information": information},
            )
        st.rerun()


def _history() -> None:
    st.header("历史与下载")
    project_id = _pick_project()
    if project_id is None:
        st.info("还没有生成记录。")
        return
    runs = list_runs(project_id)
    if runs:
        st.dataframe(
            [
                {
                    "状态": _status_label(item["status"]),
                    "运行": item["id"][:8],
                    "模型": item.get("model_name") or "",
                }
                for item in runs
            ],
            hide_index=True,
        )
    artifacts = list_artifacts(project_id)
    documents = [item for item in artifacts if item["artifact_type"] == "proposal_docx"]
    others = [item for item in artifacts if item["artifact_type"] != "proposal_docx"]
    if not documents and not others:
        st.caption("批准后可以在这里下载 DOCX。未批准的内容仍是草稿。")
        return
    st.subheader("计划书")
    for item in documents:
        st.write(f"版本 {item['version_number']} · {item['review_status']} · {item['sha256'][:12]}")
        st.caption(item.get("summary") or "")
        st.download_button(
            f"下载 DOCX v{item['version_number']}",
            data=_download_bytes(item["id"]),
            file_name=f"proposal_v{item['version_number']}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"docx-{item['id']}",
        )
    if others:
        with st.expander("其他文件"):
            for item in others:
                suffix = ".json" if item["artifact_type"] == "draft_snapshot" else ".xlsx"
                st.download_button(
                    f"{item['artifact_type']} v{item['version_number']}",
                    data=_download_bytes(item["id"]),
                    file_name=f"{item['artifact_type']}_v{item['version_number']}{suffix}",
                    mime="application/octet-stream",
                    key=f"other-{item['id']}",
                )
    if len(artifacts) >= 2:
        labels = {
            f"{item['artifact_type']} v{item['version_number']}": item["id"] for item in artifacts
        }
        names = list(labels)
        left, right = st.columns(2)
        left_name = left.selectbox("比较左侧", names)
        right_name = right.selectbox("比较右侧", names, index=min(1, len(names) - 1))
        if st.button("查看文本差异"):
            result = compare_artifacts(labels[left_name], labels[right_name])
            st.caption("这是文本差异，不是语义比较。")
            st.code(result.get("diff") or "两边的提取文本相同。", language="diff")


def _library(department: str) -> None:
    st.header("资料库")
    st.caption(f"上传到{department}或公共组。生成计划书时会自动检索这两个范围。")
    uploaded = st.file_uploader("PDF、DOCX 或 XLSX", type=["pdf", "docx", "xlsx"])
    library_choice = st.radio("放到", [department, "公共组"], horizontal=True)
    if uploaded is not None and st.button("上传并索引"):
        library = "department" if library_choice == department else PUBLIC_LIBRARY
        document = upload_document(uploaded.name, uploaded.getvalue(), None, library)
        indexed = index_document(document["id"])
        st.success(
            f"已放入{LIBRARY_LABELS.get(document['library'], document['library'])}，"
            f"切出 {indexed['chunk_count']} 个片段"
        )
    documents = list_documents(None)
    if documents:
        st.dataframe(
            [
                {
                    "文件": item["filename"],
                    "范围": LIBRARY_LABELS.get(item.get("library"), item.get("library")),
                    "片段": item["chunk_count"],
                    "索引": item["index_status"],
                }
                for item in documents
            ],
            hide_index=True,
        )
    query = st.text_input("试检索")
    if query.strip() and st.button("检索"):
        found = search_evidence(query.strip(), None)
        if found.get("embedding_mock"):
            st.warning("当前 embedding 是 mock，检索结果不能当作真实向量召回。")
        items = found.get("items") or []
        if not items:
            st.info("没有检索到可见资料。")
        for item in items:
            st.markdown(
                f"**{item.get('title')}** · 第 {item.get('page_number') or '—'} 页 · "
                f"{item.get('section') or '无章节'}"
            )
            st.text(item.get("quote") or "")


def _pick_project() -> str | None:
    projects = list_projects()
    if not projects:
        return None
    labels = {f"{item['name']} · {item['id'][:8]}": item["id"] for item in projects}
    current = st.session_state.get("project_id")
    options = list(labels)
    index = next((i for i, name in enumerate(options) if labels[name] == current), 0)
    selected = st.selectbox("计划书", options, index=index)
    project_id = labels[selected]
    st.session_state["project_id"] = project_id
    return project_id


def _pick_run() -> str | None:
    project_id = _pick_project()
    if project_id is None:
        return None
    runs = list_runs(project_id)
    if not runs:
        return None
    labels = {f"{_status_label(item['status'])} · {item['id'][:8]}": item["id"] for item in runs}
    current = st.session_state.get("run_id")
    options = list(labels)
    index = next((i for i, label in enumerate(options) if labels[label] == current), 0)
    selected = st.selectbox("本次生成", options, index=index)
    run_id = labels[selected]
    st.session_state["run_id"] = run_id
    return run_id


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status or "未知")


if __name__ == "__main__":
    main()
