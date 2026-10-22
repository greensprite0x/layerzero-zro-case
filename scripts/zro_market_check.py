# -*- coding: utf-8 -*-
"""
ZRO: цена вокруг разлоков, снимок рынка, ликвидность и свежие метрики протокола.

Ключи не нужны. Запуск:  python zro_market_check.py
Результаты: папка "zro_market" рядом со скриптом + сводка на экране.

Что делает:
  1. Цена вокруг каждого ежемесячного разлока (20 число, июнь 2025 - октябрь 2026):
     изменение ZRO за 14 дней до и 14 дней после, то же для BTC и разница.
     Разлоки, рядом с которыми были крупные новости, помечаются отдельно.
  2. Снимок рынка на момент запуска (CoinGecko): цена, капитализация, полная оценка,
     в обращении, объём за 24 часа.
  3. Ликвидность: объём по площадкам, глубина рынка +-2%, фьючерсы
     (открытый интерес и ставка финансирования).
  4. Свежие комиссии протокола LayerZero и Stargate по данным DefiLlama.
"""

import csv
import json
import os
import statistics
import time
import urllib.request
from datetime import datetime, timedelta, timezone

OUT_DIR = "zro_market"
UA = {"User-Agent": "Mozilla/5.0 (research script)"}

# Крупные новости: если такая дата попадает в окно +-14 дней от разлока, разлок помечается.
NEWS = {
    "2025-06-20": "голосование по fee switch",
    "2025-09-23": "выкуп Фондом 50 млн ZRO",
    "2026-02-10": "анонс Zero, инвестиции Citadel/ARK/Tether",
    "2026-02-19": "разъяснение токеномики ZRO",
    "2026-04-18": "взлом KelpDAO",
    "2026-06-03": "пост LayerZero о токене",
    "2026-08-25": "анонс ATLAS",
    "2026-10-07": "миграция STG в ZRO на Binance",
    "2026-10-20": "объявлена дата запуска Zero",
}

WINDOW = 14


def get_json(url, retries=4, pause=2.5):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            msg = str(e)
            wait = 20 if "429" in msg else pause * (attempt + 1)
            print(f"   ! {msg[:80]} — повтор через {wait} с")
            time.sleep(wait)
    return None


def fmt(x, d=2):
    if x is None:
        return "н/д"
    return f"{x:,.{d}f}".replace(",", " ")


def pct(x):
    return "н/д" if x is None else f"{x * 100:+.1f}%"


def write_csv(name, header, rows):
    with open(os.path.join(OUT_DIR, name), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)


# ---------- 1. Цены ----------

def daily_closes_binance(symbol):
    """Дневные цены закрытия с публичного зеркала данных Binance (без ключа)."""
    start = int(datetime(2025, 5, 1, tzinfo=timezone.utc).timestamp() * 1000)
    closes = {}
    for base in ("https://data-api.binance.vision", "https://api.binance.com"):
        url = f"{base}/api/v3/klines?symbol={symbol}&interval=1d&startTime={start}&limit=1000"
        data = get_json(url, retries=2)
        if isinstance(data, list) and data:
            for k in data:
                day = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date()
                closes[day] = float(k[4])
            return closes, "Binance"
    return {}, None


def daily_closes_coingecko(coin_id):
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=365&interval=daily"
    data = get_json(url)
    closes = {}
    if data and "prices" in data:
        for ts, p in data["prices"]:
            closes[datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date()] = p
    return closes


def nearest(closes, day, direction):
    """Цена на дату или ближайшую доступную в нужную сторону (до 3 дней)."""
    for i in range(4):
        d = day + timedelta(days=i * direction)
        if d in closes:
            return closes[d]
    return None


