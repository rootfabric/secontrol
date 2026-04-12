"""Принудительное включение RemoteControl через блок."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    drone = Grid.from_name("taburet3", redis_client=client)
    
    print("🔍 Ищу RemoteControl в блоках...")
    for block in drone.iter_blocks():
        bt = str(getattr(block, 'block_type', ''))
        if 'RemoteControl' in bt:
            state = block.state or {}
            print(f"  Найден: {bt}")
            print(f"  state: {state}")
            print(f"  block_id: {block.block_id}")
            
            # Попробую включить напрямую через команду
            print("\n⚡ Включаю напрямую через блок...")
            # Отправляем команду на включение
            result = drone.send_grid_command("block", payload={
                "cmd": "enable",
                "blockId": int(block.block_id),
            })
            print(f"  Результат: {result}")
            time.sleep(1)
            
            # Проверяем через устройство
            drone.refresh_devices()
            remotes = drone.find_devices_by_type("remote_control")
            if remotes:
                rc = remotes[0]
                t = rc.telemetry or {}
                print(f"  enabled: {t.get('enabled')}")
                print(f"  canControlShip: {t.get('canControlShip')}")
    
    # Альтернатива - включить через блок RemoteControl напрямую
    print("\n🔄 Альтернатива: включение через RemoteControlDevice...")
    remotes = drone.find_devices_by_type("remote_control")
    if remotes:
        rc = remotes[0]
        # Попробуем разные варианты команд
        for cmd in ["enable", "toggle"]:
            print(f"  Команда: {cmd}")
            rc.send_command({"cmd": cmd})
            time.sleep(0.5)
            rc.update()
            t = rc.telemetry or {}
            print(f"    enabled: {t.get('enabled')}")
            if t.get('enabled'):
                break
    
    drone.close()
    client.close()


if __name__ == "__main__":
    main()
