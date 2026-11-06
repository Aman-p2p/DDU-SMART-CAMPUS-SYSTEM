from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, Field
from typing import Optional, List

from ..core.database import get_db
from ..models.models import (
    Room, User, UserRole, Announcement, IssueReport, AuditLog,
    Building, Floor, RoomType
)
from ..services.booking_service import auto_complete_expired_bookings
from .auth import get_current_user

router = APIRouter()

def require_admin(user: User = Depends(get_current_user)):
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "Admin only")
    return user

def require_staff_or_admin(user: User = Depends(get_current_user)):
    if user.role not in (UserRole.ADMIN, UserRole.STAFF):
        raise HTTPException(403, "Staff or Admin only")
    return user

# ---------- ROOM MANAGEMENT ----------

class RoomCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=30)
    building_id: int
    floor_id: int
    capacity: int = Field(..., ge=1, le=1000)
    room_type: str = "classroom"  # classroom, lab, seminar, library, office
    facilities: Optional[str] = None
    is_maintenance: bool = False
    notes: Optional[str] = None

class RoomUpdate(BaseModel):
    code: Optional[str] = None
    building_id: Optional[int] = None
    floor_id: Optional[int] = None
    capacity: Optional[int] = Field(None, ge=1, le=1000)
    room_type: Optional[str] = None
    facilities: Optional[str] = None
    is_maintenance: Optional[bool] = None
    notes: Optional[str] = None

