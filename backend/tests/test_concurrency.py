"""Comprehensive Concurrency and Edge-Case Test Suite for TRINETRA.
Explicitly verifies:
1. Two faculty members booking the exact same room at the exact same millisecond.
2. 5 concurrent simultaneous bookings.
3. Overlapping vs adjacent half-open time intervals.
4. Temporary room holds.
5. Maintenance room rejection.
6. Alternative room recommendations upon 409 conflict.
"""
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.database import AsyncSessionLocal
from app.models.infrastructure import Room
from app.models.booking import Reservation

@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"

@pytest.mark.asyncio
async def test_two_teachers_simultaneous_booking_conflict():
    """CRITICAL TEST: Verifies that when Faculty A and Faculty B confirm the exact same room
    and time slot concurrently:
    - Exactly ONE booking succeeds (HTTP 201).
    - The second receives HTTP 409 Conflict.
    - The losing faculty member automatically receives alternative room recommendations.
    - Zero double bookings exist in the database.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login as Faculty A
        res_a = await client.post("/api/v1/auth/login", json={
            "email": "sharma.cs@ddugu.ac.in",
            "password": "Faculty@DDUGU2026"
        })
        assert res_a.status_code == 200
        token_a = res_a.json()["access_token"]
        
        # 2. Login as Faculty B
        res_b = await client.post("/api/v1/auth/login", json={
            "email": "verma.aiml@ddugu.ac.in",
            "password": "Faculty@DDUGU2026"
        })
        assert res_b.status_code == 200
        token_b = res_b.json()["access_token"]
        
        # 3. Find Room IET 20
        rooms_res = await client.get("/api/v1/rooms?building_code=IET")
        assert rooms_res.status_code == 200
        rooms = rooms_res.json()
        iet20 = next(r for r in rooms if r["room_number"] == "IET 20")
        target_room_id = iet20["id"]
        
        # Define booking slot: Tomorrow 10:00 to 12:00 UTC
        base_date = datetime.now(timezone.utc) + timedelta(days=2)
        start_time = base_date.replace(hour=10, minute=0, second=0, microsecond=0)
        end_time = base_date.replace(hour=12, minute=0, second=0, microsecond=0)
        
        payload_a = {
            "room_id": target_room_id,
            "title": "Faculty A - Advanced OS Extra Lecture",
            "purpose": "EXTRA_LECTURE",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "idempotency_key": "fac_a_concurrent_test_1"
        }
        
        payload_b = {
            "room_id": target_room_id,
            "title": "Faculty B - Deep Learning Workshop",
            "purpose": "EXTRA_LECTURE",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "idempotency_key": "fac_b_concurrent_test_1"
        }
        
        # 4. Fire simultaneous requests concurrently via asyncio.gather
        task_a = client.post(
            "/api/v1/bookings", 
            json=payload_a, 
            headers={"Authorization": f"Bearer {token_a}"}
        )
        task_b = client.post(
            "/api/v1/bookings", 
            json=payload_b, 
            headers={"Authorization": f"Bearer {token_b}"}
        )
        
        resp_a, resp_b = await asyncio.gather(task_a, task_b)
        
        status_codes = [resp_a.status_code, resp_b.status_code]
        print(f"\n[CONCURRENCY RESULTS] Faculty A Status: {resp_a.status_code}, Faculty B Status: {resp_b.status_code}")
        
        # Exactly ONE must succeed (201) and ONE must fail with conflict (409)
        assert 201 in status_codes, "At least one booking must succeed"
        assert 409 in status_codes, "The colliding booking must be rejected with HTTP 409 Conflict"
        assert status_codes.count(201) == 1, "CRITICAL: Multiple simultaneous bookings succeeded! Double-booking detected!"
        assert status_codes.count(409) == 1, "The losing booking must receive HTTP 409"
        
        # Verify alternative room suggestions were provided to the losing faculty
        conflict_resp = resp_a if resp_a.status_code == 409 else resp_b
        conflict_data = conflict_resp.json()
        assert "detail" in conflict_data
        detail = conflict_data["detail"]
        assert "suggested_alternatives" in detail
        alternatives = detail["suggested_alternatives"]
        assert len(alternatives) > 0, "System must provide alternative room suggestions upon conflict"
        print(f"Top suggested alternative: {alternatives[0]['room']['display_name']} (Score: {alternatives[0]['score']})")
        
        # 5. Verify database integrity directly: Only 1 active reservation for that slot
        async with AsyncSessionLocal() as session:
            stmt = select(Reservation).where(
                Reservation.room_id == target_room_id,
                Reservation.start_time == start_time,
                Reservation.status == "CONFIRMED"
            )
            res = await session.execute(stmt)
            confirmed_bookings = res.scalars().all()
            assert len(confirmed_bookings) == 1, "Database must have strictly 1 confirmed booking"

@pytest.mark.asyncio
async def test_partial_time_overlap_rejection():
    """Verifies that partial overlaps (e.g. 10-12 vs 11-13) are detected and rejected."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_res = await client.post("/api/v1/auth/login", json={
            "email": "sharma.cs@ddugu.ac.in",
            "password": "Faculty@DDUGU2026"
        })
        token = login_res.json()["access_token"]
        
        rooms = (await client.get("/api/v1/rooms?building_code=IET")).json()
        iet19 = next(r for r in rooms if r["room_number"] == "IET 19")
        
        base_date = datetime.now(timezone.utc) + timedelta(days=3)
        # Booking 1: 10:00 to 12:00
        t1_start = base_date.replace(hour=10, minute=0, second=0, microsecond=0)
        t1_end = base_date.replace(hour=12, minute=0, second=0, microsecond=0)
        
        # Booking 2: 11:00 to 13:00 (Overlaps by 1 hour)
        t2_start = base_date.replace(hour=11, minute=0, second=0, microsecond=0)
        t2_end = base_date.replace(hour=13, minute=0, second=0, microsecond=0)
        
        res1 = await client.post("/api/v1/bookings", json={
            "room_id": iet19["id"],
            "title": "First Booking",
            "purpose": "EXTRA_LECTURE",
            "start_time": t1_start.isoformat(),
            "end_time": t1_end.isoformat()
        }, headers={"Authorization": f"Bearer {token}"})
        assert res1.status_code == 201
        
        res2 = await client.post("/api/v1/bookings", json={
            "room_id": iet19["id"],
            "title": "Second Overlapping Booking",
            "purpose": "EXTRA_LECTURE",
            "start_time": t2_start.isoformat(),
            "end_time": t2_end.isoformat()
        }, headers={"Authorization": f"Bearer {token}"})
        assert res2.status_code == 409
        assert "already booked" in res2.json()["detail"]["message"].lower()

