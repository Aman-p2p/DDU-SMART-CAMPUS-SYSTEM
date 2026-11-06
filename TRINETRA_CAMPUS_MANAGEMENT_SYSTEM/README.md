# TRINETRA — Smart Campus Classroom Management System

**DDU Gorakhpur University (DDUGU) | GDG On Campus: Build With AI: DevOps 2026**

> **One Campus. One Intelligent System. Automated Bookings. Security First.**

---
# AUTHOR : RIO </>

# REAL : @SPIDEERIO


## 🏛️ Project Overview

TRINETRA is a centralized, intelligent campus classroom coordination platform developed for **Deen Dayal Upadhyaya Gorakhpur University (DDUGU)**. It manages academic scheduling, laboratory allocations, and room reservations across both the **Institute of Engineering & Technology (IET)** and **Deeksha Bhawan (~100m away)**.

### Solving Real Campus Challenges
Last year at DDUGU, students missed their minor examination (NSS) due to uncoordinated hall reallocations. TRINETRA eliminates scheduling ambiguity through:
1. **Automated Conflict Prevention**: Half-open interval collision checking ($[start, end)$) prevents double-bookings.
2. **Ranked Alternative Suggestions**: When a requested classroom is occupied, the backend returns HTTP 409 with an ranked list of alternative rooms matching capacity, floor, and building proximity.
3. **Role-Based Access Control (RBAC)**: Distinct permissions for **Faculty**, **Students**, **Staff Coordinators**, and **Administrators**.
4. **Student Accountability & Reporting**: Students can view personalized timetables, check verified minor examination room assignments, and report discrepancies without permission to tamper with official bookings.
5. **Smart Campus AI**: Natural-language assistant backed by live database state and constraint verification.

---

## 🗺️ Campus Infrastructure & Blueprint Alignment

TRINETRA integrates 100% of physical spaces from the official blueprints (`blueprint.png`):

### 1. Institute of Engineering & Technology (IET)
* **Ground Floor**:
  - `IET-LIB`: Central Library (Capacity: 180, Air Conditioned, Exam-Capable)
  - `IET-DIR`: Director's Office
  - `IET-ADMIN`: Administrative Office
  - `IET-TCH`: Teachers' Office / Faculty Cabins
  - `IET-PLACE`: Placement Cell
* **First Floor** (4 Specialized Labs + 4 Classrooms):
  - `IET22`: CSE Laboratory (45 Workstations, LAN, GPU Access)
  - `IET16`: Mechanical Engineering Laboratory (40 Workstations, CAD/CAM)
  - `IET14`: ECE Laboratory (40 Workstations, Microcontroller Kits)
  - `IET15`: IT Laboratory (45 Workstations, Cloud Terminals)
  - `IET20`, `IET18`, `IET19`, `IET17`: Classrooms (75 Seats each)
* **Second Floor** (Seminar Hall + 6 Classrooms):
  - `IET32`: Seminar Hall (Capacity: 200, Dual Projectors, Surround PA)
  - `IET24`, `IET25`, `IET28`, `IET29`, `IET30`, `IET23`: Classrooms (75 Seats each)

### 2. Deeksha Bhawan (~100m from IET)
* **Ground Floor**: `LH01` to `LH07` (80 Seats each, Tiered Gallery Seating)
* **First Floor**: `LH08` to `LH14` (80 Seats each, Tiered Gallery Seating)

---

## 🎓 Student Cohort & Branch Hierarchy

TRINETRA maps students across all 6 official engineering branches:
* **CSE**: ~150 students (Sections A & B)
* **AI & ML**: ~150 students (Sections A & B)
* **AI & DS**: ~75 students
* **ECE**: ~75 students
* **ME**: ~75 students
* **IT**: ~75 students

---

## 🚀 Quick Start

### 1. Backend Setup (FastAPI + SQLAlchemy)

```bash
cd backend

# Activate Virtual Environment (Windows)
..\venv\Scripts\activate

# Run automated test suite
python test_suite.py

# Launch API server
python server.py
# Or: uvicorn app.main:app --reload --port 8000
```

* API Docs (Swagger UI): `http://localhost:8000/docs`
* Health Check: `http://localhost:8000/api/health`

### 2. Frontend Launch

Open `frontend/index.html` in any modern web browser or serve with a local server:
```bash
# Optional simple web server:
cd frontend
python -m http.server 3000
```
Then visit `http://localhost:3000` or double-click `frontend/index.html`.

---

## 🔑 Demo User Credentials

The database automatically seeds the following verified accounts:

| Role | Email | Password | Details |
| :--- | :--- | :--- | :--- |
| **Faculty** | `faculty@ddugu.ac.in` | `faculty123` | Dr. Anand Sharma (Head, CSE) |
| **Faculty 2** | `faculty2@ddugu.ac.in` | `faculty123` | Dr. Sunita Verma (Assoc. Prof, AI/ML) |
| **Student** | `student@ddugu.ac.in` | `student123` | Aarav Patel (CSE, Year 3, Sec A) |
| **Staff** | `staff@ddugu.ac.in` | `staff123` | Rajesh Kumar (Exam & Schedule Coordinator) |
| **Admin** | `admin@ddugu.ac.in` | `admin123` | Chief Campus Administrator |

---

## 📡 Key API Routes

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/auth/login` | OAuth2 Bearer token generation with RBAC claims |
| `GET` | `/api/auth/me` | Fetch authenticated user profile & student branch details |
| `GET` | `/api/rooms/` | Search rooms with building, floor, capacity, date, & time filters |
| `POST` | `/api/bookings/` | Reserve classroom slot (returns HTTP 409 + ranked alternatives on collision) |
| `GET` | `/api/bookings/my` | View personal active bookings |
| `POST` | `/api/bookings/{id}/cancel` | Instant booking cancellation with audit logging |
| `GET` | `/api/bookings/all` | View master campus bookings (Staff & Admin) |
| `PATCH` | `/api/admin/rooms/{id}/maintenance` | Toggle room maintenance mode on/off |
| `GET` | `/api/schedules/timetable` | Branch-specific weekly class timetable |
| `GET` | `/api/schedules/exams` | Scheduled minor examinations & venue allocations |
| `POST` | `/api/admin/issues` | Student reporting of schedule discrepancies |
| `GET` | `/api/admin/audit` | Immutable system audit log trail |
| `POST` | `/api/ai/ask` | Natural-language campus queries & smart recommendations |

---

## 🧪 Automated Test Suite

Run `backend/test_suite.py` to verify all 11 critical system workflows:
```bash
cd backend
..\venv\Scripts\python.exe test_suite.py
```
**Test Coverage:**
* Database Seeding & Schema Creation (34 rooms, 6 users, 9 timetables, 4 exams)
* Authentication & JWT claims for all 4 roles
* Room filtering by Building, Floor, and Capacity
* Single-click Faculty booking
* Overlapping collision detection returning HTTP 409 with 6 ranked alternatives
* Booking cancellation and slot release
* Admin maintenance toggle
* Student privilege validation (HTTP 403 on unauthorized booking attempts)
* Student discrepancy submission
* NSS Minor Examination schedule verification
* AI Campus Assistant natural-language parsing
