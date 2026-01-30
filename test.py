#!/usr/bin/env python3
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import sys
import uuid

# UUID для сервиса и характеристик
SERVICE_UUID = "12345678-1234-1234-1234-123456789ABC"
WRITE_CHAR_UUID = "12345678-1234-1234-1234-123456789ABD"
NOTIFY_CHAR_UUID = "12345678-1234-1234-1234-123456789ABE"

class GATTApplication(dbus.service.Object):
    def __init__(self, bus, path):
        super().__init__(bus, path)
        self.bus = bus
        self.path = path
        self.notify_value = dbus.Array([], signature='y')
        self.notify_properties_changed = None

class GATTService(dbus.service.Object):
    def __init__(self, bus, index, uuid, primary):
        super().__init__(bus, '/org/bluez/example/service' + str(index))
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []

class GATTCharacteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        super().__init__(bus, '/org/bluez/example/service' + str(service.index) + '/char' + str(index))
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.value = dbus.Array([], signature='y')
        self.notifying = False
        service.characteristics.append(self)

    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        print(f"Read value: {list(self.value)}")
        return self.value

    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='aya{sv}')
    def WriteValue(self, value, options):
        print(f"Write value: {list(value)}")
        self.value = value
        
        # Пересылаем данные в notify характеристику
        if self.uuid == WRITE_CHAR_UUID:
            self.forward_to_notify(value)

    def forward_to_notify(self, value):
        # Находим notify характеристику в том же сервисе
        for char in self.service.characteristics:
            if char.uuid == NOTIFY_CHAR_UUID:
                char.value = value
                char.PropertiesChanged(
                    'org.bluez.GattCharacteristic1',
                    {'Value': dbus.Array(value, signature='y')},
                    []
                )
                print(f"Forwarded to notify: {list(value)}")
                break

    @dbus.service.method('org.bluez.GattCharacteristic1')
    def StartNotify(self):
        if not self.notifying:
            self.notifying = True
            print(f"Start notify: {self.uuid}")

    @dbus.service.method('org.bluez.GattCharacteristic1')
    def StopNotify(self):
        if self.notifying:
            self.notifying = False
            print(f"Stop notify: {self.uuid}")

    @dbus.service.signal('org.freedesktop.DBus.Properties', signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    @dbus.service.method('org.freedesktop.DBus.Properties', in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == 'org.bluez.GattCharacteristic1':
            return {
                'Service': self.service.path,
                'UUID': self.uuid,
                'Flags': self.flags,
                'Value': self.value,
                'Notifying': dbus.Boolean(self.notifying)
            }
        else:
            return {}

def register_gatt_application():
    bus = dbus.SystemBus()
    
    # Получаем объект BlueZ
    bluez_object = bus.get_object('org.bluez', '/org/bluez')
    adapter = dbus.Interface(bluez_object, 'org.bluez.GattManager1')
    
    # Создаем сервис
    service = GATTService(bus, 0, SERVICE_UUID, True)
    
    # Создаем характеристики
    write_char = GATTCharacteristic(
        bus, 0, WRITE_CHAR_UUID, 
        ['write', 'write-without-response'], 
        service
    )
    
    notify_char = GATTCharacteristic(
        bus, 1, NOTIFY_CHAR_UUID, 
        ['read', 'notify'], 
        service
    )
    
    # Создаем приложение
    app = GATTApplication(bus, '/org/bluez/example/app')
    
    # Регистрируем приложение
    adapter.RegisterApplication(app.path, {})
    print("GATT application registered")
    return app, service, write_char, notify_char

def start_advertising():
    bus = dbus.SystemBus()
    
    # Находим первый рекламный адаптер
    objects = bus.get_object('org.bluez', '/')
    object_manager = dbus.Interface(objects, 'org.freedesktop.DBus.ObjectManager')
    managed_objects = object_manager.GetManagedObjects()
    
    adapter_path = None
    for path, interfaces in managed_objects.items():
        if 'org.bluez.Adapter1' in interfaces:
            adapter_path = path
            break
    
    if not adapter_path:
        raise Exception("No Bluetooth adapter found")
    
    # Получаем адаптер
    adapter = dbus.Interface(
        bus.get_object('org.bluez', adapter_path),
        'org.bluez.Adapter1'
    )
    
    # Включаем рекламу
    le_advertising_manager = dbus.Interface(
        bus.get_object('org.bluez', adapter_path),
        'org.bluez.LEAdvertisingManager1'
    )
    
    # Создаем рекламные данные
    ad_data = {
        'Type': 'peripheral',
        'ServiceUUIDs': dbus.Array([SERVICE_UUID], signature='s'),
        'IncludeTxPower': dbus.Boolean(True),
        'LocalName': dbus.String('SimpleGATTServer'),
        'ManufacturerData': dbus.Dictionary({0xFFFF: dbus.Array([0x01, 0x02], signature='y')}, signature='qv')
    }
    
    # Регистрируем рекламный объект
    class Advertisement(dbus.service.Object):
        def __init__(self, bus, index):
            super().__init__(bus, '/org/bluez/example/advertisement' + str(index))
            self.type = 'peripheral'
            self.service_uuids = [SERVICE_UUID]
            self.local_name = 'SimpleGATTServer'
            self.include_tx_power = True
        
        @dbus.service.method('org.bluez.LEAdvertisement1', out_signature='a{sv}')
        def GetProperties(self):
            return {
                'Type': self.type,
                'ServiceUUIDs': dbus.Array(self.service_uuids, signature='s'),
                'LocalName': dbus.String(self.local_name),
                'IncludeTxPower': dbus.Boolean(self.include_tx_power)
            }
        
        @dbus.service.method('org.bluez.LEAdvertisement1')
        def Release(self):
            print("Advertisement released")
    
    advertisement = Advertisement(bus, 0)
    
    # Регистрируем рекламу
    le_advertising_manager.RegisterAdvertisement(
        advertisement.path,
        {}
    )
    print("Advertisement started")
    
    # Включаем адаптер
    adapter.Powered = True
    print(f"Adapter {adapter_path} powered on")
    
    return advertisement

if __name__ == "__main__":
    # Инициализируем DBus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    
    try:
        # Запускаем рекламу
        advertisement = start_advertising()
        
        # Регистрируем GATT приложение
        app, service, write_char, notify_char = register_gatt_application()
        
        print(f"""
        BLE GATT Server Started!
        Service UUID: {SERVICE_UUID}
        Write Characteristic UUID: {WRITE_CHAR_UUID}
        Notify Characteristic UUID: {NOTIFY_CHAR_UUID}
        
        Server is advertising as 'SimpleGATTServer'
        Waiting for connections...
        """)
        
        # Запускаем главный цикл событий
        loop = GLib.MainLoop()
        loop.run()
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)