@router.get("/meta/buildings")
def list_buildings_meta(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    buildings = db.query(Building).all()
    floors = db.query(Floor).all()
    return {
        "buildings": [{"id": b.id, "code": b.code, "name": b.name} for b in buildings],
        "floors": [{"id": f.id, "building_id": f.building_id, "name": f.name, "level": f.level} for f in floors],
        "room_types": [t.value for t in RoomType]
    }

@router.get("/rooms")
def admin_list_rooms(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rooms = (
        db.query(Room)
        .options(joinedload(Room.building), joinedload(Room.floor))
        .order_by(Room.code)
        .all()
    )
    return [
        {
            "id": r.id,
            "code": r.code,
            "capacity": r.capacity,
            "room_type": r.room_type.value,
            "facilities": r.facilities,
            "is_maintenance": r.is_maintenance,
            "is_verified": r.is_verified,
            "notes": r.notes,
            "building_id": r.building_id,
            "building_code": r.building.code,
            "floor_id": r.floor_id,
            "floor_name": r.floor.name,
        }
        for r in rooms
    ]

@router.post("/rooms", status_code=201)
def create_room(payload: RoomCreate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    existing = db.query(Room).filter(Room.code == payload.code.strip()).first()
    if existing:
        raise HTTPException(400, f"Room code '{payload.code}' already exists")

    building = db.query(Building).filter(Building.id == payload.building_id).first()
    if not building:
        raise HTTPException(400, "Invalid building_id")
    floor = db.query(Floor).filter(Floor.id == payload.floor_id, Floor.building_id == payload.building_id).first()
    if not floor:
        raise HTTPException(400, "Invalid floor_id for this building")

    try:
        rtype = RoomType(payload.room_type)
    except ValueError:
        raise HTTPException(400, f"Invalid room_type. Use one of: {[t.value for t in RoomType]}")

    room = Room(
        code=payload.code.strip().upper() if payload.code.strip().startswith("LH") or payload.code.strip().startswith("IET") else payload.code.strip(),
        building_id=payload.building_id,
        floor_id=payload.floor_id,
        capacity=payload.capacity,
        room_type=rtype,
        facilities=payload.facilities,
        is_maintenance=payload.is_maintenance,
        notes=payload.notes,
        is_verified=True,
    )
    db.add(room)
    db.add(AuditLog(actor_id=user.id, action="room.created", entity_type="room", details=f"Created {room.code}"))
    db.commit()
    db.refresh(room)
    return {"id": room.id, "code": room.code, "message": "Room created"}

@router.put("/rooms/{room_id}")
def update_room(room_id: int, payload: RoomUpdate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "Room not found")

    if payload.code is not None:
        code = payload.code.strip()
        conflict = db.query(Room).filter(Room.code == code, Room.id != room_id).first()
        if conflict:
            raise HTTPException(400, f"Room code '{code}' already exists")
        room.code = code

    if payload.building_id is not None:
        if not db.query(Building).filter(Building.id == payload.building_id).first():
            raise HTTPException(400, "Invalid building_id")
        room.building_id = payload.building_id

    if payload.floor_id is not None:
        floor = db.query(Floor).filter(Floor.id == payload.floor_id).first()
        if not floor:
            raise HTTPException(400, "Invalid floor_id")
        if payload.building_id and floor.building_id != payload.building_id:
            raise HTTPException(400, "Floor does not belong to selected building")
        if floor.building_id != room.building_id and payload.building_id is None:
            raise HTTPException(400, "Floor does not belong to room's building")
        room.floor_id = payload.floor_id

    if payload.capacity is not None:
        room.capacity = payload.capacity
    if payload.room_type is not None:
        try:
            room.room_type = RoomType(payload.room_type)
        except ValueError:
            raise HTTPException(400, "Invalid room_type")
    if payload.facilities is not None:
        room.facilities = payload.facilities
    if payload.is_maintenance is not None:
        room.is_maintenance = payload.is_maintenance
    if payload.notes is not None:
        room.notes = payload.notes

    db.add(AuditLog(actor_id=user.id, action="room.updated", entity_type="room", entity_id=room_id, details=f"Updated {room.code}"))
    db.commit()
    return {"id": room.id, "code": room.code, "message": "Room updated"}

@router.delete("/rooms/{room_id}")
def delete_room(room_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "Room not found")
    code = room.code
    # Check active bookings
    from ..models.models import Booking, BookingStatus
    active = db.query(Booking).filter(
        Booking.room_id == room_id,
        Booking.status == BookingStatus.CONFIRMED
    ).count()
    if active > 0:
        raise HTTPException(400, f"Cannot delete: {active} active booking(s) exist. Cancel them first.")

    db.delete(room)
    db.add(AuditLog(actor_id=user.id, action="room.deleted", entity_type="room", details=f"Deleted {code}"))
    db.commit()
    return {"message": f"Room {code} deleted"}

@router.patch("/rooms/{room_id}/maintenance")
def toggle_maintenance(room_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "Room not found")
    room.is_maintenance = not room.is_maintenance
    
    # Requirement 11: Audit log for maintenance change
    status_str = "entered maintenance mode" if room.is_maintenance else "restored to active service"
    db.add(AuditLog(
        actor_id=user.id,
        action="room.maintenance_toggled",
        entity_type="room",
        entity_id=room.id,
        details=f"Room {room.code} {status_str}"
    ))
    db.commit()
    return {"code": room.code, "is_maintenance": room.is_maintenance}

# ---------- REQUIREMENT 10: ADMIN ANALYTICS ENDPOINT ----------

@router.get("/analytics")
def admin_analytics(db: Session = Depends(get_db), user: User = Depends(require_staff_or_admin)):
    auto_complete_expired_bookings(db)
    from ..models.models import Booking, BookingStatus, UserRole
    from datetime import date, datetime
    today = date.today()
    now_utc = datetime.utcnow()

    total_rooms = db.query(Room).filter(Room.room_type != RoomType.OFFICE).count()
    maintenance_rooms = db.query(Room).filter(Room.is_maintenance == True).count()
    
    total_bookings = db.query(Booking).filter(Booking.status == BookingStatus.CONFIRMED).count()
    today_bookings = db.query(Booking).filter(Booking.status == BookingStatus.CONFIRMED, Booking.date == today).count()
    
    # Active 5-minute holds
    active_holds = db.query(Booking).filter(
        Booking.status == BookingStatus.HOLD,
        Booking.hold_expires_at != None,
        Booking.hold_expires_at > now_utc
    ).count()

    total_users = db.query(User).count()
    total_students = db.query(User).filter(User.role == UserRole.STUDENT).count()
    open_issues = db.query(IssueReport).filter(IssueReport.status == "open").count()

    # Room utilization formula
    utilization_rate = round((today_bookings / max(1, (total_rooms - maintenance_rooms))) * 100, 1)
    utilization_rate = min(100.0, utilization_rate)

    return {
        "total_bookings": total_bookings,
        "today_bookings": today_bookings,
        "room_utilization_rate": utilization_rate,
        "active_holds": active_holds,
        "total_rooms": total_rooms,
        "maintenance_rooms": maintenance_rooms,
        "total_users": total_users,
        "total_students": total_students,
        "open_issues": open_issues
    }

@router.get("/audit")
def audit_logs(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(100).all()
    return [{"id": l.id, "action": l.action, "entity": l.entity_type, "details": l.details, "at": str(l.created_at)} for l in logs]

class AnnouncementIn(BaseModel):
    title: str
    body: str
    target_roles: str = "all"

@router.post("/announcements")
def create_announcement(payload: AnnouncementIn, db: Session = Depends(get_db), user: User = Depends(require_staff_or_admin)):
    ann = Announcement(title=payload.title, body=payload.body, created_by=user.id, target_roles=payload.target_roles)
    db.add(ann)
    db.commit()
    return {"id": ann.id, "message": "Published"}

@router.get("/announcements")
def list_announcements(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    anns = db.query(Announcement).filter(Announcement.is_active == True).order_by(Announcement.created_at.desc()).limit(50).all()
    return [{"id": a.id, "title": a.title, "body": a.body, "created_at": str(a.created_at)} for a in anns]

class IssueIn(BaseModel):
    room_code: Optional[str] = None
    issue_type: str
    description: str

@router.post("/issues")
def report_issue(payload: IssueIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    issue = IssueReport(
        reporter_id=user.id,
        room_code=payload.room_code,
        issue_type=payload.issue_type,
        description=payload.description
    )
    db.add(issue)
    db.commit()
    return {"id": issue.id, "message": "Issue reported"}

@router.get("/issues")
def list_issues(db: Session = Depends(get_db), user: User = Depends(require_staff_or_admin)):
    issues = db.query(IssueReport).options(joinedload(IssueReport.reporter)).order_by(IssueReport.created_at.desc()).all()
    return [
        {
            "id": i.id,
            "reporter_name": i.reporter.full_name if i.reporter else "Anonymous",
            "reporter_email": i.reporter.email if i.reporter else "",
            "room_code": i.room_code,
            "issue_type": i.issue_type,
            "description": i.description,
            "status": i.status,
            "created_at": str(i.created_at)
        }
        for i in issues
    ]

class StatusUpdate(BaseModel):
    status: str

@router.patch("/issues/{issue_id}/status")
def update_issue_status(issue_id: int, payload: StatusUpdate, db: Session = Depends(get_db), user: User = Depends(require_staff_or_admin)):
    issue = db.query(IssueReport).filter(IssueReport.id == issue_id).first()
    if not issue:
        raise HTTPException(404, "Issue not found")
    issue.status = payload.status
    db.commit()
    return {"id": issue.id, "status": issue.status}

class CapacityUpdate(BaseModel):
    capacity: int

@router.patch("/rooms/{room_id}/capacity")
def update_room_capacity(room_id: int, payload: CapacityUpdate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "Room not found")
    room.capacity = payload.capacity
    db.commit()
    return {"id": room.id, "code": room.code, "capacity": room.capacity}
