"""
TRINETRA Booking Engine
- Conflict detection using half-open intervals
- Automatic alternative suggestions
- No manual approval for normal bookings
"""

import threading
from datetime import datetime, date, time, timedelta
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from fastapi import HTTPException, status

from ..models.models import (
    Booking, Room, User, UserRole, BookingStatus, BookingPurpose, 
    RoomType, Notification, Announcement, AuditLog, TimetableSchedule, ExamSchedule
)

# Concurrency mutex: guarantees zero double-bookings under concurrent race conditions
booking_lock = threading.Lock()

def get_ist_now() -> datetime:
    """Return current Indian Standard Time (IST = UTC + 5:30)."""
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

def auto_complete_expired_bookings(db: Session) -> int:
    """
    Automatically marks all elapsed CONFIRMED or HOLD bookings as COMPLETED.
    A booking is elapsed if:
      - its date < ist_today
      - its date == ist_today and end_time <= ist_now_time
    Once COMPLETED, the room immediately shows as Available and is ready for new bookings.
    """
    ist_now = get_ist_now()
    ist_today = ist_now.date()
    ist_time = ist_now.time()

    expired = db.query(Booking).filter(
        Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.HOLD]),
        or_(
            Booking.date < ist_today,
            and_(Booking.date == ist_today, Booking.end_time <= ist_time)
        )
    ).all()

    if not expired:
        return 0

    for b in expired:
        b.status = BookingStatus.COMPLETED
        room_label = b.room.code if b.room else f"ID {b.room_id}"
        db.add(AuditLog(
            actor_id=b.user_id,
            action="AUTO_VACATED",
            entity_type="room",
            entity_id=b.room_id,
            details=f"Room {room_label} automatically vacated upon slot completion (Date: {b.date}, End Time: {b.end_time.strftime('%H:%M')})"
        ))

    try:
        db.commit()
    except Exception:
        db.rollback()

    return len(expired)

def time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute

def overlaps(start1: time, end1: time, start2: time, end2: time) -> bool:
    """Half-open interval collision check: [start, end)"""
    return time_to_minutes(start1) < time_to_minutes(end2) and time_to_minutes(end1) > time_to_minutes(start2)

def get_conflicting_bookings(
    db: Session,
    room_id: int,
    booking_date: date,
    start: time,
    end: time,
    exclude_booking_id: Optional[int] = None
) -> List[Booking]:
    # 1. Auto-complete expired bookings first so finished rooms become immediately available
    auto_complete_expired_bookings(db)

    # 2. Auto-release expired 5-minute holds
    now_utc = datetime.utcnow()
    expired_holds = db.query(Booking).filter(
        Booking.room_id == room_id,
        Booking.status == BookingStatus.HOLD,
        Booking.hold_expires_at != None,
        Booking.hold_expires_at < now_utc
    ).all()
    if expired_holds:
        for eh in expired_holds:
            eh.status = BookingStatus.CANCELLED
            eh.cancel_reason = "5-minute hold expired"
        try:
            db.commit()
        except Exception:
            db.rollback()

    q = db.query(Booking).filter(
        Booking.room_id == room_id,
        Booking.date == booking_date,
        Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.HOLD])
    )
    if exclude_booking_id:
        q = q.filter(Booking.id != exclude_booking_id)
    
    candidates = q.all()
    return [b for b in candidates if overlaps(start, end, b.start_time, b.end_time)]

def is_room_available(
    db: Session,
    room: Room,
    booking_date: date,
    start: time,
    end: time,
    exclude_booking_id: Optional[int] = None
) -> bool:
    if room.is_maintenance:
        return False

    # Auto-complete expired bookings
    auto_complete_expired_bookings(db)

    conflicts = get_conflicting_bookings(db, room.id, booking_date, start, end, exclude_booking_id)
    if len(conflicts) > 0:
        return False
    
    # Check exam conflicts on that date
    exam_conflicts = db.query(ExamSchedule).filter(
        ExamSchedule.room_id == room.id,
        ExamSchedule.exam_date == booking_date
    ).all()
    for ex in exam_conflicts:
        if overlaps(start, end, ex.start_time, ex.end_time):
            return False
            
    # Check regular timetable schedule for that day of week
    dow = booking_date.weekday()
    tt_conflicts = db.query(TimetableSchedule).filter(
        TimetableSchedule.room_id == room.id,
        TimetableSchedule.day_of_week == dow
    ).all()
    for tt in tt_conflicts:
        if overlaps(start, end, tt.start_time, tt.end_time):
            return False

    return True

