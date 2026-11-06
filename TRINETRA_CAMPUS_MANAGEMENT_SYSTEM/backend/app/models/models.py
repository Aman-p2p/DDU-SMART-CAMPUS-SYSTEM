from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, 
    Text, Enum, Date, Time, UniqueConstraint, Index, Float
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum
from ..core.database import Base

class UserRole(str, enum.Enum):
    FACULTY = "faculty"
    STUDENT = "student"
    STAFF = "staff"
    ADMIN = "admin"

class RoomType(str, enum.Enum):
    CLASSROOM = "classroom"
    LAB = "lab"
    SEMINAR = "seminar"
    LIBRARY = "library"
    OFFICE = "office"

class BookingStatus(str, enum.Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    HOLD = "hold"
    COMPLETED = "completed"

class BookingPurpose(str, enum.Enum):
    EXTRA_LECTURE = "extra_lecture"
    MINOR_EXAM = "minor_exam"
    PRACTICAL = "practical"
    EVENT = "event"
    SEMINAR = "seminar"
    OTHER = "other"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(150), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.ADMIN)
    department = Column(String(100), nullable=True)
    employee_id = Column(String(50), nullable=True)
    branch = Column(String(50), nullable=True)  # CSE, AI_ML, AI_DS, ECE, ME, IT
    academic_year = Column(Integer, nullable=True)  # 1, 2, 3, 4
    section = Column(String(10), nullable=True)  # A, B
    is_active = Column(Boolean, default=True)
    is_test_data = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    bookings = relationship("Booking", back_populates="user")
    notifications = relationship("Notification", back_populates="user")

class Building(Base):
    __tablename__ = "buildings"
    
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)  # IET, DB
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    distance_meters = Column(Integer, default=0)  # from main IET
    
    floors = relationship("Floor", back_populates="building")
    rooms = relationship("Room", back_populates="building")

class Floor(Base):
    __tablename__ = "floors"
    
    id = Column(Integer, primary_key=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)
    name = Column(String(50), nullable=False)  # Ground, First, Second
    level = Column(Integer, default=0)
    
    building = relationship("Building", back_populates="floors")
    rooms = relationship("Room", back_populates="floor")

class Room(Base):
    __tablename__ = "rooms"
    
    id = Column(Integer, primary_key=True)
    code = Column(String(30), unique=True, nullable=False, index=True)  # IET20, LH05
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)
    floor_id = Column(Integer, ForeignKey("floors.id"), nullable=False)
    capacity = Column(Integer, nullable=False)
    room_type = Column(Enum(RoomType), nullable=False, default=RoomType.CLASSROOM)
    facilities = Column(Text, nullable=True)  # JSON string or comma-separated
    is_maintenance = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=True)  # false if capacity not confirmed from official data
    is_test_data = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)
    
    building = relationship("Building", back_populates="rooms")
    floor = relationship("Floor", back_populates="rooms")
    bookings = relationship("Booking", back_populates="room")

class Booking(Base):
    __tablename__ = "bookings"
    
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    
    purpose = Column(Enum(BookingPurpose), nullable=False)
    purpose_detail = Column(String(255), nullable=True)
    custom_reason = Column(String(255), nullable=True)
    target_branch = Column(String(50), nullable=True)
    target_year = Column(Integer, nullable=True)
    target_sem = Column(String(10), nullable=True)
    expected_students = Column(Integer, default=0)
    
    status = Column(Enum(BookingStatus), default=BookingStatus.CONFIRMED, index=True)
    hold_expires_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancel_reason = Column(String(255), nullable=True)
    
    # For audit
    is_test_data = Column(Boolean, default=True)
    
    room = relationship("Room", back_populates="bookings")
    user = relationship("User", back_populates="bookings")
    
    __table_args__ = (
        Index("ix_booking_room_date", "room_id", "date"),
    )

class Announcement(Base):
    __tablename__ = "announcements"
    
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    target_roles = Column(String(100), default="all")  # all, faculty, student, staff
    category = Column(String(50), default="general")  # general, exam, urgent, relocation
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    author = relationship("User")

class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    type = Column(String(50), default="info")  # info, success, warning, error
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="notifications")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class IssueReport(Base):
    __tablename__ = "issue_reports"
    
    id = Column(Integer, primary_key=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    room_code = Column(String(30), nullable=True)
    issue_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(30), default="open")  # open, reviewing, resolved
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    reporter = relationship("User")

class TimetableSchedule(Base):
    __tablename__ = "timetable_schedules"
    
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    branch = Column(String(50), nullable=False, index=True)
    academic_year = Column(Integer, nullable=False, index=True)
    semester = Column(String(10), default="1st")  # "1st" or "2nd"
    section = Column(String(10), nullable=True)
    day_of_week = Column(Integer, nullable=False)  # 0=Monday, 1=Tuesday, ... 5=Saturday
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    subject = Column(String(150), nullable=False)
    faculty_name = Column(String(150), nullable=False)
    schedule_type = Column(String(50), default="regular_class")  # regular_class, practical
    
    room = relationship("Room")

class ExamSchedule(Base):
    __tablename__ = "exam_schedules"
    
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    subject_name = Column(String(150), nullable=False)
    branch = Column(String(50), nullable=False, index=True)
    academic_year = Column(Integer, nullable=False, index=True)
    semester = Column(String(10), default="1st")  # "1st" or "2nd"
    section = Column(String(10), nullable=True)
    exam_date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    exam_type = Column(String(50), default="Minor Exam")  # Minor Exam, NSS Exam, Practical Exam
    instructions = Column(Text, nullable=True)
    
    room = relationship("Room")

