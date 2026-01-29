#!/usr/bin/python3
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import subprocess
import time

# Настройки
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_UUID   = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_UUID  = "12345678-1234-5678-1234-56789abcdef2"
DEVICE_NAME  = "SimpleGATT-Server"

def check_bluetooth():
    """Проверить и включить Bluetooth"""
    try:
        # Проверяем статус
        result = subprocess.run(['bluetoothctl', 'show'], 
                              capture_output=True, text=True)
        if 'Powered: no' in result.stdout:
            print("⚠️  Bluetooth is OFF, turning ON...")
            subprocess.run(['bluetoothctl', 'power', 'on'], check=False)
            time.sleep(1)
        
        # Включаем адаптер
        subprocess.run(['sudo', 'hciconfig', 'hci0', 'up'], check=False)
        subprocess.run(['sudo', 'hciconfig', 'hci0', 'piscan'], check=False)
        time.sleep(1)
        return True
    except:
        return False

def get_mac_address():
    """Получить MAC адрес"""
    try:
        result = subprocess.run(['hciconfig', 'hci0'], 
                              capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if 'BD Address' in line:
                parts = line.split()
                for part in parts:
                    if len(part) == 17 and ':' in part:
                        return part
        return "Unknown"
    except:
        return "Unknown"

class Advertisement(dbus.service.Object):
    """Реклама устройства для обнаружения"""
    
    PATH_BASE = '/org/bluez/example/advertisement'
    
    def __init__(self, bus, index):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = 'peripheral'
        self.local_name = DEVICE_NAME
        self.service_uuids = [SERVICE_UUID]
        self.manufacturer_data = None
        self.solicit_uuids = None
        self.service_data = None
        self.discoverable = True
        self.include_tx_power = True
        
        dbus.service.Object.__init__(self, bus, self.path)
    
    def get_properties(self):
        """Получить свойства рекламы"""
        properties = dict()
        properties['Type'] = self.ad_type
        properties['Discoverable'] = dbus.Boolean(self.discoverable)
        
        if self.local_name is not None:
            properties['LocalName'] = dbus.String(self.local_name)
        
        if self.service_uuids is not None:
            properties['ServiceUUIDs'] = dbus.Array(self.service_uuids,
                                                  signature='s')
        
        if self.include_tx_power:
            properties['Includes'] = dbus.Array(["tx-power"], signature='s')
        
        return {'org.bluez.LEAdvertisement1': properties}
    
    @dbus.service.method('org.freedesktop.DBus.Properties',
                         in_signature='s',
                         out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == 'org.bluez.LEAdvertisement1':
            return self.get_properties()
        else:
            raise dbus.exceptions.DBusException(
                'org.freedesktop.DBus.Error.InvalidArgs',
                'Invalid interface')
    
    @dbus.service.method('org.bluez.LEAdvertisement1',
                         in_signature='',
                         out_signature='')
    def Release(self):
        print('Advertisement released')

class GATTApplication(dbus.service.Object):
    """GATT сервер"""
    
    def __init__(self, bus):
        self.bus = bus
        self.path = "/com/example/gatt"
        self.notify_enabled = False
        self.last_value = []
        
        dbus.service.Object.__init__(self, bus, self.path)
        
        # MAC адрес
        mac = get_mac_address()
        print(f"📱 Bluetooth MAC: {mac}")
        
        # Настройка рекламы
        self.advertisement = Advertisement(bus, 0)
        
        # Регистрируем рекламу
        self.register_advertisement()
    
    def register_advertisement(self):
        """Зарегистрировать рекламу"""
        try:
            adapter_path = '/org/bluez/hci0'
            ad_manager = dbus.Interface(
                self.bus.get_object('org.bluez', adapter_path),
                'org.bluez.LEAdvertisingManager1'
            )
            
            ad_manager.RegisterAdvertisement(
                self.advertisement.path,
                {},
                reply_handler=self.register_advertisement_ok,
                error_handler=self.register_advertisement_error
            )
        except Exception as e:
            print(f"⚠️  Could not register advertisement: {e}")
    
    def register_advertisement_ok(self):
        print("📢 Advertisement registered successfully")
    
    def register_advertisement_error(self, error):
        print(f"❌ Advertisement error: {error}")
    
    @dbus.service.method("org.freedesktop.DBus.ObjectManager",
                         out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        """Описание GATT объектов"""
        return {
            dbus.ObjectPath(f"{self.path}/service0"): {
                "org.bluez.GattService1": {
                    "UUID": SERVICE_UUID,
                    "Primary": True,
                }
            },
            dbus.ObjectPath(f"{self.path}/service0/char0"): {
                "org.bluez.GattCharacteristic1": {
                    "UUID": WRITE_UUID,
                    "Service": dbus.ObjectPath(f"{self.path}/service0"),
                    "Flags": ["write", "write-without-response"],
                }
            },
            dbus.ObjectPath(f"{self.path}/service0/char1"): {
                "org.bluez.GattCharacteristic1": {
                    "UUID": NOTIFY_UUID,
                    "Service": dbus.ObjectPath(f"{self.path}/service0"),
                    "Flags": ["notify", "read"],
                }
            },
        }

class WriteCharacteristic(dbus.service.Object):
    def __init__(self, bus, app):
        self.bus = bus
        self.app = app
        self.path = f"{app.path}/service0/char0"
        dbus.service.Object.__init__(self, bus, self.path)
    
    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="aya{sv}",
                         out_signature="")
    def WriteValue(self, value, options):
        data = bytes(value)
        print(f"✏️  Write: {data.hex()}")
        self.app.last_value = list(value)
        
        # Отправляем уведомление
        if self.app.notify_enabled:
            self.send_notification(value)
    
    def send_notification(self, value):
        try:
            notify_obj = self.bus.get_object(None, 
                                           f"{self.app.path}/service0/char1")
            props = dbus.Interface(notify_obj, 
                                 "org.freedesktop.DBus.Properties")
            props.Set("org.bluez.GattCharacteristic1", 
                     "Value", 
                     dbus.Array(value, signature='y'))
            print(f"🔔 Notification sent")
        except Exception as e:
            print(f"❌ Notification failed: {e}")

class NotifyCharacteristic(dbus.service.Object):
    def __init__(self, bus, app):
        self.bus = bus
        self.app = app
        self.path = f"{app.path}/service0/char1"
        dbus.service.Object.__init__(self, bus, self.path)
    
    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="",
                         out_signature="")
    def StartNotify(self):
        print("🔔 Notifications ON")
        self.app.notify_enabled = True
    
    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="",
                         out_signature="")
    def StopNotify(self):
        print("🔕 Notifications OFF")
        self.app.notify_enabled = False
    
    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="a{sv}",
                         out_signature="ay")
    def ReadValue(self, options):
        return dbus.Array(self.app.last_value or [0x48, 0x69], 
                         signature='y')  # "Hi"

