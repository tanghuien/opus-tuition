from enum import Enum, StrEnum

class AttendanceStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    ABSENT_MC = "absent-mc"

class Subject(StrEnum):
    ENGLISH = "english"
    MATHEMATICS = "mathematics"
    SCIENCE = "science"
    BIOLOGY = "biology"
    CHEMISTRY = "chemistry"
    PHYSICS = "physics"

class PaymentStatus(StrEnum):
    PAID = "paid"
    OVERDUE = "overdue"
    PENDING = "pending"

class AssignmentStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"

class Duration(Enum):
    SHORT = 1.0
    MEDIUM = 1.5
    LONG = 2.0

class SchoolLevel(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    JUNIOR_COLLEGE = "junior college"
