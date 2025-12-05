#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BLE GATT Peripheral (BlueZ + D-Bus)
- Сервис содержит WRITE и NOTIFY характеристики
- При WriteValue данные сразу отправляются в Notify (если клиент включил уведомления)
- Добавлен дескриптор CCCD (0x2902) для Notify
- GLib loop запускается в фоновом потоке; основной поток синхронный (while True)
Запуск: sudo python3 ble_server_fixed_adv.py
"""

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import threading
import time
import sys
import signal

# BlueZ / DBus constants
BLUEZ_SERVICE = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"

# Paths and UUIDs
ADAPTER_PATH = "/org/bluez/hci0"
APP_PATH = "/org/bluez/example/app"
ADVERT_PATH = "/org/bluez/example/advertisement0"

SERVICE_UUID = "12345678-1234-5678-1234-56798abcdef0"
WRITE_UUID   = "12345678-1234-5678-1234-56798abcdef1"
NOTIFY_UUID  = "12345678-1234-5678-1234-56798abcdef2"
CCCD_UUID     = "00002902-0000-1000-8000-00805f9b34fb"  # Client Characteristic Configuration

# Helper exception
class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"

# ---------- Application / Service / Characteristic base ----------

class Application(dbus.service.Object):
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
                # include descriptors
                if hasattr(ch, "descriptors"):
                    for d in ch.descriptors:
                        managed[d.get_path()] = d.get_properties()
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
                "Primary": dbus.Boolean(self.primary),
                "Characteristics": dbus.Array([c.get_path() for c in self.characteristics], signature='o')
            }
        }

class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.bus = bus
        self.index = index
        self.uuid = uuid
        self.flags = flags  # list of strings e.g. ["write","notify"]
        self.service = service
        self.path = f"{service.get_path()}/char{index}"
        self.notifying = False
        self.descriptors = []
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            "org.bluez.GattCharacteristic1": {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": dbus.Array(self.flags, signature='s'),
                "Descriptors": dbus.Array([d.get_path() for d in self.descriptors], signature='o') if self.descriptors else dbus.Array([], signature='o')
            }
        }

    def add_descriptor(self, desc):
        self.descriptors.append(desc)

    # StartNotify / StopNotify: no args
    @dbus.service.method("org.bluez.GattCharacteristic1", in_signature="", out_signature="")
    def StartNotify(self):
        self.notifying = True
        print(f"[{self.uuid}] StartNotify called")

    @dbus.service.method("org.bluez.GattCharacteristic1", in_signature="", out_signature="")
    def StopNotify(self):
        self.notifying = False
        print(f"[{self.uuid}] StopNotify called")

    # Signal for property changes (to notify clients)
    @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

# ---------- Descriptor (CCCD) ----------

class Descriptor(dbus.service.Object):
    """
    Generic descriptor. We implement CCCD (0x2902) to allow clients to enable/disable notifications.
    """
    def __init__(self, bus, index, uuid, flags, characteristic):
        self.bus = bus
        self.index = index
        self.uuid = uuid
        self.flags = flags
        self.characteristic = characteristic
        self.path = f"{characteristic.get_path()}/desc{index}"
        # cccd_value: two-byte little-endian bitmask (0x0001 notify, 0x0002 indicate)
        self.cccd_value = bytes([0x00, 0x00])
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            "org.bluez.GattDescriptor1": {
                "Characteristic": self.characteristic.get_path(),
                "UUID": self.uuid,
                "Flags": dbus.Array(self.flags, signature='s')
            }
        }

    @dbus.service.method("org.bluez.GattDescriptor1", in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        # Return current value as array of bytes
        print(f"[Descriptor {self.uuid}] ReadValue called, returning {self.cccd_value}")
        return dbus.Array([dbus.Byte(b) for b in self.cccd_value], signature='y')

    @dbus.service.method("org.bluez.GattDescriptor1", in_signature="aya{sv}", out_signature="")
    def WriteValue(self, value, options):
        # value is array of bytes => set cccd and toggle notifying on parent characteristic
        data = bytes(value)
        print(f"[Descriptor {self.uuid}] WriteValue called with {data}")
        # Only handle CCCD
        if self.uuid.lower() == CCCD_UUID.lower():
            # store value (2 bytes expected)
            if len(data) >= 2:
                self.cccd_value = data[:2]
            else:
                self.cccd_value = data + b'\x00' * (2 - len(data))
            # bit0 = notify, bit1 = indicate
            notify_enabled = (self.cccd_value[0] & 0x01) != 0
            self.characteristic.notifying = notify_enabled
            print(f" -> CCCD notify_enabled={notify_enabled}")
        else:
            print(" -> Write to non-CCCD descriptor (ignored)")

# ---------- Notify characteristic ----------

class NotifyCharacteristic(Characteristic):
    def __init__(self, bus, index, service):
        super().__init__(bus, index, NOTIFY_UUID, ["notify"], service)
        self.value = b""
        # add CCCD descriptor
        desc = Descriptor(bus, 0, CCCD_UUID, ["read", "write"], self)
        self.add_descriptor(desc)

    def send_notify(self, data: bytes):
        if not self.notifying:
            print("Client did not enable notify (CCCD). Skipping notify.")
            return
        self.value = data
        arr = dbus.Array([dbus.Byte(b) for b in data], signature='y')
        # Emit PropertiesChanged so BlueZ will send a notification to clients
        self.PropertiesChanged("org.bluez.GattCharacteristic1", {"Value": arr}, [])
        print("NOTIFY sent:", data)

# ---------- Write characteristic ----------

class WriteCharacteristic(Characteristic):
    def __init__(self, bus, index, service, notify_char: NotifyCharacteristic):
        # include both write and write-without-response to be compatible with clients
        super().__init__(bus, index, WRITE_UUID, ["write", "write-without-response"], service)
        self.notify_char = notify_char

    @dbus.service.method("org.bluez.GattCharacteristic1", in_signature="aya{sv}", out_signature="")
    def WriteValue(self, value, options):
        data = bytes(value)
        print("WRITE received:", data, "options:", options)
        # Immediately send same data to notify characteristic (if enabled)
        try:
            self.notify_char.send_notify(data)
        except Exception as e:
            print("Error while notifying:", e)

# ---------- Advertisement ----------

class Advertisement(dbus.service.Object):
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
        # Minimal, compatible advertisement: no Includes
        props = {
            "Type": dbus.String("peripheral"),
            "LocalName": dbus.String(self.local_name),
            "ServiceUUIDs": dbus.Array(self.service_uuids, signature='s'),
            "Discoverable": dbus.Boolean(True),
        }
        return props

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def Release(self):
        print("Advertisement released")

# ---------- Utility: get adapter MAC ----------

def get_adapter_mac(bus, adapter_path=ADAPTER_PATH):
    try:
        props = dbus.Interface(bus.get_object(BLUEZ_SERVICE, adapter_path), DBUS_PROP_IFACE)
        addr = props.Get("org.bluez.Adapter1", "Address")
        return str(addr)
    except Exception as e:
        print("Cannot read adapter Address:", e)
        return None

# ---------- GLib loop runner ----------

def run_glib_loop():
    loop = GLib.MainLoop()
    try:
        loop.run()
    except Exception:
        pass

# ---------- Main ----------

def main():
    # Set GLib loop for DBus and get system bus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    mac = get_adapter_mac(bus)
    print("Adapter MAC:", mac)

    # Get managers
    try:
        gatt_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE, ADAPTER_PATH), GATT_MANAGER_IFACE)
    except Exception as e:
        print("Error: cannot get GattManager1:", e)
        sys.exit(1)

    try:
        ad_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE, ADAPTER_PATH), LE_ADVERTISING_MANAGER_IFACE)
    except Exception as e:
        print("Error: cannot get LEAdvertisingManager1:", e)
        sys.exit(1)

    # Build application
    app = Application(bus)
    service = Service(bus, 0, SERVICE_UUID, primary=True)

    notify_char = NotifyCharacteristic(bus, 0, service)
    write_char = WriteCharacteristic(bus, 1, service, notify_char)

    service.add_characteristic(notify_char)
    service.add_characteristic(write_char)
    app.add_service(service)

    # Register application
    def gatt_reply():
        print("GATT application registered.")

    def gatt_error(err):
        print("Failed to register application:", err)
        sys.exit(1)

    gatt_manager.RegisterApplication(app.get_path(), {}, reply_handler=gatt_reply, error_handler=gatt_error)

    # Register advertisement
    advert = Advertisement(bus, 0, local_name="MyBLE", service_uuids=[SERVICE_UUID])

    def adv_reply():
        print("Advertisement registered.")

    def adv_error(err):
        print("Failed to register advertisement:", err)
        sys.exit(1)

    ad_manager.RegisterAdvertisement(advert.get_path(), {}, reply_handler=adv_reply, error_handler=adv_error)

    # Run GLib loop in background thread
    t = threading.Thread(target=run_glib_loop, daemon=True)
    t.start()

    print("Server running. GLib loop in background thread. Main thread is synchronous.")

    # Graceful exit handler
    def on_sigint(signum, frame):
        print("Received SIGINT, exiting...")
        # try to unregister (best-effort)
        try:
            ad_manager.UnregisterAdvertisement(advert.get_path())
        except Exception:
            pass
        try:
            gatt_manager.UnregisterApplication(app.get_path())
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, on_sigint)

    # Synchronous main loop — your app logic can go here
    try:
        while True:
            # If you want to push periodic notifications from server side:
            # notify_char.send_notify(b'ping')   # example
            time.sleep(1)
    except KeyboardInterrupt:
        on_sigint(None, None)

if __name__ == "__main__":
    main()
