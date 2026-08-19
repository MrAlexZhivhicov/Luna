# SITE
https://www.luna-cheats.ru/

# Luna

Python-проект с оверлеем и настраиваемой панелью Luna.

> Эта копия использует гибридный рендер: меню и все интерфейсные элементы остаются на Tkinter, а ESP игроков отрисовывается через GPU-слой Dear PyGui. Оригинальный проект не изменён.

## Запуск

1. Установите Python 3.11 или новее.
2. Установите зависимости: `pip install -r requirements.txt`.
3. Запустите CS2.
4. Запустите приложение от имени администратора: `python -m milkyway`.

Клавиша `F1` открывает и скрывает меню. Настройки автоматически сохраняются в папку `configs`, а журнал работы — в `logs`.

Triggerbot, Bunnyhop и RCS поддерживают назначаемые клавиши. Режим **Hold** активирует функцию только при удержании клавиши, режим **Toggle** переключает её одиночным нажатием. Основной checkbox каждой функции остаётся общим разрешением модуля.

## Структура проекта

- `milkyway/__main__.py` — точка запуска для `python -m milkyway`;
- `milkyway/app.py` — сборка приложения и управление жизненным циклом;
- `milkyway/core.py` — настройки, CFG, подключение и общее состояние;
- `milkyway/engine.py` — общий backend чтения памяти и проверенные реализации;
- `milkyway/features/aim.py` — Aimbot, RCS, Triggerbot, Auto Fire и Auto Stop;
- `milkyway/features/esp.py` — Glow и группа player ESP;
- `milkyway/features/misc.py` — Bunnyhop, No Flash и Radar Reveal;
- `milkyway/features/skinchanger.py` — backend локального Inventory/Loadout Changer;
- `milkyway/ui/menu.py` — публичный модуль Tkinter-меню;
- `milkyway/ui/overlay.py` — Tkinter interface overlay и Dear PyGui ESP overlay;
- `configs/` — стандартный и пользовательские CFG-профили;
- `logs/` — локальные журналы запуска, исключённые из Git;
- `scripts/` — пакет для дополнительных модулей;
- `assets/` — изображения интерфейса и ESP Preview;
- `requirements.txt` — зависимости Python.

## Возможности

- разделы Aim, Vision и Misc;
- прозрачный click-through ESP-оверлей;
- настраиваемые элементы ESP и их цвета;
- Vector Aim с выбором точки и назначаемой клавишей или кнопкой мыши;
- NoRecoil, TriggerBot, Anti-Flash, Bunny Hop и Radar;
- создание, сохранение, загрузка и удаление CFG;
- адаптивная частота обновления для снижения нагрузки.

Используйте проект только там, где это разрешено правилами игры и сервера. Проект не содержит обхода VAC или средств сокрытия процесса.

## Сравнение рендереров

Запустите `python scripts/benchmark_overlay.py`. Скрипт одинаково отрисует 16 синтетических игроков через Tkinter и Dear PyGui и покажет среднее время кадра и p95.
