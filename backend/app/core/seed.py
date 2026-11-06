from datetime import date, time, timedelta, datetime
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from ..models.models import (
    User, UserRole, Building, Floor, Room, RoomType,
    Booking, BookingStatus, BookingPurpose,
    Announcement, TimetableSchedule, ExamSchedule, AuditLog
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def safe_hash(password: str) -> str:
    return pwd_context.hash(password[:72])

def seed_database(db: Session, force: bool = False):
    """Seed comprehensive campus data matching blueprints and official requirements."""
    # Check if already seeded
    user_count = db.query(User).count()
    if user_count > 0 and not force:
        return

    print("[+] Seeding TRINETRA database with official campus infrastructure...")

    # 1. BUILDINGS
    iet = Building(
        code="IET",
        name="Institute of Engineering and Technology",
        description="Main engineering campus building housing classrooms, specialized labs, seminar hall, and administrative offices.",
        distance_meters=0
    )
    db_b = Building(
        code="DB",
        name="Deeksha Bhawan",
        description="Academic and examination complex located approximately 100 metres from IET with 14 lecture halls.",
        distance_meters=100
    )
    db.add_all([iet, db_b])
    db.commit()

    # 2. FLOORS
    f_iet_g = Floor(building_id=iet.id, name="Ground Floor", level=0)
    f_iet_1 = Floor(building_id=iet.id, name="First Floor", level=1)
    f_iet_2 = Floor(building_id=iet.id, name="Second Floor", level=2)

    f_db_g = Floor(building_id=db_b.id, name="Ground Floor", level=0)
    f_db_1 = Floor(building_id=db_b.id, name="First Floor", level=1)
    db.add_all([f_iet_g, f_iet_1, f_iet_2, f_db_g, f_db_1])
    db.commit()

    # 3. ROOMS (Matching official blueprint exactly)
    rooms = [
        # --- IET GROUND FLOOR ---
        Room(code="IET-LIB", building_id=iet.id, floor_id=f_iet_g.id, capacity=180, room_type=RoomType.LIBRARY,
             facilities="Air Conditioned, High Capacity Seating, Exam Capable", notes="Used for study and minor/major examinations"),
        Room(code="IET-DIR", building_id=iet.id, floor_id=f_iet_g.id, capacity=15, room_type=RoomType.OFFICE,
             facilities="Executive Conference Setup", notes="Director's Office"),
        Room(code="IET-ADMIN", building_id=iet.id, floor_id=f_iet_g.id, capacity=25, room_type=RoomType.OFFICE,
             facilities="Administrative Terminals", notes="Administrative Office"),
        Room(code="IET-TCH", building_id=iet.id, floor_id=f_iet_g.id, capacity=35, room_type=RoomType.OFFICE,
             facilities="Faculty Desks, Discussion Cubicles", notes="Teachers' Office / Faculty Cabins"),
        Room(code="IET-PLACE", building_id=iet.id, floor_id=f_iet_g.id, capacity=30, room_type=RoomType.OFFICE,
             facilities="Interview Rooms, Presentation Display", notes="Placement Cell"),

        # --- IET FIRST FLOOR (4 Labs + 4 Classrooms) ---
        Room(code="IET20", building_id=iet.id, floor_id=f_iet_1.id, capacity=75, room_type=RoomType.CLASSROOM,
             facilities="Projector, PA System, Smart Board"),
        Room(code="IET18", building_id=iet.id, floor_id=f_iet_1.id, capacity=75, room_type=RoomType.CLASSROOM,
             facilities="Projector, Whiteboard"),
        Room(code="IET19", building_id=iet.id, floor_id=f_iet_1.id, capacity=75, room_type=RoomType.CLASSROOM,
             facilities="Projector, Whiteboard"),
        Room(code="IET17", building_id=iet.id, floor_id=f_iet_1.id, capacity=75, room_type=RoomType.CLASSROOM,
             facilities="Projector, Whiteboard", is_maintenance=True, notes="Audio-visual projector upgrade in progress"),
        Room(code="IET22", building_id=iet.id, floor_id=f_iet_1.id, capacity=45, room_type=RoomType.LAB,
             facilities="45 High-Spec Workstations, Gigabit LAN, GPU Access", notes="CSE Department Laboratory"),
        Room(code="IET16", building_id=iet.id, floor_id=f_iet_1.id, capacity=40, room_type=RoomType.LAB,
             facilities="CAD/CAM Systems, Simulation Workstations", notes="Mechanical Engineering Laboratory"),
        Room(code="IET14", building_id=iet.id, floor_id=f_iet_1.id, capacity=40, room_type=RoomType.LAB,
             facilities="Digital Oscilloscopes, Microcontroller Kits", notes="ECE Department Laboratory"),
        Room(code="IET15", building_id=iet.id, floor_id=f_iet_1.id, capacity=45, room_type=RoomType.LAB,
             facilities="Cloud Terminals, Network Simulator Workbench", notes="IT Department Laboratory"),

        # --- IET SECOND FLOOR (Seminar Hall + 6 Classrooms) ---
        Room(code="IET32", building_id=iet.id, floor_id=f_iet_2.id, capacity=200, room_type=RoomType.SEMINAR,
             facilities="Surround Audio, Dual Laser Projectors, Motorized Screen, Podiums", notes="IET Seminar Hall (Approx 200 Students)"),
        Room(code="IET24", building_id=iet.id, floor_id=f_iet_2.id, capacity=75, room_type=RoomType.CLASSROOM,
             facilities="Projector, Whiteboard"),
        Room(code="IET25", building_id=iet.id, floor_id=f_iet_2.id, capacity=75, room_type=RoomType.CLASSROOM,
             facilities="Projector, Whiteboard"),
        Room(code="IET28", building_id=iet.id, floor_id=f_iet_2.id, capacity=75, room_type=RoomType.CLASSROOM,
             facilities="Projector, Whiteboard"),
        Room(code="IET29", building_id=iet.id, floor_id=f_iet_2.id, capacity=75, room_type=RoomType.CLASSROOM,
             facilities="Projector, Whiteboard"),
        Room(code="IET30", building_id=iet.id, floor_id=f_iet_2.id, capacity=75, room_type=RoomType.CLASSROOM,
             facilities="Projector, Whiteboard"),
        Room(code="IET23", building_id=iet.id, floor_id=f_iet_2.id, capacity=75, room_type=RoomType.CLASSROOM,
             facilities="Projector, Whiteboard", notes="Corner Classroom verified from blueprint"),

        # --- DEEKSHA BHAWAN GROUND FLOOR (LH01–LH07) ---
        Room(code="LH01", building_id=db_b.id, floor_id=f_db_g.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Mic/PA, Whiteboard"),
        Room(code="LH02", building_id=db_b.id, floor_id=f_db_g.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Mic/PA, Whiteboard"),
        Room(code="LH03", building_id=db_b.id, floor_id=f_db_g.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Whiteboard"),
        Room(code="LH04", building_id=db_b.id, floor_id=f_db_g.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Whiteboard"),
        Room(code="LH05", building_id=db_b.id, floor_id=f_db_g.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Whiteboard"),
        Room(code="LH06", building_id=db_b.id, floor_id=f_db_g.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Whiteboard"),
        Room(code="LH07", building_id=db_b.id, floor_id=f_db_g.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Whiteboard"),

        # --- DEEKSHA BHAWAN FIRST FLOOR (LH08–LH14) ---
        Room(code="LH08", building_id=db_b.id, floor_id=f_db_1.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Mic/PA, Whiteboard"),
        Room(code="LH09", building_id=db_b.id, floor_id=f_db_1.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Mic/PA, Whiteboard"),
        Room(code="LH10", building_id=db_b.id, floor_id=f_db_1.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Whiteboard"),
        Room(code="LH11", building_id=db_b.id, floor_id=f_db_1.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Whiteboard"),
        Room(code="LH12", building_id=db_b.id, floor_id=f_db_1.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Whiteboard"),
        Room(code="LH13", building_id=db_b.id, floor_id=f_db_1.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Whiteboard"),
        Room(code="LH14", building_id=db_b.id, floor_id=f_db_1.id, capacity=80, room_type=RoomType.CLASSROOM,
             facilities="Tiered Gallery Seating, Projector, Whiteboard"),
    ]
    db.add_all(rooms)
    db.commit()

    # 4. USERS (Roles: Faculty, Student, Staff, Admin)
    users = [
        User(
            email="faculty@ddugu.ac.in",
            hashed_password=safe_hash("Trinetra123@"),
            full_name="Dr. Anand Sharma",
            role=UserRole.FACULTY,
            department="CSE",
            employee_id="FAC-CSE-001",
            is_test_data=True
        ),
        User(
            email="faculty2@ddugu.ac.in",
            hashed_password=safe_hash("Trinetra123@"),
            full_name="Dr. Sunita Verma",
            role=UserRole.FACULTY,
            department="AI_ML",
            employee_id="FAC-AIML-002",
            is_test_data=True
        ),
        User(
            email="student@ddugu.ac.in",
            hashed_password=safe_hash("Trinetra123@"),
            full_name="Aarav Patel (3rd Year AI ML)",
            role=UserRole.STUDENT,
            department="AI_ML",
            employee_id="STU-2023-AIML012",
            branch="AI_ML",
            academic_year=3,
            section="A",
            is_test_data=True
        ),
        User(
            email="student2@ddugu.ac.in",
            hashed_password=safe_hash("Trinetra123@"),
            full_name="Priya Singh",
            role=UserRole.STUDENT,
            department="AI_ML",
            employee_id="STU-2024-AIML019",
            branch="AI_ML",
            academic_year=2,
            section="B",
            is_test_data=True
        ),
        User(
            email="staff@ddugu.ac.in",
            hashed_password=safe_hash("Trinetra123@"),
            full_name="Rajesh Kumar",
            role=UserRole.STAFF,
            department="Academic Coordination",
            employee_id="STF-COORD-101",
            is_test_data=True
        ),
        User(
            email="admin@ddugu.ac.in",
            hashed_password=safe_hash("Trinetra123@"),
            full_name="Chief Campus Administrator",
            role=UserRole.ADMIN,
            department="IT Infrastructure & Administration",
            employee_id="ADM-SYS-001",
            is_test_data=True
        ),
    ]
    db.add_all(users)
    db.commit()

    # 5. TIMETABLE SCHEDULES
    room_map = {r.code: r.id for r in db.query(Room).all()}
    
    timetables = [
        # Monday (0)
        TimetableSchedule(room_id=room_map["IET20"], branch="CSE", academic_year=3, section="A",
                          day_of_week=0, start_time=time(9, 0), end_time=time(10, 30),
                          subject="Operating Systems", faculty_name="Dr. Anand Sharma"),
        TimetableSchedule(room_id=room_map["IET22"], branch="CSE", academic_year=3, section="A",
                          day_of_week=0, start_time=time(10, 30), end_time=time(12, 30),
                          subject="OS Kernel & Systems Lab", faculty_name="Dr. Anand Sharma", schedule_type="practical"),
        TimetableSchedule(room_id=room_map["IET18"], branch="AI_ML", academic_year=3, section="A",
                          day_of_week=0, start_time=time(11, 0), end_time=time(12, 30),
                          subject="Deep Learning Architectures", faculty_name="Dr. Sunita Verma"),
        TimetableSchedule(room_id=room_map["IET25"], branch="AI_ML", academic_year=3, section="A",
                          day_of_week=1, start_time=time(9, 30), end_time=time(11, 0),
                          subject="Natural Language Processing", faculty_name="Dr. Sunita Verma"),
        TimetableSchedule(room_id=room_map["IET22"], branch="AI_ML", academic_year=3, section="A",
                          day_of_week=2, start_time=time(14, 0), end_time=time(16, 0),
                          subject="Computer Vision & Robotics Lab", faculty_name="Dr. Sunita Verma", schedule_type="practical"),
        TimetableSchedule(room_id=room_map["LH02"], branch="AI_ML", academic_year=3, section="A",
                          day_of_week=3, start_time=time(10, 0), end_time=time(11, 30),
                          subject="Reinforcement Learning", faculty_name="Prof. R. Srivastava"),
        TimetableSchedule(room_id=room_map["IET18"], branch="AI_ML", academic_year=3, section="A",
                          day_of_week=4, start_time=time(9, 0), end_time=time(10, 30),
                          subject="AI Ethics & Governance", faculty_name="Dr. Anand Sharma"),
        
        # Tuesday (1)
        TimetableSchedule(room_id=room_map["IET20"], branch="CSE", academic_year=3, section="A",
                          day_of_week=1, start_time=time(10, 0), end_time=time(11, 30),
                          subject="Compiler Design", faculty_name="Prof. R. Srivastava"),
        TimetableSchedule(room_id=room_map["LH01"], branch="CSE", academic_year=3, section="B",
                          day_of_week=1, start_time=time(11, 30), end_time=time(13, 0),
                          subject="Computer Networks", faculty_name="Dr. Anand Sharma"),
        
        # Wednesday (2)
        TimetableSchedule(room_id=room_map["IET20"], branch="CSE", academic_year=3, section="A",
                          day_of_week=2, start_time=time(9, 0), end_time=time(10, 30),
                          subject="Software Engineering", faculty_name="Dr. Sunita Verma"),
        TimetableSchedule(room_id=room_map["IET32"], branch="CSE", academic_year=3, section="A",
                          day_of_week=2, start_time=time(14, 0), end_time=time(16, 0),
                          subject="Guest Lecture: Cloud Infrastructure", faculty_name="Visiting Industry Expert"),

        # Thursday (3)
        TimetableSchedule(room_id=room_map["IET24"], branch="AI_DS", academic_year=2, section=None,
                          day_of_week=3, start_time=time(10, 0), end_time=time(11, 30),
                          subject="Data Mining & Warehousing", faculty_name="Dr. Sunita Verma"),

        # Friday (4)
        TimetableSchedule(room_id=room_map["IET20"], branch="CSE", academic_year=3, section="A",
                          day_of_week=4, start_time=time(11, 0), end_time=time(12, 30),
                          subject="Distributed Systems", faculty_name="Prof. R. Srivastava"),
    ]
    db.add_all(timetables)
    db.commit()

    # 6. EXAM SCHEDULES (Solving the missed NSS Minor Exam problem!)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)

    exams = [
        ExamSchedule(
            room_id=room_map["LH01"],
            subject_name="NSS & Value Education (Minor Exam)",
            branch="CSE",
            academic_year=3,
            section="A",
            exam_date=tomorrow,
            start_time=time(10, 0),
            end_time=time(12, 0),
            exam_type="Minor Exam",
            instructions="Official Room Allocated: Deeksha Bhawan LH01. Seat numbers displayed at entry corridor. Bring University ID card."
        ),
        ExamSchedule(
            room_id=room_map["LH02"],
            subject_name="NSS & Value Education (Minor Exam)",
            branch="AI_ML",
            academic_year=3,
            section="A",
            exam_date=tomorrow,
            start_time=time(10, 0),
            end_time=time(12, 0),
            exam_type="Minor Exam",
            instructions="Official Room Allocated: Deeksha Bhawan LH02. All registered students must take assigned seating."
        ),
        ExamSchedule(
            room_id=room_map["IET-LIB"],
            subject_name="NSS & Value Education (Minor Exam)",
            branch="IT",
            academic_year=3,
            section=None,
            exam_date=tomorrow,
            start_time=time(10, 0),
            end_time=time(12, 0),
            exam_type="Minor Exam",
            instructions="Allocated at IET Ground Floor Library Hall for Year 3 IT cohort."
        ),
        ExamSchedule(
            room_id=room_map["IET20"],
            subject_name="Operating Systems Minor Examination",
            branch="CSE",
            academic_year=3,
            section="A",
            exam_date=day_after,
            start_time=time(14, 0),
            end_time=time(16, 0),
            exam_type="Minor Exam",
            instructions="Written theory examination in IET20. Calculators not permitted."
        )
    ]
    db.add_all(exams)
    db.commit()

    # 7. ANNOUNCEMENTS
    fac_user = db.query(User).filter(User.email == "faculty@ddugu.ac.in").first()
    adm_user = db.query(User).filter(User.email == "admin@ddugu.ac.in").first()
    stf_user = db.query(User).filter(User.email == "staff@ddugu.ac.in").first()

    announcements = [
        Announcement(
            title="CRITICAL: Minor Examination (NSS) Room Allocations Finalized",
            body="To ensure no students face schedule confusion, room allocations for the NSS Minor Exam tomorrow are officially set: CSE Year 3 in Deeksha Bhawan LH01, AI/ML Year 3 in Deeksha Bhawan LH02, and IT Year 3 in IET Library. Please verify your student timetable.",
            created_by=stf_user.id,
            target_roles="all"
        ),
        Announcement(
            title="TRINETRA Classroom Management Platform Live",
            body="Welcome to TRINETRA. Real-time conflict-free room booking is now active across both IET and Deeksha Bhawan. Automated alternative recommendations will trigger whenever a collision is detected.",
            created_by=adm_user.id,
            target_roles="all"
        ),
        Announcement(
            title="Room IET17 Scheduled Maintenance",
            body="Classroom IET17 on First Floor is temporarily undergoing audio-visual projector repairs. All bookings will automatically re-route to IET18 or Deeksha Bhawan.",
            created_by=adm_user.id,
            target_roles="faculty"
        )
    ]
    db.add_all(announcements)

    # 8. SAMPLE CONFIRMED BOOKING
    booking1 = Booking(
        room_id=room_map["IET19"],
        user_id=fac_user.id,
        date=tomorrow,
        start_time=time(14, 0),
        end_time=time(15, 30),
        purpose=BookingPurpose.EXTRA_LECTURE,
        purpose_detail="Special Doubt Clearing Session: Compiler Parsing Algorithms",
        expected_students=65,
        status=BookingStatus.CONFIRMED,
        is_test_data=False
    )
    db.add(booking1)
    
    # Audit log
    db.add(AuditLog(actor_id=adm_user.id, action="system.initialized", entity_type="system", details="TRINETRA initial campus catalogue seeded"))
    db.commit()

    print(f"[OK] Seeding complete: {len(rooms)} rooms, {len(users)} users, {len(timetables)} timetable slots, {len(exams)} exams.")
