"""查看当前项目 PostgreSQL 中的库信息和业务数据。不打印密码、口令哈希或登录令牌。"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, text

from app.authz import LIBRARY_LABELS
from app.config import get_settings
from app.db.models import Document, DocumentChunk, DocumentVersion, User
from app.db.session import get_session_factory


def main() -> None:
    settings = get_settings()
    parsed = urlparse(settings.database_url)
    database = (parsed.path or "").lstrip("/") or "(未指定)"
    host = parsed.hostname or "(未指定)"
    port = parsed.port or "(默认)"
    user = parsed.username or "(未指定)"

    db = get_session_factory()()
    try:
        version, vector_version = db.execute(
            text("select version(), extversion from pg_extension where extname = 'vector'")
        ).one()
        print("== 连接 ==")
        print(f"主机: {host}")
        print(f"端口: {port}")
        print(f"数据库: {database}")
        print(f"用户: {user}")
        print(f"PostgreSQL: {version}")
        print(f"pgvector: {vector_version}")

        print("\n== 表行数 ==")
        tables = db.execute(
            text(
                """
                select relname
                from pg_stat_user_tables
                order by relname
                """
            )
        ).all()
        for (name,) in tables:
            exact = db.execute(text(f'select count(*) from "{name}"')).scalar()
            print(f"{name}: {exact}")
        if not tables:
            print("(public 下没有用户表)")

        print("\n== 用户 ==")
        users = db.scalars(select(User).order_by(User.username)).all()
        if not users:
            print("(无用户)")
        for item in users:
            department = LIBRARY_LABELS.get(item.department, item.department)
            print(f"{item.username}  部门={department}  创建于={item.created_at}")

        print("\n== 资料库 ==")
        counts = db.execute(
            select(Document.library, func.count(Document.id)).group_by(Document.library)
        ).all()
        count_by_library = {library: count for library, count in counts}
        for code, label in LIBRARY_LABELS.items():
            print(f"{label}: {count_by_library.get(code, 0)} 份")
        chunk_total = db.scalar(select(func.count()).select_from(DocumentChunk)) or 0
        embedded = (
            db.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.embedding.is_not(None))
            )
            or 0
        )
        print(f"片段: {chunk_total}，其中已有向量: {embedded}")

        print("\n== 文档明细 ==")
        documents = db.scalars(select(Document).order_by(Document.filename)).all()
        if not documents:
            print("(无文档)")
        for document in documents:
            versions = db.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document.id)
                .order_by(DocumentVersion.version_number)
            ).all()
            library = LIBRARY_LABELS.get(document.library, document.library)
            print(
                f"\n[{library}] {document.filename}  类型={document.document_type}  "
                f"上传者={document.created_by}  上传于={document.uploaded_at}"
            )
            print(f"  id={document.id}")
            if not versions:
                print("  (无版本)")
                continue
            for version in versions:
                chunks = db.scalars(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_version_id == version.id)
                    .order_by(DocumentChunk.chunk_index)
                ).all()
                print(
                    f"  版本 {version.version_number}  状态={version.validity_status}  "
                    f"片段={len(chunks)}"
                )
                for chunk in chunks:
                    location = chunk.section or (
                        f"第{chunk.page_number}页" if chunk.page_number else "无位置"
                    )
                    preview = " ".join(chunk.content.split())
                    if len(preview) > 80:
                        preview = preview[:80] + "…"
                    print(f"    #{chunk.chunk_index} {location}: {preview}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
