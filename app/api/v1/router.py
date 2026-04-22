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
    admin_product,
    admin_price,
)
from app.api.v1.endpoints import order, order_read

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(google_auth.router)
api_router.include_router(kakao_auth.router)
api_router.include_router(naver_auth.router)
api_router.include_router(category.router)
api_router.include_router(order.router)
api_router.include_router(cart.router)
api_router.include_router(admin_product.router)
api_router.include_router(admin_price.router)
api_router.include_router(order.router, prefix="/orders", tags=["orders"])
api_router.include_router(order_read.router, prefix="/orders", tags=["orders"])
