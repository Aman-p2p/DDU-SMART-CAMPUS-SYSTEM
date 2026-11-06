
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.database import engine, Base, SessionLocal
from .core.seed import seed_database
from .services.booking_service import auto_complete_expired_bookings
from .routers import (
    auth,
    rooms,
    bookings,
    admin,
    ai_assistant,
    schedules,
)

# Project frontend directory
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


async def background_auto_vacate_loop():
    """Background worker: automatically frees rooms and marks bookings completed as soon as their slot ends."""
    while True:
        try:
            db = SessionLocal()
            auto_complete_expired_bookings(db)
            db.close()
        except asyncio.CancelledError:
            break
        except Exception:
            pass
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create database tables
    Base.metadata.create_all(bind=engine)

    # Seed initial database data
    db = SessionLocal()
    try:
        seed_database(db)
        auto_complete_expired_bookings(db)
    except Exception as e:
        print("Seed error during startup:", e)
    finally:
        db.close()

    # Launch background auto-vacate task
    vacate_task = asyncio.create_task(background_auto_vacate_loop())

    yield

    vacate_task.cancel()


app = FastAPI(
    title="TRINETRA — Smart Campus Classroom Management System",
    description=(
        "Intelligent campus coordination, conflict-free "
        "booking, and schedule distribution for DDUGU."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# API routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(rooms.router, prefix="/api/rooms", tags=["Rooms"])
app.include_router(bookings.router, prefix="/api/bookings", tags=["Bookings"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(ai_assistant.router, prefix="/api/ai", tags=["AI Assistant"])
app.include_router(schedules.router, prefix="/api/schedules", tags=["Schedules"])


# Health endpoint
@app.get("/health", tags=["System"])
@app.get("/api/health", tags=["System"])
def health():
    return {
        "status": "ok",
        "app": "TRINETRA",
        "version": "2.0.0",
        "system": "Smart Campus Coordination Platform (DDUGU)",
    }


# Root API information
@app.get("/api", tags=["System"])
def api_info():
    return {
        "app": "TRINETRA",
        "status": "running",
        "docs_url": "/docs",
        "health_url": "/api/health",
    }


# Serve frontend
if not (FRONTEND_DIR / "index.html").is_file():
    raise RuntimeError(
        f"Frontend index.html not found: {FRONTEND_DIR}"
    )

app.mount(
    "/",
    StaticFiles(
        directory=str(FRONTEND_DIR),
        html=True,
    ),
    name="frontend",
)
