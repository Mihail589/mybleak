#!/usr/bin/python3
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import subprocess

# Настройки
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_UUID   = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_UUID  = "12345678-1234-5678-1234-56789abcdef2"

def get_mac_address():
    """Получить MAC адрес Bluetooth адаптера"""
    try:
        # Простой способ через hciconfig
        result = subprocess.run(
            ['hciconfig', 'hci0'],
            capture_output=True,
            text=True
        )
        
        for line in result.stdout.split('\n'):
            if 'BD Address' in line or 'Address' in line:
                parts = line.split()
                for part in parts:
                    if ':' in part and len(part) == 17:
                        return part
                        
        print("❌ MAC address not found in hciconfig")
        return "Unknown"
        
    except Exception as e:
        print(f"❌ Error getting MAC: {e}")
        return "Unknown"

class GATTApplication(dbus.service.Object):
    """Простое GATT приложение"""
    
    def __init__(self, bus):
        self.bus = bus
        self.path = "/com/example/gatt"
        self.notify_enabled = False
        self.last_value = []
        
        # Регистрируем объект в D-Bus
        dbus.service.Object.__init__(self, bus, self.path)
        
        # Выводим MAC адрес
        mac = get_mac_address()
        print(f"📱 Bluetooth MAC: {mac}")
    
    @dbus.service.method("org.freedesktop.DBus.ObjectManager",
                         out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        """Возвращаем описание всех GATT объектов"""
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
                    "Flags": ["write"],
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
        print(f"✏️  Received data: {data.hex()}")
        
        # Сохраняем значение
        self.app.last_value = list(value)
        
        # Если уведомления включены - отправляем
        if self.app.notify_enabled:
            self.send_notification(value)
    
    def send_notification(self, value):
        """Отправить уведомление"""
        try:
            # Получаем объект notify характеристики
            notify_path = f"{self.app.path}/service0/char1"
            obj = self.bus.get_object(None, notify_path)
            
            # Создаем интерфейс Properties
            props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
            
            # Отправляем изменение свойства Value
            props.Set("org.bluez.GattCharacteristic1", 
                     "Value", 
                     dbus.Array(value, signature='y'))
            
            print(f"🔔 Notification sent: {bytes(value).hex()}")
            
        except Exception as e:
            print(f"❌ Failed to send notification: {e}")

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
        print("🔔 Notifications enabled")
        self.app.notify_enabled = True
    
    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="",
                         out_signature="")
    def StopNotify(self):
        print("🔕 Notifications disabled")
        self.app.notify_enabled = False
    
    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="a{sv}",
                         out_signature="ay")
    def ReadValue(self, options):
        """Чтение значения"""
        return dbus.Array(self.app.last_value, signature='y')

def main():
    print("🚀 Starting Simple GATT Server")
    print("=" * 40)
    
    # Инициализируем D-Bus главный цикл
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    
    # Подключаемся к системной шине
    bus = dbus.SystemBus()
    
    # Создаем приложение и характеристики
    app = GATTApplication(bus)
    write_char = WriteCharacteristic(bus, app)
    notify_char = NotifyCharacteristic(bus, app)
    
    try:
        # Получаем GATT менеджер BlueZ
        manager = dbus.Interface(
            bus.get_object("org.bluez", "/org/bluez/hci0"),
            "org.bluez.GattManager1"
        )
        
        # Регистрируем приложение
        manager.RegisterApplication(
            app.path,
            {},
            reply_handler=lambda: print("✅ GATT service registered!"),
            error_handler=lambda e: print(f"❌ Registration error: {e}")
        )
        
    except Exception as e:
        print(f"❌ Bluetooth error: {e}")
        print("\n💡 Try running:")
        print("   sudo systemctl start bluetooth")
        print("   sudo python3 gatt_server.py")
        return
    
    print(f"\n📋 Service UUID: {SERVICE_UUID}")
    print(f"📝 Write UUID:   {WRITE_UUID}")
    print(f"🔔 Notify UUID:  {NOTIFY_UUID}")
    print("\n⚡ Server ready! Press Ctrl+C to stop")
    print("=" * 40)
    
    # Запускаем главный цикл
    try:
        loop = GLib.MainLoop()
        loop.run()
    except KeyboardInterrupt:
        print("\n👋 Stopping...")
        loop.quit()

if __name__ == "__main__":
    main()