from uuid import UUID
from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Set, Optional, Any
#from structures.slots import slots
from concurrency.sm.mp import Event
from structures.datadict import DataDict


@dataclass(init = False, slots = True)
class DeviceUuids:
    """
    Структура для хранения UUID сервиса и характеристик BLE устройства
    
    Attributes:
        service (str | UUID): UUID сервиса BLE устройства
        write (Optional[str | UUID]):
            UUID характеристики для записи данных
        notify (Optional[str | UUID]):
            UUID характеристики для получения уведомлений
    """

    service: UUID  # UUID сервиса BLE устройства
    write: Optional[UUID]  # UUID характеристики для записи данных
    notify: Optional[UUID]  # UUID характеристики для получения уведомлений

    def __init__(
            self,
            service: str | UUID,
            write: Optional[str | UUID] = None,
            notify: Optional[str | UUID] = None
        ):

        # Устанавливаем UUID устройства:
        self.service = UUID(str(service))
        self.write = UUID(str(write))
        self.notify = UUID(str(notify))



class BleConfig(DataDict):
    """
    Конфигурация аксессора BLE GATT

    Attributes:
        address (Optional[str]):
            MAC-адрес BLE устройства для подключения
            в формате "XX:XX:XX:XX:XX:XX".  
            Если не передан - считается сервером.  
            На данный момент сервер ожидает новое подключение
            и подключает устройство,
            только после этого начиная обмен данными
    """

    address: Optional[str] = None  # MAC-адрес BLE устройства в формате "XX:XX:XX:XX:XX:XX"