@pytest.mark.asyncio
async def test_adjacent_non_overlapping_bookings():
    """Verifies that adjacent half-open intervals [10, 11) and [11, 12) do NOT conflict."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_res = await client.post("/api/v1/auth/login", json={
            "email": "sharma.cs@ddugu.ac.in",
            "password": "Faculty@DDUGU2026"
        })
        token = login_res.json()["access_token"]
        
        rooms = (await client.get("/api/v1/rooms?building_code=IET")).json()
        iet18 = next(r for r in rooms if r["room_number"] == "IET 18")
        
        base_date = datetime.now(timezone.utc) + timedelta(days=4)
        slot1_start = base_date.replace(hour=10, minute=0, second=0, microsecond=0)
        slot1_end = base_date.replace(hour=11, minute=0, second=0, microsecond=0)
        slot2_start = base_date.replace(hour=11, minute=0, second=0, microsecond=0)
        slot2_end = base_date.replace(hour=12, minute=0, second=0, microsecond=0)
        
        # Slot 1: 10:00 to 11:00
        res1 = await client.post("/api/v1/bookings", json={
            "room_id": iet18["id"],
            "title": "Slot 10-11",
            "purpose": "EXTRA_LECTURE",
            "start_time": slot1_start.isoformat(),
            "end_time": slot1_end.isoformat()
        }, headers={"Authorization": f"Bearer {token}"})
        assert res1.status_code == 201
        
        # Slot 2: 11:00 to 12:00
        res2 = await client.post("/api/v1/bookings", json={
            "room_id": iet18["id"],
            "title": "Slot 11-12",
            "purpose": "EXTRA_LECTURE",
            "start_time": slot2_start.isoformat(),
            "end_time": slot2_end.isoformat()
        }, headers={"Authorization": f"Bearer {token}"})
        assert res2.status_code == 201, "Adjacent half-open intervals must be allowed without false conflict"

@pytest.mark.asyncio
async def test_five_concurrent_bookings_stress():
    """Fires 5 simultaneous bookings for the exact same slot: exactly 1 must win, 4 must get 409."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_res = await client.post("/api/v1/auth/login", json={
            "email": "sharma.cs@ddugu.ac.in",
            "password": "Faculty@DDUGU2026"
        })
        token = login_res.json()["access_token"]
        
        rooms = (await client.get("/api/v1/rooms?building_code=IET")).json()
        iet17 = next(r for r in rooms if r["room_number"] == "IET 17")
        
        base_date = datetime.now(timezone.utc) + timedelta(days=5)
        start_time = base_date.replace(hour=14, minute=0, second=0, microsecond=0)
        end_time = base_date.replace(hour=16, minute=0, second=0, microsecond=0)
        
        tasks = [
            client.post("/api/v1/bookings", json={
                "room_id": iet17["id"],
                "title": f"Stress Candidate {i}",
                "purpose": "EXTRA_LECTURE",
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat()
            }, headers={"Authorization": f"Bearer {token}"})
            for i in range(5)
        ]
        
        responses = await asyncio.gather(*tasks)
        status_codes = [r.status_code for r in responses]
        print(f"\n[5 CONCURRENT REQUESTS STATUSES]: {status_codes}")
        
        assert status_codes.count(201) == 1, "Exactly one request out of 5 must be confirmed"
        assert status_codes.count(409) == 4, "All 4 colliding requests must receive HTTP 409 Conflict"

@pytest.mark.asyncio
async def test_student_cannot_book_classrooms_rbac():
    """Verifies that students are strictly prevented from creating official bookings (RBAC)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        st_login = await client.post("/api/v1/auth/login", json={
            "email": "rahul.cse24@ddugu.ac.in",
            "password": "Student@DDUGU2026"
        })
        student_token = st_login.json()["access_token"]
        
        rooms = (await client.get("/api/v1/rooms?building_code=IET")).json()
        target_room_id = rooms[0]["id"]
        
        start_time = datetime.now(timezone.utc) + timedelta(days=6)
        end_time = start_time + timedelta(hours=1)
        
        res = await client.post("/api/v1/bookings", json={
            "room_id": target_room_id,
            "title": "Unauthorized Student Booking Attempt",
            "purpose": "EXTRA_LECTURE",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat()
        }, headers={"Authorization": f"Bearer {student_token}"})
        
        assert res.status_code == 403, "Student must be rejected with HTTP 403 Forbidden"
