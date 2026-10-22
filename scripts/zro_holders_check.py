# -*- coding: utf-8 -*-
"""
Проверка крупных держателей ZRO и их контрагентов через Etherscan API (v2).

Нужно только одно: вставить свой API-ключ в строку API_KEY ниже.
Запуск:  python zro_holders_check.py
Результаты: папка "zro_results_v2" рядом со скриптом (CSV открываются в Excel).

Что делает:
  1. По держателям из топ-25: баланс, тип адреса, владельцы Safe, первое поступление,
     переводы после 01.09.2025, переводы 20 числа. Нулевой спам («отравление адреса»)
     считается отдельно и в итоги не попадает.
  2. По контрагентам (куда и откуда шли крупные суммы): тип, баланс, сколько у адреса
     контрагентов (много = похоже на биржу), топ-3 получателя и отправителя.
  3. Все переводы ZRO от 1 млн за 19-21 октября 2026 (UTC).
"""

import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ====== НАСТРОЙКИ: ЗАПОЛНИ ======

API_KEY = "ВСТАВЬ_СЮДА_СВОЙ_КЛЮЧ"

# ====== ДАЛЬШЕ МЕНЯТЬ НИЧЕГО НЕ НУЖНО ======

ADDRESSES = [
    (1,  "LayerZero: Future Initiatives Multisig", "0x8F6449530606A9EFddaC42e05612427dDeBA449C"),
    (2,  "Safe без метки",                         "0x744Dbc48D11415ec5cB2f78609DeA5E1E738DA24"),
    (5,  "Safe без метки (22.5M)",                 "0x806f68Bb6ce8f3100D4745C8b13b36e4f40D8431"),
    (6,  "Кошелёк (22.5M)",                        "0x6e0e32684df6e3aE415aB1146A305bFd03E42427"),
    (7,  "Без метки",                              "0x53326CFB6eC33F18cCb0E23828a133bC6805390c"),
    (8,  "Без метки",                              "0xDA8B6EB4e31A387577C0e20c00c8f7e31cBC18bc"),
    (9,  "Без метки",                              "0x72afAA442B98F71B8Bba9937f95bE764Ab9f97d1"),
    (10, "Без метки",                              "0x637ca60DFB4d3Acbd2ba65aaeD9C6ca564bBF7BF"),
    (11, "Без метки (16 666 666)",                 "0x7be1125E9284ee108850a19f362B111526737CFD"),
    (12, "Без метки (16.4M)",                      "0xC2f31575b97DF563A3BBA2A94e3a0b317ba2D412"),
    (13, "Без метки",                              "0x63be42b40816eB08F6Ea480e5875E6F4668da379"),
    (14, "Без метки",                              "0x3425BD866c5d0CBACb1Fe011E604789456A28F88"),
    (15, "Без метки",                              "0x7c8AAE256203a2aDA50676470bb5E2EAd1F0e705"),
    (17, "Safe без метки (10M)",                   "0x29e5dd2187168f77b68F9e38B0DE7ff3D797f9e3"),
    (18, "Safe без метки (10M)",                   "0x17Ba3D0fE1F4F2380b0b12a4831a926FEAcA2717"),
    (21, "Без метки (8 771 929.82)",               "0x7026b038a643E737f10C175A026C7aaaE556DD53"),
    (23, "Safe без метки",                         "0xDE131676312eb2ac1cB69cAAe8Ae25Cf26Bb6630"),
    (24, "Safe без метки (8.55M)",                 "0x7e98a4643CEfCBe3dDB639afaD95c22513C97Ad0"),
    (25, "Safe без метки (8.55M)",                 "0xF8B81c26782DFf6c79b82a65363B23580558F137"),
]

# Контрагенты, которые всплыли в истории держателей: куда и откуда шли крупные суммы.
COUNTERPARTIES = [
    ("Куда №8 и №14 вывели 8 млн 02.10.2026",          "0xc6f27a8fb4b552c7c2698f4ef1202a8978f3a780"),
    ("Куда №12 вывел 21,8 млн (янв-мар 2026)",          "0x4355951b4f1a5bab81a3bebcbf9f263302cc742d"),
    ("Куда №12 вывел 14,35 млн (сен-окт 2026)",         "0x10f4f69ff556bb5c0893f7ea212bd609eb55ddf7"),
    ("Куда №1 отправил 56,98 млн 26.08.2025",           "0x921949cc006a563d76abd111a3e4c2ace2c4273f"),
    ("Кому №1 отдал 30 млн 13.11.2025",                 "0x1f903473376fbe98cc763f1bc459c8fdb6ac3909"),
    ("Кому №1 отдал 3,33 млн 11.11.2025",               "0x7b0ac51037f43754275bd87446d35351f58448fe"),
    ("Откуда пришли 48,5 млн на №1 в сентябре 2025",    "0x386453e28939a72b7440398ab8ad40a5a3610d7b"),
    ("Общий получатель №11 и Safe №2",                  "0x410d1713192cc444606023cc76762807f7ffa80a"),
    ("Откуда 22,5 млн на №6 в момент разлока",          "0x1d4a12a09c293b816bff3625abda3ae07dee19f5"),
    ("Корневой адрес (раздал №10 и №12)",               "0xb5061abdce22ae6e7e731ec022bfd3503ca2d633"),
    ("Корневой адрес (раздал №1, №2 и Safe в 2024)",    "0x3437f6f7bd47d75780981d0b5a0ce9a038f19ed3"),
]

