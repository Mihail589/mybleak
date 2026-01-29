#!/usr/bin/python3
import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib
import subprocess
import time

BLUEZ_SERVICE_NAME = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
ADAPTER_IFACE = "org.bluez.Adapter1"
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
        print(f"WRITE received ({len(data_bytes)} bytes): {data_bytes.hex()}")

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
                print(f"Notified notify-characteristic with: {data_bytes.hex()}")
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
        if not self.notifying:
            self.notifying = True
            print(f"StartNotify called on {self.path}")

    # Notify Stop
    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def StopNotify(self):
        if self.notifying:
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
        # По умолчанию читаем CCCD как disabled (0x00 0x00)
        return dbus.ByteArray(b"\x00\x00")


# ============================================================
# Helper Functions
# ============================================================
def check_bluetooth_status():
    """Проверить статус Bluetooth служб"""
    try:
        # Проверяем, запущен ли bluetooth сервис
        result = subprocess.run(['systemctl', 'is-active', 'bluetooth'], 
                              capture_output=True, text=True)
        if result.stdout.strip() != 'active':
            print("Bluetooth service is not active. Trying to start...")
            subprocess.run(['sudo', 'systemctl', 'start', 'bluetooth'], check=False)
            time.sleep(2)
        
        # Проверяем состояние адаптера
        result = subprocess.run(['hciconfig'], capture_output=True, text=True)
        if 'hci0' not in result.stdout:
            print("No Bluetooth adapter found (hci0)")
            return False
            
        print("Bluetooth service is active")
        return True
    except Exception as e:
        print(f"Error checking Bluetooth status: {e}")
        return False

def get_adapter_info(bus):
    """Получить информацию о Bluetooth адаптере"""
    try:
        # Получаем менеджер объектов BlueZ
        obj_manager = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE
        )
        
        # Получаем все объекты
        objects = obj_manager.GetManagedObjects()
        
        print("Searching for Bluetooth adapters...")
        adapters = []
        
        # Ищем все адаптеры
        for path, interfaces in objects.items():
            if ADAPTER_IFACE in interfaces:
                adapter_props = interfaces[ADAPTER_IFACE]
                adapter_info = {
                    'path': str(path),
                    'address': adapter_props.get('Address', 'Unknown'),
                    'name': adapter_props.get('Name', 'Unknown'),
                    'powered': adapter_props.get('Powered', False),
                    'discoverable': adapter_props.get('Discoverable', False),
                    'pairable': adapter_props.get('Pairable', False),
                    'discovering': adapter_props.get('Discovering', False)
                }
                adapters.append(adapter_info)
        
        if not adapters:
            print("No Bluetooth adapters found via D-Bus")
            return None
        
        # Используем первый адаптер
        adapter = adapters[0]
        print(f"\n=== Bluetooth Adapter Information ===")
        print(f"Adapter: {adapter['name']}")
        print(f"MAC Address: {adapter['address']}")
        print(f"Powered: {'Yes' if adapter['powered'] else 'No'}")
        print(f"Discoverable: {'Yes' if adapter['discoverable'] else 'No'}")
        print(f"Pairable: {'Yes' if adapter['pairable'] else 'No'}")
        print(f"Discovering: {'Yes' if adapter['discovering'] else 'No'}")
        print(f"D-Bus Path: {adapter['path']}")
        print("=====================================\n")
        
        # Включаем адаптер если он выключен
        if not adapter['powered']:
            print("Adapter is powered off. Trying to power on...")
            try:
                adapter_obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter['path'])
                adapter_iface = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)
                adapter_iface.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(1))
                print("Adapter powered on successfully")
                time.sleep(1)
            except Exception as e:
                print(f"Failed to power on adapter: {e}")
        
        return adapter['address']
        
    except dbus.exceptions.DBusException as e:
        if "org.freedesktop.DBus.Error.ServiceUnknown" in str(e):
            print("BlueZ service is not running!")
            print("Try running: sudo systemctl start bluetooth")
        elif "org.freedesktop.DBus.Error.AccessDenied" in str(e):
            print("Permission denied! Try running with sudo:")
            print("sudo python3 gatt_server.py")
        else:
            print(f"D-Bus error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error getting adapter info: {e}")
        return None


