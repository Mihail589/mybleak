#!/usr/bin/env python3
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import threading
import time

BLUEZ = "org.bluez"
GATT_MANAGER = "org.bluez.GattManager1"

SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_UUID   = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_UUID  = "12345678-1234-5678-1234-56789abcdef2"


# =======================================================

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = "/"
        self.services = []
        super().__init__(bus, self.path)

    def add_service(self, s):
        self.services.append(s)

    @dbus.service.method("org.freedesktop.DBus.ObjectManager",
                         out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        res = {}
        for s in self.services:
            res[s.get_path()] = s.get_properties()
            for ch in s.characteristics:
                res[ch.get_path()] = ch.get_properties()
        return res


class Service(dbus.service.Object):
    def __init__(self, bus, index, uuid, primary=True):
        self.path = f"/service{index}"
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        super().__init__(bus, self.path)

    def add_characteristic(self, ch):
        self.characteristics.append(ch)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            "org.bluez.GattService1": {
                "UUID": self.uuid,
                "Primary": self.primary,
                "Characteristics": [c.get_path() for c in self.characteristics]
            }
        }


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.get_path() + f"/char{index}"
        self.uuid = uuid
        self.flags = flags
        self.service = service
        self.notifying = False
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            "org.bluez.GattCharacteristic1": {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": self.flags,
            }
        }

    @dbus.service.method("org.bluez.GattCharacteristic1")
    def StartNotify(self):
        self.notifying = True
        print("Notify enabled")

    @dbus.service.method("org.bluez.GattCharacteristic1")
    def StopNotify(self):
        self.notifying = False
        print("Notify disabled")


class NotifyChar(Characteristic):
    def __init__(self, bus, index, service):
        super().__init__(bus, index, NOTIFY_UUID, ["notify"], service)

    def send(self, data: bytes):
        if not self.notifying:
            print("Notify is off")
            return

        arr = [dbus.Byte(b) for b in data]

        self.PropertiesChanged(
            "org.bluez.GattCharacteristic1",
            {"Value": arr},
            []
        )
        print("NOTIFY:", data)

    @dbus.service.signal("org.freedesktop.DBus.Properties",
                         signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class WriteChar(Characteristic):
    def __init__(self, bus, index, service, notify_char):
        super().__init__(bus, index, WRITE_UUID, ["write"], service)
        self.notify_char = notify_char

    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="aya{sv}")
    def WriteValue(self, value, options):
        data = bytes(value)
        print("WRITE:", data)
        self.notify_char.send(data)


# =======================================================

def run_dbus_loop():
    loop = GLib.MainLoop()
    loop.run()


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    adapter = "/org/bluez/hci0"
    gatt = dbus.Interface(bus.get_object(BLUEZ, adapter), GATT_MANAGER)

    app = Application(bus)
    service = Service(bus, 0, SERVICE_UUID)

    notify_char = NotifyChar(bus, 0, service)
    write_char  = WriteChar(bus, 1, service, notify_char)

    service.add_characteristic(notify_char)
    service.add_characteristic(write_char)
    app.add_service(service)

    gatt.RegisterApplication(app.get_path(), {},
        reply_handler=lambda: print("GATT registered"),
        error_handler=lambda e: print("ERR:", e)
    )

    # ---- запускаем GLib в отдельном потоке ----
    t = threading.Thread(target=run_dbus_loop, daemon=True)
    t.start()

    print("MAIN LOOP: synchronous code running")

    # ---- ваш собственный синхронный цикл ----
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
