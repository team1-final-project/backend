from enum import Enum


class MemberRole(str, Enum):
    USER = "USER"            # 일반 사용자
    ADMIN = "ADMIN"          # 관리자


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"        # 정상 사용 가능
    INACTIVE = "INACTIVE"    # 비활성 상태
    SUSPENDED = "SUSPENDED"  # 정지 상태
    DELETED = "DELETED"      # 탈퇴/삭제 처리 상태


class SocialType(str, Enum):
    LOCAL = "LOCAL"          # 일반 이메일 로그인
    GOOGLE = "GOOGLE"        # 구글 로그인
    KAKAO = "KAKAO"          # 카카오 로그인
    NAVER = "NAVER"          # 네이버 로그인


class VerificationPurpose(str, Enum):
    SIGNUP = "SIGNUP"        # 회원가입 이메일 인증


class ProductSaleStatus(str, Enum):
    READY = "READY"          # 판매예정
    ON_SALE = "ON_SALE"      # 판매중
    STOPPED = "STOPPED"      # 판매중지
    SOLD_OUT = "SOLD_OUT"    # 품절
    ENDED = "ENDED"          # 판매종료


class PriceChangeSource(str, Enum):
    AI = "AI"                # AI 자동 가격 변경
    MANUAL = "MANUAL"        # 관리자 수동 변경
    SYSTEM = "SYSTEM"        # 시스템 내부 로직 변경
    INITIAL = "INITIAL"      # 최초 등록 시점 가격


class InventoryChangeType(str, Enum):
    INBOUND = "INBOUND"              # 입고
    ORDER_OUT = "ORDER_OUT"          # 주문으로 인한 차감
    CANCEL_RETURN = "CANCEL_RETURN"  # 주문 취소/반품으로 인한 복원
    ADJUST = "ADJUST"                # 관리자 수동 조정
    EXPIRE = "EXPIRE"                # 유통기한 만료/폐기


class ImageType(str, Enum):
    THUMBNAIL = "THUMBNAIL"  # 대표 썸네일 이미지
    DETAIL = "DETAIL"        # 상세설명 이미지


class CartStatus(str, Enum):
    ACTIVE = "ACTIVE"        # 사용 중인 장바구니
    ORDERED = "ORDERED"      # 주문 완료된 장바구니
    ABANDONED = "ABANDONED"  # 버려진 장바구니


class OrderStatus(str, Enum):
    CREATED = "CREATED"                  # 주문 생성
    PAYMENT_PENDING = "PAYMENT_PENDING"  # 결제 대기
    PAID = "PAID"                        # 결제 완료
    CANCELED = "CANCELED"                # 주문 취소


class PaymentStatus(str, Enum):
    READY = "READY"        # 결제 준비
    APPROVED = "APPROVED"  # 결제 승인
    FAILED = "FAILED"      # 결제 실패
    CANCELED = "CANCELED"  # 결제 취소


class PaymentProvider(str, Enum):
    TOSS = "TOSS"            # TossPayments


class MatchActionType(str, Enum):
    MATCH = "MATCH"          # 카탈로그 매칭
    UNMATCH = "UNMATCH"      # 카탈로그 매칭 해제