ZRO = "0x6985884c4392d348587b19cb9eaaf157f13271cd"
BASE_URL = "https://api.etherscan.io/v2/api"
CHAIN_ID = "1"
OUT_DIR = "zro_results_v2"

RELOCK_CUTOFF = datetime(2025, 9, 1, tzinfo=timezone.utc)
BUYBACK_FROM = datetime(2025, 9, 10, tzinfo=timezone.utc)
BUYBACK_TO = datetime(2025, 10, 10, tzinfo=timezone.utc)
UNLOCK_DAY_START = datetime(2026, 10, 19, tzinfo=timezone.utc)
UNLOCK_DAY_END = datetime(2026, 10, 22, tzinfo=timezone.utc)
BIG_TRANSFER = 1_000_000  # ZRO

SEL_GET_OWNERS = "0xa0e67e2b"     # Safe: getOwners()
SEL_GET_THRESHOLD = "0xe75235b8"  # Safe: getThreshold()


def api(params, retries=5):
    """Запрос к Etherscan с паузой (бесплатный ключ: до 5 запросов в секунду)."""
    params = dict(params)
    params["chainid"] = CHAIN_ID
    params["apikey"] = API_KEY
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        time.sleep(0.25)
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"   ! сетевая ошибка ({e}), повтор...")
            time.sleep(2)
            continue
        result = data.get("result")
        if isinstance(result, str) and "rate limit" in result.lower():
            time.sleep(1.5)
            continue
        return data
    return {"status": "0", "message": "NOTOK", "result": "не удалось получить ответ"}


def ts(tx):
    return datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc)


def amount(tx):
    dec = int(tx.get("tokenDecimal") or 18)
    return int(tx["value"]) / (10 ** dec)


def fmt(x):
    return f"{x:,.2f}".replace(",", " ")


def token_transfers(address=None, start_block=0, end_block=99999999):
    """Все переводы ZRO (по адресу или по всему токену в диапазоне блоков).
    API отдаёт данные страницами по 1000 записей, не больше 10 000 на диапазон.
    Если диапазон упирается в лимит, он делится пополам."""
    PAGE = 1000
    rows = []
    for page in range(1, 11):
        params = {
            "module": "account", "action": "tokentx", "contractaddress": ZRO,
            "startblock": start_block, "endblock": end_block,
            "page": page, "offset": PAGE, "sort": "asc",
        }
        if address:
            params["address"] = address
        data = api(params)
        result = data.get("result")
        if not isinstance(result, list):
            if "No transactions" in str(data.get("message", "")):
                break
            print(f"   ! ошибка API: {data.get('message')} / {result}")
            break
        rows.extend(result)
        if len(result) < PAGE:
            return rows
    # дошли до 10 000 записей: делим диапазон блоков
    if end_block - start_block > 1:
        if end_block >= 99999999:
            end_block = int(api({"module": "proxy", "action": "eth_blockNumber"})["result"], 16)
        mid = (start_block + end_block) // 2
        return (token_transfers(address, start_block, mid)
                + token_transfers(address, mid + 1, end_block))
    return rows


def token_balance(address):
    data = api({"module": "account", "action": "tokenbalance",
                "contractaddress": ZRO, "address": address, "tag": "latest"})
    try:
        return int(data["result"]) / 1e18
    except (KeyError, ValueError, TypeError):
        return None


def is_contract(address):
    data = api({"module": "proxy", "action": "eth_getCode",
                "address": address, "tag": "latest"})
    code = data.get("result") or "0x"
    return isinstance(code, str) and len(code) > 2


def eth_call(address, selector):
    data = api({"module": "proxy", "action": "eth_call",
                "to": address, "data": selector, "tag": "latest"})
    res = data.get("result")
    if isinstance(res, str) and res.startswith("0x") and len(res) > 2:
        return res[2:]
    return None


