class UserGroupType:
    QuickAccess: str = "quick-access"


class UserStatus:
    ACCOUNT_STATUS_OK = 0
    ACCOUNT_STATUS_CLOSED = 3
    ACCOUNT_STATUS_PENDING = 5
    ACCOUNT_STATUS_DISABLED = 9
    ACCOUNT_STATUS_DELETED = 10
    Valid: list[int] = [
        ACCOUNT_STATUS_OK,
        ACCOUNT_STATUS_CLOSED,
        ACCOUNT_STATUS_PENDING,
        ACCOUNT_STATUS_DISABLED,
        ACCOUNT_STATUS_DELETED,
    ]

    @classmethod
    def is_valid_status(cls, status: int) -> bool:
        return status in cls.Valid



class OnlineStatus:
    OFFLINE: int = 2
    ONLINE: int = 1

class UserRole:
    # --- Base and Local Community Roles ---
    User: int = 0
    Leader: int = 100
    Curator: int = 101
    Agent: int = 102  # Community creator/owner

    # --- Global Platform Roles (AltAmino Staff) ---
    AltAminoMod: int = 200  # Global moderator
    AltAminoAdmin: int = 201  # Global administrator

    # --- System and Service Accounts ---
    Feed: int = 253  # News feed / Notification bot
    System: int = 254  # System account for automated actions

    # --- Superusers / Developers ---
    AltAminoStaff: int = 555  # Platform staff

    # --- Permission Groups ---

    # Accounts with global administrative privileges across the platform
    GODS: list[int] = [
        AltAminoMod,
        AltAminoAdmin,
        AltAminoStaff,
        Feed,
        System,
        250,
        251,
    ]

    # Local administration (Community management)
    LOCALSTAFF: list[int] = [Curator, Leader, Agent]

    # Regular roles that can be assigned within individual communities
    ALLOWED_ROLES: list[int] = [User] + LOCALSTAFF + GODS

    @classmethod
    def is_valid_role(cls, role: int) -> bool:
        """
        Verify if the given role ID exists within the allowed platform roles.
        """
        return role in cls.ALLOWED_ROLES

    @classmethod
    def is_privileged_role(cls, role: int) -> bool:
        """
        Check if the user has any elevated privileges (Global Staff or Local Staff).
        """
        return role in cls.GODS + cls.LOCALSTAFF

    @classmethod
    def is_local_staff(cls, role: int) -> bool:
        """
        Check if the user is a local community staff (Leader or Agent or Curator).
        """
        return role in cls.LOCALSTAFF

    @classmethod
    def is_local_admin(cls, role: int) -> bool:
        """
        Check if the user is a local community administrator (Leader or Agent).
        """
        return role in (cls.Leader, cls.Agent)

    @classmethod
    def is_global_staff(cls, role: int) -> bool:
        """
        Check if the user has platform-wide management permissions.
        """
        return role in cls.GODS