def unlock_study():
    print("\n=== 1. Цена вокруг разлоков ===")
    zro, src = daily_closes_binance("ZROUSDT")
    btc, _ = daily_closes_binance("BTCUSDT")
    if not zro or not btc:
        print("   Binance недоступен, беру CoinGecko (только последние 365 дней)")
        time.sleep(3)
        zro = daily_closes_coingecko("layerzero")
        time.sleep(3)
        btc = daily_closes_coingecko("bitcoin")
        src = "CoinGecko"
    if not zro or not btc:
        print("   ! не удалось получить цены")
        return
    print(f"   Источник цен: {src}, дней ZRO: {len(zro)}, последняя дата: {max(zro)}")

    news_days = {datetime.strptime(k, "%Y-%m-%d").date(): v for k, v in NEWS.items()}
    rows, clean_pre, clean_post, all_pre, all_post = [], [], [], [], []
    today = max(zro)

    d = datetime(2025, 6, 20).date()
    while d <= today:
        before = nearest(zro, d - timedelta(days=WINDOW + 1), -1)
        eve = nearest(zro, d - timedelta(days=1), -1)
        after_day = min(d + timedelta(days=WINDOW), today)
        after = nearest(zro, after_day, -1)
        b_before = nearest(btc, d - timedelta(days=WINDOW + 1), -1)
        b_eve = nearest(btc, d - timedelta(days=1), -1)
        b_after = nearest(btc, after_day, -1)

        pre = eve / before - 1 if before and eve else None
        post = after / eve - 1 if eve and after else None
        b_pre = b_eve / b_before - 1 if b_before and b_eve else None
        b_post = b_after / b_eve - 1 if b_eve and b_after else None
        ex_pre = pre - b_pre if pre is not None and b_pre is not None else None
        ex_post = post - b_post if post is not None and b_post is not None else None

        near = [f"{k:%d.%m.%Y} {v}" for k, v in news_days.items()
                if abs((k - d).days) <= WINDOW]
        partial = "да" if after_day < d + timedelta(days=WINDOW) else ""

        rows.append([d.isoformat(), fmt(eve, 4), pct(pre), pct(b_pre), pct(ex_pre),
                     pct(post), pct(b_post), pct(ex_post), partial, "; ".join(near)])
        if ex_pre is not None:
            all_pre.append(ex_pre)
            if not near:
                clean_pre.append(ex_pre)
        if ex_post is not None and not partial:
            all_post.append(ex_post)
            if not near:
                clean_post.append(ex_post)

        d = (d.replace(day=1) + timedelta(days=32)).replace(day=20)

    print(f"\n   {'Разлок':<11}{'ZRO до':>9}{'vs BTC':>9}{'ZRO после':>11}{'vs BTC':>9}  новости рядом")
    for r in rows:
        print(f"   {r[0]:<11}{r[2]:>9}{r[4]:>9}{r[5]:>11}{r[7]:>9}  {r[9][:60]}")

    def summary(name, xs):
        if not xs:
            return f"   {name}: нет данных"
        neg = sum(1 for x in xs if x < 0)
        return (f"   {name}: случаев {len(xs)}, среднее {pct(statistics.mean(xs))}, "
                f"медиана {pct(statistics.median(xs))}, отрицательных {neg} из {len(xs)}")

    print("\n   Итог (разница с BTC, то есть за вычетом общего рынка):")
    print(summary("14 дней ДО разлока, все", all_pre))
    print(summary("14 дней ДО разлока, без новостей рядом", clean_pre))
    print(summary("14 дней ПОСЛЕ разлока, все", all_post))
    print(summary("14 дней ПОСЛЕ разлока, без новостей рядом", clean_post))
    print("   Важно: выборка маленькая, это наблюдение, а не статистически доказанная закономерность.")

    write_csv("разлоки_цена.csv",
              ["Разлок", "Цена ZRO накануне", "ZRO за 14 дн до", "BTC за 14 дн до",
               "ZRO минус BTC до", "ZRO за 14 дн после", "BTC за 14 дн после",
               "ZRO минус BTC после", "Окно после неполное", "Новости в окне +-14 дн"], rows)


# ---------- 2-3. Снимок рынка и ликвидность ----------

def market_snapshot():
    print("\n=== 2. Снимок рынка (CoinGecko) ===")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data = get_json("https://api.coingecko.com/api/v3/coins/layerzero?localization=false"
                    "&tickers=false&market_data=true&community_data=false&developer_data=false")
    rows = [["Время снимка", stamp]]
    if data and "market_data" in data:
        m = data["market_data"]
        items = [
            ("Цена, $", m["current_price"].get("usd")),
            ("Капитализация, $", m["market_cap"].get("usd")),
            ("Полная оценка (FDV), $", (m.get("fully_diluted_valuation") or {}).get("usd")),
            ("В обращении, ZRO", m.get("circulating_supply")),
            ("Общее предложение, ZRO", m.get("total_supply")),
            ("Объём за 24 ч, $", m["total_volume"].get("usd")),
            ("Изменение за 24 ч, %", m.get("price_change_percentage_24h")),
            ("Изменение за 7 дней, %", m.get("price_change_percentage_7d")),
            ("Изменение за 30 дней, %", m.get("price_change_percentage_30d")),
            ("Исторический максимум, $", m["ath"].get("usd")),
            ("Дата максимума", m["ath_date"].get("usd")),
        ]
        print(f"   Время снимка: {stamp}")
        for k, v in items:
            shown = v if isinstance(v, str) else fmt(v)
            print(f"   {k}: {shown}")
            rows.append([k, v])
        mc, vol = m["market_cap"].get("usd"), m["total_volume"].get("usd")
        if mc and vol:
            print(f"   Объём / капитализация: {vol / mc * 100:.1f}%")
            rows.append(["Объём / капитализация, %", round(vol / mc * 100, 2)])
    else:
        print("   ! не удалось получить снимок")
    write_csv("снимок_рынка.csv", ["Показатель", "Значение"], rows)


