# Systemd Services

## Назначение

`systemd` нужен, чтобы запускать detection и связанные процессы как сервисы:

- автоматически после загрузки Raspberry Pi;
- с перезапуском при падении;
- с логами в `journalctl`;
- без ручного запуска из терминала.

## Что добавлено

```text
systemd/imx-object-detection.service
```

Основной сервис. Запускает:

```bash
python3 object_detection.py --target-class person --udp-host 127.0.0.1 --udp-port 5005 --no-preview
```

Этот вариант отправляет только `bbox` UDP на `127.0.0.1:5005`.

```text
systemd/imx-object-detection-video.service
```

Вариант с видео. Запускает:

```bash
python3 object_detection.py --target-class person --udp-host 127.0.0.1 --udp-port 5005 --video-udp --video-udp-host 127.0.0.1 --video-udp-port 5006 --no-preview
```

Этот вариант отправляет:

```text
127.0.0.1:5005/udp - bbox JSON
127.0.0.1:5006/udp - video with bbox overlay
```

Важно: не включайте одновременно `imx-object-detection.service` и `imx-object-detection-video.service`, потому что оба будут пытаться использовать камеру.

```text
systemd/imx-bbox-receiver.service
```

Отладочный receiver. Запускает:

```bash
python3 udp_bbox_receiver.py --host 127.0.0.1 --port 5005
```

Для production его лучше заменить на настоящий `control_loop.py`.

```text
scripts/install_systemd_services.sh
```

Скрипт установки unit-файлов в `/etc/systemd/system`.

## Установка

На Raspberry Pi из корня проекта:

```bash
./scripts/install_systemd_services.sh
```

По умолчанию скрипт считает, что проект находится здесь:

```text
/home/pi/tool_for_imx
```

И что сервисы должны запускаться от пользователя:

```text
pi
```

Если путь или пользователь другие:

```bash
PROJECT_DIR=/path/to/tool_for_imx SERVICE_USER=myuser ./scripts/install_systemd_services.sh
```

Скрипт:

- копирует unit-файлы в `/etc/systemd/system`;
- подставляет `PROJECT_DIR`;
- подставляет `SERVICE_USER`;
- выполняет `systemctl daemon-reload`.

## Запуск bbox-only сервиса

Включить автозапуск и сразу запустить:

```bash
sudo systemctl enable --now imx-object-detection.service
```

Проверить статус:

```bash
sudo systemctl status imx-object-detection.service
```

Смотреть логи:

```bash
sudo journalctl -u imx-object-detection.service -f
```

Остановить:

```bash
sudo systemctl stop imx-object-detection.service
```

Отключить автозапуск:

```bash
sudo systemctl disable imx-object-detection.service
```

## Запуск сервиса с video UDP

Сначала убедитесь, что обычный detection service выключен:

```bash
sudo systemctl disable --now imx-object-detection.service
```

Включите вариант с video UDP:

```bash
sudo systemctl enable --now imx-object-detection-video.service
```

Логи:

```bash
sudo journalctl -u imx-object-detection-video.service -f
```

Остановить:

```bash
sudo systemctl stop imx-object-detection-video.service
```

## Отладочный bbox receiver

Включить receiver:

```bash
sudo systemctl enable --now imx-bbox-receiver.service
```

Смотреть входящие `bbox` сообщения:

```bash
sudo journalctl -u imx-bbox-receiver.service -f
```

Остановить:

```bash
sudo systemctl stop imx-bbox-receiver.service
```

## Частые команды

Перезапустить detection:

```bash
sudo systemctl restart imx-object-detection.service
```

Посмотреть последние 100 строк логов:

```bash
sudo journalctl -u imx-object-detection.service -n 100
```

Проверить, какие IMX-сервисы активны:

```bash
systemctl list-units 'imx-*'
```

Посмотреть установленные unit-файлы:

```bash
ls -l /etc/systemd/system/imx-*.service
```

## Как менять параметры запуска

Шаблоны лежат в:

```text
systemd/
```

После изменения шаблона переустановите сервисы:

```bash
./scripts/install_systemd_services.sh
```

Затем перезапустите нужный сервис:

```bash
sudo systemctl restart imx-object-detection.service
```

Если нужно быстро изменить уже установленный unit:

```bash
sudo systemctl edit --full imx-object-detection.service
sudo systemctl daemon-reload
sudo systemctl restart imx-object-detection.service
```

## Production-модель процессов

Рекомендуемая схема:

```text
imx-object-detection.service
  - камера
  - inference
  - bbox UDP producer
  - optional video UDP producer

control-loop.service
  - слушает bbox UDP
  - принимает решения управления

optional video consumer
  - принимает video UDP
  - показывает или пишет видео
```

`detection_udp.py` и `video_udp_streamer.py` не являются сервисами. Это библиотечные модули, которые импортирует `object_detection.py`.