def safe_info(address):
    """Владельцы и порог подписей Safe. Если это не Safe, вернёт (None, None)."""
    thr_hex = eth_call(address, SEL_GET_THRESHOLD)
    own_hex = eth_call(address, SEL_GET_OWNERS)
    if not thr_hex or not own_hex:
        return None, None
    try:
        threshold = int(thr_hex, 16)
        n = int(own_hex[64:128], 16)
        owners = ["0x" + own_hex[128 + i * 64 + 24: 128 + (i + 1) * 64] for i in range(n)]
        return threshold, owners
    except ValueError:
        return None, None


def block_by_time(dt):
    data = api({"module": "block", "action": "getblocknobytime",
                "timestamp": int(dt.timestamp()), "closest": "before"})
    return int(data["result"])


def write_csv(path, rows, header):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)


def tx_row(tx):
    return [ts(tx).strftime("%Y-%m-%d %H:%M:%S"), tx["from"], tx["to"],
            f"{amount(tx):.4f}", tx["hash"]]


def analyse_address(rank, label, address):
    addr = address.lower()
    print(f"\n#{rank} {label}\n   {address}")

    balance = token_balance(address)
    contract = is_contract(address)
    threshold, owners = safe_info(address) if contract else (None, None)
    txs = token_transfers(address)

    zero_spam = [t for t in txs if int(t["value"]) == 0]
    real = [t for t in txs if int(t["value"]) > 0]
    incoming = [t for t in real if t["to"].lower() == addr]
    outgoing = [t for t in real if t["from"].lower() == addr]

    first_in = incoming[0] if incoming else None
    buyback_in = [t for t in incoming if BUYBACK_FROM <= ts(t) < BUYBACK_TO]
    out_after = [t for t in outgoing if ts(t) >= RELOCK_CUTOFF]
    out_20th = [t for t in outgoing if ts(t).day == 20]

    kind = "Safe" if threshold else ("контракт" if contract else "обычный кошелёк")
    print(f"   Баланс ZRO: {fmt(balance) if balance is not None else 'н/д'} | тип: {kind}")
    if threshold:
        print(f"   Safe: нужно {threshold} подписи(ей) из {len(owners)} владельцев")
    if first_in:
        print(f"   Первое поступление: {ts(first_in):%Y-%m-%d} от {first_in['from']} — {fmt(amount(first_in))} ZRO")
    print(f"   Поступлений в окне выкупа (сен-окт 2025): {len(buyback_in)} на {fmt(sum(amount(t) for t in buyback_in))} ZRO")
    print(f"   Исходящих после 01.09.2025: {len(out_after)} на {fmt(sum(amount(t) for t in out_after))} ZRO")
    print(f"   Исходящих 20 числа (дни разлоков): {len(out_20th)} на {fmt(sum(amount(t) for t in out_20th))} ZRO")
    print(f"   Всего записей: {len(txs)}, из них нулевых (спам «отравления адреса»): {len(zero_spam)}")

    header = ["Дата UTC", "От", "Кому", "ZRO", "Хэш"]
    write_csv(os.path.join(OUT_DIR, f"{rank:02d}_{address[:10]}_переводы.csv"),
              [tx_row(t) for t in txs], header)

    return [
        rank, label, address, kind,
        f"{balance:.2f}" if balance is not None else "",
        threshold or "", len(owners) if owners else "",
        ", ".join(owners) if owners else "",
        ts(first_in).strftime("%Y-%m-%d") if first_in else "",
        first_in["from"] if first_in else "",
        f"{amount(first_in):.2f}" if first_in else "",
        len(buyback_in), f"{sum(amount(t) for t in buyback_in):.2f}",
        len(out_after), f"{sum(amount(t) for t in out_after):.2f}",
        len(out_20th), f"{sum(amount(t) for t in out_20th):.2f}",
    ]


def quick_transfers(address, pages=2):
    """Первые до 2000 переводов ZRO адреса (для оценки, биржа это или нет)."""
    rows = []
    for page in range(1, pages + 1):
        data = api({"module": "account", "action": "tokentx", "contractaddress": ZRO,
                    "address": address, "page": page, "offset": 1000, "sort": "desc"})
        result = data.get("result")
        if not isinstance(result, list):
            break
        rows.extend(result)
        if len(result) < 1000:
            return rows, False
    return rows, True