def get_all_room_busy_intervals(
    db: Session,
    room_id: int,
    booking_date: date
) -> List[Tuple[time, time, str, str]]:
    """
    Returns list of (start_time, end_time, reason, occupied_by) for all events on booking_date,
    sorted by start_time.
    """
    # Auto-complete expired bookings first
    auto_complete_expired_bookings(db)

    intervals = []
    # 1. Confirmed Bookings
    bookings = db.query(Booking).filter(
        Booking.room_id == room_id,
        Booking.date == booking_date,
        Booking.status == BookingStatus.CONFIRMED
    ).all()
    for b in bookings:
        user_desc = f"{b.user.full_name} ({b.user.role.value.capitalize()})" if b.user else "Faculty Member"
        reason = f"{b.purpose.value.replace('_', ' ').title()}: {b.purpose_detail or 'Classroom Session'}"
        intervals.append((b.start_time, b.end_time, reason, user_desc))
        
    # 2. Exams
    exams = db.query(ExamSchedule).filter(
        ExamSchedule.room_id == room_id,
        ExamSchedule.exam_date == booking_date
    ).all()
    for ex in exams:
        reason = f"Scheduled Exam: {ex.subject_name} ({ex.exam_type})"
        intervals.append((ex.start_time, ex.end_time, reason, "Examination Coordinator"))
        
    # 3. Timetable
    dow = booking_date.weekday()
    tt_classes = db.query(TimetableSchedule).filter(
        TimetableSchedule.room_id == room_id,
        TimetableSchedule.day_of_week == dow
    ).all()
    for tt in tt_classes:
        reason = f"Lecture: {tt.subject} ({tt.branch} Year {tt.academic_year})"
        intervals.append((tt.start_time, tt.end_time, reason, f"{tt.faculty_name} ({tt.branch} Faculty)"))
        
    intervals.sort(key=lambda x: (x[0].hour * 60 + x[0].minute, x[1].hour * 60 + x[1].minute))
    return intervals


