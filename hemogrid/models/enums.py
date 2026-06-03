from enum import Enum


class Provenance(str, Enum):
    PROVIDED = "provided"
    DERIVED = "derived"
    SYNTHETIC = "synthetic"


class ABOGroup(str, Enum):
    A = "A"
    B = "B"
    AB = "AB"
    O = "O"


class Component(str, Enum):
    PRBC = "PRBC"
    PLATELETS = "platelets"
    PLASMA = "plasma"


class BankCategory(str, Enum):
    GOVERNMENT = "Government"
    PRIVATE = "Private"
    CHARITY = "Charity"


class Lever(str, Enum):
    INVENTORY = "inventory"
    DONOR = "donor"
    EMERGENCY = "emergency"


class RequestStatus(str, Enum):
    PREDICTED = "predicted"
    PROPOSED = "proposed"
    APPROVED = "approved"
    FULFILLED = "fulfilled"
