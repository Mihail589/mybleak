#!/usr/bin/env python3
import dbus
import dbus.service
import dbus.mainloop
import time

BLUEZ = "org.bluez"
GATT_MANAGER = "org.bluez.GattManager1"

SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_UUID   = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_UUID  = "12345678-1234-5678-1234-56789abcdef2"


# ====================== Base Classes =========================

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = "/"
        self.services = []
        super().__init__(bus, self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method("org.freedesktop.DBus.ObjectManager",
                         out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        result = {}
        for s in self.services:
            result[s.get_path()] = s.get_properties()
            for ch in s.characteristics:
                result[ch.get_path()] = ch.get_properties()
        return result


class Service(dbus.service.Object):
    def __init__(self, bus, index, uuid, primary):
        self.path = f"/service{index}"
        self.bus = bus
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
                "Characteristics": dbus.Array(
                    [c.get_path() for c in self.characteristics],
                    signature="o"
                )
            }
        }


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.get_path() + f"/char{index}"
        self.bus = bus
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
                "Flags": self.flags
            }
        }

    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="", out_signature="")
    def StartNotify(self):
        self.notifying = True
        print("Notify enabled")

    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="", out_signature="")
    def StopNotify(self):
        self.notifying = False
        print("Notify disabled")


# ====================== Notify Characteristic =========================

class NotifyChar(Characteristic):
    def __init__(self, bus, index, service):
        super().__init__(bus, index, NOTIFY_UUID, ["notify"], service)
        self.value = b""

    def send_notify(self, data: bytes):
        if not self.notifying:
            print("Notify not active by client")
            return

        self.value = data

        arr = dbus.Array([dbus.Byte(b) for b in data], signature="y")

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


# ====================== Write Characteristic =========================

class WriteChar(Characteristic):
    def __init__(self, bus, index, service, notify_char):
        super().__init__(bus, index, WRITE_UUID, ["write"], service)
        self.notify_char = notify_char

    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="aya{sv}", out_signature="")
    def WriteValue(self, value, options):
        data = bytes(value)
        print("WRITE:", data)

        # Отправляем в notify
        self.notify_char.send_notify(data)



# ====================== MAIN =========================

def main():
    # создаём "нативную" синхронную D-Bus-петлю
    dbus.mainloop.NativeMainLoop().setup()

    bus = dbus.SystemBus()

    adapter = "/org/bluez/hci0"
    gatt_mgr = dbus.Interface(
        bus.get_object(BLUEZ, adapter), GATT_MANAGER
    )

    # приложение
    app = Application(bus)

    # сервис
    service = Service(bus, 0, SERVICE_UUID, True)

    notify_char = NotifyChar(bus, 0, service)
    write_char  = WriteChar(bus, 1, service, notify_char)

    service.add_characteristic(notify_char)
    service.add_characteristic(write_char)
    app.add_service(service)

    # регистрация приложения
    gatt_mgr.RegisterApplication(
        app.get_path(),
        {},
        reply_handler=lambda: print("GATT server started"),
        error_handler=lambda e: print("Error:", e)
    )

    # === СИНХРОННЫЙ цикл ===
    print("Running synchronously. Waiting for BLE events...")

    while True:
        time.sleep(0.1)  # синхронная пауза


if __name__ == "__main__":
    main()
