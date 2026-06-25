from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

'''
点击日志数据模型，用于记录用户点击搜索结果的行为
常用于分析搜索质量和用户行为。

'''
class ClickLog(Base):
    """点击日志模型 - 记录用户点击搜索结果的行为"""
    __tablename__ = "click_logs" # 数据库名

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 关联用户，可以为空表示匿名用户
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    # 文档 ID，即被点击的搜索结果的唯一标识
    doc_id: Mapped[str] = mapped_column(String(128), index=True)
    # 搜索词，允许为空
    query_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 点击时间
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

