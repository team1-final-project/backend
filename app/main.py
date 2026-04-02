from fastapi import FastAPI
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import Base, engine
from app.models.member import Member

app = FastAPI(title=settings.app_name)

Base.metadata.create_all(bind=engine)

app.include_router(api_router, prefix="/api/v1")