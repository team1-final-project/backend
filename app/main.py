from fastapi import FastAPI
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import Base, engine
from app.models.member import Member
from app.api.v1.payments_router import router as payments_router
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
load_dotenv()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

app.include_router(api_router, prefix="/api/v1")
app.include_router(payments_router)