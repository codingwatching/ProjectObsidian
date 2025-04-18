from __future__ import annotations

import enum
import struct
from typing import Any, Type, Optional, Generic, TYPE_CHECKING
from dataclasses import dataclass
from obsidian.module import Submodule, AbstractModule, AbstractSubmodule, AbstractManager

# from obsidian.network import *
from obsidian.errors import InitRegisterError, PacketError, ConverterError
from obsidian.utils.ptl import PrettyTableLite
from obsidian.log import Logger
from obsidian.types import T

if TYPE_CHECKING:
    from obsidian.player import Player

# Enums
class PacketDirections(enum.Enum):
    REQUEST = 0
    RESPONSE = 1
    NONE = -1


# Packet Utils
def unpackString(data: bytearray, encoding: str = "ascii") -> str:
    Logger.verbose(f"Unpacking String {data}", module="packet")
    # Decode Data From Bytes To String
    # Remove Excess Zeros and Null characters
    return data.replace(b'\x00', b'').decode(encoding, errors="ignore").strip()


def packageString(data: str, maxSize: int = 64, encoding: str = "ascii") -> bytearray:
    Logger.verbose(f"Packing String {data}", module="packet")
    # Trim Text Down To maxSize
    # Fill Blank Space With Spaces Using ljust
    # Encode String Into Bytes Using Encoding
    return bytearray(data[:maxSize].ljust(maxSize), encoding)


# Packet Skeleton
@dataclass
class AbstractPacket(AbstractSubmodule[T], Generic[T]):
    ID: int = 0             # Packet Id
    FORMAT: str = ""        # Packet Structure Format
    CRITICAL: bool = False  # Packet Criticality. Dictates What Event Should Occur When Error

    def __repr__(self):
        return f"<Packet {self.NAME} ({self.ID})>"

    def __str__(self):
        return self.NAME

    # Error Handler. Called If Critical If False And An Error Occurs
    @classmethod
    def onError(cls, error: Exception):
        Logger.error(f"Packet {cls.NAME} Raised Error {error}", module="packet")

    @property
    def SIZE(self) -> int:
        return int(struct.calcsize(self.FORMAT))


@dataclass
class AbstractRequestPacket(AbstractPacket[T], Generic[T]):
    # Mandatory Values Defined In Packet Init
    PLAYERLOOP: bool = False            # Accept Packet During Player Loop
    DIRECTION: PacketDirections = PacketDirections.REQUEST  # Network Direction (Response or Response)

    def __repr__(self):
        return f"<RequestPacket {self.NAME} ({self.ID})>"

    def __str__(self):
        return self.NAME

    async def deserialize(self, ctx: Optional[Player], *args, **kwargs) -> Any:
        raise NotImplementedError("Deserialization For This Packet Is Not Implemented")

    @staticmethod
    def _convertArgument(_, argument: str) -> AbstractRequestPacket:
        try:
            # Try to grab the request packet from the packets list
            return PacketManager.RequestManager.getPacket(argument)
        except KeyError:
            # Raise error if request packet not found
            raise ConverterError(f"Request Packet {argument} Not Found!")


@dataclass
class AbstractResponsePacket(AbstractPacket[T], Generic[T]):
    # Mandatory Values Defined In Packet Init
    DIRECTION = PacketDirections.REQUEST  # Network Direction (Response or Response)

    def __repr__(self):
        return f"<ResponsePacket {self.NAME} ({self.ID})>"

    def __str__(self):
        return self.NAME

    async def serialize(self, *args, **kwargs) -> bytearray:
        return bytearray()

    @staticmethod
    def _convertArgument(_, argument: str) -> AbstractResponsePacket:
        try:
            # Try to grab the response packet from the packet list
            return PacketManager.ResponseManager.getPacket(argument)
        except KeyError:
            # Raise error if response packet not found
            raise ConverterError(f"Response Packet {argument} Not Found!")


# Request Packet Decorator
# Used In @RequestPacket
def RequestPacket(*args, **kwargs):
    return Submodule(PacketManager.RequestManager, *args, **kwargs)


# Response Packet Decorator
# Used In @ResponsePacket
def ResponsePacket(*args, **kwargs):
    return Submodule(PacketManager.ResponseManager, *args, **kwargs)


