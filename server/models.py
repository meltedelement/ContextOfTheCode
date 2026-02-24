"""SQLAlchemy ORM models for metrics storage."""

import time
from sqlalchemy import Column, String, Float, Integer, ForeignKey, Index
from sqlalchemy.orm import relationship
from server.database import Base


class Message(Base):
    """
    One row per DataMessage received from a collector.

    collected_at is the timestamp from the payload (when the data was measured).
    received_at is when the server ingested it. Queries should always sort by
    collected_at so out-of-order delivery from the retry queue is handled correctly.
    """
    __tablename__ = "messages"

    message_id   = Column(String(36),  primary_key=True)
    device_id    = Column(String(255), nullable=False)
    source       = Column(String(50),  nullable=False)
    collected_at = Column(Float,       nullable=False)  # from DataMessage.timestamp
    received_at  = Column(Float,       nullable=False, default=time.time)

    metrics = relationship("Metric", back_populates="message", cascade="all, delete-orphan")

    __table_args__ = (
        # Supports dashboard queries: "give me all local metrics since T, ordered by time"
        Index("idx_device_source_collected", "device_id", "source", "collected_at"),
        Index("idx_collected_at", "collected_at"),
    )


class Metric(Base):
    """One row per MetricEntry within a DataMessage."""

    __tablename__ = "metrics"

    id           = Column(Integer,     primary_key=True, autoincrement=True)
    message_id   = Column(String(36),  ForeignKey("messages.message_id"), nullable=False)
    metric_name  = Column(String(255), nullable=False)
    metric_value = Column(Float,       nullable=False)
    unit         = Column(String(50),  nullable=False, server_default="")

    message = relationship("Message", back_populates="metrics")

    __table_args__ = (
        # Supports queries like "give me all cpu_usage_percent readings"
        Index("idx_metric_name", "metric_name"),
    )
