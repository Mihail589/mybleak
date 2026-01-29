#!/usr/bin/python3
import dbus
import dbus.service
from gi.repository import GLib

# Настройки
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_UUID   = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_UUID  = "12345678-1234-5678-1234-56789abcdef2"

class GATTService(dbus.service.Object):
    """
    Простой GATT сервер с одной службой и двумя характеристиками
    """
    
    def __init__(self, bus, path):
        super().__init__(bus, path)
        self.bus = bus
        self.path = path
        
        # Состояние уведомлений
        self.notify_enabled = False
        self.last_value = dbus.Array([], signature='y')
        
        # Создаем службу
        self.service_path = f"{path}/service0"
        self.service = dbus.service.Object(bus, self.service_path)
        
        # Создаем характеристики
        self.write_char_path = f"{self.service_path}/char0"
        self.notify_char_path = f"{self.service_path}/char1"
        
        # Регистрируем методы характеристик
        self.write_char = WriteCharacteristic(bus, self.write_char_path, self)
        self.notify_char = NotifyCharacteristic(bus, self.notify_char_path, self)
        
        # Выводим MAC адрес адаптера
        self.print_mac_address()

    def print_mac_address(self):
        """Получить и вывести MAC адрес Bluetooth адаптера"""
        try:
            # Получаем системную шину
            system_bus = dbus.SystemBus()
            
            # Получаем менеджер объектов BlueZ
            manager = dbus.Interface(
                system_bus.get_object("org.bluez", "/"),
                "org.freedesktop.DBus.ObjectManager"
            )
            
            # Ищем адаптеры
            objects = manager.GetManagedObjects()
            for path, interfaces in objects.items():
                if "org.bluez.Adapter1" in interfaces:
                    adapter = interfaces["org.bluez.Adapter1"]
                    if "Address" in adapter:
                        mac = adapter["Address"]
                        print(f"📱 Bluetooth MAC Address: {mac}")
                        return mac
            
            print("⚠️  Bluetooth adapter not found")
            return None
            
        except Exception as e:
            print(f"❌ Error getting MAC address: {e}")
            return None

    @dbus.service.method("org.freedesktop.DBus.ObjectManager",
                         out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        """Возвращаем все объекты GATT"""
        result = {
            dbus.ObjectPath(self.service_path): {
                "org.bluez.GattService1": {
                    "UUID": SERVICE_UUID,
                    "Primary": True,
                }
            },
            dbus.ObjectPath(self.write_char_path): {
                "org.bluez.GattCharacteristic1": {
                    "UUID": WRITE_UUID,
                    "Service": dbus.ObjectPath(self.service_path),
                    "Flags": ["write", "write-without-response"],
                }
            },
            dbus.ObjectPath(self.notify_char_path): {
                "org.bluez.GattCharacteristic1": {
                    "UUID": NOTIFY_UUID,
                    "Service": dbus.ObjectPath(self.service_path),
                    "Flags": ["notify", "read"],
                }
            }
        }
        return result

    def send_notification(self, value):
        """Отправить уведомление клиенту"""
        if self.notify_enabled:
            print(f"🔔 Sending notification: {bytes(value).hex()}")
            self.notify_char.PropertiesChanged(
                "org.bluez.GattCharacteristic1",
                {"Value": value},
                []
            )


class WriteCharacteristic(dbus.service.Object):
    """Характеристика для записи данных"""
    
    def __init__(self, bus, path, gatt_service):
        super().__init__(bus, path)
        self.gatt_service = gatt_service

    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="aya{sv}",
                         out_signature="")
    def WriteValue(self, value, options):
        """Обработчик записи"""
        data = bytes(value)
        print(f"✏️  Write received: {data.hex()} ({len(data)} bytes)")
        
        # Отправляем уведомление с теми же данными
        self.gatt_service.send_notification(value)

    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="a{sv}",
                         out_signature="ay")
    def ReadValue(self, options):
        """Обработчик чтения (возвращаем тестовые данные)"""
        return dbus.Array([0x4F, 0x4B], signature='y')  # "OK" в hex


class NotifyCharacteristic(dbus.service.Object):
    """Характеристика для уведомлений"""
    
    def __init__(self, bus, path, gatt_service):
        super().__init__(bus, path)
        self.gatt_service = gatt_service

    @dbus.service.signal("org.freedesktop.DBus.Properties",
                         signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        """Сигнал об изменении свойств (для уведомлений)"""
        pass

    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="",
                         out_signature="")
    def StartNotify(self):
        """Включить уведомления"""
        self.gatt_service.notify_enabled = True
        print("🔔 Notifications enabled")

    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="",
                         out_signature="")
    def StopNotify(self):
        """Выключить уведомления"""
        self.gatt_service.notify_enabled = False
        print("🔕 Notifications disabled")

    @dbus.service.method("org.bluez.GattCharacteristic1",
                         in_signature="a{sv}",
                         out_signature="ay")
    def ReadValue(self, options):
        """Обработчик чтения (возвращаем последнее значение)"""
        return self.gatt_service.last_value


def main():
    """Главная функция"""
    print("🚀 Starting Simple GATT Server")
    print("=" * 40)
    
    # Настраиваем D-Bus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    
    # Создаем GATT службу
    service = GATTService(bus, "/com/example/gatt")
    
    try:
        # Регистрируем приложение в BlueZ
        manager = dbus.Interface(
            bus.get_object("org.bluez", "/org/bluez/hci0"),
            "org.bluez.GattManager1"
        )
        
        manager.RegisterApplication(
            service.path,
            {},
            reply_handler=lambda: print("✅ GATT service registered successfully"),
            error_handler=lambda e: print(f"❌ Registration failed: {e}")
        )
        
    except Exception as e:
        print(f"❌ Cannot access Bluetooth adapter: {e}")
        print("\nTroubleshooting tips:")
        print("1. Make sure Bluetooth is enabled: sudo systemctl start bluetooth")
        print("2. Check if adapter exists: hciconfig")
        print("3. Try running with sudo: sudo python3 simple_gatt.py")
        return
    
    print("\n📋 Service Information:")
    print(f"   Service UUID: {SERVICE_UUID}")
    print(f"   Write UUID:   {WRITE_UUID}")
    print(f"   Notify UUID:  {NOTIFY_UUID}")
    print("\n⚡ Server is running. Press Ctrl+C to stop.")
    print("=" * 40)
    
    # Запускаем главный цикл
    try:
        loop = GLib.MainLoop()
        loop.run()
    except KeyboardInterrupt:
        print("\n👋 Stopping server...")
        loop.quit()


if __name__ == "__main__":
    main()