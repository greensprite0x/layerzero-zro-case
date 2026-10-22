# -*- coding: utf-8 -*-
"""
Метрики протокола LayerZero: сообщения и объёмы.

Ключи не нужны. Запуск:  python lz_scan_stats.py
Результаты: папка "lz_stats" + сводка на экране.

Что делает:
  1. Пробует несколько методов LayerZero Scan API и показывает, что реально отдаёт
     сервер. Структура ответа заранее неизвестна, поэтому скрипт печатает её как есть.
  2. Запасной вариант: объёмы мостов Stargate по месяцам с DefiLlama.
  3. Для сверки: сколько сообщений прошло через контракт ZRO в Ethereum за 30 дней
     (это только часть протокола, не весь объём).
"""

import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

OUT_DIR = "lz_stats"
UA = {"User-Agent": "Mozilla/5.0 (research script)", "Accept": "application/json"}
SCAN = "https://scan.layerzero-api.com/v1"


def get(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            code = getattr(e, "code", None)
            if code in (400, 404, 422):
                return {"__error__": f"HTTP {code}"}
            time.sleep(2 * (i + 1))
    return {"__error__": "нет ответа"}


def preview(obj, depth=0, limit=6):
    """Печатает структуру ответа, не вываливая тысячи строк."""
    pad = "      " * (depth + 1)
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:limit]:
            if isinstance(v, (dict, list)):
                size = len(v)
                print(f"{pad}{k}: {type(v).__name__}[{size}]")
                if depth < 2:
                    preview(v, depth + 1, limit)
            else:
                print(f"{pad}{k}: {v}")
        if len(obj) > limit:
            print(f"{pad}... ещё {len(obj) - limit} полей")
    elif isinstance(obj, list) and obj:
        print(f"{pad}первый элемент:")
        preview(obj[0], depth + 1, limit)


def scan_api():
    print("=== 1. LayerZero Scan API ===")
    now = datetime.now(timezone.utc)
    prev = (now.replace(day=1) - timedelta(days=1))
    candidates = [
        ("статистика за текущий месяц", f"{SCAN}/messages/month/{now:%Y-%m}"),
        ("статистика за прошлый месяц", f"{SCAN}/messages/month/{prev:%Y-%m}"),
        ("то же, формат с днём", f"{SCAN}/messages/month/{now:%Y-%m-01}"),
        ("последние сообщения", f"{SCAN}/messages/latest"),
        ("сводка (если есть)", f"{SCAN}/stats"),
        ("аналитика (если есть)", f"{SCAN}/analytics"),
    ]
    saved = {}
    for name, url in candidates:
        print(f"\n   {name}\n   {url}")
        data = get(url)
        if isinstance(data, dict) and "__error__" in data:
            print(f"      не сработало: {data['__error__']}")
            continue
        print("      ответ получен, структура:")
        preview(data)
        saved[name] = data
        time.sleep(1)

    if saved:
        with open(os.path.join(OUT_DIR, "scan_api_ответы.json"), "w", encoding="utf-8") as f:
            json.dump(saved, f, ensure_ascii=False, indent=2)
        print("\n   Полные ответы сохранены в scan_api_ответы.json")
    else:
        print("\n   Scan API не отдал сводных данных: он рассчитан на поиск отдельных")
        print("   сообщений. Цифры за 30 дней придётся взять с главной layerzeroscan.com.")


def stargate_volume():
    print("\n=== 2. Объёмы Stargate (DefiLlama) ===")
    ids = get("https://bridges.llama.fi/bridges")
    target = None
    if isinstance(ids, dict):
        for b in ids.get("bridges", []):
            if "stargate" in str(b.get("name", "")).lower():
                target = b
                break
    if not target:
        print("   не нашёл Stargate в списке мостов")
        return
    print(f"   Мост: {target.get('displayName') or target.get('name')} (id {target.get('id')})")
    for k in ("lastDailyVolume", "dayBeforeLastVolume", "weeklyVolume", "monthlyVolume"):
        if target.get(k) is not None:
            print(f"   {k}: ${target[k]:,.0f}".replace(",", " "))

    data = get(f"https://bridges.llama.fi/bridgevolume/all?id={target.get('id')}")
    if isinstance(data, list) and data:
        monthly = {}
        for row in data:
            ts = int(row.get("date", 0))
            m = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")
            v = (row.get("depositUSD") or 0) + (row.get("withdrawUSD") or 0)
            monthly[m] = monthly.get(m, 0) + v
        print("   Объём по месяцам (депозиты + выводы):")
        for m in sorted(monthly)[-6:]:
            print(f"     {m}: ${monthly[m]:,.0f}".replace(",", " "))
        with open(os.path.join(OUT_DIR, "stargate_объёмы.csv"), "w", encoding="utf-8-sig") as f:
            f.write("Месяц;Объём $\n")
            for m in sorted(monthly):
                f.write(f"{m};{monthly[m]:.0f}\n")


def zro_messages():
    print("\n=== 3. Сверка: кросс-чейн-переводы самого ZRO за 30 дней ===")
    print("   (только токен ZRO в Ethereum — малая часть протокола, для масштаба)")
    zro = "0x6985884c4392d348587b19cb9eaaf157f13271cd"
    burn = "0x0000000000000000000000000000000000000000"
    url = ("https://api.etherscan.io/v2/api?chainid=1&module=account&action=tokentx"
           f"&contractaddress={zro}&address={burn}&page=1&offset=1000&sort=desc")
    data = get(url)
    res = data.get("result") if isinstance(data, dict) else None
    if not isinstance(res, list) or not res:
        print("   не удалось получить (для Etherscan нужен ключ; это необязательный шаг)")
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    recent = [t for t in res if datetime.fromtimestamp(int(t["timeStamp"]), tz=timezone.utc) > cutoff]
    out = sum(int(t["value"]) for t in recent if t["from"].lower() == burn) / 1e18
    inc = sum(int(t["value"]) for t in recent if t["to"].lower() == burn) / 1e18
    print(f"   Выпущено в Ethereum (пришло из других сетей): {out:,.0f} ZRO".replace(",", " "))
    print(f"   Сожжено в Ethereum (ушло в другие сети): {inc:,.0f} ZRO".replace(",", " "))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for step in (scan_api, stargate_volume, zro_messages):
        try:
            step()
        except Exception as e:
            print(f"   ! шаг {step.__name__}: {e}")
    print(f"\nГотово. Файлы в папке: {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    main()
