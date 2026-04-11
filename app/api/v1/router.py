from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    google_auth,
    kakao_auth,
    naver_auth,
    health,
    category,
    order,
    cart,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(google_auth.router)
api_router.include_router(kakao_auth.router)
api_router.include_router(naver_auth.router)
api_router.include_router(category.router)
api_router.include_router(order.router)
api_router.include_router(cart.router)