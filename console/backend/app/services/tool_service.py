"""工具注册表：CRUD、可见性、所有权边界与审计。"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models.tool import ConsoleTool
from app.repositories.audit_repository import AuditRepository
from app.repositories.tool_repository import ToolRepository
from app.schemas.tool import ToolCreate, ToolParamIn, ToolUpdate

TYPES = ("web_search", "calendar", "weather", "kb", "http")
SCOPES = ("global", "session", "tenant")
METHODS = ("GET", "POST")


def _check_enum(value: str, allowed: tuple[str, ...], label: str) -> None:
    if value not in allowed:
        raise ApiError("invalid_request", f"{label} must be one of {', '.join(allowed)}", 400)


def _audit(db: Session, *, actor: str, action: str, name: str, fields: list[str]) -> None:
    AuditRepository(db).record(actor=actor, role="", action=action, profile=name, fields=fields)


def _out(row, *, username: str) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "type": row.type,
        "description": row.description,
        "endpoint": row.endpoint,
        "method": row.method,
        "scope": row.scope,
        "enabled": row.enabled,
        "builtin": row.builtin,
        "owner": row.owner,
        "params": [
            {"k": p.get("k", ""), "t": p.get("t", "string"), "req": bool(p.get("req", False))}
            for p in (row.params or [])
        ],
        "config": row.config or {},
        "effectiveEnabled": row.enabled if row.scope != "session" else None,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        "createdBy": row.created_by,
        "updatedBy": row.updated_by,
        "writable": row.builtin or row.owner == username or row.owner == "",
    }


def _visible(row, *, username: str) -> bool:
    # 内置工具一律可见；自定义工具 global 全体可见，其余按 owner 隔离。
    return bool(row.builtin) or row.scope == "global" or row.owner == username or row.owner == ""


def list_tools(db: Session, username: str, *, q: str = "") -> list[dict]:
    repo = ToolRepository(db)
    return [_out(row, username=username) for row in repo.list(q=q) if _visible(row, username=username)]


def get_tool(db: Session, tool_id: str, *, username: str) -> dict:
    row = ToolRepository(db).get(tool_id)
    if row is None or not _visible(row, username=username):
        raise KeyError(tool_id)
    return _out(row, username=username)


def create_tool(db: Session, payload: ToolCreate, *, actor: str, username: str, role: str) -> dict:
    _check_enum(payload.type, TYPES, "type")
    _check_enum(payload.scope, SCOPES, "scope")
    _check_enum(payload.method, METHODS, "method")
    if payload.type == "http" and not payload.endpoint.strip():
        raise ApiError("invalid_request", "HTTP tools require an endpoint", 400)
    if payload.scope == "global" and role != "admin":
        raise ApiError("forbidden", "only admin may create global tools", 403)
    name = payload.name.strip()
    if not name:
        raise ApiError("invalid_request", "name is required", 400)
    repo = ToolRepository(db)
    if repo.get_by_name(name) is not None:
        raise ValueError(name)
    row = repo.create(
        row=ConsoleTool(
            id=f"tool-custom-{uuid.uuid4().hex[:8]}",
            name=name,
            type=payload.type,
            description=payload.description,
            endpoint=payload.endpoint,
            method=payload.method,
            scope=payload.scope,
            enabled=payload.enabled,
            builtin=False,
            owner=username,
            params=[p.model_dump() for p in payload.params],
            config=payload.config,
            created_by=actor,
            updated_by=actor,
        )
    )
    _audit(db, actor=actor, action="tool.create", name=row.name, fields=[p.k for p in payload.params])
    return _out(row, username=username)


def _writable(row, *, username: str, role: str, deleting: bool = False) -> None:
    # 内置工具可编辑（原型弹 builtin-warning 后允许），但删除需 admin。
    if row.builtin:
        if deleting and role != "admin":
            raise ApiError("forbidden", "builtin tools require admin to delete", 403)
        return
    if row.scope == "global" and role != "admin":
        raise ApiError("forbidden", "only admin may modify global tools", 403)
    if row.owner not in (username, ""):
        raise ApiError("forbidden", "not the tool owner", 403)


def update_tool(db: Session, tool_id: str, payload: ToolUpdate, *, actor: str, username: str, role: str) -> dict:
    repo = ToolRepository(db)
    row = repo.get(tool_id)
    if row is None:
        raise KeyError(tool_id)
    _writable(row, username=username, role=role)
    changed = payload.model_dump(exclude_unset=True)
    for label, allowed in (("type", TYPES), ("scope", SCOPES), ("method", METHODS)):
        if label in changed and changed[label] is not None:
            _check_enum(changed[label], allowed, label)
    if "name" in changed and changed["name"] and changed["name"] != row.name:
        existing = repo.get_by_name(changed["name"])
        if existing is not None and existing.id != row.id:
            raise ValueError(changed["name"])
    mapping = {"description": "description"}
    for attr, value in changed.items():
        column = mapping.get(attr, attr)
        if attr == "params" and value is not None:
            value = [p if isinstance(p, dict) else p.model_dump() for p in value]
        if hasattr(row, column) and value is not None:
            setattr(row, column, value)
    row.updated_by = actor
    db.commit()
    db.refresh(row)
    _audit(db, actor=actor, action="tool.update", name=row.name, fields=sorted(changed))
    return _out(row, username=username)


def delete_tool(db: Session, tool_id: str, *, actor: str, username: str, role: str) -> None:
    repo = ToolRepository(db)
    row = repo.get(tool_id)
    if row is None:
        raise KeyError(tool_id)
    _writable(row, username=username, role=role, deleting=True)
    name = row.name
    if not repo.delete(tool_id):
        raise KeyError(tool_id)
    _audit(db, actor=actor, action="tool.delete", name=name, fields=[])


def copy_tool(db: Session, tool_id: str, *, actor: str, username: str, role: str) -> dict:
    source = ToolRepository(db).get(tool_id)
    if source is None:
        raise KeyError(tool_id)
    repo = ToolRepository(db)
    base = f"{source.name} Copy"
    name = base
    suffix = 2
    while repo.get_by_name(name) is not None:
        name = f"{base} {suffix}"
        suffix += 1
    payload = ToolCreate(
        name=name,
        type=source.type,
        description=source.description,
        endpoint=source.endpoint,
        method=source.method,
        scope="tenant" if source.scope == "global" else source.scope,
        enabled=source.enabled,
        params=[ToolParamIn(**p) for p in (source.params or [])],
        config=source.config or {},
    )
    return create_tool(db, payload, actor=actor, username=username, role=role)


def toggle_tool(db: Session, tool_id: str, enabled: bool, *, actor: str, username: str) -> dict:
    repo = ToolRepository(db)
    row = repo.get(tool_id)
    if row is None or not _visible(row, username=username):
        raise KeyError(tool_id)
    # session 工具的 enabled 归浏览器 localStorage，服务端不落库。
    if row.scope == "session":
        return _out(row, username=username)
    row.enabled = bool(enabled)
    row.updated_by = actor
    db.commit()
    db.refresh(row)
    _audit(db, actor=actor, action="tool.toggle", name=row.name, fields=["enabled"])
    return _out(row, username=row.owner)
