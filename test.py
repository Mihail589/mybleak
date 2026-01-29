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

def setup_adapter():
    """Настроить адаптер для обнаружения"""
    commands = [
        ['sudo', 'hciconfig', 'hci0', 'up'],
        ['sudo', 'hciconfig', 'hci0', 'leadv'],
        ['sudo', 'hciconfig', 'hci0', 'piscan'],
        ['sudo', 'hciconfig', 'hci0', 'name', 'Python-GATT-Server'],
    ]
    
    for cmd in commands:
        try:
            subprocess.run(cmd, check=False)
            print(f"✓ {cmd[2:]} executed")
        except:
            pass
    
    # Даем время на применение настроек
    time.sleep(1)

def get_mac():
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

class SimpleGATT(dbus.service.Object):
    def __init__(self):
        # Настраиваем адаптер
        setup_adapter()
        
        # Инициализируем D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()
        
        # Путь для приложения
        self.path = "/test/gatt"
        dbus.service.Object.__init__(self, bus, self.path)
        
        # Состояние
        self.notify = False
        self.value = []
        self.mac = get_mac()
        
        print(f"📱 MAC Address: {self.mac}")
        
        # Регистрируемся в BlueZ
        try:
            obj = bus.get_object("org.bluez", "/org/bluez/hci0")
            manager = dbus.Interface(obj, "org.bluez.GattManager1")
            manager.RegisterApplication(self.path, {})
            print("✅ Registered with BlueZ")
        except Exception as e:
            print(f"❌ Registration failed: {e}")
            return
        
        print(f"\n🔧 Service UUID: {SERVICE_UUID}")
        print(f"✏️  Write UUID:  {WRITE_UUID}")
        print(f"🔔 Notify UUID:  {NOTIFY_UUID}")
        print("\n⚡ Server is running!")
        print("   Use 'sudo hcitool lescan' to find the device")
        print("   Device name: 'Python-GATT-Server'")
        print("\nPress Ctrl+C to stop")
    
    @dbus.service.method("org.freedesktop.DBus.ObjectManager",
                         out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        """Возвращаем структуру GATT сервиса"""
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

def main():
    print("🚀 Starting Simple GATT Server")
    print("=" * 50)
    
    # Проверяем права
    import os
    if os.geteuid() != 0:
        print("⚠️  Please run with sudo:")
        print("   sudo python3 simple_gatt.py")
        exit(1)
    
    # Создаем сервер
    server = SimpleGATT()
    
    # Запускаем главный цикл
    try:
        loop = GLib.MainLoop()
        loop.run()
    except KeyboardInterrupt:
        print("\n👋 Stopping server...")
        loop.quit()

if __name__ == "__main__":
    main()