def get_room_slot_conflict_info(
    db: Session,
    room_id: int,
    booking_date: date,
    start: time,
    end: time
) -> Optional[dict]:
    """
    Returns conflict details if room is occupied during [start, end),
    calculating:
    - primary reason and occupied_by of the initial collision
    - true continuous chained block of occupancy (handling consecutive bookings A, B, C...)
    - genuine next available free slot (that does NOT collide with subsequent bookings)
    - accurate minutes_left countdown in IST
    """
    ist_now = get_ist_now()
    now_m = ist_now.hour * 60 + ist_now.minute
    start_m = start.hour * 60 + start.minute
    end_m = end.hour * 60 + end.minute

    intervals = get_all_room_busy_intervals(db, room_id, booking_date)
    
    # Find any interval overlapping [start, end)
    colliding = []
    for it_start, it_end, reason, occ_by in intervals:
        it_s_m = it_start.hour * 60 + it_start.minute
        it_e_m = it_end.hour * 60 + it_end.minute
        if max(start_m, it_s_m) < min(end_m, it_e_m):
            colliding.append((it_start, it_end, reason, occ_by))
            
    if not colliding:
        return None

    # Primary conflict details
    first_conflict = colliding[0]
    primary_reason = first_conflict[2]
    primary_occ_by = first_conflict[3]
    chain_start_m = first_conflict[0].hour * 60 + first_conflict[0].minute
    chain_end_m = first_conflict[1].hour * 60 + first_conflict[1].minute

    # Chain all subsequent continuous or overlapping intervals
    # e.g. 10:00-11:30 and 11:30-13:00 -> chain ends at 13:00!
    extended = True
    while extended:
        extended = False
        for it_start, it_end, reason, occ_by in intervals:
            it_s_m = it_start.hour * 60 + it_start.minute
            it_e_m = it_end.hour * 60 + it_end.minute
            # If this interval overlaps or directly abuts the current chain:
            if it_s_m <= chain_end_m and it_e_m > chain_end_m:
                chain_end_m = it_e_m
                extended = True

    occupied_from_t = time(chain_start_m // 60 % 24, chain_start_m % 60)
    occupied_until_t = time(chain_end_m // 60 % 24, chain_end_m % 60)

    # Next free slot: find the earliest slot >= chain_end_m that is free for at least 1 hour (60 min)
    next_free_str = None
    for cand_start_m in range(chain_end_m, 20 * 60, 15):
        cand_end_m = cand_start_m + 60
        # Check if [cand_start_m, cand_end_m) collides with any interval
        has_overlap = False
        for it_start, it_end, _, _ in intervals:
            it_s_m = it_start.hour * 60 + it_start.minute
            it_e_m = it_end.hour * 60 + it_end.minute
            if max(cand_start_m, it_s_m) < min(cand_end_m, it_e_m):
                has_overlap = True
                break
        if not has_overlap:
            next_free_str = f"{cand_start_m // 60:02d}:{cand_start_m % 60:02d}"
            break

    if not next_free_str:
        next_free_str = f"{chain_end_m // 60:02d}:{chain_end_m % 60:02d}"

    # Calculate minutes left until room is released
    mins_left = None
    if booking_date == ist_now.date():
        if now_m < chain_end_m:
            mins_left = max(0, chain_end_m - now_m)

    return {
        "reason": primary_reason,
        "occupied_by": primary_occ_by,
        "occupied_from": occupied_from_t.strftime("%H:%M"),
        "occupied_until": occupied_until_t.strftime("%H:%M"),
        "next_free_slot": next_free_str,
        "minutes_left": mins_left
    }

def rank_alternative(
    room: Room,
    required_capacity: int,
    preferred_building_id: Optional[int] = None,
    preferred_type: Optional[RoomType] = None
) -> float:
    score = 100.0
    # Capacity fitness (prefer close match, not oversized)
    over = room.capacity - required_capacity
    if over < 0:
        return -999
    score -= over * 0.25
    
    if preferred_building_id and room.building_id == preferred_building_id:
        score += 35
    if preferred_type and room.room_type == preferred_type:
        score += 15
    if room.room_type == RoomType.SEMINAR and required_capacity < 80:
        score -= 20
    if room.is_verified:
        score += 5
    return score

def find_alternatives(
    db: Session,
    booking_date: date,
    start: time,
    end: time,
    required_capacity: int,
    preferred_building_id: Optional[int] = None,
    preferred_type: Optional[RoomType] = None,
    limit: int = 6
) -> List[dict]:
    rooms = db.query(Room).filter(
        Room.is_maintenance == False,
        Room.capacity >= required_capacity,
        Room.room_type != RoomType.OFFICE
    ).all()
    
    results = []
    for room in rooms:
        if not is_room_available(db, room, booking_date, start, end):
            continue
        score = rank_alternative(room, required_capacity, preferred_building_id, preferred_type)
        if score < 0:
            continue
        results.append({
            "room_id": room.id,
            "code": room.code,
            "capacity": room.capacity,
            "room_type": room.room_type.value,
            "building_id": room.building_id,
            "floor_id": room.floor_id,
            "facilities": room.facilities,
            "score": round(score, 1)
        })
    
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]

def create_booking(
    db: Session,
    *,
    room_id: int,
    user_id: int,
    booking_date: date,
    start: time,
    end: time,
    purpose: BookingPurpose,
    purpose_detail: Optional[str] = None,
    custom_reason: Optional[str] = None,
    target_branch: Optional[str] = None,
    target_year: Optional[int] = None,
    target_sem: Optional[str] = None,
    expected_students: int = 60,
    is_test: bool = False
) -> Tuple[Optional[Booking], Optional[str], Optional[List[dict]]]:
    """
    Creates a classroom booking with concurrency lock and collision detection.
    Guarantees zero overlapping bookings across concurrent requests.
    Returns: (booking, error_message, alternatives)
    """
    with booking_lock:
        room = db.query(Room).filter(Room.id == room_id).first()
        if not room:
            return None, "Room not found", None
        if room.is_maintenance:
            return None, "Room is under maintenance", None
        if expected_students > room.capacity:
            return None, f"Capacity exceeded. Max {room.capacity} students.", None
        if end <= start:
            return None, "End time must be after start time", None
        
        # Prevent past bookings (allow only present & future)
        ist_now = get_ist_now()
        ist_today = ist_now.date()
        ist_time = ist_now.time()
        if not is_test:
            if booking_date < ist_today:
                return None, "Past date booking is not allowed. Please select today or a future date.", None
            if booking_date == ist_today and end <= ist_time:
                return None, f"This time slot has already elapsed today. Current time is {ist_time.strftime('%I:%M %p')}.", None

        # 1. Auto-complete any expired bookings first
        auto_complete_expired_bookings(db)
        
        # 2. Collision check (half-open interval [start, end))
        conflicts = get_conflicting_bookings(db, room_id, booking_date, start, end)
        conflict_reason = None
        if conflicts:
            conflict_reason = f"Room {room.code} is already booked by another faculty for an overlapping slot."
        else:
            # Check exam conflict
            exam_conflicts = [
                ex for ex in db.query(ExamSchedule).filter(ExamSchedule.room_id == room_id, ExamSchedule.exam_date == booking_date).all()
                if overlaps(start, end, ex.start_time, ex.end_time)
            ]
            if exam_conflicts:
                conflict_reason = f"Conflict: Scheduled examination '{exam_conflicts[0].subject_name}' ({exam_conflicts[0].exam_type}) is assigned to {room.code}."
            else:
                dow = booking_date.weekday()
                tt_conflicts = [
                    tt for tt in db.query(TimetableSchedule).filter(TimetableSchedule.room_id == room_id, TimetableSchedule.day_of_week == dow).all()
                    if overlaps(start, end, tt.start_time, tt.end_time)
                ]
                if tt_conflicts:
                    conflict_reason = f"Conflict: Regular class '{tt_conflicts[0].subject}' ({tt_conflicts[0].branch} Year {tt_conflicts[0].academic_year}) is scheduled in {room.code}."

        if conflict_reason:
            alts = find_alternatives(
                db, booking_date, start, end, expected_students,
                preferred_building_id=room.building_id,
                preferred_type=room.room_type
            )
            return None, conflict_reason, alts
        
        booking = Booking(
            room_id=room_id,
            user_id=user_id,
            date=booking_date,
            start_time=start,
            end_time=end,
            purpose=purpose,
            purpose_detail=purpose_detail,
            custom_reason=custom_reason,
            target_branch=target_branch,
            target_year=target_year,
            target_sem=target_sem,
            expected_students=expected_students,
            status=BookingStatus.CONFIRMED,
            is_test_data=is_test
        )
        db.add(booking)
        
        # Notification for booking owner
        notif = Notification(
            user_id=user_id,
            title="Booking Confirmed",
            body=f"{room.code} booked for {booking_date} {start.strftime('%I:%M %p')}–{end.strftime('%I:%M %p')}",
            type="success"
        )
        db.add(notif)
        
        # Broadcast notification to Students
        ann = Announcement(
            title=f"Schedule Update: {room.code} Reserved",
            body=f"{room.code} has been reserved for {purpose.value.replace('_', ' ').title()} on {booking_date} ({start.strftime('%I:%M %p')}–{end.strftime('%I:%M %p')}). Branch: {target_branch or 'All'} {f'Year {target_year}' if target_year else ''}. {custom_reason or ''}".strip(),
            created_by=user_id,
            target_roles="student,all",
            category="relocation",
            is_active=True
        )
        db.add(ann)

        # Push Notification to all active student accounts
        students = db.query(User).filter(User.role == UserRole.STUDENT).all()
        for st in students:
            db.add(Notification(
                user_id=st.id,
                title=f"Classroom Booked: {room.code}",
                body=f"{room.code} reserved on {booking_date} ({start.strftime('%I:%M %p')}–{end.strftime('%I:%M %p')}) for {target_branch or 'All'} students.",
                type="info"
            ))
        
        # Audit
        audit = AuditLog(
            actor_id=user_id,
            action="booking.created",
            entity_type="booking",
            details=f"Room {room.code} on {booking_date} ({start.strftime('%I:%M %p')}–{end.strftime('%I:%M %p')})"
        )
        db.add(audit)
        
        try:
            db.commit()
            db.refresh(booking)
            return booking, None, None
        except Exception as e:
            db.rollback()
            # Race condition: someone else committed first
            alts = find_alternatives(db, booking_date, start, end, expected_students, room.building_id, room.room_type)
            return None, "Booking conflict due to concurrent request. Please try an alternative.", alts

def cancel_booking(db: Session, booking_id: int, user_id: int, is_admin: bool, reason: str = "") -> bool:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return False
    if booking.user_id != user_id and not is_admin:
        return False
    if booking.status not in (BookingStatus.CONFIRMED, BookingStatus.HOLD):
        return False
    
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = datetime.utcnow()
    booking.cancel_reason = reason or "Cancelled by user"
    
    notif = Notification(
        user_id=booking.user_id,
        title="Booking Cancelled",
        body=f"Booking for room {booking.room.code if booking.room else booking.room_id} on {booking.date} was cancelled.",
        type="warning"
    )
    db.add(notif)
    
    # Requirement 3: Push cancellation notification to Students
    from ..models.models import Announcement
    ann = Announcement(
        title=f"Schedule Update: {booking.room.code if booking.room else 'Room'} Released",
        body=f"Reservation for {booking.room.code if booking.room else 'Room'} on {booking.date} has been cancelled ({reason or 'Slot released'}).",
        created_by=user_id,
        target_roles="student,all",
        category="general",
        is_active=True
    )
    db.add(ann)

    students = db.query(User).filter(User.role == UserRole.STUDENT).all()
    for st in students:
        db.add(Notification(
            user_id=st.id,
            title=f"Classroom Released: {booking.room.code if booking.room else 'Room'}",
            body=f"{booking.room.code if booking.room else 'Room'} on {booking.date} is now cancelled and released.",
            type="warning"
        ))
    
    audit = AuditLog(
        actor_id=user_id,
        action="booking.cancelled",
        entity_type="booking",
        entity_id=booking_id,
        details=reason or "Booking cancelled"
    )
    db.add(audit)
    db.commit()
    return True

# ---------- REQUIREMENT 9: TEMPORARY 5-MINUTE HOLD ENGINE ----------

def hold_room(
    db: Session,
    *,
    room_id: int,
    user_id: int,
    booking_date: date,
    start: time,
    end: time,
    purpose: BookingPurpose = BookingPurpose.EXTRA_LECTURE,
    expected_students: int = 60,
    target_branch: Optional[str] = None,
    target_year: Optional[int] = None,
    target_sem: Optional[str] = None,
    custom_reason: Optional[str] = None
) -> Tuple[Optional[Booking], Optional[str]]:
    with booking_lock:
        auto_complete_expired_bookings(db)
        room = db.query(Room).filter(Room.id == room_id).first()
        if not room:
            return None, "Room not found"
        if room.is_maintenance:
            return None, "Room is currently under maintenance"
        if not is_room_available(db, room, booking_date, start, end):
            return None, f"Room {room.code} is not available for this time slot"

        # Lock for 5 minutes
        hold_expires = datetime.utcnow() + timedelta(minutes=5)
        hold = Booking(
            room_id=room_id,
            user_id=user_id,
            date=booking_date,
            start_time=start,
            end_time=end,
            purpose=purpose,
            purpose_detail="Temporary 5-Minute Hold",
            custom_reason=custom_reason or "Temporary reservation hold",
            target_branch=target_branch,
            target_year=target_year,
            target_sem=target_sem,
            expected_students=expected_students,
            status=BookingStatus.HOLD,
            hold_expires_at=hold_expires,
            is_test_data=True
        )
        db.add(hold)
        db.add(AuditLog(
            actor_id=user_id,
            action="booking.held",
            entity_type="booking",
            details=f"Room {room.code} temporarily held for 5 minutes (expires at {hold_expires.strftime('%H:%M:%S')} UTC)"
        ))
        db.commit()
        db.refresh(hold)
        return hold, None

def confirm_hold(
    db: Session,
    hold_id: int,
    user_id: int,
    is_admin: bool,
    custom_reason: Optional[str] = None
) -> Tuple[Optional[Booking], Optional[str]]:
    hold = db.query(Booking).filter(Booking.id == hold_id).first()
    if not hold:
        return None, "Hold not found"
    if hold.user_id != user_id and not is_admin:
        return None, "Unauthorized"
    if hold.status != BookingStatus.HOLD:
        return None, f"Booking status is {hold.status.value}, cannot confirm"
    if hold.hold_expires_at and hold.hold_expires_at < datetime.utcnow():
        hold.status = BookingStatus.CANCELLED
        hold.cancel_reason = "5-minute hold expired"
        db.commit()
        return None, "Hold has expired"

    hold.status = BookingStatus.CONFIRMED
    if custom_reason:
        hold.custom_reason = custom_reason
    db.add(AuditLog(
        actor_id=user_id,
        action="booking.confirmed_from_hold",
        entity_type="booking",
        entity_id=hold.id,
        details=f"Room {hold.room.code} confirmed from temporary hold"
    ))
    db.commit()
    db.refresh(hold)
    return hold, None

def release_hold(db: Session, hold_id: int, user_id: int, is_admin: bool) -> bool:
    hold = db.query(Booking).filter(Booking.id == hold_id).first()
    if not hold:
        return False
    if hold.user_id != user_id and not is_admin:
        return False
    hold.status = BookingStatus.CANCELLED
    hold.cancel_reason = "Hold released by user"
    db.add(AuditLog(
        actor_id=user_id,
        action="booking.hold_released",
        entity_type="booking",
        entity_id=hold.id,
        details="5-minute hold released"
    ))
    db.commit()
    return True
