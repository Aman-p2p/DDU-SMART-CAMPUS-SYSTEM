from datetime import date, time, datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from pydantic import BaseModel

from ..core.database import get_db
from ..models.models import Room, Building, Floor, Booking, BookingStatus, User
from ..services.booking_service import (
    is_room_available, time_to_minutes, get_room_slot_conflict_info,
    auto_complete_expired_bookings, get_ist_now
)

router = APIRouter()

class RoomOut(BaseModel):
    id: int
    code: str
    capacity: int
    room_type: str
    facilities: Optional[str]
    is_maintenance: bool
    is_test_data: Optional[bool] = True
    building_code: str
    building_name: str
    floor_name: str
    live_status: Optional[str] = None
    occupied_reason: Optional[str] = None
    occupied_by: Optional[str] = None
    occupied_from: Optional[str] = None
    occupied_until: Optional[str] = None
    next_free_slot: Optional[str] = None
    minutes_left: Optional[int] = None

    class Config:
        from_attributes = True

@router.get("/", response_model=List[RoomOut])
def list_rooms(
    building: Optional[str] = None,
    floor: Optional[str] = None,
    room_type: Optional[str] = None,
    min_capacity: int = 0,
    search: Optional[str] = None,
    date_str: Optional[str] = None,
    start: Optional[str] = None,
    duration_hours: float = 1.5,
    available_only: bool = False,
    db: Session = Depends(get_db)
):
    q = db.query(Room).options(joinedload(Room.building), joinedload(Room.floor))
    
    if building:
        q = q.join(Building).filter(Building.code == building.upper())
    if floor:
        q = q.join(Floor).filter(Floor.name == floor)
    if room_type:
        q = q.filter(Room.room_type == room_type)
    if min_capacity > 0:
        q = q.filter(Room.capacity >= min_capacity)
    if search:
        s = f"%{search.strip().lower()}%"
        q = q.filter(
            or_(
                Room.code.ilike(s),
                Room.facilities.ilike(s),
                Room.notes.ilike(s),
                Building.name.ilike(s),
                Building.code.ilike(s)
            )
        )
    
    rooms = q.all()

    # 1. Auto-complete expired bookings first so room status is always real-time
    auto_complete_expired_bookings(db)
    
    # 2. Parse time window (default to current IST date and time)
    ist_now = get_ist_now()
    booking_date = ist_now.date()
    if date_str:
        try:
            if "/" in date_str:
                d, m, y = map(int, date_str.strip().split("/"))
                if y < 100: y += 2000
                booking_date = date(y, m, d)
            else:
                booking_date = date.fromisoformat(date_str.strip())
        except Exception:
            pass
            
    start_t = time(ist_now.hour, ist_now.minute)
    if start:
        try:
            h, m = map(int, start.split(":"))
            start_t = time(h, m)
        except Exception:
            pass
            
    end_minutes = time_to_minutes(start_t) + int(duration_hours * 60)
    end_t = time(end_minutes // 60 % 24, end_minutes % 60)
    
    result = []
    for r in rooms:
        if r.room_type.value == "office":
            continue
            
        is_avail = is_room_available(db, r, booking_date, start_t, end_t)
        if r.is_maintenance:
            status = "maintenance"
        elif not is_avail:
            # Check if reason is an active temporary 5-minute hold
            now_utc = datetime.utcnow()
            active_hold = db.query(Booking).filter(
                Booking.room_id == r.id,
                Booking.date == booking_date,
                Booking.status == BookingStatus.HOLD,
                Booking.hold_expires_at != None,
                Booking.hold_expires_at > now_utc
            ).first()
            if active_hold and (time_to_minutes(start_t) < time_to_minutes(active_hold.end_time) and time_to_minutes(end_t) > time_to_minutes(active_hold.start_time)):
                status = "hold"
            else:
                status = "booked"
        else:
            status = "available"
        
        if available_only and status != "available":
            continue
            
        conflict_info = None
        if status in ("booked", "hold"):
            conflict_info = get_room_slot_conflict_info(db, r.id, booking_date, start_t, end_t)
            
        result.append(RoomOut(
            id=r.id,
            code=r.code,
            capacity=r.capacity,
            room_type=r.room_type.value,
            facilities=r.facilities,
            is_maintenance=r.is_maintenance,
            is_test_data=getattr(r, "is_test_data", True),
            building_code=r.building.code,
            building_name=r.building.name,
            floor_name=r.floor.name,
            live_status=status,
            occupied_reason=conflict_info["reason"] if conflict_info else ("5-Minute Temporary Hold" if status == "hold" else None),
            occupied_by=conflict_info["occupied_by"] if conflict_info else ("Reserved by Faculty" if status == "hold" else None),
            occupied_from=conflict_info["occupied_from"] if conflict_info else None,
            occupied_until=conflict_info["occupied_until"] if conflict_info else None,
            next_free_slot=conflict_info["next_free_slot"] if conflict_info else None,
            minutes_left=conflict_info["minutes_left"] if conflict_info else None
        ))
        
    return result

@router.get("/buildings")
def list_buildings(db: Session = Depends(get_db)):
    buildings = db.query(Building).all()
    return [{"id": b.id, "code": b.code, "name": b.name, "distance_meters": b.distance_meters} for b in buildings]

@router.get("/{room_id}")
def get_room(room_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).options(joinedload(Room.building), joinedload(Room.floor)).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "Room not found")
    return {
        "id": room.id,
        "code": room.code,
        "capacity": room.capacity,
        "room_type": room.room_type.value,
        "facilities": room.facilities,
        "is_maintenance": room.is_maintenance,
        "building": room.building.code,
        "floor": room.floor.name
    }
