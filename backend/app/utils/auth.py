"""Tableau 连接权限验证工具"""
from sqlalchemy.orm import Session
from services.tableau.models import TableauConnection
from app.core.errors import TABError


def verify_connection_access(connection_id: int, user: dict, db: Session) -> None:
    """
    验证用户有权访问指定 Tableau 连接。
    管理员可访问所有连接，非管理员只能访问自己的连接。
    """
    conn = db.query(TableauConnection).filter(TableauConnection.id == connection_id).first()
    if not conn:
        raise TABError.connection_not_found()
    # admin 可访问所有连接，非 admin 只能访问自己的
    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise TABError.access_denied()
