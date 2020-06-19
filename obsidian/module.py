from dataclasses import dataclass
from typing import Type
import importlib
import pkgutil

from obsidian.constants import InitError, MODULESIMPORT, MODULESFOLDER
from obsidian.utils.ptl import PrettyTableLite
from obsidian.log import Logger

# Module Skeleton
@dataclass
class AbstractModule():
    # Defined Later In _ModuleManager
    NAME: str = ""
    DESCRIPTION: str = ""
    VERSION: str = ""


# Internal Module Manager Singleton
class _ModuleManager():
    def __init__(self):
        # Creates List Of Modules That Has The Module Name As Keys
        self._module_list = dict()
        self._completed = False

    # Registration. Called by Module Decorator
    def register(self, name: str, description: str, version: str, module: Type[AbstractModule]):
        Logger.debug(f"Registering Module {name}", module="init-" + name)
        from obsidian.packet import PacketManager  # Prevent Circular Looping :/
        obj = module()  # Create Object
        # Attach Values As Attribute
        obj.NAME = name
        obj.DESCRIPTION = description
        obj.VERSION = version
        Logger.verbose(f"Looping Through All Items In {name}", module="init-" + name)
        for _, item in module.__dict__.items():  # Loop Through All Items In Class
            Logger.verbose(f"Checking {item}", module="init-" + name)
            if hasattr(item, "obsidian_packet"):  # Check If Item Has "obsidian_packet" Flag
                Logger.verbose(f"{item} Is A Packet! Adding As Packet.", module="init-" + name)
                packet = item.obsidian_packet
                # Register Packet Using information Provided By "obsidian_packet"
                PacketManager.register(
                    packet["direction"],
                    packet["name"],
                    packet["description"],
                    packet["packet"],
                    obj
                )
        self._module_list[name] = obj

    # Function to libimport and register all modules
    # EnsureCore ensures core module is present
    def initModules(self, blacklist=[], ensureCore=True):
        if not self._completed:
            Logger.info("Initializing Modules", module="module-init")
            if ensureCore:
                try:
                    importlib.import_module(MODULESIMPORT + "core")
                    blacklist.append("core")  # Adding core to whitelist to prevent re-importing
                    Logger.info("Loaded (mandatory) Module core", module="module-init")
                except ModuleNotFoundError:
                    Logger.fatal("Core Module Not Found! (Failed ensureCore). Check if 'core.py' module is present in modules folder!")
                    raise InitError("Core Module Not Found!")
                except Exception as e:
                    raise e
            for loader, module_name, _ in pkgutil.walk_packages([MODULESFOLDER]):
                Logger.verbose(f"Detected Module {module_name}", module="module-init")
                if module_name not in blacklist:
                    Logger.verbose(f"Module Not In Blacklist. Adding!", module="module-init")
                    _module = loader.find_module(module_name).load_module(module_name)
                    globals()[module_name] = _module
            self._completed = True  # setting completed flag to prevent re-importation
        else:
            Logger.info("Modules Already Initialized; Skipping.", module="module-init")

    # Generate a Pretty List of Modules
    def generateTable(self):
        table = PrettyTableLite()  # Create Pretty List Class

        table.field_names = ["Module", "Version"]
        # Loop Through All Modules And Add Value
        for _, module in self._module_list.items():
            table.add_row([module.NAME, module.VERSION])

        return table

    # Property Method To Get Number Of Modules
    @property
    def numModules(self):
        return len(self._module_list)

    # Handles _ModuleManager["item"]
    def __getitem__(self, module: str):
        return self._module_list[module]

    # Handles _ModuleManager.item
    def __getattr__(self, *args, **kwargs):
        return self.__getitem__(*args, **kwargs)


# Module Registration Decorator
def Module(name: str, description: str = None, version: str = None):
    def internal(cls):
        ModuleManager.register(name, description, version, cls)
    return internal


# Creates Global ModuleManager As Singleton
ModuleManager = _ModuleManager()
# Adds Alias To ModuleManager
Modules = ModuleManager