def liquidity():
    print("\n=== 3. Ликвидность: площадки и глубина рынка ===")
    tickers = []
    for page in (1, 2):
        time.sleep(3)
        data = get_json("https://api.coingecko.com/api/v3/coins/layerzero/tickers"
                        f"?depth=true&order=volume_desc&page={page}")
        if not data or not data.get("tickers"):
            break
        tickers.extend(data["tickers"])
    if not tickers:
        print("   ! не удалось получить данные о площадках")
    else:
        by_ex, up, down, total = {}, 0, 0, 0
        rows = []
        for t in tickers:
            vol = (t.get("converted_volume") or {}).get("usd") or 0
            ex = t["market"]["name"]
            by_ex[ex] = by_ex.get(ex, 0) + vol
            total += vol
            up += t.get("cost_to_move_up_usd") or 0
            down += t.get("cost_to_move_down_usd") or 0
            rows.append([ex, f"{t['base']}/{t['target']}", round(vol),
                         round(t.get("cost_to_move_up_usd") or 0),
                         round(t.get("cost_to_move_down_usd") or 0),
                         t.get("trust_score")])
        print(f"   Спотовый объём по {len(tickers)} парам: ${fmt(total, 0)}")
        print(f"   Глубина +2% (сколько $ нужно, чтобы поднять цену на 2%): ${fmt(up, 0)}")
        print(f"   Глубина -2% (сколько $ нужно, чтобы опустить цену на 2%): ${fmt(down, 0)}")
        print("   Крупнейшие площадки по объёму:")
        for ex, v in sorted(by_ex.items(), key=lambda x: -x[1])[:8]:
            print(f"     {ex:<22} ${fmt(v, 0):>16}  ({v / total * 100:.1f}%)")
        write_csv("площадки_спот.csv",
                  ["Площадка", "Пара", "Объём 24ч $", "Глубина +2% $", "Глубина -2% $", "Доверие"],
                  rows)

    print("\n   Фьючерсы (бессрочные контракты на ZRO):")
    time.sleep(3)
    der = get_json("https://api.coingecko.com/api/v3/derivatives")
    if not isinstance(der, list):
        print("   ! не удалось получить фьючерсы")
        return
    zro = [d for d in der if str(d.get("index_id", "")).upper() == "ZRO"
           or str(d.get("symbol", "")).upper().startswith("ZRO")]
    oi = sum(float(d.get("open_interest") or 0) for d in zro)
    vol = sum(float(d.get("volume_24h") or 0) for d in zro)
    rates = [float(d["funding_rate"]) for d in zro if d.get("funding_rate") not in (None, "")]
    print(f"   Контрактов: {len(zro)}, открытый интерес: ${fmt(oi, 0)}, объём за 24 ч: ${fmt(vol, 0)}")
    if rates:
        print(f"   Ставка финансирования: медиана {statistics.median(rates):.4f}%, "
              f"мин {min(rates):.4f}%, макс {max(rates):.4f}%")
        print("   (плюс: лонги платят шортам, на рынке больше ставок на рост; минус — наоборот)")
    top = sorted(zro, key=lambda d: -float(d.get("open_interest") or 0))[:8]
    for d in top:
        print(f"     {d.get('market', ''):<22} OI ${fmt(float(d.get('open_interest') or 0), 0):>14}  "
              f"ставка {d.get('funding_rate')}")
    write_csv("фьючерсы.csv", ["Площадка", "Контракт", "Открытый интерес $", "Объём 24ч $", "Ставка финансирования %"],
              [[d.get("market"), d.get("symbol"), d.get("open_interest"), d.get("volume_24h"),
                d.get("funding_rate")] for d in zro])


# ---------- 4. Комиссии протокола (DefiLlama) ----------

def protocol_fees():
    print("\n=== 4. Комиссии протокола (DefiLlama) ===")
    rows = []
    for label, slugs in (("LayerZero (комиссии за сообщения)", ["layerzero", "layerzero-v2"]),
                         ("Stargate", ["stargate-finance", "stargate-v2", "stargate"])):
        found = False
        for slug in slugs:
            for kind in ("dailyFees", "dailyRevenue"):
                data = get_json(f"https://api.llama.fi/summary/fees/{slug}?dataType={kind}", retries=2)
                chart = (data or {}).get("totalDataChart")
                if not chart:
                    continue
                found = True
                monthly = {}
                for ts, v in chart:
                    m = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")
                    monthly[m] = monthly.get(m, 0) + (v or 0)
                last = sorted(monthly)[-4:]
                name = "комиссии" if kind == "dailyFees" else "выручка"
                print(f"   {label} [{slug}], {name} по месяцам:")
                for m in last:
                    print(f"     {m}: ${fmt(monthly[m], 0)}")
                    rows.append([label, slug, name, m, round(monthly[m])])
                time.sleep(1)
            if found:
                break
        if not found:
            print(f"   {label}: DefiLlama не отдал данные")
    if rows:
        print("   Последний месяц неполный: считается с 1 числа по сегодня.")
    write_csv("комиссии_протокола.csv", ["Протокол", "Код DefiLlama", "Показатель", "Месяц", "$"], rows)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for step in (unlock_study, market_snapshot, liquidity, protocol_fees):
        try:
            step()
        except Exception as e:
            print(f"   ! шаг {step.__name__} завершился с ошибкой: {e}")
    print(f"\nГотово. Файлы в папке: {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    main()
