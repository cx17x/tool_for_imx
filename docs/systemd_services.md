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
/home/pi/venv/bin/python object_detection.py --model /home/qwerty/q_imx_model/rpk_out/network.rpk --labels /home/qwerty/q_imx_model/labels.txt --target-class person --udp-host 127.0.0.1 --udp-port 5005 --no-preview
```

Этот вариант отправляет только `bbox` UDP на `127.0.0.1:5005`.

```text
systemd/imx-object-detection-video.service
```

Вариант с MJPEG video. Видео отдается из того же процесса, который владеет камерой:

```bash
/home/pi/venv/bin/python object_detection.py --model /home/qwerty/q_imx_model/rpk_out/network.rpk --labels /home/qwerty/q_imx_model/labels.txt --target-class person --udp-host 127.0.0.1 --udp-port 5005 --mjpeg --mjpeg-host 0.0.0.0 --mjpeg-port 8081 --mjpeg-quality 75 --no-preview
```

Этот вариант отправляет:

```text
127.0.0.1:5005/udp - bbox JSON
0.0.0.0:8081/http - MJPEG video
```

Важно: не включайте одновременно `imx-object-detection.service` и `imx-object-detection-video.service`, потому что оба будут пытаться использовать камеру.

```text
systemd/imx-bbox-receiver.service
```

Отладочный receiver. Запускает:

```bash
/home/pi/venv/bin/python udp_bbox_receiver.py --host 127.0.0.1 --port 5005
```

Для production его лучше заменить на настоящий `control_loop.py`.

```text
systemd/imx-web-dashboard.service
```

Web dashboard. Запускает:

```bash
/home/pi/venv/bin/python web_dashboard/server.py --host 0.0.0.0 --port 8080 --bbox-host 127.0.0.1 --bbox-port 5005 --no-video
```

Dashboard принимает `bbox` UDP и video UDP, а в браузер отдает:

```text
http://<raspberry-pi-ip>:8080
```

Важно: `imx-web-dashboard.service` и `imx-bbox-receiver.service` оба слушают `127.0.0.1:5005`, поэтому их нельзя запускать одновременно без изменения портов.

Для HLS-видео в Chrome/Firefox frontend использует `hls.js` из CDN. Если устройство работает без доступа в интернет, bbox-панель останется рабочей, но для видео нужно будет положить `hls.js` локально.

```text
scripts/install_systemd_services.sh
```

Скрипт установки unit-файлов в `/etc/systemd/system`.

## Установка

На Raspberry Pi из корня проекта:

```bash
./scripts/install_pi_dependencies.sh
```

Если сервисы запускаются из `/home/qwerty/venv`, этот venv должен видеть системные пакеты `picamera2` и `cv2`. Скрипт включает `include-system-site-packages = true` в `pyvenv.cfg`.

Затем установить сервисы:

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

По умолчанию сервисы запускают Python из:

```text
/home/<SERVICE_USER>/venv/bin/python
```

Если virtualenv находится в другом месте:

```bash
PROJECT_DIR=/path/to/tool_for_imx SERVICE_USER=myuser VENV_DIR=/path/to/venv ./scripts/install_systemd_services.sh
```

Если модель `.rpk` или labels находятся в другом месте:

```bash
PROJECT_DIR=/path/to/tool_for_imx SERVICE_USER=myuser VENV_DIR=/path/to/venv MODEL_PATH=/path/to/model.rpk LABELS_PATH=/path/to/labels.txt ./scripts/install_systemd_services.sh
```

Скрипт:

- копирует unit-файлы в `/etc/systemd/system`;
- подставляет `PROJECT_DIR`;
- подставляет `SERVICE_USER`;
- подставляет `VENV_DIR`;
- подставляет `MODEL_PATH`;
- подставляет `LABELS_PATH`;
- выполняет `systemctl daemon-reload`.

Detection services use `scripts/wait_for_camera.sh` before starting Python. This prevents the service from starting before `rpicam-hello --list-cameras` can see the IMX500 camera.

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

## Web dashboard

Включить dashboard:

```bash
sudo systemctl enable --now imx-web-dashboard.service
```

Открыть в браузере:

```text
http://<raspberry-pi-ip>:8080
```

Логи:

```bash
sudo journalctl -u imx-web-dashboard.service -f
```

Остановить:

```bash
sudo systemctl stop imx-web-dashboard.service
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
