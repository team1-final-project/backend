import asyncio
from contextlib import asynccontextmanager


from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.payments_router import router as payments_router
from app.api.v1.router import api_router
from app.core.master_seed import seed_master_data
from app.core.config import settings
from app.core.database import Base, engine
from app.models.member import Member
from app.services.ai_pricing_scheduler import (
    run_ai_pricing_scheduler_forever,
    stop_task_safely,
)

load_dotenv()


# 자동 프라이싱
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     Base.metadata.create_all(bind=engine)

#     ai_task = None

#     if settings.AI_PRICING_SCHEDULER_ENABLED:
#         ai_task = asyncio.create_task(run_ai_pricing_scheduler_forever())
#         app.state.ai_pricing_task = ai_task
#         print(
#             f"[AI SCHEDULER] started "
#             f"(interval={settings.AI_PRICING_INTERVAL_MINUTES} minutes)"
#         )

#     try:
#         yield
#     finally:
#         await stop_task_safely(ai_task)
#         print("[AI SCHEDULER] stopped")


# app = FastAPI(
#     title=settings.app_name,
#     lifespan=lifespan,
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=[
#         "http://localhost:3000",
#         "http://127.0.0.1:3000",
#     ],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# 자동 프라이싱 없음
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

# Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
seed_master_data()

app.include_router(api_router, prefix="/api/v1")
app.include_router(payments_router)