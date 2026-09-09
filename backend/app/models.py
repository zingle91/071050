from datetime import datetime
import uuid
from sqlalchemy import (
    String, Boolean, DateTime, ForeignKey, Text, Integer, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)

    parent: Mapped["Department | None"] = relationship(
        remote_side="Department.id", back_populates="children"
    )
    children: Mapped[list["Department"]] = relationship(back_populates="parent")
    employees: Mapped[list["Employee"]] = relationship(back_populates="department")


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    department: Mapped[Department | None] = relationship(back_populates="employees")
    room_memberships: Mapped[list["RoomMember"]] = relationship(back_populates="employee", foreign_keys="RoomMember.employee_id")


class FavoriteEmployee(Base):
    """Per-user favorited employees for the org picker favorites tab."""
    __tablename__ = "favorite_employees"
    __table_args__ = (UniqueConstraint("owner_id", "employee_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    employee: Mapped[Employee] = relationship(foreign_keys=[employee_id])


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stable external identity. Display names are NOT unique; clients should use public_id.
    public_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    room_type: Mapped[str] = mapped_column(String(20), nullable=False)  # direct | group
    created_by: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    members: Mapped[list["RoomMember"]] = relationship(back_populates="room", cascade="all, delete-orphan")
    messages: Mapped[list["Message"]] = relationship(back_populates="room", cascade="all, delete-orphan")


class RoomMember(Base):
    __tablename__ = "room_members"
    __table_args__ = (UniqueConstraint("room_id", "employee_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Per-user personal room alias (None = use Room.name)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True, default=None)
    # Messages after this timestamp count as unread for this member
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    # Soft-leave: active | left | kicked (hard DELETE only on history dismiss)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    removed_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True, default=None)

    room: Mapped[Room] = relationship(back_populates="members")
    employee: Mapped[Employee] = relationship(
        back_populates="room_memberships", foreign_keys=[employee_id]
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "room_id",
            "sender_id",
            "client_message_id",
            name="uq_messages_room_sender_client_message_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    sender_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional client-supplied idempotency key (UUID / opaque). NULLs are distinct in PG unique.
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    # leave | kick | None — personalize system text per viewer
    system_event: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    system_actor_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True, default=None)
    system_target_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True, default=None)

    room: Mapped[Room] = relationship(back_populates="messages")
    sender: Mapped[Employee] = relationship(foreign_keys=[sender_id])


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sender: Mapped[Employee] = relationship(foreign_keys=[sender_id])
    recipient: Mapped[Employee] = relationship(foreign_keys=[recipient_id])
