"""SQLAlchemy ORM models for metrics storage."""

import time
from sqlalchemy import Column, String, Float, Integer, ForeignKey, Index
from sqlalchemy.orm import relationship
from server.database import Base


class Aggregator(Base):
    """One row per aggregator (machine running run_all.py)."""

    __tablename__ = "aggregators"

    aggregator_id = Column(String(36),  primary_key=True)
    name          = Column(String(255), nullable=False, unique=True)

    devices = relationship("Device", back_populates="aggregator", cascade="all, delete-orphan")


class Device(Base):
    """
    One row per logical data source registered by an aggregator.

    source is a property of the device (e.g. 'local', 'wikipedia'), not
    of individual snapshots — it describes what kind of data the device
    produces, not a per-reading attribute.
    """

    __tablename__ = "devices"

    device_id     = Column(String(36),  primary_key=True)
    aggregator_id = Column(String(36),  ForeignKey("aggregators.aggregator_id"), nullable=False)
    name          = Column(String(255), nullable=False)
    source        = Column(String(50),  nullable=False)

    aggregator = relationship("Aggregator", back_populates="devices")
    snapshots  = relationship("Snapshot", back_populates="device", cascade="all, delete-orphan")


class Snapshot(Base):
    """
    One row per collection cycle from a device.

    collected_at is the timestamp from the payload (when the data was measured).
    received_at  is when the server ingested it. Queries should always sort by
    collected_at so out-of-order delivery from the retry queue is handled correctly.
    """

    __tablename__ = "snapshots"

    snapshot_id  = Column(String(36), primary_key=True)
    device_id    = Column(String(36), ForeignKey("devices.device_id"), nullable=False)
    collected_at = Column(Float,      nullable=False)
    received_at  = Column(Float,      nullable=False, default=time.time)

    device  = relationship("Device", back_populates="snapshots")
    metrics = relationship("Metric", back_populates="snapshot", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_device_collected", "device_id", "collected_at"),
        Index("idx_collected_at", "collected_at"),
    )


class Metric(Base):
    """One row per MetricEntry within a Snapshot."""

    __tablename__ = "metrics"

    metric_id    = Column(Integer,     primary_key=True, autoincrement=True)
    snapshot_id  = Column(String(36),  ForeignKey("snapshots.snapshot_id"), nullable=False)
    metric_name  = Column(String(255), nullable=False)
    metric_value = Column(Float,       nullable=False)
    unit         = Column(String(50),  nullable=False, server_default="")

    snapshot = relationship("Snapshot", back_populates="metrics")

    __table_args__ = (
        Index("idx_metric_name", "metric_name"),
    )
