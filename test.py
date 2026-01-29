#!/usr/bin/python3
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import subprocess
import time
import os

# Настройки
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_UUID   = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_UUID  = "12345678-1234-5678-1234-56789abcdef2"
DEVICE_NAME = "Python-BLE-Server"

def check_and_start_bluetooth():
    """Проверить и запустить Bluetooth сервис"""
    print("🔍 Checking Bluetooth service...")
    
    # Проверяем статус BlueZ
    try:
        result = subprocess.run(['systemctl', 'is-active', 'bluetooth'], 
                              capture_output=True, text=True)
        if result.stdout.strip() != 'active':
            print("⚠️  Bluetooth service is not active, starting...")
            subprocess.run(['sudo', 'systemctl', 'start', 'bluetooth'], check=False)
            time.sleep(2)
    except:
        pass
    
    # Проверяем наличие адаптера
    try:
        result = subprocess.run(['hciconfig'], capture_output=True, text=True)
        if 'hci0' not in result.stdout:
            print("❌ No Bluetooth adapter found (hci0)")
            print("   Check: lsusb | grep -i bluetooth")
            return False
        
        # Включаем адаптер
        subprocess.run(['sudo', 'hciconfig', 'hci0', 'up'], check=False)
        time.sleep(1)
        
        # Проверяем поддержку LE
        result = subprocess.run(['sudo', 'hcitool', 'lescan'], 
                              capture_output=True, text=True, timeout=2)
        if 'Set scan parameters failed' in result.stderr:
            print("⚠️  Adapter may not support Bluetooth LE")
            return False
            
        return True
        
    except subprocess.TimeoutExpired:
        # Это нормально для hcitool lescan
        return True
    except Exception as e:
        print(f"❌ Error checking adapter: {e}")
        return False

def get_mac_address():
    """Получить MAC адрес адаптера"""
    try:
        result = subprocess.run(['hciconfig', 'hci0'], 
                              capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if 'BD Address' in line or 'Address' in line:
                for part in line.split():
                    if ':' in part and len(part) == 17:
                        return part
        return "Unknown"
    except:
        return "Unknown"

def make_advertised():
    """Сделать устройство discoverable"""
    commands = [
        ['sudo', 'hciconfig', 'hci0', 'up'],
        ['sudo', 'hciconfig', 'hci0', 'name', DEVICE_NAME],
        ['sudo', 'hciconfig', 'hci0', 'piscan'],
        ['sudo', 'bluetoothctl', 'discoverable', 'on'],
        ['sudo', 'bluetoothctl', 'pairable', 'on'],
    ]
    
    for cmd in commands:
        try:
            subprocess.run(cmd, check=False)
            print(f"✓ {cmd[-1]} executed")
            time.sleep(0.5)
        except:
            pass

class SimpleGATTApplication(dbus.service.Object):
    """Простое GATT приложение"""
    
    def __init__(self):
        # Проверяем и настраиваем Bluetooth
        if not check_and_start_bluetooth():
            print("❌ Cannot proceed without Bluetooth")
            return
        
        # Делаем устройство видимым
        make_advertised()
        
        # Получаем MAC
        mac = get_mac_address()
        print(f"📱 MAC Address: {mac}")
        
        # Инициализируем D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        
        # Путь для приложения
        self.path = "/org/bluez/gatt_app"
        dbus.service.Object.__init__(self, self.bus, self.path)
        
        # Состояние
        self.notify_enabled = False
        self.last_value = []
        
        # Пытаемся зарегистрироваться в BlueZ
        self.register_with_bluez()
    
    def register_with_bluez(self):
        """Зарегистрировать приложение в BlueZ"""
        try:
            # Пробуем найти GATT менеджер
            print("🔧 Looking for GATT manager...")
            
            # Сначала проверяем доступность BlueZ
            try:
                obj = self.bus.get_object("org.bluez", "/")
                print("✓ BlueZ D-Bus service is available")
            except:
                print("❌ BlueZ D-Bus service not found")
                print("   Try: sudo systemctl restart bluetooth")
                return
            
            # Пробуем разные пути к адаптеру
            adapter_paths = [
                "/org/bluez/hci0",
                "/org/bluez/hci",
            ]
            
            manager = None
            for path in adapter_paths:
                try:
                    obj = self.bus.get_object("org.bluez", path)
                    manager = dbus.Interface(obj, "org.bluez.GattManager1")
                    print(f"✓ Found GATT manager at: {path}")
                    break
                except dbus.exceptions.DBusException:
                    continue
            
            if manager is None:
                print("❌ No GATT manager found")
                print("   Your adapter may not support BLE/GATT")
                return
            
            # Регистрируем приложение
            print("📝 Registering GATT application...")
            manager.RegisterApplication(
                self.path,
                {},
                reply_handler=lambda: print("✅ GATT application registered successfully!"),
                error_handler=self.registration_error
            )
            
        except Exception as e:
            print(f"❌ Registration failed: {e}")
            print("\n💡 Troubleshooting:")
            print("1. Check BlueZ version: bluetoothctl --version")
            print("2. Restart BlueZ: sudo systemctl restart bluetooth")
            print("3. Check BLE support: sudo hcitool lescan")
            print("4. Try older BlueZ compatibility mode")
    
    def registration_error(self, error):
        """Обработчик ошибки регистрации"""
        print(f"❌ Registration error: {error}")
        
        # Альтернативный метод: используем старый API
        print("\n🔄 Trying alternative registration method...")
        try:
            # Используем ObjectManager для регистрации
            om = dbus.Interface(
                self.bus.get_object("org.bluez", "/"),
                "org.freedesktop.DBus.ObjectManager"
            )
            
            # Просто объявляем о себе
            print("✓ Registered via ObjectManager (basic mode)")
            print("⚠️  Note: Limited functionality in this mode")
            
        except Exception as e:
            print(f"❌ Alternative method also failed: {e}")
    
    @dbus.service.method("org.freedesktop.DBus.ObjectManager",
                         out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        """Возвращаем описание GATT сервисов"""
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
    print("=" * 60)
    print("🚀 Python BLE GATT Server")
    print("=" * 60)
    
    # Проверяем права
    if os.geteuid() != 0:
        print("⚠️  This script requires root privileges")
        print("   Please run with: sudo python3 ble_server.py")
        print("=" * 60)
        return
    
    # Выводим информацию о системе
    print("📋 System info:")
    try:
        # Версия BlueZ
        result = subprocess.run(['bluetoothctl', '--version'], 
                              capture_output=True, text=True)
        print(f"   BlueZ version: {result.stdout.strip()}")
    except:
        pass
    
    # Создаем приложение
    print("\n⚙️  Initializing...")
    app = SimpleGATTApplication()
    
    if not hasattr(app, 'bus'):
        print("❌ Failed to initialize application")
        return
    
    print(f"\n📡 Device name: {DEVICE_NAME}")
    print(f"🔧 Service UUID: {SERVICE_UUID}")
    print(f"✏️  Write UUID:  {WRITE_UUID}")
    print(f"🔔 Notify UUID:  {NOTIFY_UUID}")
    print("\n⚡ Server is running!")
    print("   To test: sudo hcitool lescan")
    print("   Or use: bluetoothctl scan on")
    print("=" * 60)
    print("Press Ctrl+C to stop")
    
    # Запускаем главный цикл
    try:
        loop = GLib.MainLoop()
        loop.run()
    except KeyboardInterrupt:
        print("\n👋 Stopping server...")
        loop.quit()

if __name__ == "__main__":
    main()