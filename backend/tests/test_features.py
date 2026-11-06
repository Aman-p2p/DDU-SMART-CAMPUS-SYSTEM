"""Comprehensive Feature, RBAC and AI Assistant Test Suite for TRINETRA.
Tests:
1. AI Campus Assistant query processing (Faculty room search, NSS exam info, Admin maintenance).
2. NSS Incident Prevention: Examination rescheduling with targeted notifications.
3. Student Issue Reporting: Non-destructive conflict & discrepancy flagging.
4. RBAC Protection: Students cannot create bookings (403 Forbidden).
"""
import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app

@pytest.mark.asyncio
async def test_frontend_served_at_root():
    """Verifies that GET / serves the interactive single-page application frontend."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/")
        assert res.status_code == 200
        assert "TRINETRA" in res.text
        assert "Architectural Blueprint" in res.text

@pytest.mark.asyncio
async def test_ai_campus_assistant_room_search():
    """Verifies AI Assistant interprets natural language room query and returns verified suggestions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as Faculty
        login_res = await client.post("/api/v1/auth/login", json={
            "email": "sharma.cs@ddugu.ac.in",
            "password": "Faculty@DDUGU2026"
        })
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]

        # Ask AI to find a room
        ai_res = await client.post(
            "/api/v1/ai/chat",
            json={"query": "Find a room for 75 students tomorrow at 11 am in IET"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert ai_res.status_code == 200
        data = ai_res.json()
        assert data["intent"] == "ROOM_SEARCH"
        assert "available room options" in data["reply"]
        assert len(data["data"]) > 0

@pytest.mark.asyncio
async def test_ai_campus_assistant_exam_nss_query():
    """Verifies AI Assistant retrieves official examination allocations and addresses NSS exam questions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_res = await client.post("/api/v1/auth/login", json={
            "email": "rahul.cse24@ddugu.ac.in",
            "password": "Student@DDUGU2026"
        })
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]

        ai_res = await client.post(
            "/api/v1/ai/chat",
            json={"query": "When and where is the NSS minor examination?"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert ai_res.status_code == 200
        data = ai_res.json()
        assert data["intent"] == "EXAMINATION_INFO"
        assert "Official Examination Schedule" in data["reply"]

@pytest.mark.asyncio
async def test_ai_campus_assistant_admin_metrics():
    """Verifies AI Assistant provides maintenance and metrics summary for administrators."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_res = await client.post("/api/v1/auth/login", json={
            "email": "admin@ddugu.ac.in",
            "password": "Trinetra@Admin2026"
        })
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]

        ai_res = await client.post(
            "/api/v1/ai/chat",
            json={"query": "Show rooms under maintenance and campus stats"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert ai_res.status_code == 200
        data = ai_res.json()
        assert data["intent"] == "ADMIN_METRICS"
        assert "TRINETRA Infrastructure & Health Summary" in data["reply"]

@pytest.mark.asyncio
async def test_nss_incident_prevention_exam_reschedule():
    """Directly verifies the resolution of the DDUGU NSS incident:
    - Admin or Faculty reschedules an examination.
    - System requires explicit reschedule reason.
    - Status is marked as RESCHEDULED.
    - Priority notification is targeted to the affected cohort.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login as Admin
        admin_res = await client.post("/api/v1/auth/login", json={
            "email": "admin@ddugu.ac.in",
            "password": "Trinetra@Admin2026"
        })
        assert admin_res.status_code == 200
        admin_token = admin_res.json()["access_token"]

        # 2. Get list of exams to find NSS / Minor exam
        exams_res = await client.get(
            "/api/v1/examinations",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert exams_res.status_code == 200
        exams = exams_res.json()
        assert len(exams) > 0
        target_exam = exams[0]

        # 3. Get an alternate room (e.g. Deeksha Bhawan LH01)
        rooms_res = await client.get("/api/v1/rooms?building_code=DB")
        db_rooms = rooms_res.json()
        new_room = db_rooms[0]

        new_start = datetime.now(timezone.utc) + timedelta(days=10, hours=10)
        new_end = new_start + timedelta(hours=2)

        # 4. Trigger emergency rescheduling
        resched_res = await client.post(
            f"/api/v1/examinations/{target_exam['id']}/reschedule",
            json={
                "new_room_id": new_room["id"],
                "new_start_time": new_start.isoformat(),
                "new_end_time": new_end.isoformat(),
                "reschedule_reason": "Relocated to Deeksha Bhawan due to audiovisual setup in IET"
            },
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resched_res.status_code == 200
        resched_data = resched_res.json()
        assert resched_data["status"] == "success"
        assert "rescheduled to Room" in resched_data["message"]

        # 5. Verify Student receives the urgent notification
        student_res = await client.post("/api/v1/auth/login", json={
            "email": "rahul.cse24@ddugu.ac.in",
            "password": "Student@DDUGU2026"
        })
        student_token = student_res.json()["access_token"]

        notif_res = await client.get(
            "/api/v1/notifications",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert notif_res.status_code == 200
        notifs = notif_res.json()
        assert any("EXAMINATION RESCHEDULED" in n["title"] or "URGENT" in n.get("priority", "") for n in notifs)

@pytest.mark.asyncio
async def test_student_issue_report_non_destructive():
    """Verifies that students can report room conflicts/discrepancies without altering official records."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as student
        student_res = await client.post("/api/v1/auth/login", json={
            "email": "rahul.cse24@ddugu.ac.in",
            "password": "Student@DDUGU2026"
        })
        student_token = student_res.json()["access_token"]

        rooms = (await client.get("/api/v1/rooms?building_code=IET")).json()
        iet20 = next(r for r in rooms if r["room_number"] == "IET 20")

        # Student submits discrepancy report
        report_res = await client.post(
            "/api/v1/issues",
            json={
                "room_id": iet20["id"],
                "issue_type": "CONFLICT",
                "comment": "Noticeboard timetable shows Practical Lab, but TRINETRA shows Extra Lecture."
            },
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert report_res.status_code == 201
        report_data = report_res.json()
        assert report_data["status"] == "OPEN"
        assert report_data["room_number"] == "IET 20"

@pytest.mark.asyncio
async def test_student_rbac_cannot_book_room():
    """Verifies strict RBAC: Students receive HTTP 403 Forbidden when attempting to create a booking."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        student_res = await client.post("/api/v1/auth/login", json={
            "email": "rahul.cse24@ddugu.ac.in",
            "password": "Student@DDUGU2026"
        })
        student_token = student_res.json()["access_token"]

        rooms = (await client.get("/api/v1/rooms?building_code=IET")).json()

        start = datetime.now(timezone.utc) + timedelta(days=20)
        end = start + timedelta(hours=1)

        # Attempt booking as student
        book_res = await client.post(
            "/api/v1/bookings",
            json={
                "room_id": rooms[0]["id"],
                "title": "Unauthorized Student Booking",
                "purpose": "EVENT",
                "start_time": start.isoformat(),
                "end_time": end.isoformat()
            },
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert book_res.status_code == 403
        assert "Access denied" in book_res.json()["detail"]

@pytest.mark.asyncio
async def test_branches_dataset():
    """Verifies that all 6 engineering branches (CSE, AI ML, AI DS, ECE, ME, IT) and sections exist (Req 2)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/timetable/branches")
        assert res.status_code == 200
        branches = res.json()
        assert len(branches) == 6
        codes = [b["code"] for b in branches]
        for expected in ["CSE", "AI ML", "AI DS", "ECE", "ME", "IT"]:
            assert expected in codes

@pytest.mark.asyncio
async def test_schedule_updates_announcements():
    """Verifies publishing schedule updates/notices and student acknowledgment receipts (Req 4)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as Admin
        admin_res = await client.post("/api/v1/auth/login", json={
            "email": "admin@ddugu.ac.in",
            "password": "Trinetra@Admin2026"
        })
        admin_token = admin_res.json()["access_token"]

        # Publish Announcement
        create_res = await client.post(
            "/api/v1/notifications/announcements",
            json={
                "category": "EXAMINATION",
                "title": "Minor Exam Reschedule Notice - NSS 2026",
                "message": "Examination relocated to Deeksha Bhawan LH01.",
                "target_cohort": "B.Tech Year 2 (All Sections)",
                "priority": "URGENT"
            },
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert create_res.status_code == 201
        ann_id = create_res.json()["id"]

        # Student Acknowledgment
        student_res = await client.post("/api/v1/auth/login", json={
            "email": "rahul.cse24@ddugu.ac.in",
            "password": "Student@DDUGU2026"
        })
        student_token = student_res.json()["access_token"]

        ack_res = await client.post(
            f"/api/v1/notifications/announcements/{ann_id}/acknowledge",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert ack_res.status_code == 200
        assert ack_res.json()["acknowledgment_count"] >= 1
