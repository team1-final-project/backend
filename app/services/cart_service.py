from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.enums import CartStatus, ImageType, ProductSaleStatus
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
    def _get_owned_cart_item(
        db: Session,
        current_user: Member,
        cart_item_id: int,
    ) -> CartItem:
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
    def _get_public_product_or_raise(db: Session, product_id: int) -> Product:
        product = (
            db.query(Product)
            .filter(
                Product.id == product_id,
                Product.deleted_at.is_(None),
            )
            .first()
        )

        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="상품을 찾을 수 없습니다.",
            )

        if product.sale_status != ProductSaleStatus.ON_SALE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="판매중인 상품만 장바구니에 담을 수 있습니다.",
            )

        return product

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
                    price=int(cart_item.unit_price_snapshot or product.sale_price or 0),
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
    def add_item(
        db: Session,
        current_user: Member,
        product_id: int,
        quantity: int,
    ) -> CartResponse:
        if quantity < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="수량은 1개 이상이어야 합니다.",
            )

        product = CartService._get_public_product_or_raise(db, product_id)
        active_cart = CartService._get_or_create_active_cart(db, current_user.id)

        existing_item = (
            db.query(CartItem)
            .filter(
                CartItem.cart_id == active_cart.id,
                CartItem.product_id == product_id,
            )
            .first()
        )

        target_quantity = quantity
        if existing_item is not None:
            target_quantity = int(existing_item.quantity or 0) + quantity

        if target_quantity > int(product.stock_qty or 0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="재고보다 많은 수량을 장바구니에 담을 수 없습니다.",
            )

        if existing_item is not None:
            existing_item.quantity = target_quantity
            existing_item.unit_price_snapshot = int(product.sale_price or 0)
            existing_item.is_selected = True
            db.add(existing_item)
        else:
            db.add(
                CartItem(
                    cart_id=active_cart.id,
                    product_id=product_id,
                    quantity=quantity,
                    unit_price_snapshot=int(product.sale_price or 0),
                    is_selected=True,
                )
            )

        db.commit()
        return CartService._build_cart_response(db, active_cart)

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
        product = CartService._get_public_product_or_raise(db, cart_item.product_id)

        if quantity > int(product.stock_qty or 0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="재고보다 많은 수량으로 변경할 수 없습니다.",
            )

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