# ============================================================
# Main
# ============================================================
def main():
    global MAIN_LOOP

    print("=== GATT Server Starting ===")
    
    # Проверяем статус Bluetooth
    if not check_bluetooth_status():
        print("\nTroubleshooting steps:")
        print("1. Check if Bluetooth adapter is physically present: lsusb | grep -i bluetooth")
        print("2. Check kernel module: lsmod | grep bt")
        print("3. Start Bluetooth service: sudo systemctl start bluetooth")
        print("4. Enable Bluetooth: sudo systemctl enable bluetooth")
        print("5. Check adapter: sudo hciconfig hci0 up")
        return

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    
    try:
        bus = dbus.SystemBus()
    except dbus.exceptions.DBusException as e:
        print(f"Failed to connect to system D-Bus: {e}")
        print("Make sure D-Bus is running: sudo systemctl start dbus")
        return

    # Получаем и выводим информацию об адаптере
    mac_address = get_adapter_info(bus)
    if not mac_address:
        print("Cannot proceed without a Bluetooth adapter")
        return

    # Get BlueZ objects
    try:
        # Пробуем разные пути к адаптеру
        adapter_paths = ["/org/bluez/hci0", "/org/bluez/hci"]
        manager = None
        
        for path in adapter_paths:
            try:
                obj = bus.get_object(BLUEZ_SERVICE_NAME, path)
                manager = dbus.Interface(obj, GATT_MANAGER_IFACE)
                print(f"Using adapter at path: {path}")
                break
            except dbus.exceptions.DBusException:
                continue
        
        if manager is None:
            # Пробуем найти адаптер через ObjectManager
            obj_manager = dbus.Interface(
                bus.get_object(BLUEZ_SERVICE_NAME, "/"),
                DBUS_OM_IFACE
            )
            objects = obj_manager.GetManagedObjects()
            
            for path, interfaces in objects.items():
                if GATT_MANAGER_IFACE in interfaces:
                    obj = bus.get_object(BLUEZ_SERVICE_NAME, path)
                    manager = dbus.Interface(obj, GATT_MANAGER_IFACE)
                    print(f"Found GATT manager at: {path}")
                    break
        
        if manager is None:
            print("No GATT manager interface found!")
            print("Make sure your Bluetooth adapter supports Bluetooth LE (Low Energy)")
            return
            
    except dbus.exceptions.DBusException as e:
        print(f"Error accessing Bluetooth adapter: {e}")
        print("Make sure you have proper permissions (try running with sudo)")
        print(f"Error details: {e.get_dbus_message()}")
        return

    app = Application(bus)
    service = Service(bus, 0, SERVICE_UUID, True)
    app.add_service(service)

    # Write characteristic
    write_char = Characteristic(bus, 0, WRITE_UUID, 
                                ["write", "write-without-response"], service)
    service.add_characteristic(write_char)

    # Notify characteristic
    notify_char = Characteristic(bus, 1, NOTIFY_UUID, 
                                 ["notify", "read"], service)
    service.add_characteristic(notify_char)

    # CCCD descriptor for notify
    cccd = Descriptor(bus, 0, "00002902-0000-1000-8000-00805f9b34fb", 
                      ["read", "write"], notify_char)
    notify_char.add_descriptor(cccd)

    # Свяжем write-характеристику с notify-характеристикой — чтобы WriteValue мог отправлять уведомления
    write_char.notify_target = notify_char

    print("\n=== GATT Service Information ===")
    print(f"Service UUID: {SERVICE_UUID}")
    print(f"Write characteristic UUID: {WRITE_UUID}")
    print(f"Notify characteristic UUID: {NOTIFY_UUID}")
    print(f"CCCD UUID: 00002902-0000-1000-8000-00805f9b34fb")
    print("=================================\n")

    print("Registering GATT application…")
    manager.RegisterApplication(app.get_path(), {},
                                reply_handler=lambda: print("✓ GATT application registered successfully"),
                                error_handler=lambda e: print(f"✗ Failed to register application: {e}"))

    print("\nServer is running. Press Ctrl+C to stop.")
    print(f"You can connect to this device using MAC address: {mac_address}")

    try:
        MAIN_LOOP = GLib.MainLoop()
        MAIN_LOOP.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
        MAIN_LOOP.quit()
    except Exception as e:
        print(f"Error in main loop: {e}")


if __name__ == "__main__":
    main()