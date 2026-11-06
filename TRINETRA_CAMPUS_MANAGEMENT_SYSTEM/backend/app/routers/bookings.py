from datetime import date, time, datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, Field, field_validator

from ..core.database import get_db
from ..models.models import Booking, BookingStatus, BookingPurpose, User, UserRole, Room
from ..services.booking_service import (
    create_booking, cancel_booking, find_alternatives, auto_complete_expired_bookings,
    hold_room as service_hold_room, confirm_hold as service_confirm_hold, release_hold as service_release_hold
)
from .auth import get_current_user

router = APIRouter()

class BookingCreate(BaseModel):
    room_id: int
    date: date
    start_time: str  # "HH:MM"
    duration_hours: float = Field(ge=0.5, le=6)
    purpose: str = "extra_lecture"
    purpose_detail: Optional[str] = None
    custom_reason: Optional[str] = None
    target_branch: Optional[str] = None
    target_year: Optional[int] = None
    target_sem: Optional[str] = None
    expected_students: int = Field(ge=1, le=500)

    @field_validator("date", mode="before")
    @classmethod
    def parse_indian_or_iso_date(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if "/" in v:
                d, m, y = map(int, v.split("/"))
                if y < 100: y += 2000
                return date(y, m, d)
            if "-" in v and len(v.split("-")[0]) <= 2:
                d, m, y = map(int, v.split("-"))
                if y < 100: y += 2000
                return date(y, m, d)
        return v

class HoldCreate(BaseModel):
    room_id: int
    date: date
    start_time: str
    duration_hours: float = 1.5
    purpose: str = "extra_lecture"

    @field_validator("date", mode="before")
    @classmethod
    def parse_indian_or_iso_date(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if "/" in v:
                d, m, y = map(int, v.split("/"))
                if y < 100: y += 2000
                return date(y, m, d)
        return v
    custom_reason: Optional[str] = None
    target_branch: Optional[str] = None
    target_year: Optional[int] = None
    target_sem: Optional[str] = None
    expected_students: int = 60

class ConfirmHoldRequest(BaseModel):
    custom_reason: Optional[str] = None

class BookingOut(BaseModel):
    id: int
    room_code: str
    building: str
    floor: str
    date: date
    start_time: str
    end_time: str
    purpose: str
    expected_students: int
    status: str
    user_name: str

    class Config:
        from_attributes = True

def parse_time(s: str) -> time:
    h, m = map(int, s.split(":"))
    return time(h, m)

@router.post("/", status_code=201)
def book_room(payload: BookingCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == UserRole.STUDENT:
        raise HTTPException(403, "Students cannot book rooms")
    
    try:
        purpose = BookingPurpose(payload.purpose)
    except:
        purpose = BookingPurpose.OTHER
    
    start = parse_time(payload.start_time)
    end_minutes = start.hour * 60 + start.minute + int(payload.duration_hours * 60)
    end = time(end_minutes // 60 % 24, end_minutes % 60)
    
    booking, error, alternatives = create_booking(
        db,
        room_id=payload.room_id,
        user_id=current_user.id,
        booking_date=payload.date,
        start=start,
        end=end,
        purpose=purpose,
        purpose_detail=payload.purpose_detail,
        custom_reason=payload.custom_reason,
        target_branch=payload.target_branch,
        target_year=payload.target_year,
        target_sem=payload.target_sem,
        expected_students=payload.expected_students
    )
    
    if error:
        if alternatives is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": error,
                    "alternatives": alternatives
                }
            )
        raise HTTPException(400, error)
    
    room = booking.room
    user = booking.user
    start_mins = booking.start_time.hour * 60 + booking.start_time.minute
    end_mins = booking.end_time.hour * 60 + booking.end_time.minute
    duration_hrs = round((end_mins - start_mins) / 60, 1)

    return {
        "id": booking.id,
        "room_code": room.code,
        "building_name": room.building.name if room.building else "IET",
        "floor_name": room.floor.name if room.floor else "Ground Floor",
        "date": str(booking.date),
        "start_time": booking.start_time.strftime("%H:%M"),
        "end_time": booking.end_time.strftime("%H:%M"),
        "start_time_12": booking.start_time.strftime("%I:%M %p"),
        "end_time_12": booking.end_time.strftime("%I:%M %p"),
        "duration_hours": duration_hrs,
        "purpose": booking.purpose.value,
        "purpose_detail": booking.purpose_detail or "Classroom Allocation",
        "custom_reason": booking.custom_reason or "",
        "target_branch": booking.target_branch or "All",
        "target_year": booking.target_year,
        "expected_students": booking.expected_students,
        "booked_by_name": user.full_name if user else "Current User",
        "booked_by_role": user.role.value if user else "faculty",
        "status": booking.status.value,
        "is_test_data": getattr(booking, "is_test_data", True),
        "message": "Booking confirmed successfully"
    }

# ---------- REQUIREMENT 9: 5-MINUTE TEMPORARY HOLD ENDPOINTS ----------

@router.post("/hold", status_code=201)
def hold_room_endpoint(payload: HoldCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == UserRole.STUDENT:
        raise HTTPException(403, "Students cannot hold or reserve rooms")
    
    start = parse_time(payload.start_time)
    end_minutes = start.hour * 60 + start.minute + int(payload.duration_hours * 60)
    end = time(end_minutes // 60 % 24, end_minutes % 60)

    try:
        purpose = BookingPurpose(payload.purpose)
    except:
        purpose = BookingPurpose.OTHER

    hold, error = service_hold_room(
        db,
        room_id=payload.room_id,
        user_id=current_user.id,
        booking_date=payload.date,
        start=start,
        end=end,
        purpose=purpose,
        expected_students=payload.expected_students,
        target_branch=payload.target_branch,
        target_year=payload.target_year,
        target_sem=payload.target_sem,
        custom_reason=payload.custom_reason
    )
    if error:
        raise HTTPException(400, error)

    expires_seconds = int((hold.hold_expires_at - datetime.utcnow()).total_seconds()) if hold.hold_expires_at else 300

    return {
        "hold_id": hold.id,
        "room_code": hold.room.code,
        "room_id": hold.room_id,
        "date": str(hold.date),
        "start_time": hold.start_time.strftime("%H:%M"),
        "end_time": hold.end_time.strftime("%H:%M"),
        "expires_at": hold.hold_expires_at.isoformat() if hold.hold_expires_at else "",
        "expires_in_seconds": max(0, expires_seconds),
        "status": "hold",
        "message": "Room held successfully for 5 minutes"
    }

@router.post("/hold/{hold_id}/confirm")
def confirm_hold_endpoint(hold_id: int, payload: ConfirmHoldRequest = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    is_admin = current_user.role == UserRole.ADMIN
    custom_reason = payload.custom_reason if payload else None
    booking, error = service_confirm_hold(db, hold_id, current_user.id, is_admin, custom_reason)
    if error:
        raise HTTPException(400, error)
    return {
        "id": booking.id,
        "room_code": booking.room.code,
        "status": booking.status.value,
        "message": "Hold successfully converted to confirmed booking"
    }

@router.post("/hold/{hold_id}/release")
def release_hold_endpoint(hold_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    is_admin = current_user.role == UserRole.ADMIN
    ok = service_release_hold(db, hold_id, current_user.id, is_admin)
    if not ok:
        raise HTTPException(400, "Could not release hold")
    return {"message": "Hold released successfully"}

@router.post("/sync-expired")
def sync_expired_bookings(db: Session = Depends(get_db)):
    """Automatically frees up and marks any completed booking slots as vacated."""
    count = auto_complete_expired_bookings(db)
    return {"vacated_count": count, "status": "ok"}

@router.get("/my")
def my_bookings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    auto_complete_expired_bookings(db)
    bookings = (
        db.query(Booking)
        .options(joinedload(Booking.room).joinedload(Room.building), joinedload(Booking.room).joinedload(Room.floor))
        .filter(Booking.user_id == current_user.id)
        .order_by(Booking.date.desc(), Booking.start_time.desc())
        .all()
    )
    return [
        {
            "id": b.id,
            "room_code": b.room.code,
            "building": b.room.building.code,
            "floor": b.room.floor.name,
            "date": str(b.date),
            "start_time": b.start_time.strftime("%H:%M"),
            "end_time": b.end_time.strftime("%H:%M"),
            "start_time_12": b.start_time.strftime("%I:%M %p"),
            "end_time_12": b.end_time.strftime("%I:%M %p"),
            "purpose": b.purpose.value,
            "purpose_detail": b.purpose_detail or "",
            "custom_reason": b.custom_reason or "",
            "target_branch": b.target_branch or "All",
            "target_year": b.target_year,
            "target_sem": getattr(b, "target_sem", None) or ("1st" if "[1st Sem]" in (b.custom_reason or "") else "2nd" if "[2nd Sem]" in (b.custom_reason or "") else None),
            "expected_students": b.expected_students,
            "status": b.status.value,
            "is_test_data": getattr(b, "is_test_data", True)
        }
        for b in bookings
    ]

@router.get("/all")
def all_bookings(
    date_str: Optional[str] = None,
    room_code: Optional[str] = None,
    building: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in (UserRole.ADMIN, UserRole.STAFF, UserRole.FACULTY):
        raise HTTPException(403, "Not authorized to view master bookings")
        
    auto_complete_expired_bookings(db)

    q = db.query(Booking).options(
        joinedload(Booking.room).joinedload(Room.building),
        joinedload(Booking.room).joinedload(Room.floor),
        joinedload(Booking.user)
    )
    
    if date_str:
        try:
            if "/" in date_str:
                d, m, y = map(int, date_str.strip().split("/"))
                if y < 100: y += 2000
                q = q.filter(Booking.date == date(y, m, d))
            else:
                q = q.filter(Booking.date == date.fromisoformat(date_str.strip()))
        except Exception:
            pass
    if room_code:
        q = q.join(Room).filter(Room.code.ilike(f"%{room_code.strip()}%"))
    if status:
        q = q.filter(Booking.status == status)
        
    bookings = q.order_by(Booking.date.desc(), Booking.start_time.desc()).limit(300).all()
    
    result = []
    for b in bookings:
        start_m = b.start_time.hour * 60 + b.start_time.minute
        end_m = b.end_time.hour * 60 + b.end_time.minute
        dur = round((end_m - start_m) / 60, 1)
        result.append({
            "id": b.id,
            "room_code": b.room.code,
            "building": b.room.building.name if b.room.building else "IET",
            "floor": b.room.floor.name if b.room.floor else "Ground Floor",
            "date": str(b.date),
            "start_time": b.start_time.strftime("%H:%M"),
            "end_time": b.end_time.strftime("%H:%M"),
            "start_time_12": b.start_time.strftime("%I:%M %p"),
            "end_time_12": b.end_time.strftime("%I:%M %p"),
            "duration_hours": dur,
            "purpose": b.purpose.value,
            "purpose_detail": b.purpose_detail or "Classroom Session",
            "custom_reason": b.custom_reason or "",
            "target_branch": b.target_branch or "All",
            "target_year": b.target_year,
            "target_sem": getattr(b, "target_sem", None) or ("1st" if "[1st Sem]" in (b.custom_reason or "") else "2nd" if "[2nd Sem]" in (b.custom_reason or "") else None),
            "status": b.status.value,
            "user_name": b.user.full_name if b.user else "Faculty",
            "user_email": b.user.email if b.user else "",
            "user_role": b.user.role.value if b.user else "faculty",
            "user_department": b.user.department if b.user else "",
            "expected_students": b.expected_students,
            "is_test_data": getattr(b, "is_test_data", True),
            "created_at": str(b.created_at) if b.created_at else ""
        })
    return result

@router.post("/{booking_id}/cancel")
def cancel(booking_id: int, reason: str = "", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    is_admin = current_user.role == UserRole.ADMIN
    ok = cancel_booking(db, booking_id, current_user.id, is_admin, reason)
    if not ok:
        raise HTTPException(400, "Cannot cancel this booking")
    return {"message": "Booking cancelled"}
