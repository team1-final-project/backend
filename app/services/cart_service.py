from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.enums import CartStatus, ImageType
from app.models.cart import Cart
from app.models.cart_item import CartItem
from app.models.member import Member
from app.models.product import Product
from app.models.product_image import ProductImage
from app.schemas.cart import CartItemResponse, CartResponse


class CartService:
    @staticmethod
    def _get_or_create_active_cart(db: Session, member_id: int) -> Cart:
        cart = (
            db.query(Cart)
            .filter(
                Cart.member_id == member_id,
                Cart.status == CartStatus.ACTIVE,
            )
            .first()
        )

        if cart is None:
            cart = Cart(member_id=member_id, status=CartStatus.ACTIVE)
            db.add(cart)
            db.commit()
            db.refresh(cart)

        return cart

    @staticmethod
    def _get_owned_cart_item(db: Session, current_user: Member, cart_item_id: int) -> CartItem:
        active_cart = CartService._get_or_create_active_cart(db, current_user.id)

        cart_item = (
            db.query(CartItem)
            .filter(
                CartItem.id == cart_item_id,
                CartItem.cart_id == active_cart.id,
            )
            .first()
        )

        if cart_item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="장바구니 항목이 없습니다.",
            )

        return cart_item

    @staticmethod
    def _build_cart_response(db: Session, cart: Cart) -> CartResponse:
        cart_items = (
            db.query(CartItem)
            .filter(CartItem.cart_id == cart.id)
            .order_by(CartItem.id.asc())
            .all()
        )

        items: list[CartItemResponse] = []

        for cart_item in cart_items:
            product = db.query(Product).filter(Product.id == cart_item.product_id).first()
            if product is None:
                continue

            thumbnail = (
                db.query(ProductImage)
                .filter(
                    ProductImage.product_id == product.id,
                    ProductImage.image_type == ImageType.THUMBNAIL,
                    ProductImage.is_active.is_(True),
                )
                .order_by(ProductImage.sort_order.asc(), ProductImage.id.asc())
                .first()
            )

            items.append(
                CartItemResponse(
                    id=cart_item.id,
                    productId=product.id,
                    name=product.product_name,
                    price=product.sale_price,
                    quantity=cart_item.quantity,
                    image=thumbnail.image_url if thumbnail else None,
                    checked=cart_item.is_selected,
                )
            )

        return CartResponse(
            cartId=cart.id,
            items=items,
        )

    @staticmethod
    def get_my_cart(db: Session, current_user: Member) -> CartResponse:
        cart = CartService._get_or_create_active_cart(db, current_user.id)
        return CartService._build_cart_response(db, cart)

    @staticmethod
    def update_quantity(
        db: Session,
        current_user: Member,
        cart_item_id: int,
        quantity: int,
    ) -> CartResponse:
        if quantity < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="수량은 1개 이상이어야 합니다.",
            )

        cart_item = CartService._get_owned_cart_item(db, current_user, cart_item_id)
        cart_item.quantity = quantity
        db.add(cart_item)
        db.commit()

        cart = CartService._get_or_create_active_cart(db, current_user.id)
        return CartService._build_cart_response(db, cart)

    @staticmethod
    def update_checked(
        db: Session,
        current_user: Member,
        cart_item_id: int,
        checked: bool,
    ) -> CartResponse:
        cart_item = CartService._get_owned_cart_item(db, current_user, cart_item_id)
        cart_item.is_selected = checked
        db.add(cart_item)
        db.commit()

        cart = CartService._get_or_create_active_cart(db, current_user.id)
        return CartService._build_cart_response(db, cart)

    @staticmethod
    def check_all(
        db: Session,
        current_user: Member,
        checked: bool,
    ) -> CartResponse:
        cart = CartService._get_or_create_active_cart(db, current_user.id)

        cart_items = db.query(CartItem).filter(CartItem.cart_id == cart.id).all()
        for cart_item in cart_items:
            cart_item.is_selected = checked
            db.add(cart_item)

        db.commit()
        return CartService._build_cart_response(db, cart)

    @staticmethod
    def delete_item(
        db: Session,
        current_user: Member,
        cart_item_id: int,
    ) -> CartResponse:
        cart_item = CartService._get_owned_cart_item(db, current_user, cart_item_id)
        db.delete(cart_item)
        db.commit()

        cart = CartService._get_or_create_active_cart(db, current_user.id)
        return CartService._build_cart_response(db, cart)