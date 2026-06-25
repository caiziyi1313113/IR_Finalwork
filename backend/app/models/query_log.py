from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

'''
查询日志数据模型
用于记录用户的搜索行为
包括原始查询、纠错后的查询、搜索模式等。
'''

class QueryLog(Base):
    """查询日志模型 - 记录用户的搜索行为"""
    __tablename__ = "query_logs"
    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 关联用户，可以为空表示匿名用户
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    # 原始查询
    query_text: Mapped[str] = mapped_column(String(255), index=True)
    # 纠错后的查询
    corrected_query: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 搜索模式
    mode: Mapped[str] = mapped_column(String(20), default="normal")
    # 结果数量
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

