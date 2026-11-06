import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from datetime import date, time, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal, Base, engine
from app.core.seed import seed_database
from app.models.models import Room, Booking, BookingStatus, User, UserRole

def run_tests():
    print("=" * 60)
    print("TRINETRA AUTOMATED TEST SUITE")
    print("=" * 60)
    
    # 1. Reset and Seed Database
    print("\n[Step 1] Initializing and Seeding Database...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    seed_database(db, force=True)
    db.close()
    print("✓ Database initialized with blueprint & student dataset.")

    client = TestClient(app)

    # 2. Test Health Endpoint
    print("\n[Step 2] Testing Health Endpoint...")
    res = client.get("/api/health")
    assert res.status_code == 200, f"Health check failed: {res.text}"
    print(f"✓ Health check OK: {res.json()}")

    # 3. Test Authentication for All 4 Roles
    print("\n[Step 3] Testing Authentication for Faculty, Student, Staff, Admin...")
    tokens = {}
    users_to_test = [
        ("faculty@ddugu.ac.in", "Trinetra123@", "faculty"),
        ("student@ddugu.ac.in", "Trinetra123@", "student"),
        ("staff@ddugu.ac.in", "Trinetra123@", "staff"),
        ("admin@ddugu.ac.in", "Trinetra123@", "admin"),
    ]
    for email, password, expected_role in users_to_test:
        res = client.post("/api/auth/login", data={"username": email, "password": password})
        assert res.status_code == 200, f"Login failed for {email}: {res.text}"
        data = res.json()
        assert "access_token" in data, "No token returned"
        assert data["user"]["role"] == expected_role, f"Role mismatch for {email}"
        tokens[expected_role] = data["access_token"]
        print(f"✓ Login successful: {email} ({expected_role})")

    fac_auth = {"Authorization": f"Bearer {tokens['faculty']}"}
    stu_auth = {"Authorization": f"Bearer {tokens['student']}"}
    adm_auth = {"Authorization": f"Bearer {tokens['admin']}"}

    # 4. Test Room Catalogue
    print("\n[Step 4] Testing Room Catalogue...")
    res = client.get("/api/rooms/", headers=fac_auth)
    assert res.status_code == 200
    rooms = res.json()
    print(f"✓ Retrieved {len(rooms)} total rooms across IET and Deeksha Bhawan.")
    assert len(rooms) >= 25, "Expected full campus catalogue of rooms"

    # Test Building Filter
    res_db = client.get("/api/rooms/?building=DB", headers=fac_auth)
    db_rooms = res_db.json()
    print(f"✓ Deeksha Bhawan Lecture Halls found: {len(db_rooms)} (LH01–LH14)")
    assert len(db_rooms) >= 12, "Deeksha Bhawan rooms missing"

    # 5. Test Room Booking & Conflict Engine
    print("\n[Step 5] Testing Automated Booking & Conflict Resolution...")
    room_iet20 = next(r for r in rooms if r["code"] == "IET20")
    test_date = str(date.today() + timedelta(days=5))

    # Faculty 1 books IET20
    booking_payload = {
        "room_id": room_iet20["id"],
        "date": test_date,
        "start_time": "15:00",
        "duration_hours": 1.5,
        "purpose": "extra_lecture",
        "purpose_detail": "Automated Test Session",
        "expected_students": 70
    }
    res_b1 = client.post("/api/bookings/", json=booking_payload, headers=fac_auth)
    assert res_b1.status_code == 201, f"Booking 1 failed: {res_b1.text}"
    b1_data = res_b1.json()
    print(f"✓ Booking 1 Confirmed: Room {b1_data['room_code']} on {b1_data['date']} at {b1_data['start_time']}")

    # Simultaneous/Overlapping Booking by Faculty 2 for same slot
    print("\n[Step 6] Testing Overlapping Conflict Detection (HTTP 409 & Alternatives)...")
    res_b2 = client.post("/api/bookings/", json=booking_payload, headers=fac_auth)
    assert res_b2.status_code == 409, f"Expected 409 Conflict, got {res_b2.status_code}: {res_b2.text}"
    conflict_data = res_b2.json()
    print(f"✓ Conflict correctly triggered (HTTP 409): {conflict_data['detail']['message']}")
    alts = conflict_data['detail'].get('alternatives', [])
    print(f"✓ System generated {len(alts)} ranked alternative rooms:")
    for alt in alts[:3]:
        print(f"   • Room {alt['code']} (Capacity: {alt['capacity']}, Score: {alt['score']})")
    assert len(alts) > 0, "No alternatives returned for conflict"

    # 7. Cancel Booking
    print("\n[Step 7] Testing Booking Cancellation...")
    res_cancel = client.post(f"/api/bookings/{b1_data['id']}/cancel?reason=TestComplete", headers=fac_auth)
    assert res_cancel.status_code == 200, f"Cancel failed: {res_cancel.text}"
    print(f"✓ Booking ID {b1_data['id']} cancelled successfully.")

    # 8. Test Admin Maintenance Toggle
    print("\n[Step 8] Testing Admin Maintenance Control...")
    room_iet18 = next(r for r in rooms if r["code"] == "IET18")
    res_maint = client.patch(f"/api/admin/rooms/{room_iet18['id']}/maintenance", headers=adm_auth)
    assert res_maint.status_code == 200
    print(f"✓ Room {room_iet18['code']} maintenance mode toggled: {res_maint.json()}")

    # 9. Test Student Access & Issue Reporting (NSS Exam dispute workflow)
    print("\n[Step 9] Testing Student Reporting & Timetable Protection...")
    # Student attempts unauthorized booking
    res_stu_book = client.post("/api/bookings/", json=booking_payload, headers=stu_auth)
    assert res_stu_book.status_code == 403, f"Student should be forbidden from booking: {res_stu_book.status_code}"
    print("✓ Student booking correctly forbidden with HTTP 403.")

    # Student reports schedule discrepancy
    issue_payload = {
        "room_code": "LH01",
        "issue_type": "Schedule Clarification",
        "description": "Confirming seat allocation for NSS Minor Exam tomorrow morning."
    }
    res_issue = client.post("/api/admin/issues", json=issue_payload, headers=stu_auth)
    assert res_issue.status_code == 200, f"Issue reporting failed: {res_issue.text}"
    print(f"✓ Student successfully filed issue report (ID: {res_issue.json()['id']})")

    # 10. Test Exam Schedules (Verifying NSS Exam data)
    print("\n[Step 10] Testing Scheduled Examinations Endpoint...")
    res_exams = client.get("/api/schedules/exams", headers=stu_auth)
    assert res_exams.status_code == 200
    exams_list = res_exams.json()
    print(f"✓ Scheduled exams found: {len(exams_list)}")
    nss_exam = next((e for e in exams_list if "NSS" in e["subject_name"]), None)
    assert nss_exam is not None, "NSS exam record not found"
    print(f"✓ NSS Minor Exam verified: Room {nss_exam['room_code']} on {nss_exam['exam_date']} ({nss_exam['start_time']}–{nss_exam['end_time']})")

    # 11. Test AI Campus Assistant
    print("\n[Step 11] Testing AI Campus Assistant...")
    ai_queries = [
        "Find a room for 75 students tomorrow at 11 AM",
        "When is the NSS minor exam scheduled?",
        "Which computer labs are free today?",
        "Are any rooms under maintenance?"
    ]
    for q in ai_queries:
        res_ai = client.post("/api/ai/ask", json={"query": q}, headers=fac_auth)
        assert res_ai.status_code == 200
        reply = res_ai.json()["reply"]
        first_line = reply.splitlines()[0] if reply else ""
        print(f"✓ Query: \"{q}\" -> {first_line[:75]}...")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY! TRINETRA ENGINE FULLY VERIFIED.")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
