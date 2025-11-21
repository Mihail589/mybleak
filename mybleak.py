from base_ble import *
import dbus, time

class BluetoothError(Exception):
    pass

class BleGatt(BaseBle):
    def __init__(self, address: Optional[str] = None, uuids: Optional[DeviceUuids] = None, is_server: bool = False, server_search_time: float | None = None):
        super().__init__(address, uuids, is_server, server_search_time)

        self._busname = "org.bluez"
        self._obj_manager_iface = "org.freedesktop.DBus.ObjectManager"
        self._adapter_iface = "org.bluez.Adapter1"
        self._device_iface = "org.bluez.Device1"
        self._dbussetting()
        self.address = address
        self.uuids = uuids
        if address:
            self.device_path = None
            for path, ifaces in self.manager.GetManagedObjects().items():
                dev = ifaces.get("org.bluez.Device1")
                if dev and dev.get("Address") == address:
                    self.device_path = path
                    
                    break

            if not self.device_path:
                raise Exception("Устройство не найдено")
            self.device = dbus.Interface(self.bus.get_object("org.bluez", self.device_path), "org.bluez.Device1")


    def _dbussetting(self):
        self.bus = dbus.SystemBus()
        self.manager = dbus.Interface(self.bus.get_object(self._busname, "/"), self._obj_manager_iface)
        self.adapter_path = None
        for path, ifaces in self.manager.GetManagedObjects().items():
            if self._adapter_iface in ifaces:
                self.adapter_path = path
                break

        if not self.adapter_path:
            raise BluetoothError("Not Found Bluetooth adapter")
        
        self.adapter = dbus.Interface(
        self.bus.get_object("org.bluez", self.adapter_path),
    self._adapter_iface
    
)
        self.adapter_prob = dbus.Interface(
    self.bus.get_object("org.bluez", self.adapter_path),
    "org.freedesktop.DBus.Properties"
)
    
    def set_self_name(self, adapter_name: str) -> bool:
        return super().set_self_name(adapter_name)
    
    def advertise(self, timeout: Optional[float] = None) -> bool:
        return super().advertise(timeout)
    
    def connect(self, device: Any) -> bool:
        self.device.Connect()
    
    def connected(self) -> bool:
        return super().connected
    
    def discovered_uuids(self) -> DeviceUuids | None:
        return super().discovered_uuids
    
    def discover(self, scan_duration: float = 10.) -> Set[Any]:
        if not self.is_bluetooth_on():
            raise BluetoothError("Bluetooth is off")
        devicelist = []
        self.adapter.StartDiscovery()
        start = time.time()
        while time.time() - start < scan_duration:
            objects = self.manager.GetManagedObjects()
            for path, ifaces in objects.items():
                if self._device_iface in ifaces:
                    props = ifaces[self._device_iface]
                    addr = props.get("Address")
                    name = props.get("Name") or props.get("Alias")
                    data = {"addr": str(addr), "name": str(name)}
                    if addr and data not in devicelist:
                        devicelist.append(data)
            time.sleep(0.01)
        self.adapter.StopDiscovery()
        return devicelist

    def fileno(self) -> int:
        return super().fileno()
    
    def get_event(self) -> Event:
        return super().get_event()
    
    def get_self_name(self) -> str:
        return super().get_self_name()
    
    def inWaiting(self) -> int:
        return super().inWaiting()
    
    def in_waiting(self) -> int:
        return super().in_waiting
    
    def is_advertising(self) -> bool:
        return super().is_advertising
    
    def is_bluetooth_on(self):
        
        

        powered = self.adapter_prob.Get("org.bluez.Adapter1", "Powered")
        return powered
    def name(self) -> Optional[str]:
        return super().name
    
    def read(self, size: int = 1) -> bytes:
        return super().read(size)

    def read_packet(self) -> bytes:
        return super().read_packet()

    def receive(self) -> bytes:
        return super().receive()

    def set_bluetooth_power(self, state: bool) -> bool:
        self.adapter.Set("org.bluez.Adapter1", "Powered", state)

        powered = self.adapter_prob.Get("org.bluez.Adapter1", "Powered")
        if not powered or powered:
            return True
        else:
            return False

    def set_event(self, event: Event):
        return super().set_event(event)

    def set_timeout(self, timeout: Optional[float] = None):
        return super().set_timeout(timeout)
    
    
    def write(self, data: bytes) -> bool:
        
        self.connect(self.address)
    # найти сервис
        service_path = None
        for path, ifaces in self.manager.GetManagedObjects().items():
            svc = ifaces.get("org.bluez.GattService1")
            if svc and svc.get("UUID") == str(self.uuids.service) and svc.get("Device") == self.device_path:
                service_path = path
                break

        if not service_path:
            raise Exception("Сервис не найден")

    # найти характеристику
        char_path = None
        for path, ifaces in self.manager.GetManagedObjects().items():
            chr = ifaces.get("org.bluez.GattCharacteristic1")
            if chr and chr.get("UUID") == str(self.uuids.write) and chr.get("Service") == service_path:
                char_path = path
                break

        if not char_path:
            raise Exception("Характеристика не найдена")

    # запись
        char = dbus.Interface(self.bus.get_object("org.bluez", char_path),
                          "org.bluez.GattCharacteristic1")

        char.WriteValue([dbus.Byte(b) for b in data], {})

        self.device.Disconnect()
        return True
    def recvall(self, size: int) -> bytes:
        return super().recvall(size)
print(BleGatt().discover(2))
print(BleGatt("34:B7:DA:DB:F6:82", DeviceUuids("0000abf0-0000-1000-8000-00805f9b34fb", "0000abf1-0000-1000-8000-00805f9b34fb", "0000abf2-0000-1000-8000-00805f9b34fb")).write(b'$M<\x00\x04\x04'))