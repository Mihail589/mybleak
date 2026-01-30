#!/usr/bin/env python3
"""
Рабочий BLE GATT сервер с правильной рекламой
"""

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib
import time
import sys
import os
import subprocess
import uuid

# UUID для сервиса и характеристик
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
WRITE_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef2"

class Advertisement(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/advertisement'

    def __init__(self, bus, index):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.index = index
        self.local_name = "BLE-Server"
        self.service_uuids = [SERVICE_UUID]
        self.manufacturer_data = None
        self.solicit_uuids = None
        self.service_data = None
        self.include_tx_power = True
        self.discoverable = True
        dbus.service.Object.__init__(self, bus, self.path)
        print(f"Advertisement created at {self.path}")

    def get_properties(self):
        properties = {
            'Type': 'peripheral',
            'LocalName': dbus.String(self.local_name),
            'ServiceUUIDs': dbus.Array(self.service_uuids, signature='s'),
        }
        
        if self.discoverable:
            properties['Discoverable'] = dbus.Boolean(self.discoverable)
            
        if self.include_tx_power:
            properties['Includes'] = dbus.Array(['tx-power'], signature='s')
            
        return properties

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == 'org.bluez.LEAdvertisement1':
            print(f"Advertisement GetAll called")
            return self.get_properties()
        raise dbus.exceptions.DBusException(
            'org.freedesktop.DBus.Error.InvalidArgs',
            'Invalid interface'
        )

    @dbus.service.method('org.bluez.LEAdvertisement1', in_signature='', out_signature='')
    def Release(self):
        print(f"Advertisement {self.path} released")

class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.value = []
        self.notifying = False
        dbus.service.Object.__init__(self, bus, path)
        self.path = path
        print(f"Characteristic {uuid} created at {path}")

    def get_properties(self):
        return {
            'Service': self.service.get_path(),
            'UUID': self.uuid,
            'Flags': dbus.Array(self.flags, signature='s'),
            'Value': dbus.Array(self.value, signature='y'),
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == 'org.bluez.GattCharacteristic1':
            return self.get_properties()
        raise dbus.exceptions.DBusException(
            'org.freedesktop.DBus.Error.InvalidArgs',
            'Invalid interface'
        )

    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        print(f"Read {self.uuid}: {self.value}")
        return dbus.Array(self.value, signature='y')

    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        print(f"Write {self.uuid}: {value}")
        self.value = value
        
        if self.uuid == WRITE_CHAR_UUID:
            for char in self.service.characteristics:
                if char.uuid == NOTIFY_CHAR_UUID:
                    char.value = value
                    char.PropertiesChanged(
                        'org.bluez.GattCharacteristic1',
                        {'Value': dbus.Array(value, signature='y')},
                        []
                    )
                    print(f"Notified with: {value}")
                    break

    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='', out_signature='')
    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        print(f"Start notify on {self.uuid}")

    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='', out_signature='')
    def StopNotify(self):
        if not self.notifying:
            return
        self.notifying = False
        print(f"Stop notify on {self.uuid}")

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