def main():
    print("🚀 Starting GATT Server with Advertising")
    print("=" * 50)
    
    # Проверяем Bluetooth
    if not check_bluetooth():
        print("❌ Bluetooth not available")
        return
    
    # Инициализируем D-Bus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    
    # Создаем сервис
    app = GATTApplication(bus)
    write_char = WriteCharacteristic(bus, app)
    notify_char = NotifyCharacteristic(bus, app)
    
    # Регистрируем GATT приложение
    try:
        gatt_manager = dbus.Interface(
            bus.get_object("org.bluez", "/org/bluez/hci0"),
            "org.bluez.GattManager1"
        )
        
        gatt_manager.RegisterApplication(
            app.path,
            {},
            reply_handler=lambda: print("✅ GATT registered!"),
            error_handler=lambda e: print(f"❌ GATT error: {e}")
        )
        
    except Exception as e:
        print(f"❌ Cannot register GATT: {e}")
        return
    
    print(f"\n📋 Device Name: {DEVICE_NAME}")
    print(f"📱 MAC Address: {get_mac_address()}")
    print(f"🔧 Service UUID: {SERVICE_UUID}")
    print(f"✏️  Write UUID:  {WRITE_UUID}")
    print(f"🔔 Notify UUID: {NOTIFY_UUID}")
    print("\n📡 Device is now ADVERTISING and discoverable!")
    print("⚡ Press Ctrl+C to stop")
    print("=" * 50)
    
    # Запускаем
    try:
        loop = GLib.MainLoop()
        loop.run()
    except KeyboardInterrupt:
        print("\n👋 Stopping...")
        loop.quit()

if __name__ == "__main__":
    # Требуются права для рекламы
    print("Note: This script requires root privileges for advertising")
    print("Running with sudo...")
    
    # Проверяем права
    import os
    if os.geteuid() != 0:
        print("\n⚠️  Please run with sudo:")
        print("   sudo python3 gatt_server.py")
        exit(1)
    
    main()