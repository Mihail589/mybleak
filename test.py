#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Синхронный BLE GATT сервер (BlueZ + D-Bus)
- SERVICE_UUID содержит две характеристики: WRITE и NOTIFY
- При записи в WRITE данные сразу пересылаются в NOTIFY
- Реклама включена (device will be visible)
Запуск: sudo python3 ble_full_sync.py
"""

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import threading
import time
import sys

BLUEZ_SERVICE = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"

# UUIDs
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_UUID   = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_UUID  = "12345678-1234-5678-1234-56789abcdef2"

ADAPTER_PATH = "/org/bluez/hci0"
ADVERT_PATH = "/org/bluez/example/advertisement0"
APP_PATH = "/org/bluez/example/app"


# -------------------- Helpers / Exceptions --------------------

class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


# -------------------- Application / Service / Characteristic --------------------

class Application(dbus.service.Object):
    """
    Реализует org.freedesktop.DBus.ObjectManager
    """
    def __init__(self, bus):
        self.bus = bus
        self.path = APP_PATH
        self.services = []
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        managed = {}
        for s in self.services:
            managed[s.get_path()] = s.get_properties()
            for ch in s.characteristics:
                managed[ch.get_path()] = ch.get_properties()
        return managed


class Service(dbus.service.Object):
    def __init__(self, bus, index, uuid, primary=True):
        self.bus = bus
        self.index = index
        self.uuid = uuid
        self.primary = primary
        self.path = f"{APP_PATH}/service{index}"
        self.characteristics = []
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, ch):
        self.characteristics.append(ch)

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
        self.bus = bus
        self.index = index
        self.uuid = uuid
        self.flags = flags
        self.service = service
        self.path = f"{service.get_path()}/char{index}"
        self.notifying = False
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            "org.bluez.GattCharacteristic1": {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": dbus.Array(self.flags, signature="s")
            }
        }

    # StartNotify / StopNotify имеют простую сигнатуру без аргументов
    @dbus.service.method("org.bluez.GattCharacteristic1", in_signature="", out_signature="")
    def StartNotify(self):
        self.notifying = True
        print(f"[{self.uuid}] StartNotify called")

    @dbus.service.method("org.bluez.GattCharacteristic1", in_signature="", out_signature="")
    def StopNotify(self):
        self.notifying = False
        print(f"[{self.uuid}] StopNotify called")

    # Для свойств/сигналов
    @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        # Сигнал формально определён — тело пустое
        pass


# -------------------- Notify Characteristic --------------------

class NotifyCharacteristic(Characteristic):
    def __init__(self, bus, index, service):
        super().__init__(bus, index, NOTIFY_UUID, ["notify"], service)
        self.value = b""

    def send_notify(self, data: bytes):
        if not self.notifying:
            print("Client didn't enable notify. Skipping send.")
            return

        self.value = data
        # Формируем dbus.Array байтов
        arr = dbus.Array([dbus.Byte(b) for b in data], signature='y')
        # Отправляем сигнал PropertiesChanged, чтобы клиент получил уведомление
        self.PropertiesChanged("org.bluez.GattCharacteristic1", {"Value": arr}, [])
        print("NOTIFY sent:", data)


# -------------------- Write Characteristic --------------------

class WriteCharacteristic(Characteristic):
    def __init__(self, bus, index, service, notify_char: NotifyCharacteristic):
        super().__init__(bus, index, WRITE_UUID, ["write"], service)
        self.notify_char = notify_char

    # WriteValue(value: ay, options: a{sv})
    @dbus.service.method("org.bluez.GattCharacteristic1", in_signature="aya{sv}", out_signature="")
    def WriteValue(self, value, options):
        """
        value: array of bytes (ay)
        options: dict (a{sv})
        """
        data = bytes(value)
        print("WRITE received:", data, "options:", options)
        # Немедленно отправляем те же данные в notify
        try:
            self.notify_char.send_notify(data)
        except Exception as e:
            print("Error while notifying:", e)


# -------------------- Advertisement --------------------

class Advertisement(dbus.service.Object):
    """
    Реализует org.bluez.LEAdvertisement1 через Properties.GetAll и метод Release.
    """
    IFACE = "org.bluez.LEAdvertisement1"

    def __init__(self, bus, index, local_name, service_uuids):
        self.bus = bus
        self.index = index
        self.path = ADVERT_PATH
        self.local_name = local_name
        self.service_uuids = service_uuids
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != self.IFACE:
            raise InvalidArgsException()
        props = {
            "Type": dbus.String("peripheral"),
            "LocalName": dbus.String(self.local_name),
            "ServiceUUIDs": dbus.Array(self.service_uuids, signature='s'),
            "Discoverable": dbus.Boolean(True),
            # можно добавить ManufacturerData, ServiceData и т.д.
        }
        return props

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def Release(self):
        print("Advertisement released")


# -------------------- Main --------------------

def run_glib_loop():
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        loop.quit()


def main():
    # Подготавливаем GLib D-Bus loop (обязательно)
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    # Получаем интерфейсы менеджеров
    try:
        gatt_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE, ADAPTER_PATH), GATT_MANAGER_IFACE)
    except Exception as e:
        print("Failed to get GattManager1 on adapter", ADAPTER_PATH, ":", e)
        sys.exit(1)

    try:
        ad_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE, ADAPTER_PATH), LE_ADVERTISING_MANAGER_IFACE)
    except Exception as e:
        print("Failed to get LEAdvertisingManager1 on adapter", ADAPTER_PATH, ":", e)
        sys.exit(1)

    # Создаём приложение, сервис и характеристики
    app = Application(bus)
    service = Service(bus, 0, SERVICE_UUID, primary=True)

    notify_char = NotifyCharacteristic(bus, 0, service)
    write_char = WriteCharacteristic(bus, 1, service, notify_char)

    service.add_characteristic(notify_char)
    service.add_characteristic(write_char)
    app.add_service(service)

    # Регистрируем GATT приложение в BlueZ
    def gatt_reply():
        print("GATT application registered.")

    def gatt_error(error):
        print("Failed to register application:", error)
        sys.exit(1)

    gatt_manager.RegisterApplication(app.get_path(), {},
                                     reply_handler=gatt_reply,
                                     error_handler=gatt_error)

    # Создаём и регистрируем рекламу
    advert = Advertisement(bus, 0, local_name="MyBLE", service_uuids=[SERVICE_UUID])

    def adv_reply():
        print("Advertisement registered.")

    def adv_error(error):
        print("Failed to register advertisement:", error)
        sys.exit(1)

    ad_manager.RegisterAdvertisement(advert.get_path(), {},
                                     reply_handler=adv_reply,
                                     error_handler=adv_error)

    # Запускаем GLib loop в отдельном демоническом потоке — BlueZ/DBus будут обрабатывать запросы
    t = threading.Thread(target=run_glib_loop, daemon=True)
    t.start()

    print("Server started. Main thread is synchronous; GLib loop runs in background.")
    print("Make sure adapter hci0 is powered and supports advertising. Run 'bluetoothctl show' to check.")
    print('"'+SERVICE_UUID+'",', '"'+WRITE_UUID+'",', '"'+NOTIFY_UUID+'"')

    # Синхронная часть — можно делать свою логику здесь
    try:
        while True:
            # Здесь твой синхронный код. Например, логика или мониторинг.
            # Если нужно отправлять уведомления из приложения — вызывай notify_char.send_notify(...)
            time.sleep(1)
    except KeyboardInterrupt:
        print("Interrupted by user, exiting...")
        # Можно при желании дерегистрировать рекламу и приложение, но это опционально.
        # ad_manager.UnregisterAdvertisement(advert.get_path())
        # gatt_manager.UnregisterApplication(app.get_path())
        sys.exit(0)


if __name__ == "__main__":
    main()