class Service(dbus.service.Object):
    def __init__(self, bus, index, uuid, primary):
        path = '/org/bluez/example/service' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        self.path = path
        dbus.service.Object.__init__(self, bus, path)
        print(f"Service {uuid} created at {path}")

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

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == 'org.bluez.GattService1':
            return self.get_properties()
        raise dbus.exceptions.DBusException(
            'org.freedesktop.DBus.Error.InvalidArgs',
            'Invalid interface'
        )

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = '/org/bluez/example/app'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)
        print(f"Application created at {self.path}")

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method('org.freedesktop.DBus.ObjectManager', out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        
        print("GetManagedObjects called")
        
        for service in self.services:
            service_path = service.get_path()
            response[service_path] = {
                'org.bluez.GattService1': service.get_properties()
            }
            print(f"Added service: {service_path}")
            
            for char in service.characteristics:
                char_path = char.get_path()
                response[char_path] = {
                    'org.bluez.GattCharacteristic1': char.get_properties()
                }
                print(f"Added characteristic: {char_path}")
        
        return response

    def add_service(self, service):
        self.services.append(service)

def setup_bluetooth():
    """Настроить Bluetooth перед запуском"""
    print("Setting up Bluetooth...")
    
    commands = [
        "sudo rfkill unblock bluetooth",
        "sudo systemctl start bluetooth",
        "sleep 1",
        "sudo hciconfig hci0 up",
        "sudo hciconfig hci0 leadv",
        "sudo btmgmt --index hci0 bredr off",
        "sudo btmgmt --index hci0 le on",
        "sudo btmgmt --index hci0 connectable on",
        "sudo btmgmt --index hci0 discov on",
        "sudo btmgmt --index hci0 power on",
        "sleep 2",
    ]
    
    for cmd in commands:
        print(f"Running: {cmd}")
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Note: {cmd} returned {result.returncode}")
        except Exception as e:
            print(f"Warning: {cmd} - {e}")
    
    print("Bluetooth setup complete")

def find_adapter(bus):
    """Найти адаптер Bluetooth"""
    try:
        remote_om = dbus.Interface(bus.get_object('org.bluez', '/'), 
                                  'org.freedesktop.DBus.ObjectManager')
        objects = remote_om.GetManagedObjects()
        
        for path, interfaces in objects.items():
            if 'org.bluez.Adapter1' in interfaces:
                print(f"Found adapter: {path}")
                adapter = dbus.Interface(bus.get_object('org.bluez', path),
                                        'org.freedesktop.DBus.Properties')
                
                # Включаем адаптер
                try:
                    powered = adapter.Get('org.bluez.Adapter1', 'Powered')
                    if not powered:
                        print("Powering on adapter...")
                        adapter.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
                        time.sleep(1)
                except:
                    pass
                    
                return path
    except Exception as e:
        print(f"Error finding adapter: {e}")
    
    return None

def setup_advertising(bus, adapter_path, advertisement):
    """Настроить рекламу"""
    try:
        print("Setting up advertising...")
        
        # Сначала получаем объект адаптера
        adapter_obj = bus.get_object('org.bluez', adapter_path)
        adapter = dbus.Interface(adapter_obj, 'org.bluez.LEAdvertisingManager1')
        
        # Регистрируем рекламу
        print(f"Registering advertisement at {advertisement.path}")
        adapter.RegisterAdvertisement(
            advertisement.path,
            {},
            reply_handler=lambda: print("✓ Advertising started successfully"),
            error_handler=lambda e: print(f"✗ Error starting advertising: {e}")
        )
        
        return True
    except dbus.exceptions.DBusException as e:
        print(f"DBus error in setup_advertising: {e}")
        return False
    except Exception as e:
        print(f"Error in setup_advertising: {e}")
        import traceback
        traceback.print_exc()
        return False

def setup_gatt(bus, adapter_path, application):
    """Настроить GATT сервер"""
    try:
        print("Setting up GATT server...")
        
        adapter_obj = bus.get_object('org.bluez', adapter_path)
        gatt_manager = dbus.Interface(adapter_obj, 'org.bluez.GattManager1')
        
        print(f"Registering application at {application.path}")
        gatt_manager.RegisterApplication(
            application.path,
            {},
            reply_handler=lambda: print("✓ GATT server registered successfully"),
            error_handler=lambda e: print(f"✗ Error registering GATT: {e}")
        )
        
        return True
    except Exception as e:
        print(f"Error in setup_gatt: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("=" * 60)
    print("BLE GATT Server")
    print("=" * 60)
    
    # Проверка прав
    if os.geteuid() != 0:
        print("ERROR: Must run as root (use sudo)")
        print("Usage: sudo python3 ble_server.py")
        sys.exit(1)
    
    # Настраиваем Bluetooth
    setup_bluetooth()
    time.sleep(2)
    
    # Инициализация DBus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    
    # Найти адаптер
    adapter_path = find_adapter(bus)
    if not adapter_path:
        print("ERROR: No Bluetooth adapter found")
        sys.exit(1)
    
    print(f"Using adapter: {adapter_path}")
    
    # Создаем приложение
    app = Application(bus)
    
    # Создаем сервис
    service = Service(bus, 0, SERVICE_UUID, True)
    
    # Добавляем характеристики
    write_char = Characteristic(
        bus, 0, WRITE_CHAR_UUID,
        ['write', 'write-without-response'],
        service
    )
    service.add_characteristic(write_char)
    
    notify_char = Characteristic(
        bus, 1, NOTIFY_CHAR_UUID,
        ['read', 'notify'],
        service
    )
    service.add_characteristic(notify_char)
    
    # Добавляем сервис в приложение
    app.add_service(service)
    
    # Создаем рекламу
    advertisement = Advertisement(bus, 0)
    
    # Ждем инициализации
    time.sleep(1)
    
    print("\n" + "=" * 60)
    print("Registering services...")
    print("=" * 60)
    
    # Настраиваем GATT сервер
    if not setup_gatt(bus, adapter_path, app):
        print("WARNING: GATT server setup failed")
    else:
        print("✓ GATT server ready")
    
    time.sleep(1)
    
    # Настраиваем рекламу
    if not setup_advertising(bus, adapter_path, advertisement):
        print("ERROR: Advertising setup failed")
        
        # Попробуем альтернативный метод
        print("\nTrying alternative advertising method...")
        try_manual_advertising()
    else:
        print("✓ Advertising started")
    
    print("\n" + "=" * 60)
    print("SERVER STATUS")
    print("=" * 60)
    print("Device should be advertising as: BLE-Server")
    print(f"Service UUID: {SERVICE_UUID}")
    print("\nCheck if device is visible:")
    print("$ sudo hcitool lescan")
    print("\nTest with nRF Connect or gatttool")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    
    try:
        mainloop = GLib.MainLoop()
        mainloop.run()
    except KeyboardInterrupt:
        print("\nStopping server...")
    except Exception as e:
        print(f"Error: {e}")

def try_manual_advertising():
    """Попробовать ручной запуск рекламы через hcitool"""
    print("\nAttempting manual advertising via hcitool...")
    
    commands = [
        # Останавливаем любую существующую рекламу
        "sudo hciconfig hci0 noleadv",
        # Задаем параметры рекламы
        "sudo hcitool -i hci0 cmd 0x08 0x0008 1E 02 01 1A 1A FF 4C 00 02 15 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00",
        # Включаем рекламу
        "sudo hciconfig hci0 leadv",
        # Показываем статус
        "sudo hciconfig hci0",
    ]
    
    for cmd in commands:
        print(f"$ {cmd}")
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            print(result.stdout)
            if result.stderr:
                print(f"stderr: {result.stderr}")
            time.sleep(0.5)
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()