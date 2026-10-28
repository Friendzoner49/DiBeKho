<div align="center">

<img src="resources/dibekho.png" alt="DiBeKho logo" width="112">

# DiBeKho

[English](README.md) · [Tiếng Việt](README.vi.md) · [中文](README.zh.md) · **Русский**

**Автоматический учёт склада по накладным Excel: работает на вашем компьютере, без интернета, бесплатно.**

[![Windows 10 | 11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)](https://github.com/Friendzoner49/DiBeKho/releases/latest/download/DiBeKho-windows-setup.exe)
[![macOS 13+](https://img.shields.io/badge/macOS-13%2B%20Apple%20Silicon-000000?logo=apple&logoColor=white)](https://github.com/Friendzoner49/DiBeKho/releases/latest/download/DiBeKho-mac-arm64.dmg)

<img src="docs/images/en/ton-kho.png" alt="Экран склада" width="860">

</div>

---

> Это краткое описание на русском, чтобы было понятно, что делает программа. Сам интерфейс приложения пока есть только на **вьетнамском, английском и китайском**. Подробная пошаговая инструкция (на английском, с картинками для каждого экрана): **[docs/user-guide.md](docs/user-guide.md)**. Скачивание и установка — см. [README.md](README.md#download-and-install).

## Что делает DiBeKho

Вы кладёте накладные Excel (`.xlsx`) в папку. Приложение само их читает, списывает товар со склада и записывает заказы и клиентов — вводить данные вручную не нужно.

- 📦 **Остатки** по каждому товару, отдельно по **главному складу** и **офису**; товар, которого мало, подсвечивается, отрицательный остаток — тоже.
- 📥 **Приход товара** от поставщика или возврат от клиента; **инвентаризация** и **перемещение** между двумя местами.
- 🔎 **Поиск** товаров, клиентов, телефонов и накладных.
- 💰 **Выручка по клиенту** и по товару, с ценами из самих накладных.
- 📊 **Статистика** за любой период, с **экспортом в Excel**.
- ↶ **Отмена действия** одной кнопкой; **ежедневные резервные копии**; перенос всех данных на другой компьютер одним файлом.

Закупочных цен в программе нет, прибыль она не считает. Все данные остаются на вашем компьютере и никуда не отправляются — работает полностью бесплатно, без сервера и без интернета.

## Скачать

Все файлы — на странице [**Releases**](https://github.com/Friendzoner49/DiBeKho/releases/latest): установщик для **Windows** (`DiBeKho-windows-setup.exe`) или **Mac с процессором Apple** (`DiBeKho-mac-arm64.dmg`). Подробные шаги установки (разблокировка в Windows/macOS, обновление, удаление) — в [README.md](README.md#download-and-install).

## Лицензия

DiBeKho — программа с открытым исходным кодом под [лицензией MIT](LICENSE).
