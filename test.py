#!/usr/bin/env python3
"""
Простой синхронный BLE GATT сервер с использованием dbus-python
Требует установки: sudo apt-get install python3-dbus bluez
Запускать с правами суперпользователя: sudo python3 ble_server.py
"""

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib
import array
import threading
import time

# UUID для сервиса и характеристик
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef2"

# UUID для BLE сервисов и характеристик
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
ADAPTER_IFACE = 'org.bluez.Adapter1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'

GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHARACTERISTIC_IFACE = 'org.bluez.GattCharacteristic1'
GATT_DESCRIPTOR_IFACE = 'org.bluez.GattDescriptor1'

LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'

class Advertisement(dbus.service.Object):
    def __init__(self, bus, index, adapter_path):
        self.path = '/com/example/ble/advertisement' + str(index)
        self.ad_type = 'peripheral'
        self.local_name = 'Simple BLE Server'
        self.service_uuids = [SERVICE_UUID]
        self.solicit_uuids = None
        self.manufacturer_data = None
        self.service_data = None
        self.include_tx_power = False
        dbus.service.Object.__init__(self, bus, self.path)
        self.adapter_path = adapter_path

    def get_properties(self):
        properties = dict()
        properties['Type'] = self.ad_type
        properties['LocalName'] = dbus.String(self.local_name)
        if self.service_uuids is not None:
            properties['ServiceUUIDs'] = dbus.Array(self.service_uuids, signature='s')
        return properties

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == LE_ADVERTISEMENT_IFACE:
            return self.get_properties()
        else:
            raise dbus.exceptions.DBusException(
                'org.freedesktop.DBus.Error.InvalidArgs',
                'Invalid interface'
            )

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature='', out_signature='')
    def Release(self):
        print('Advertisement released')

class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.value = []
        self.notifying = False
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHARACTERISTIC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
                'Value': self.value,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == GATT_CHARACTERISTIC_IFACE:
            return self.get_properties()[GATT_CHARACTERISTIC_IFACE]
        else:
            raise dbus.exceptions.DBusException(
                'org.freedesktop.DBus.Error.InvalidArgs',
                'Invalid interface'
            )

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        print(f'Read value on {self.uuid}: {self.value}')
        return self.value

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        print(f'Write value on {self.uuid}: {value}')
        self.value = value
        
        # Если это write характеристика, отправляем уведомление через notify характеристику
        if self.uuid == WRITE_CHAR_UUID:
            # Находим notify характеристику и отправляем уведомление
            for char in self.service.characteristics:
                if char.uuid == NOTIFY_CHAR_UUID:
                    char.value = value
                    char.PropertiesChanged(GATT_CHARACTERISTIC_IFACE, {'Value': value}, [])
                    print(f'Notified with value: {value}')
                    break

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature='', out_signature='')
    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        print(f'Start notify on {self.uuid}')

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature='', out_signature='')
    def StopNotify(self):
        if not self.notifying:
            return
        self.notifying = False
        print(f'Stop notify on {self.uuid}')

    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

class Service(dbus.service.Object):
    def __init__(self, bus, index, uuid, primary):
        self.path = '/com/example/ble/service' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(
                    [c.get_path() for c in self.characteristics],
                    signature='o'
                )
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == GATT_SERVICE_IFACE:
            return self.get_properties()[GATT_SERVICE_IFACE]
        else:
            raise dbus.exceptions.DBusException(
                'org.freedesktop.DBus.Error.InvalidArgs',
                'Invalid interface'
            )

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = '/com/example/ble/app'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for char in service.characteristics:
                response[char.get_path()] = char.get_properties()
        
        return response

    def add_service(self, service):
        self.services.append(service)

def register_advertisement(advertisement, adapter_path, bus):
    adapter = dbus.Interface(bus.get_object('org.bluez', adapter_path), LE_ADVERTISING_MANAGER_IFACE)
    adapter.RegisterAdvertisement(
        advertisement.get_path(),
        {},
        reply_handler=lambda: print('Advertisement registered successfully'),
        error_handler=lambda error: print(f'Failed to register advertisement: {error}')
    )

def register_application(application, adapter_path, bus):
    adapter = dbus.Interface(bus.get_object('org.bluez', adapter_path), GATT_MANAGER_IFACE)
    adapter.RegisterApplication(
        application.get_path(),
        {},
        reply_handler=lambda: print('Application registered successfully'),
        error_handler=lambda error: print(f'Failed to register application: {error}')
    )

def find_adapter(bus):
    remote_om = dbus.Interface(bus.get_object('org.bluez', '/'), DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()

    for o, props in objects.items():
        if GATT_MANAGER_IFACE in props and LE_ADVERTISING_MANAGER_IFACE in props:
            return o

    return None

def main():
    # Инициализация DBus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    # Находим адаптер Bluetooth
    adapter_path = find_adapter(bus)
    if not adapter_path:
        print('LEAdvertisingManager1 interface not found')
        return

    print(f'Using adapter: {adapter_path}')

    # Создаем приложение
    app = Application(bus)

    # Создаем сервис
    service = Service(bus, 0, SERVICE_UUID, True)

    # Создаем характеристику для записи
    write_char = Characteristic(
        bus, 
        0, 
        WRITE_CHAR_UUID,
        ['write', 'write-without-response'],
        service
    )
    service.add_characteristic(write_char)

    # Создаем характеристику для уведомлений
    notify_char = Characteristic(
        bus,
        1,
        NOTIFY_CHAR_UUID,
        ['read', 'notify'],
        service
    )
    service.add_characteristic(notify_char)

    # Добавляем сервис в приложение
    app.add_service(service)

    # Создаем и регистрируем рекламу
    advertisement = Advertisement(bus, 0, adapter_path)
    
    # Регистрируем приложение
    register_application(app, adapter_path, bus)
    
    # Регистрируем рекламу
    register_advertisement(advertisement, adapter_path, bus)

    print('=' * 50)
    print('BLE GATT Server запущен')
    print(f'Service UUID: {SERVICE_UUID}')
    print(f'Write UUID: {WRITE_CHAR_UUID}')
    print(f'Notify UUID: {NOTIFY_CHAR_UUID}')
    print('=' * 50)
    print('Ожидание подключения...')
    print('Данные, записанные в Write характеристику, будут отправляться через Notify')
    print('Для выхода нажмите Ctrl+C')
    print('=' * 50)

    try:
        # Запускаем GLib main loop
        loop = GLib.MainLoop()
        loop.run()
    except KeyboardInterrupt:
        print('\nСервер остановлен')

if __name__ == '__main__':
    main()