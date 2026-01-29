#!/usr/bin/python3
import subprocess
import time

def setup_simple_ble_server():
    """Простая настройка BLE сервера через командную строку"""
    print("🚀 Setting up Simple BLE Advertisement")
    print("=" * 50)
    
    # Останавливаем любые существующие рекламы
    subprocess.run(['sudo', 'hciconfig', 'hci0', 'noleadv'], check=False)
    time.sleep(1)
    
    # Включаем адаптер
    subprocess.run(['sudo', 'hciconfig', 'hci0', 'up'], check=False)
    
    # Устанавливаем имя
    subprocess.run(['sudo', 'hciconfig', 'hci0', 'name', 'BLE-Test-Server'], check=False)
    
    # Включаем discoverable режим
    subprocess.run(['sudo', 'hciconfig', 'hci0', 'piscan'], check=False)
    
    # Получаем MAC
    result = subprocess.run(['hciconfig', 'hci0'], capture_output=True, text=True)
    for line in result.stdout.split('\n'):
        if 'BD Address' in line:
            for part in line.split():
                if ':' in part and len(part) == 17:
                    print(f"📱 MAC Address: {part}")
    
    print("\n📡 Starting BLE advertisement...")
    print("   Device name: BLE-Test-Server")
    
    # Запускаем рекламу в фоне
    cmd = [
        'sudo', 'hcitool', '-i', 'hci0', 'cmd',
        '0x08', '0x0008',  # OGF=0x08 (LE), OCF=0x0008 (LE Set Advertising Data)
        '0x02',             # Length
        '0x01',             # Flags length
        '0x01',             # Flags type (LE Limited Discoverable Mode)
        '0x02'              # Flags value
    ]
    
    subprocess.run(cmd, check=False)
    
    # Включаем рекламу
    cmd = [
        'sudo', 'hcitool', '-i', 'hci0', 'cmd',
        '0x08', '0x000A',  # OGF=0x08, OCF=0x000A (LE Set Advertise Enable)
        '0x01'             # Enable
    ]
    
    subprocess.run(cmd, check=False)
    
    print("✅ BLE advertisement started!")
    print("\n⚡ Device should now be visible in scans")
    print("   Run in another terminal: sudo hcitool lescan")
    print("\nPress Ctrl+C to stop")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Stopping advertisement...")
        subprocess.run(['sudo', 'hciconfig', 'hci0', 'noleadv'], check=False)

if __name__ == "__main__":
    setup_simple_ble_server()