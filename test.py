#!/usr/bin/python3
import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

BLUEZ_SERVICE_NAME = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"

MAIN_LOOP = None

# =============================
# UUIDs
# =============================
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_UUID   = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_UUID  = "12345678-1234-5678-1234-56789abcdef2"


# ============================================================
# Base Class
# ============================================================
class Application(dbus.service.Object):
    PATH = "/example/gatt"

    def __init__(self, bus):
        self.path = self.PATH
        self.services = []
        super().__init__(bus, self.path)

    def add_service(self, service):
        self.services.append(service)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):

        managed = {}

        for service in self.services:
            managed[service.get_path()] = service.get_properties()

            for char in service.characteristics:
                managed[char.get_path()] = char.get_properties()

                for desc in char.descriptors:
                    managed[desc.get_path()] = desc.get_properties()

        return managed


# ============================================================
# Service
# ============================================================
class Service(dbus.service.Object):
    IFACE = "org.bluez.GattService1"

    def __init__(self, bus, index, uuid, primary):
        self.path = f"{Application.PATH}/service{index}"
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        super().__init__(bus, self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            self.IFACE: {
                "UUID": self.uuid,
                "Primary": self.primary,
            }
        }


# ============================================================
# Characteristic
# ============================================================
class Characteristic(dbus.service.Object):
    IFACE = "org.bluez.GattCharacteristic1"

    def __init__(self, bus, index, uuid, flags, service):
        self.path = f"{service.path}/char{index}"
        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.service = service
        self.descriptors = []
        self.notifying = False
        super().__init__(bus, self.path)

    def add_descriptor(self, descriptor):
        self.descriptors.append(descriptor)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            self.IFACE: {
                "UUID": self.uuid,
                "Service": self.service.get_path(),
                "Flags": self.flags,
            }
        }

    # Signal — стандартный org.freedesktop.DBus.Properties.PropertiesChanged
    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        # тело остаётся пустым — сигнал будет отправлен автоматически
        pass

    # WRITE Handler
    @dbus.service.method(IFACE, in_signature="aya{sv}", out_signature="")
    def WriteValue(self, value, options):
        # value приходит как массив байтов dbus.Byte (или список)
        data_bytes = bytes(value)
        print("WRITE received:", data_bytes)

        # Если у этой характеристики есть связанная цель notify_target — отправляем уведомление туда
        # мы ожидаем, что в main() мы установим атрибут notify_target для write-характеристики
        if hasattr(self, "notify_target") and self.notify_target is not None:
            try:
                # Подготовим dbus.Array байтов с сигнатурой 'y'
                dbus_value = dbus.Array(value, signature='y')
                # Отправляем сигнал PropertiesChanged на путь notify-характеристики
                # Первый аргумент — интерфейс GATT Characteristic, второй — словарь изменённых свойств
                self.notify_target.PropertiesChanged(self.notify_target.IFACE,
                                                    {"Value": dbus_value},
                                                    [])
                print("Notified notify-characteristic with:", data_bytes)
            except Exception as e:
                print("Failed to send notification:", e)

    # READ Handler
    @dbus.service.method(IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        return dbus.ByteArray(b"OK")

    # Notify Start
    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def StartNotify(self):
        # Включаем флаг уведомлений
        self.notifying = True
        print(f"StartNotify called on {self.path}")

    # Notify Stop
    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def StopNotify(self):
        self.notifying = False
        print(f"StopNotify called on {self.path}")


# ============================================================
# Descriptor (CCCD)
# ============================================================
class Descriptor(dbus.service.Object):
    IFACE = "org.bluez.GattDescriptor1"

    def __init__(self, bus, index, uuid, flags, characteristic):
        self.path = f"{characteristic.path}/desc{index}"
        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.characteristic = characteristic
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            self.IFACE: {
                "UUID": self.uuid,
                "Characteristic": self.characteristic.get_path(),
                "Flags": self.flags,
            }
        }

    @dbus.service.method(IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        # По умолчанию читаем CCCD как enabled (0x01 0x00) — это просто пример
        return dbus.ByteArray(b"\x01\x00")


# ============================================================
# Main
# ============================================================
def main():
    global MAIN_LOOP

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    # Get BlueZ objects
    manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez/hci0"),
                             GATT_MANAGER_IFACE)

    app = Application(bus)
    service = Service(bus, 0, SERVICE_UUID, True)
    app.add_service(service)

    # Write characteristic
    write_char = Characteristic(bus, 0, WRITE_UUID, ["write", "write-without-response"], service)
    service.add_characteristic(write_char)

    # Notify characteristic
    notify_char = Characteristic(bus, 1, NOTIFY_UUID, ["notify", "read"], service)
    service.add_characteristic(notify_char)

    # CCCD descriptor for notify
    cccd = Descriptor(bus, 0, "00002902-0000-1000-8000-00805f9b34fb", ["read", "write"], notify_char)
    notify_char.add_descriptor(cccd)

    # Свяжем write-характеристику с notify-характеристикой — чтобы WriteValue мог отправлять уведомления
    write_char.notify_target = notify_char

    print("Registering application…")
    manager.RegisterApplication(app.get_path(), {},
                                reply_handler=lambda: print("GATT application registered."),
                                error_handler=lambda e: print("Failed:", e))

    MAIN_LOOP = GLib.MainLoop()
    MAIN_LOOP.run()


if __name__ == "__main__":
    main()
