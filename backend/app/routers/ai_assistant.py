from datetime import date, time, timedelta, datetime
import json
import os
import re
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from typing import Optional, Dict, Any, List

from ..core.database import get_db
from ..core.config import get_settings
from ..models.models import (
    User, Room, Booking, BookingStatus, RoomType, UserRole,
    ExamSchedule, TimetableSchedule, Building, Announcement
)
from ..services.booking_service import find_alternatives, is_room_available, time_to_minutes
from .auth import get_current_user

router = APIRouter()
settings = get_settings()

class AIQuery(BaseModel):
    query: str

def get_gemini_client():
    key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    except Exception as e:
        print(f"[TRINETRA AI] Gemini Client initialization error: {e}")
        return None

def parse_time_str(s: str) -> time:
    m = re.search(r'(\d{1,2}):(\d{2})', s)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        return time(h % 24, mn % 60)
    m2 = re.search(r'(\d{1,2})\s*(am|pm)?', s, re.IGNORECASE)
    if m2:
        h = int(m2.group(1))
        ampm = (m2.group(2) or '').lower()
        if ampm == 'pm' and h < 12: h += 12
        elif ampm == 'am' and h == 12: h = 0
        return time(h % 24, 0)
    return time(10, 0)

@router.post("/ask")
def ask(payload: AIQuery, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user_query = payload.query.strip()
    q_lower = user_query.lower()
    today = date.today()
    tomorrow = today + timedelta(days=1)
    is_student = (current_user.role == UserRole.STUDENT)

    # ========================================================
    # 1. STRICT STUDENT ACCESS ENFORCEMENT (Requirement 4)
    # ========================================================
    booking_admin_keywords = [
        "book", "reserve", "hold", "lock", "cancel", "maintenance", 
        "delete", "admin", "audit", "override", "reallocate", "toggle"
    ]
    if is_student and any(re.search(r'\b' + re.escape(w) + r'\b', q_lower) for w in booking_admin_keywords):
        return {
            "reply": (
                "🔒 **Access Restricted (Student Security Policy)**\n\n"
                "Room reservation, temporary holds, and administrative settings are restricted to **Faculty** and **Campus Administration**.\n\n"
                "As a student, you can ask me about:\n"
                "• **Academic Schedule**: *\"What lectures do I have today?\"*\n"
                "• **Minor Examinations**: *\"When and where is the NSS minor exam scheduled?\"*\n"
                "• **Campus Announcements**: *\"Show latest university notices\"*\n"
                "• **Lab & Room Directions**: *\"Where is the Robotics Lab or LH05?\"*\n"
                "• **Report Timetable Issue**: Head to the *Report Issue* tab in your sidebar."
            ),
            "action": "student_restricted"
        }

    # ========================================================
    # 2. GEMINI API INTEGRATION (Requirement 4)
    # ========================================================
    client = get_gemini_client()
    model_name = settings.GEMINI_MODEL or "gemini-2.5-flash"

    if client:
        try:
            if not is_student:
                # FACULTY / ADMIN GEMINI PROMPT (Intent Extraction & Structured JSON)
                prompt = f"""
You are the TRINETRA Campus Intelligence Assistant for Deen Dayal Upadhyaya Gorakhpur University (DDUGU).
Current Date: {today.isoformat()} (Tomorrow is {tomorrow.isoformat()}).
User Role: {current_user.role.value.upper()} ({current_user.full_name}, Dept: {current_user.department or 'Engineering'}).
Available Campus Rooms: IET17, IET18, IET19, IET20, IET22, IET24, IET25, IET32, IET-LIB, and Deeksha Bhawan LH01 to LH14.

User Query: "{user_query}"

Determine if the user wants to book, reserve, or allocate a classroom/lab.
Return a STRICT JSON object in this exact schema:
{{
  "is_booking_request": boolean,
  "room_code": string or null,
  "date_iso": "YYYY-MM-DD" or null,
  "start_time": "HH:MM" (24-hour) or null,
  "duration_hours": float (e.g. 1.0, 1.5, 2.0) or null,
  "expected_students": integer or null,
  "purpose": "extra_lecture" | "minor_exam" | "practical" | "event" | "seminar" | "other",
  "purpose_detail": string or null,
  "conversational_reply": string
}}
"""
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "temperature": 0.2
                    }
                )
                parsed = json.loads(resp.text)
                
                # If Gemini extracted booking intent, verify against live database and auto-fill!
                if parsed.get("is_booking_request"):
                    target_room_code = (parsed.get("room_code") or "").upper().strip()
                    target_date_str = parsed.get("date_iso")
                    target_time_str = parsed.get("start_time") or "10:00"
                    duration_hrs = float(parsed.get("duration_hours") or 1.5)
                    students = int(parsed.get("expected_students") or 60)
                    purpose_str = parsed.get("purpose") or "extra_lecture"
                    detail_str = parsed.get("purpose_detail") or user_query

                    # Parse date
                    try:
                        b_date = date.fromisoformat(target_date_str) if target_date_str else tomorrow
                    except Exception:
                        b_date = tomorrow

                    # Parse start & end times
                    st_time = parse_time_str(target_time_str)
                    end_mins = time_to_minutes(st_time) + int(duration_hrs * 60)
                    end_time = time(end_mins // 60 % 24, end_mins % 60)

                    # Look up room
                    room = None
                    if target_room_code:
                        room = db.query(Room).options(joinedload(Room.building), joinedload(Room.floor)).filter(Room.code == target_room_code).first()

                    # If room found, check availability
                    if room:
                        is_avail = is_room_available(db, room, b_date, st_time, end_time)
                        if is_avail:
                            st_12 = st_time.strftime("%I:%M %p")
                            end_12 = end_time.strftime("%I:%M %p")
                            return {
                                "reply": (
                                    f"🎯 **Room Vacancy Confirmed!**\n\n"
                                    f"**{room.code}** ({room.building.name if room.building else 'Campus'}) is **100% available** for "
                                    f"{students} students on **{b_date.strftime('%d %b %Y')}** from **{st_12}** to **{end_12}**.\n\n"
                                    f"I have prepared the booking form below. Click **Confirm Reservation** or edit any field."
                                ),
                                "action": "autofill_booking",
                                "booking_intent": {
                                    "room_id": room.id,
                                    "room_code": room.code,
                                    "building_name": room.building.name if room.building else "IET",
                                    "floor_name": room.floor.name if room.floor else "Ground Floor",
                                    "capacity": room.capacity,
                                    "date": str(b_date),
                                    "start_time": st_time.strftime("%H:%M"),
                                    "start_time_12": st_12,
                                    "end_time": end_time.strftime("%H:%M"),
                                    "end_time_12": end_12,
                                    "duration_hours": duration_hrs,
                                    "expected_students": students,
                                    "purpose": purpose_str,
                                    "purpose_detail": detail_str
                                }
                            }
                        else:
                            # Conflict! Suggest ranked alternatives
                            alts = find_alternatives(db, b_date, st_time, end_time, students, room.building_id, room.room_type, limit=4)
                            alt_lines = []
                            for i, a in enumerate(alts):
                                b_title = "Deeksha Bhawan" if a.get("building_id") == 2 else "IET"
                                badge = " ⭐ (Best Match)" if i == 0 else ""
                                alt_lines.append(f"• **{a['code']}** ({b_title}) — Capacity: **{a['capacity']} seats** • Type: *{a.get('room_type', 'Classroom').capitalize()}*{badge}")
                            
                            return {
                                "reply": (
                                    f"⚠️ **Schedule Collision Alert on {room.code}**\n\n"
                                    f"Room **{room.code}** is already occupied on {b_date.strftime('%d %b %Y')} during "
                                    f"{st_time.strftime('%I:%M %p')}–{end_time.strftime('%I:%M %p')}.\n\n"
                                    f"🎯 **Best Available Alternatives for {students} Students:**\n" +
                                    "\n".join(alt_lines) +
                                    "\n\n*Select any alternative in 'Find a Room' to lock it instantly.*"
                                ),
                                "action": "conflict_alternatives",
                                "alternatives": alts
                            }
                else:
                    if parsed.get("conversational_reply"):
                        return {
                            "reply": parsed["conversational_reply"],
                            "action": "info"
                        }
            else:
                # STUDENT GEMINI PROMPT (Restricted Academic Guidance)
                student_context = f"Student: {current_user.full_name}, Branch: {current_user.branch or 'AI_ML'}, Year: {current_user.academic_year or 3}."
                prompt = f"""
You are the TRINETRA Academic Assistant for DDUGU Students.
{student_context}
Date: {today.isoformat()}
Rules: Answer student questions about lectures, timetable, minor exams, announcements, and building directions.
Refuse room booking, room holding, or administrative tools politely.

User Question: "{user_query}"
"""
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={"temperature": 0.3}
                )
                if resp.text:
                    return {
                        "reply": resp.text.strip(),
                        "action": "student_info"
                    }
        except Exception as e:
            print(f"[TRINETRA AI] Gemini execution exception (falling back to database heuristics): {e}")

    # ========================================================
    # 3. HIGH-ACCURACY DETERMINISTIC FALLBACK (Offline / Resilient)
    # ========================================================
    # Notifications / Circulars
    if any(w in q_lower for w in ["notification", "notice", "announcement", "circular", "update"]):
        anns = db.query(Announcement).filter(Announcement.is_active == True).order_by(Announcement.created_at.desc()).limit(5).all()
        if anns:
            lines = [f"📢 **{a.title}** ({a.created_at.strftime('%d %b %Y') if a.created_at else 'Recent'})\n   {a.body}" for a in anns]
            return {
                "reply": "🔔 **Official Campus Notices & Broadcasts:**\n\n" + "\n\n".join(lines),
                "action": "notifications_view"
            }
        return {"reply": "No recent campus notifications have been posted.", "action": "info"}

    # Issue Reporting
    if any(w in q_lower for w in ["report", "discrepancy", "issue", "complaint", "broken"]):
        return {
            "reply": (
                "🚩 **Classroom Issue & Discrepancy Reporting**\n\n"
                "To report scheduling conflicts, uncleaned classrooms, or broken projectors:\n"
                "1. Click on the **Report Issue** tab in the sidebar.\n"
                "2. Choose the affected room (e.g. IET20 or LH01).\n"
                "3. Submit your report — it immediately alerts Campus Administration and Staff."
            ),
            "action": "report_view"
        }

    # Exam Queries (NSS Minor Exam)
    if any(w in q_lower for w in ["exam", "nss", "minor", "test"]):
        exams = db.query(ExamSchedule).options(joinedload(ExamSchedule.room)).order_by(ExamSchedule.exam_date).all()
        if exams:
            lines = []
            for ex in exams:
                room_code = ex.room.code if ex.room else f"Room #{ex.room_id}"
                st_12 = ex.start_time.strftime("%I:%M %p")
                et_12 = ex.end_time.strftime("%I:%M %p")
                lines.append(
                    f"📝 **{ex.subject_name}** ({ex.exam_type})\n"
                    f"   • Room: **{room_code}** ({ex.branch} Year {ex.academic_year})\n"
                    f"   • Date: {ex.exam_date.strftime('%d %b %Y')} from {st_12} to {et_12}\n"
                    f"   • Instructions: {ex.instructions or 'Report 15 minutes before session.'}"
                )
            return {
                "reply": "Here are the scheduled minor examinations:\n\n" + "\n\n".join(lines),
                "action": "exams_view"
            }
        return {"reply": "No minor examinations are currently scheduled.", "action": "info"}

    # Timetable / Schedule Queries
    if any(w in q_lower for w in ["timetable", "class", "lecture", "schedule", "my class"]):
        branch = current_user.branch or "AI_ML"
        year = current_user.academic_year or 3
        dow = today.weekday()
        
        classes = db.query(TimetableSchedule).options(joinedload(TimetableSchedule.room)).filter(
            TimetableSchedule.branch == branch,
            TimetableSchedule.academic_year == year
        ).order_by(TimetableSchedule.day_of_week, TimetableSchedule.start_time).all()
        
        if classes:
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            today_classes = [c for c in classes if c.day_of_week == dow]
            reply_lines = [f"📅 Academic Schedule for **{branch} Year {year}**:"]
            if today_classes:
                reply_lines.append(f"\n**Today's Lectures ({day_names[dow]}):**")
                for c in today_classes:
                    r_code = c.room.code if c.room else "TBD"
                    st_12 = c.start_time.strftime("%I:%M %p")
                    et_12 = c.end_time.strftime("%I:%M %p")
                    reply_lines.append(f"• **{c.subject}** in **{r_code}** ({st_12}–{et_12}) by {c.faculty_name}")
            else:
                reply_lines.append(f"\nNo regular lectures scheduled for today ({day_names[dow]}).")
            return {"reply": "\n".join(reply_lines), "action": "timetable_view"}
        return {"reply": f"No timetable found for branch {branch} Year {year}."}

    # Maintenance Status
    if "maintenance" in q_lower:
        m_rooms = db.query(Room).filter(Room.is_maintenance == True).all()
        if m_rooms:
            lines = [f"• **{r.code}** (Capacity {r.capacity}) — Under Maintenance" for r in m_rooms]
            return {"reply": "🔧 **Rooms Currently Under Maintenance:**\n\n" + "\n".join(lines)}
        return {"reply": "All campus rooms are currently in active service! None are under maintenance."}

    # Room Discovery & Alternative Recommendation for Faculty
    if any(w in q_lower for w in ["find", "available", "free", "room", "book", "recommend", "need"]):
        capacity = 60
        for word in user_query.split():
            if word.isdigit() and 10 <= int(word) <= 300:
                capacity = int(word)
                break
        
        target_date = tomorrow if "tomorrow" in q_lower else today
        start = parse_time_str(user_query)
        end_h = (start.hour + 1) if start.hour < 23 else 23
        end = time(end_h, 30)

        alts = find_alternatives(db, target_date, start, end, capacity, limit=5)
        if not alts:
            return {"reply": f"⚠️ No rooms with capacity >= {capacity} are vacant around {start.strftime('%I:%M %p')} on {target_date.strftime('%d %b %Y')}."}
        
        lines = []
        for i, a in enumerate(alts):
            b_name = "Deeksha Bhawan" if a.get("building_id") == 2 else "IET"
            badge = " ⭐ *(Best Match)*" if i == 0 else ""
            lines.append(f"{i+1}. **{a['code']}** ({b_name}) — Capacity: **{a['capacity']} seats**, Type: *{a['room_type'].capitalize()}*{badge}")
            
        return {
            "reply": f"🎯 **Top Recommended Rooms for ~{capacity} students on {target_date.strftime('%d %b %Y')} ({start.strftime('%I:%M %p')}–{end.strftime('%I:%M %p')}):**\n\n" + "\n".join(lines),
            "action": "room_recommendation"
        }

    return {
        "reply": (
            "🤖 **TRINETRA Campus Intelligence Assistant**\n\n"
            "I can assist with room discovery, schedule conflict verification, minor exam halls, and natural language bookings across IET and Deeksha Bhawan."
        )
    }