def analyse_counterparty(name, address):
    addr = address.lower()
    print(f"\n{name}\n   {address}")
    balance = token_balance(address)
    contract = is_contract(address)
    threshold, owners = safe_info(address) if contract else (None, None)
    txs, capped = quick_transfers(address)
    real = [t for t in txs if int(t["value"]) > 0]
    inc = [t for t in real if t["to"].lower() == addr]
    out = [t for t in real if t["from"].lower() == addr]
    senders = {t["from"] for t in inc}
    receivers = {t["to"] for t in out}

    kind = "Safe" if threshold else ("контракт" if contract else "обычный кошелёк")
    count = "2000+ (последние 2000)" if capped else str(len(txs))
    print(f"   Тип: {kind} | баланс ZRO: {fmt(balance) if balance is not None else 'н/д'} | переводов ZRO: {count}")
    if threshold:
        print(f"   Safe: нужно {threshold} из {len(owners)}")
    print(f"   Разных отправителей: {len(senders)}, разных получателей: {len(receivers)}")
    if capped or len(senders) > 50:
        print("   Похоже на биржу или крупный хаб (очень много контрагентов)")

    def top(items, key):
        agg = {}
        for t in items:
            agg[t[key]] = agg.get(t[key], 0) + amount(t)
        return sorted(agg.items(), key=lambda x: -x[1])[:3]

    for a, v in top(out, "to"):
        print(f"   -> отправил {fmt(v)} ZRO на {a}")
    for a, v in top(inc, "from"):
        print(f"   <- получил {fmt(v)} ZRO от {a}")

    return [name, address, kind, f"{balance:.2f}" if balance is not None else "",
            threshold or "", len(owners) if owners else "",
            ", ".join(owners) if owners else "", count, len(senders), len(receivers),
            "; ".join(f"{a} ({v:.0f})" for a, v in top(out, "to")),
            "; ".join(f"{a} ({v:.0f})" for a, v in top(inc, "from"))]


def unlock_day_transfers():
    print("\n=== Переводы ZRO от 1 млн за 19-21.10.2026 (UTC) ===")
    start = block_by_time(UNLOCK_DAY_START)
    end = block_by_time(UNLOCK_DAY_END)
    print(f"   Блоки {start} - {end}")
    total = 0
    big = []
    step = 300  # примерно час блоков; крупные окна делятся автоматически
    for b in range(start, end + 1, step):
        chunk = token_transfers(None, b, min(b + step - 1, end))
        total += len(chunk)
        big.extend(t for t in chunk if amount(t) >= BIG_TRANSFER)
    print(f"   Всего переводов ZRO за период: {total}")
    big.sort(key=lambda t: int(t["timeStamp"]))
    for t in big:
        print(f"   {ts(t):%d.%m %H:%M} {t['from']} -> {t['to']}  {fmt(amount(t))} ZRO")

    by_sender = {}
    for t in big:
        by_sender[t["from"]] = by_sender.get(t["from"], 0) + amount(t)
    print("\n   Итого по отправителям:")
    for s, v in sorted(by_sender.items(), key=lambda x: -x[1]):
        print(f"   {s}  {fmt(v)} ZRO")

    write_csv(os.path.join(OUT_DIR, "19-21_октября_крупные_переводы.csv"),
              [tx_row(t) for t in big], ["Дата UTC", "От", "Кому", "ZRO", "Хэш"])


def main():
    if "ВСТАВЬ" in API_KEY:
        print("Сначала вставь свой API-ключ Etherscan в строку API_KEY в начале файла.")
        sys.exit(1)
    os.makedirs(OUT_DIR, exist_ok=True)

    print("=== Держатели ZRO ===")
    summary = []
    for rank, label, address in ADDRESSES:
        if not address:
            print(f"\n#{rank} {label}: адрес не заполнен, пропускаю")
            continue
        summary.append(analyse_address(rank, label, address))

    write_csv(os.path.join(OUT_DIR, "сводка_держателей.csv"), summary, [
        "№", "Метка", "Адрес", "Тип", "Баланс ZRO", "Safe: подписей нужно",
        "Safe: владельцев", "Safe: адреса владельцев",
        "Первое поступление: дата", "Первое поступление: от кого",
        "Первое поступление: ZRO", "Поступлений сен-окт 2025",
        "ZRO сен-окт 2025", "Исходящих после 01.09.2025",
        "ZRO исходящих после 01.09.2025", "Исходящих 20 числа", "ZRO исходящих 20 числа",
    ])

    print("\n=== Контрагенты ===")
    cp = [analyse_counterparty(n, a) for n, a in COUNTERPARTIES]
    write_csv(os.path.join(OUT_DIR, "контрагенты.csv"), cp, [
        "Что это", "Адрес", "Тип", "Баланс ZRO", "Safe: подписей", "Safe: владельцев",
        "Safe: адреса владельцев", "Переводов ZRO", "Разных отправителей",
        "Разных получателей", "Топ-3 получателя (ZRO)", "Топ-3 отправителя (ZRO)",
    ])

    unlock_day_transfers()
    print(f"\nГотово. Файлы в папке: {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    main()
