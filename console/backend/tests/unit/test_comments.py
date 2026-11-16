"""中文注释的覆盖率闸：新增表/列若漏写注释会在这里失败。"""

from __future__ import annotations

import re

import app.models  # noqa: F401 - registers the tables on Base.metadata
from app.db.base import Base
from app.models.comments import (
    COLUMN_COMMENTS,
    TABLE_COMMENTS,
    comment_statements,
    drop_comment_statements,
)

CJK = re.compile(r"[\u4e00-\u9fff]")


def _tables():
    return {table.name: table for table in Base.metadata.sorted_tables}


def test_every_table_and_column_has_a_chinese_comment():
    tables = _tables()
    assert set(TABLE_COMMENTS) == set(tables), "表注释与 metadata 不一致"
    assert set(COLUMN_COMMENTS) == set(tables), "列注释与 metadata 不一致"
    for name, table in tables.items():
        assert CJK.search(table.comment or ""), f"{name} 缺少中文表注释"
        assert set(COLUMN_COMMENTS[name]) == {c.name for c in table.columns}, (
            f"{name} 列注释与模型不一致"
        )
        for column in table.columns:
            text = COLUMN_COMMENTS[name][column.name]
            assert CJK.search(text), f"{name}.{column.name} 缺少中文注释"


def test_comments_are_free_of_single_quotes_and_forbidden_literals():
    texts = [
        *TABLE_COMMENTS.values(),
        *(text for columns in COLUMN_COMMENTS.values() for text in columns.values()),
    ]
    for text in texts:
        assert "'" not in text, f"注释含单引号：{text}"
        # 离线 SQLite 文件的静态闸禁止大写字面量 TIMESTAMP。
        assert "TIMESTAMP" not in text, f"注释含禁用字面量：{text}"


def test_sqlite_is_a_no_op():
    assert comment_statements("sqlite") == []
    assert drop_comment_statements("sqlite") == []


def test_postgresql_statements_cover_every_table_and_column():
    statements = comment_statements("postgresql")
    expected = len(TABLE_COMMENTS) + sum(len(c) for c in COLUMN_COMMENTS.values())
    assert len(statements) == expected
    joined = "\n".join(statements)
    for name, comment in TABLE_COMMENTS.items():
        assert f'COMMENT ON TABLE "{name}" IS \'{comment}\'' in joined
        assert ";;" not in joined
    for name, columns in COLUMN_COMMENTS.items():
        for column, comment in columns.items():
            assert f'COMMENT ON COLUMN "{name}"."{column}" IS \'{comment}\'' in joined


def test_downgrade_clears_every_comment():
    statements = drop_comment_statements("postgresql")
    assert len(statements) == len(comment_statements("postgresql"))
    assert all(statement.endswith("IS NULL") for statement in statements)
