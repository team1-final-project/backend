from enum import Enum

class MemberRole(str, Enum):
    USER = "USER"
    ADMIN = "ADMIN"

class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"

class SocialType(str, Enum):
    LOCAL = "LOCAL"
    GOOGLE = "GOOGLE"
    KAKAO = "KAKAO"
    NAVER = "NAVER"

class VerificationPurpose(str, Enum):
    SIGNUP = "SIGNUP"