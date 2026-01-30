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
import time
import sys

# UUID для сервиса и характеристик
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef2"

# UUID для BLE сервисов и характеристик
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHARACTERISTIC_IFACE = 'org.bluez.GattCharacteristic1'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'

class Advertisement(dbus.service.Object):
    def __init__(self, bus, index):
        self.path = '/com/example/ble/advertisement' + str(index)
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            'Type': 'peripheral',
            'LocalName': dbus.String('Simple BLE Server'),
            'ServiceUUIDs': dbus.Array([SERVICE_UUID], signature='s'),
            'Includes': dbus.Array(['tx-power'], signature='s'),
        }

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == LE_ADVERTISEMENT_IFACE:
            print('GetAll called for advertisement')
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
            'Service': self.service.get_path(),
            'UUID': self.uuid,
            'Flags': dbus.Array(self.flags, signature='s'),
            'Value': dbus.Array(self.value, signature='y'),
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == GATT_CHARACTERISTIC_IFACE:
            return self.get_properties()
        else:
            raise dbus.exceptions.DBusException(
                'org.freedesktop.DBus.Error.InvalidArgs',
                'Invalid interface'
            )

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        print(f'Read value on {self.uuid}: {self.value}')
        return dbus.Array(self.value, signature='y')

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
                    # Используем правильную сигнатуру для PropertiesChanged
                    char.PropertiesChanged(
                        GATT_CHARACTERISTIC_IFACE,
                        {'Value': dbus.Array(value, signature='y')},
                        []
                    )
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
            'UUID': self.uuid,
            'Primary': self.primary,
            'Characteristics': dbus.Array(
                [c.get_path() for c in self.characteristics],
                signature='o'
            )
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == GATT_SERVICE_IFACE:
            return self.get_properties()
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
        
        print('GetManagedObjects called')
        
        for service in self.services:
            service_props = service.get_properties()
            response[service.get_path()] = {GATT_SERVICE_IFACE: service_props}
            print(f'Added service: {service.path}')
            
            for char in service.characteristics:
                char_props = char.get_properties()
                response[char.get_path()] = {GATT_CHARACTERISTIC_IFACE: char_props}
                print(f'Added characteristic: {char.path}')
        
        print(f'Total objects in response: {len(response)}')
        return response

    def add_service(self, service):
        self.services.append(service)

def setup_advertising(advertisement, adapter_path, bus):
    """Настройка рекламы"""
    try:
        print(f'Setting up advertisement on {adapter_path}')
        ad_manager = dbus.Interface(bus.get_object('org.bluez', adapter_path), LE_ADVERTISING_MANAGER_IFACE)
        
        # Проверяем, поддерживается ли реклама
        props = dbus.Interface(bus.get_object('org.bluez', adapter_path), DBUS_PROP_IFACE)
        ad_props = props.GetAll(LE_ADVERTISING_MANAGER_IFACE)
        print(f'Advertising properties: {ad_props}')
        
        # Регистрируем рекламу
        print('Registering advertisement...')
        ad_manager.RegisterAdvertisement(
            advertisement.path,
            {},
            reply_handler=lambda: print('✓ Advertisement registered successfully'),
            error_handler=lambda error: print(f'✗ Failed to register advertisement: {error}')
        )
        return True
    except dbus.exceptions.DBusException as e:
        print(f'DBus error setting up advertisement: {e}')
        return False
    except Exception as e:
        print(f'Error setting up advertisement: {e}')
        return False

def setup_gatt(application, adapter_path, bus):
    """Настройка GATT сервера"""
    try:
        print(f'Setting up GATT on {adapter_path}')
        gatt_manager = dbus.Interface(bus.get_object('org.bluez', adapter_path), GATT_MANAGER_IFACE)
        
        # Регистрируем приложение
        print('Registering application...')
        gatt_manager.RegisterApplication(
            application.path,
            {},
            reply_handler=lambda: print('✓ Application registered successfully'),
            error_handler=lambda error: print(f'✗ Failed to register application: {error}')
        )
        return True
    except Exception as e:
        print(f'Error setting up GATT: {e}')
        return False

def find_adapter(bus):
    """Поиск Bluetooth адаптера с поддержкой LE Advertising"""
    try:
        print('Looking for Bluetooth adapter...')
        remote_om = dbus.Interface(bus.get_object('org.bluez', '/'), DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()

        for path, interfaces in objects.items():
            if LE_ADVERTISING_MANAGER_IFACE in interfaces:
                print(f'Found adapter with LE Advertising support: {path}')
                # Проверяем, включен ли адаптер
                if 'org.bluez.Adapter1' in interfaces:
                    adapter_props = interfaces['org.bluez.Adapter1']
                    powered = adapter_props.get('Powered', False)
                    if not powered:
                        print('Adapter is not powered. Powering on...')
                        adapter = dbus.Interface(bus.get_object('org.bluez', path), DBUS_PROP_IFACE)
                        adapter.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
                        time.sleep(1)
                return path
        
        print('No adapter with LE Advertising support found')
        return None
    except Exception as e:
        print(f'Error finding adapter: {e}')
        return None

def main():
    print('=' * 50)
    print('Starting Simple BLE GATT Server')
    print('=' * 50)
    
    # Проверка прав
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        print('ERROR: This script must be run as root (sudo)')
        print('Please run: sudo python3 ble_server.py')
        sys.exit(1)
    
    # Инициализация DBus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    
    # Находим адаптер Bluetooth
    adapter_path = find_adapter(bus)
    if not adapter_path:
        print('ERROR: No suitable Bluetooth adapter found')
        print('Please make sure:')
        print('1. Bluetooth hardware is present')
        print('2. Bluetooth service is running: sudo systemctl start bluetooth')
        print('3. Adapter supports LE Advertising (Bluetooth 4.0+)')
        sys.exit(1)
    
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
    
    # Создаем рекламу
    advertisement = Advertisement(bus, 0)
    
    # Даем время для инициализации
    print('Initializing services...')
    time.sleep(2)
    
    # Настраиваем GATT
    if not setup_gatt(app, adapter_path, bus):
        print('ERROR: Failed to setup GATT server')
        sys.exit(1)
    
    # Даем время для регистрации GATT
    time.sleep(2)
    
    # Настраиваем рекламу
    if not setup_advertising(advertisement, adapter_path, bus):
        print('ERROR: Failed to setup advertising')
        print('Continuing without advertising...')
    
    print('=' * 50)
    print('BLE GATT Server запущен!')
    print(f'Service UUID: {SERVICE_UUID}')
    print(f'Write UUID: {WRITE_CHAR_UUID}')
    print(f'Notify UUID: {NOTIFY_CHAR_UUID}')
    print('=' * 50)
    print('Ожидание подключения...')
    print('Для тестирования можно использовать:')
    print('1. nRF Connect на телефоне')
    print('2. bluetoothctl на Linux:')
    print('   sudo bluetoothctl')
    print('   power on')
    print('   scan on')
    print('   connect <адрес>')
    print('=' * 50)
    print('Для выхода нажмите Ctrl+C')
    print('=' * 50)
    
    try:
        # Запускаем GLib main loop
        loop = GLib.MainLoop()
        loop.run()
    except KeyboardInterrupt:
        print('\nСервер остановлен')
    except Exception as e:
        print(f'Error in main loop: {e}')

if __name__ == '__main__':
    import os
    main()