from datetime import date, time
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel

from ..core.database import get_db
from ..models.models import (
    TimetableSchedule, ExamSchedule, Room, User, UserRole, Announcement
)
from ..services.booking_service import auto_complete_expired_bookings
from .auth import get_current_user

router = APIRouter()

class TimetableOut(BaseModel):
    id: int
    room_code: str
    branch: str
    academic_year: int
    semester: Optional[str] = "1st"
    section: Optional[str]
    day_of_week: int
    day_name: str
    start_time: str
    end_time: str
    subject: str
    faculty_name: str
    schedule_type: str

class ExamOut(BaseModel):
    id: int
    room_code: str
    subject_name: str
    branch: str
    academic_year: int
    semester: Optional[str] = "1st"
    section: Optional[str]
    exam_date: str
    start_time: str
    end_time: str
    exam_type: str
    instructions: Optional[str]

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

@router.get("/timetable", response_model=List[TimetableOut])
def get_timetable(
    branch: Optional[str] = None,
    academic_year: Optional[int] = None,
    semester: Optional[str] = None,
    section: Optional[str] = None,
    faculty_name: Optional[str] = None,
    room_code: Optional[str] = None,
    day_of_week: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    auto_complete_expired_bookings(db)
    q = db.query(TimetableSchedule).options(joinedload(TimetableSchedule.room))
    
    # If student, default to their branch & year if not explicitly overridden
    if current_user.role == UserRole.STUDENT and not branch and current_user.branch:
        q = q.filter(TimetableSchedule.branch == current_user.branch)
        if not academic_year and current_user.academic_year:
            q = q.filter(TimetableSchedule.academic_year == current_user.academic_year)
    else:
        if branch:
            q = q.filter(TimetableSchedule.branch == branch)
        if academic_year:
            q = q.filter(TimetableSchedule.academic_year == academic_year)
            
    if semester:
        q = q.filter(TimetableSchedule.semester == semester)
    if section:
        q = q.filter(TimetableSchedule.section == section)
    if faculty_name:
        q = q.filter(TimetableSchedule.faculty_name.ilike(f"%{faculty_name.strip()}%"))
    if room_code:
        q = q.join(Room).filter(Room.code.ilike(f"%{room_code.strip()}%"))
    if day_of_week is not None and day_of_week >= 0:
        q = q.filter(TimetableSchedule.day_of_week == day_of_week)
        
    entries = q.order_by(TimetableSchedule.day_of_week, TimetableSchedule.start_time).all()
    
    return [
        TimetableOut(
            id=e.id,
            room_code=e.room.code if e.room else f"Room #{e.room_id}",
            branch=e.branch,
            academic_year=e.academic_year,
            semester=getattr(e, "semester", "1st") or "1st",
            section=e.section,
            day_of_week=e.day_of_week,
            day_name=DAY_NAMES[e.day_of_week % 7],
            start_time=e.start_time.strftime("%H:%M"),
            end_time=e.end_time.strftime("%H:%M"),
            subject=e.subject,
            faculty_name=e.faculty_name,
            schedule_type=e.schedule_type
        )
        for e in entries
    ]

@router.get("/faculties")
def get_faculties(db: Session = Depends(get_db)):
    faculties = db.query(TimetableSchedule.faculty_name).distinct().all()
    return sorted([f[0] for f in faculties if f[0]])

@router.get("/branches")
def get_branches(db: Session = Depends(get_db)):
    branches = db.query(TimetableSchedule.branch).distinct().all()
    return sorted([b[0] for b in branches if b[0]])

@router.get("/student-schedule")
def get_student_schedule(
    branch: Optional[str] = None,
    academic_year: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    auto_complete_expired_bookings(db)
    eff_branch = branch or current_user.branch or "AI_ML"
    eff_year = academic_year or current_user.academic_year or 3
    today = date.today()

    # 1. Regular Timetable classes
    tt_classes = db.query(TimetableSchedule).options(joinedload(TimetableSchedule.room)).filter(
        TimetableSchedule.branch == eff_branch,
        TimetableSchedule.academic_year == eff_year
    ).order_by(TimetableSchedule.day_of_week, TimetableSchedule.start_time).all()

    # 2. Booked Extra Lectures & Sessions (Requirement 3: Student Sync)
    from ..models.models import Booking, BookingStatus
    from sqlalchemy import or_
    extra_bookings = db.query(Booking).options(
        joinedload(Booking.room), joinedload(Booking.user)
    ).filter(
        Booking.status == BookingStatus.CONFIRMED,
        Booking.date >= today,
        or_(
            Booking.target_branch == eff_branch,
            Booking.target_branch == "All",
            Booking.target_branch == None
        )
    ).order_by(Booking.date, Booking.start_time).all()

    # 3. Scheduled Exams
    exams = db.query(ExamSchedule).options(joinedload(ExamSchedule.room)).filter(
        ExamSchedule.branch == eff_branch,
        ExamSchedule.exam_date >= today
    ).order_by(ExamSchedule.exam_date, ExamSchedule.start_time).all()

    # 4. Announcements for students
    anns = db.query(Announcement).filter(
        Announcement.is_active == True
    ).order_by(Announcement.created_at.desc()).limit(10).all()

    return {
        "profile": {
            "student_name": current_user.full_name,
            "branch": eff_branch,
            "academic_year": eff_year
        },
        "timetable": [
            {
                "id": t.id,
                "room_code": t.room.code if t.room else f"Room #{t.room_id}",
                "day_of_week": t.day_of_week,
                "day_name": DAY_NAMES[t.day_of_week % 7],
                "start_time": t.start_time.strftime("%H:%M"),
                "end_time": t.end_time.strftime("%H:%M"),
                "start_time_12": t.start_time.strftime("%I:%M %p"),
                "end_time_12": t.end_time.strftime("%I:%M %p"),
                "subject": t.subject,
                "faculty_name": t.faculty_name,
                "schedule_type": t.schedule_type,
                "semester": getattr(t, "semester", "1st") or "1st"
            }
            for t in tt_classes
        ],
        "extra_bookings": [
            {
                "id": b.id,
                "room_code": b.room.code if b.room else "TBD",
                "date": str(b.date),
                "start_time": b.start_time.strftime("%H:%M"),
                "end_time": b.end_time.strftime("%H:%M"),
                "start_time_12": b.start_time.strftime("%I:%M %p"),
                "end_time_12": b.end_time.strftime("%I:%M %p"),
                "purpose": b.purpose.value,
                "purpose_detail": b.purpose_detail or "Special Lecture",
                "custom_reason": b.custom_reason or "",
                "booked_by": b.user.full_name if b.user else "Faculty",
                "target_branch": b.target_branch,
                "target_year": b.target_year,
                "target_sem": getattr(b, "target_sem", None) or ("1st" if "[1st Sem]" in (b.custom_reason or "") else "2nd" if "[2nd Sem]" in (b.custom_reason or "") else None)
            }
            for b in extra_bookings
        ],
        "exams": [
            {
                "id": ex.id,
                "room_code": ex.room.code if ex.room else "TBD",
                "subject_name": ex.subject_name,
                "branch": ex.branch,
                "academic_year": ex.academic_year,
                "semester": getattr(ex, "semester", "1st") or "1st",
                "exam_date": str(ex.exam_date),
                "start_time": ex.start_time.strftime("%H:%M"),
                "end_time": ex.end_time.strftime("%H:%M"),
                "start_time_12": ex.start_time.strftime("%I:%M %p"),
                "end_time_12": ex.end_time.strftime("%I:%M %p"),
                "exam_type": ex.exam_type,
                "instructions": ex.instructions or ""
            }
            for ex in exams
        ],
        "notices": [
            {
                "id": a.id,
                "title": a.title,
                "body": a.body,
                "category": a.category,
                "created_at": a.created_at.strftime("%d %b %Y, %I:%M %p") if a.created_at else ""
            }
            for a in anns
        ]
    }

@router.get("/exams", response_model=List[ExamOut])
def get_exams(
    branch: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(ExamSchedule).options(joinedload(ExamSchedule.room))
    if branch:
        q = q.filter(ExamSchedule.branch == branch)
    elif current_user.role == UserRole.STUDENT and current_user.branch:
        q = q.filter(ExamSchedule.branch == current_user.branch)
        
    exams = q.order_by(ExamSchedule.exam_date, ExamSchedule.start_time).all()
    return [
        ExamOut(
            id=ex.id,
            room_code=ex.room.code if ex.room else f"Room #{ex.room_id}",
            subject_name=ex.subject_name,
            branch=ex.branch,
            academic_year=ex.academic_year,
            semester=getattr(ex, "semester", "1st") or "1st",
            section=ex.section,
            exam_date=str(ex.exam_date),
            start_time=ex.start_time.strftime("%H:%M"),
            end_time=ex.end_time.strftime("%H:%M"),
            exam_type=ex.exam_type,
            instructions=ex.instructions
        )
        for ex in exams
    ]

class AnnouncementCreate(BaseModel):
    title: str
    body: str
    target_roles: str = "all"
    category: str = "general"

@router.get("/announcements")
def get_announcements(db: Session = Depends(get_db)):
    anns = db.query(Announcement).options(joinedload(Announcement.author)).filter(Announcement.is_active == True).order_by(Announcement.created_at.desc()).limit(30).all()
    return [
        {
            "id": a.id,
            "title": a.title,
            "body": a.body,
            "target_roles": a.target_roles,
            "category": getattr(a, "category", "general") or "general",
            "author_name": a.author.full_name if a.author else "University Administration",
            "author_role": a.author.role.value if a.author else "admin",
            "created_at": a.created_at.strftime("%d %b %Y, %H:%M") if a.created_at else ""
        }
        for a in anns
    ]

@router.post("/announcements", status_code=201)
def create_announcement(
    payload: AnnouncementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in (UserRole.FACULTY, UserRole.ADMIN, UserRole.STAFF):
        raise HTTPException(403, "Only Faculty, Staff, and Administrators can broadcast notifications.")
    
    ann = Announcement(
        title=payload.title.strip(),
        body=payload.body.strip(),
        created_by=current_user.id,
        target_roles=payload.target_roles,
        category=payload.category,
        is_active=True
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    
    return {
        "id": ann.id,
        "title": ann.title,
        "body": ann.body,
        "target_roles": ann.target_roles,
        "category": getattr(ann, "category", "general") or "general",
        "author_name": current_user.full_name,
        "author_role": current_user.role.value,
        "created_at": ann.created_at.strftime("%d %b %Y, %H:%M") if ann.created_at else "Just now"
    }

@router.delete("/announcements/{ann_id}")
def delete_announcement(
    ann_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in (UserRole.ADMIN, UserRole.FACULTY, UserRole.STAFF):
        raise HTTPException(403, "Not authorized")
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if not ann:
        raise HTTPException(404, "Notification not found")
    if current_user.role != UserRole.ADMIN and ann.created_by != current_user.id:
        raise HTTPException(403, "You can only delete your own notifications")
    db.delete(ann)
    db.commit()
    return {"message": "Notification deleted successfully"}