# Internal Directional Packet Manager
class _DirectionalPacketManager(AbstractManager):
    def __init__(self, direction: PacketDirections):
        # Initialize Overarching Manager Class
        super().__init__(f"{direction.name.title()} Packet", AbstractPacket)

        # Creates List Of Packets That Has The Packet Name As Keys
        self._packetDict = {}  # Not putting a type here as it breaks more things than it fixes
        self.direction: PacketDirections = direction
        # Only Used If Request
        if self.direction is PacketDirections.REQUEST:
            self.loopPackets = {}  # Fast Cache Of Packet Ids to Packet Objects That Are Used During PlayerLoop

    # Registration. Called by (Directional) Packet Decorator
    def register(self, packetClass: Type[AbstractPacket], module: AbstractModule) -> AbstractPacket:
        Logger.debug(f"Registering Packet {packetClass.NAME} From Module {module.NAME}", module=f"{module.NAME}-submodule-init")
        packet: AbstractPacket = super()._initSubmodule(packetClass, module)

        # Check if the name has a space. If so, raise warning
        if " " in packetClass.NAME:
            Logger.warn(f"Packet '{packetClass.NAME}' has white space in its name!", module=f"{module.NAME}-submodule-init")

        # Handling Special Cases if OVERRIDE is Set
        if packet.OVERRIDE:
            # Check If Override Is Going To Do Anything
            # If Not, Warn
            if (packet.ID not in self._packetDict) and (packet.NAME not in self.getAllPacketIds()):
                Logger.warn(
                    f"Packet {packet.NAME} (ID: {packet.ID}) From Module {packet.MODULE.NAME} Is Trying To Override A Packet That Does Not Exist! " + \
                    "If This Is An Accident, Remove The 'override' Flag.", module=f"{module.NAME}-submodule-init"
                )
            else:
                Logger.debug(f"Packet {packet.NAME} Is Overriding Packet {self._packetDict[packet.NAME].NAME} (ID: {packet.ID})", module=f"{module.NAME}-submodule-init")

        # Checking If Packet And PacketId Is Already In Packets List
        # Ignoring if OVERRIDE is set
        if packet.NAME in self._packetDict and not packet.OVERRIDE:
            raise InitRegisterError(f"Packet {packet.NAME} Has Already Been Registered! If This Is Intentional, Set the 'override' Flag to True")
        if packet.ID in self.getAllPacketIds() and not packet.OVERRIDE:
            raise InitRegisterError(f"Packet Id {packet.ID} Has Already Been Registered! If This Is Intentional, Set the 'override' Flag to True")

        # Only Used If Request
        if isinstance(packet, AbstractRequestPacket):
            # Add To Packet Cache If Packet Is Used In Main Player Loop
            if packet.PLAYERLOOP:
                Logger.verbose(f"Adding Packet {packet.ID} To Main Player Loop Request Packet Cache", module=f"{module.NAME}-submodule-init")
                self.loopPackets[packet.ID] = packet

        # Add Packet to Packets List
        self._packetDict[packet.NAME] = packet

        return packet

    def getAllPacketIds(self) -> list[int]:
        return [obj.ID for obj in self._packetDict.values()]

    def getPacketById(self, packetId: int):
        # Search Packet With Matching packetId
        for packet in self._packetDict.values():
            if packet.ID == packetId:
                return packet
        raise PacketError(f"Packet {packetId} Was Not Found")

    # Function To Get Packet Object From Packet Name
    def getPacket(self, packet: str, ignoreCase: bool = True):
        if ignoreCase:
            for pName, pObject in self._packetDict.items():
                if pName.lower() == packet.lower():
                    return pObject
            raise KeyError(packet)
        return self._packetDict[packet]

    # Handles _DirectionalPacketManager["item"]
    def __getitem__(self, *args, **kwargs):
        return self.getPacket(*args, **kwargs)

    # Handles _DirectionalPacketManager.item
    def __getattr__(self, *args, **kwargs):
        return self.getPacket(*args, **kwargs)

    # Gets number of packets registered
    def __len__(self):
        return len(self._packetDict)

    # Check if packet exists
    def __contains__(self, packet: str):
        return packet in self._packetDict


# Internal Packet Manager Singleton
class _PacketManager:
    def __init__(self):
        # Creates List Of Packets That Has The Packet Name As Keys
        self.RequestManager: _DirectionalPacketManager = _DirectionalPacketManager(PacketDirections.REQUEST)
        self.ResponseManager: _DirectionalPacketManager = _DirectionalPacketManager(PacketDirections.RESPONSE)
        self.Request: _DirectionalPacketManager = self.RequestManager  # Alias for RequestManager
        self.Response: _DirectionalPacketManager = self.ResponseManager  # Alias for ResponseManager

    # Generate a Pretty List of Packets
    def generateTable(self):
        try:
            table = PrettyTableLite()  # Create Pretty List Class

            table.field_names = ["Direction", "Packet", "Id", "Player Loop", "Module"]
            # Loop Through All Request Modules And Add Value
            for _, packet in self.RequestManager._packetDict.items():
                requestPacket: AbstractRequestPacket = packet
                # Adding Row To Table
                table.add_row(["Request", requestPacket.NAME, requestPacket.ID, requestPacket.PLAYERLOOP, requestPacket.MODULE.NAME])
            # Loop Through All Response Modules And Add Value
            for _, packet in self.ResponseManager._packetDict.items():
                responsePacket: AbstractResponsePacket = packet
                # Adding Row To Table
                table.add_row(["Response", responsePacket.NAME, responsePacket.ID, "N/A", responsePacket.MODULE.NAME])
            return table

        except Exception as e:
            Logger.error(f"Error While Printing Table - {type(e).__name__}: {e}", module="table")
            return None

    # Get Number Of Packets
    def __len__(self) -> int:
        return len(self.RequestManager) + len(self.ResponseManager)

    # Check if packet exists
    def __contains__(self, packet: str):
        return packet in self.RequestManager or packet in self.ResponseManager


# Creates Global PacketManager As Singleton
PacketManager = _PacketManager()
# Adds Alias To PacketManager
Packets = PacketManager
