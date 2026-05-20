# tool_for_imx

Проект для запуска object detection на Raspberry Pi с камерой IMX500.

Он делает три основные вещи:

- запускает `Picamera2` + IMX500 model inference;
- фильтрует detections по классу, сейчас сервис настроен на `airplane`;
- отдает координаты `bbox` по UDP и видео с отрисованными рамками через MJPEG/web dashboard.

## Текущая схема

```text
IMX500 camera
  |
  v
object_detection.py
  |
  +--> bbox UDP JSON --> 127.0.0.1:5005
  |
  +--> MJPEG video with bbox overlay --> 0.0.0.0:8081/mjpeg
  |
  v
web_dashboard/server.py --> http://<raspberry-pi-ip>:8080
```

Dashboard показывает:

- live MJPEG video;
- последние detections;
- raw JSON с `bbox`, `center`, `track_id`, `bbox_yolo`, `center_yolo`.

## Основные файлы

```text
object_detection.py
```

Главный процесс камеры. Настраивает IMX500, парсит detections, фильтрует класс, ведет bbox tracker, рисует overlay, отправляет bbox UDP и поднимает MJPEG stream.

```text
detection_udp.py
```

Сериализация и отправка bbox JSON по UDP. В payload есть пиксельные координаты и нормализованные YOLO-style координаты `0..1`.

```text
mjpeg_streamer.py
```

Минимальный HTTP MJPEG streamer. Используется текущим web dashboard как основной низколатентный видеопоток.

```text
web_dashboard/
```

HTTP dashboard на `:8080`. Принимает bbox UDP, проксирует MJPEG и показывает видео/координаты в браузере.

```text
udp_bbox_receiver.py
```

Debug receiver для проверки UDP bbox без dashboard.

```text
systemd/
```

Unit-файлы для запуска на Raspberry Pi:

- `imx-object-detection-video.service` - основной сервис detection + MJPEG;
- `imx-object-detection.service` - detection без MJPEG;
- `imx-web-dashboard.service` - web dashboard;
- `imx-bbox-receiver.service` - optional debug receiver.

```text
scripts/
```

Скрипты установки, синхронизации и диагностики Raspberry Pi.

## Текущие параметры detection

Основной сервис запускает:

```bash
object_detection.py \
  --model /home/qwerty/q_imx_model/rpk_out/network.rpk \
  --labels /home/qwerty/q_imx_model/labels.txt \
  --bbox-normalization \
  --bbox-order xy \
  --threshold 0.10 \
  --iou 0.45 \
  --tracker \
  --tracker-iou-threshold 0.2 \
  --tracker-max-missed 2 \
  --tracker-process-noise 4.0 \
  --tracker-measurement-noise 30.0 \
  --target-class airplane \
  --udp-host 127.0.0.1 \
  --udp-port 5005 \
  --main-width 640 \
  --main-height 640 \
  --mjpeg \
  --mjpeg-host 0.0.0.0 \
  --mjpeg-port 8081 \
  --mjpeg-quality 90 \
  --no-preview
```

## UDP payload

Пример сообщения на `127.0.0.1:5005`:

```json
{
  "ts": 1710000000.123,
  "target_class": "airplane",
  "image": {
    "width": 640,
    "height": 480
  },
  "detections": [
    {
      "track_id": 1,
      "label": "airplane",
      "conf": 0.82,
      "bbox": {"x": 120, "y": 80, "w": 64, "h": 180},
      "center": {"x": 152, "y": 170},
      "bbox_yolo": {"x": 0.1875, "y": 0.1667, "w": 0.1, "h": 0.375},
      "center_yolo": {"x": 0.2375, "y": 0.3542}
    }
  ]
}
```

Для управления лучше использовать `bbox_yolo` и `center_yolo`, потому что они не зависят от текущего размера кадра.

## Быстрый запуск на Raspberry Pi

Синхронизация с Mac:

```bash
PI_USER=qwerty ./scripts/sync_to_pi.sh
```

Установка systemd services на Raspberry Pi:

```bash
cd /home/qwerty/tool_for_imx
PROJECT_DIR=/home/qwerty/tool_for_imx SERVICE_USER=qwerty VENV_DIR=/home/qwerty/venv ./scripts/install_systemd_services.sh
```

Запуск основного варианта:

```bash
sudo systemctl enable --now imx-object-detection-video.service
sudo systemctl enable --now imx-web-dashboard.service
```

После запуска:

```text
http://<raspberry-pi-ip>:8080
```

## Документация

- `docs/runbook.md` - практический запуск, установка, диагностика;
- `docs/object_detection_architecture.md` - архитектура потоков bbox/video;
- `docs/detection_parameters.md` - описание параметров detection/tracker/video и влияние изменения значений;
- `docs/systemd_services.md` - детали systemd services.