# @slots [todo] Проблема с обработкой декоратора slots для DataDict?
class BaseBle(ABC):
    """
    Аксессор обмена данными посредством BLE GATT
    (Bluetooth Low Energy Generic Attribute Profile)
    """


    @abstractmethod
    def __init__(
            self,
            address: Optional[str] = None, 
            uuids: Optional[DeviceUuids] = None,
            is_server: bool = False,
            server_search_time: float | None = None
        ):
        """
        Инициализация BLE сериал соединения
        
        Args:
            address (str):
                Имя Bluetooth адаптера сервера, для подключения.
                Для сервера можно установить
                только если код запущен от имени администратора.
                Для клиента передавать не обязательно,
                если передан UUID сервиса или используется стандартный
            uuids (Optional[DeviceUuids]):
                Опционально, UUID устройства
                (для сервера - собственные, для клиента - UUID сервера),
                по умолчанию определяются автоматически.
                Для клиента, можно подключаться по UUID сервиса сервера,
                если не передано имя сервера
            is_server (bool):
                Является ли сервером.
                На данный момент сервер ожидает новое подключение
                и подключает устройство,
                только после этого начиная обмен данными
            server_search_time (float | None):
                Только для клиента, сколько времени искать сервер.  
                `None` - бесконечный поиск
        Returns:
            is_connected (bool):
                - `True` - подключение успешно
                - `False` - не удалось подключиться
        """

        self.is_open = False  # BLE GATT соединение пока не установлено


    @abstractmethod
    def set_self_name(self, adapter_name: str) -> bool:
        """
        Установка нового имени Bluetooth адаптера.
        Работает только в случае запуска скрипта от имени администратора

        Args:
            adapter_name (str): Новое имя адаптера, для установки
        Returns:
            is_access (bool): Удалось ли установить новое имя
        """


    @abstractmethod
    def get_self_name(self) -> str:
        """
        Получение имени устройства адаптера из реестра

        Returns:
            adapter_name (str): Текущее установленное имя адаптера
        """
    

    @abstractmethod
    def fileno(self) -> int:
        """
        Получение дескриптора адаптера Bluetooth

        Returns:
            fd (int): Файловый дескриптор устройства Bluetooth
        """


    @abstractmethod
    def get_event(self) -> Event:
        """
        Получение внутреннего ивента, через активацию которого
        можно инициировать пробуждение аксессора

        Returns:
            event (Event): Ивент для пробуждения процесса
        """
    

    @abstractmethod
    def set_event(self, event: Event):
        """
        Установка внешнего ивента для пробуждения процесса
        из другого процесса

        Args:
            event (Event): Внешний ивент с автоматическим сбросом
        """
    

    @property
    @abstractmethod
    def connected(self) -> bool:
        """
        Возвращает статус подключения

        Returns:
            is_connected (bool):
                - `True` - устройство подключено
                - `False` - устройство не подключено
        """


    @property
    @abstractmethod
    def in_waiting(self) -> int:
        """
        Возвращает количество байт в буфере приема

        Returns:
            in_waiting (int): Количество байт ожидающих чтения
        """


    @abstractmethod
    def inWaiting(self) -> int:
        """
        Возвращает количество байт, ожидающих в буфере.
        Для совместимости с pyserial < 3.x

        Returns:
            in_waiting (int): Количество байт, ожидающих в буфере
        """


    @property
    @abstractmethod
    def name(self) -> Optional[str]:
        """
        Возвращает имя подключенного устройства

        Returns:
            name (Optional[str]):
                Имя устройства или None если устройство не подключено
        """


    @property
    @abstractmethod
    def discovered_uuids(self) -> DeviceUuids | None:
        """
        Возвращает обнаруженные UUID для отладки

        Returns:
            uuids (DeviceUuids | None):
                Структура с UUID сервиса и характеристик
                найденного устройства, если получены, иначе `None`
        """
    

    @property
    @abstractmethod
    def is_advertising(self) -> bool:
        """
        Публикует ли сейчас данные сервер

        Returns:
            is_advertising (bool):
                Флаг того, публикует ли сейчас данные сервер
        """
    

    @staticmethod
    @abstractmethod
    def discover(scan_duration: float = 10.) -> Set[Any]:
        """
        Обнаружение BLE устройств в окружении

        Args:
            scan_duration (float):
                Продолжительность сканирования в секундах

        Returns:
            devices_found (Set[Any]):
                Набор структур с информацией
                о найденных BLE устройствах
        """
    

    @staticmethod
    @abstractmethod
    def is_bluetooth_on() -> bool:
        """
        Проверка, включен ли Bluetooth

        Returns:
            is_on (bool): Включён ли Bluetooth
        """


    @staticmethod
    @abstractmethod
    def set_bluetooth_power(state: bool) -> bool:
        """
        Включение или выключение Bluetooth

        Args:
            state (bool): Флаг того, включить Bluetooth или выключить
        Returns:
            is_access (bool): Удалось ли изменить статус Bluetooth
        """


    @abstractmethod
    def advertise(self, timeout: Optional[float] = None) -> bool:
        """
        Запуск публикации сервера и ожидание подключения клиента
        
        Args:
            timeout (float):
                Время ожидания подключения в секундах,
                `None` - бесконечное ожидание
        Returns:
            is_connected (bool): `True` если подключение установлено
        """


    @abstractmethod
    def connect(self, device: Any) -> bool:
        """
        Подключение к BLE устройству

        Args:
            device (Any): Устройство для подключения
        Returns:
            is_connected (bool):
                - `True` - подключение успешно
                - `False` - не удалось подключиться
        """
    

    def run(self):
        """
        Запускаем работу аксессора последовательного обмена данными
        посредством BLE GATT
        """

        self.is_open = True  # BLE GATT соединение установлено
    

    @abstractmethod
    def set_timeout(self, timeout: Optional[float] = None):
        """
        Установка таймаута на ожидание. По умолчанию не установлен

        Args:
            timeout (Optional[float]):
                Таймаут в секундах (`None` - бесконечное ожидание)
        """


    @abstractmethod
    def write(self, data: bytes) -> bool:
        """
        Записывает данные в BLE устройство

        Args:
            data (bytes): Данные для отправки
        Returns:
            is_access (bool):
                - `True` - данные успешно отправлены
                - `False` - не удалось отправить данные
        """


    @abstractmethod
    def receive(self) -> bytes:
        """
        Получение всех доступных данных из буфера.
        Удаляет данные из буфера после чтения

        Returns:
            data (bytes): Данные в виде байт
        """


    @abstractmethod
    def read(self, size: int = 1) -> bytes:
        """
        Блокирующее чтение указанного количества байт.
        Будет ждать, пока не получит >= байт, чем указано

        Args:
            size (int):
                Количество байт, необходимых к прочтению
                (всегда должно быть > 0)
        Returns:
            read_bytes (bytes):
                Необходимое количество байт.
                - `>= size` - по умолчанию
                - Пустой набор байт, если активация внешнего ивента
        """


    @abstractmethod
    def recvall(self, size: int) -> bytes:
        """
        Чтение определённого количества байт
        с использованием метода read, аналог read(size)

        Args:
            size (int): Количество байт для чтения
        Returns:
            bytes (bytes): Прочитанные данные в виде байт
        """


    @abstractmethod
    def read_packet(self) -> bytes:
        """
        Чтение одного пакета данных.
        Кадр начинается с 4-байтового заголовка,
        содержащего длину данных

        Returns:
            packet_data (bytes): Данные фрейма в виде байт
        """


    def close(self):
        """
        Закрытие соединения с BLE устройством и освобождение ресурсов
        """

        self.is_open = False  # BLE GATT соединение отключено