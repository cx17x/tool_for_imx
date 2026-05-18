# Runbook

## Что делает проект

Проект запускает object detection на IMX500, фильтрует нужный класс, например `person`, рисует `bbox` на видео и отправляет координаты `bbox` по UDP.

Основные выходы:

```text
127.0.0.1:5005/udp - bbox JSON
127.0.0.1:5006/udp - video with bbox overlay, optional
```

## За что отвечает каждый файл

```text
object_detection.py
```

Главный скрипт. Он:

- запускает Picamera2 и IMX500;
- получает inference metadata;
- парсит detections;
- фильтрует нужный класс через `--target-class`;
- рисует `bbox` на preview;
- отправляет `bbox` по UDP;
- опционально отправляет видео с overlay по UDP.

```text
detection_udp.py
```

Модуль отправки координат. Он:

- открывает UDP socket;
- сериализует detections в JSON;
- добавляет `ts`, `target_class`, `bbox`, `center`, `conf`, `label`;
- отправляет datagram на заданный host/port.

```text
udp_bbox_receiver.py
```

Тестовый приемник для проверки `bbox` UDP. Его удобно запускать в отдельном терминале.

```text
video_udp_streamer.py
```

Опциональный модуль для отправки видео. Он:

- использует H.264 encoder Picamera2;
- отправляет MPEG-TS поток по UDP;
- должен использоваться только когда нужен видеопоток по сети.

```text
web_dashboard/server.py
```

Web dashboard backend. Он:

- слушает `bbox` UDP;
- запускает `ffmpeg` bridge для video UDP в HLS;
- отдает веб-страницу на HTTP-порту;
- отправляет новые `bbox` в браузер через Server-Sent Events.

```text
web_dashboard/static/
```

Frontend dashboard:

- показывает видео;
- показывает последние координаты `bbox`;
- показывает raw JSON.

```text
docs/object_detection_architecture.md
```

Архитектурное описание: зачем два UDP-потока, почему `bbox` и видео разделены, как устроен поток данных.

```text
docs/systemd_services.md
```

Инструкция по установке и запуску проекта как `systemd` сервисов на Raspberry Pi.

```text
docs/runbook.md
```

Этот файл: как настроить, запустить и проверить систему.

## Требования

Ожидается Raspberry Pi с IMX500 и установленными библиотеками:

- `picamera2`;
- `opencv-python` или системный OpenCV для Python;
- IMX500 model files;
- `ffmpeg`, если нужен video UDP через `--video-udp`.

Модель по умолчанию:

```text
/home/qwerty/q_imx_model/rpk_out/network.rpk
```

Labels по умолчанию:

```text
/home/qwerty/q_imx_model/labels.txt
```

Если используется другая модель, передайте ее через `--model`.

Найти доступные `.rpk` модели на Raspberry Pi:

```bash
find /usr/share -name '*.rpk' 2>/dev/null
find /home/qwerty -name '*.rpk' 2>/dev/null
```

Установить базовые зависимости на Raspberry Pi:

```bash
./scripts/install_pi_dependencies.sh
```

Скрипт устанавливает:

- `python3-opencv`, чтобы работал импорт `cv2`;
- `python3-picamera2`;
- `ffmpeg`, если нужен video UDP/dashboard;
- `rsync`.

Скрипт также создает или настраивает `~/venv` так, чтобы virtualenv видел системные Raspberry Pi пакеты:

```text
include-system-site-packages = true
```

Это важно для `picamera2`, который обычно устанавливается через `apt`, а не через `pip`.

Проверить вручную:

```bash
/home/qwerty/venv/bin/python -c "import cv2; print(cv2.__version__)"
/home/qwerty/venv/bin/python -c "import picamera2; print('picamera2 ok')"
```

## Базовый запуск bbox UDP

Откройте терминал 1 и запустите приемник:

```bash
python3 udp_bbox_receiver.py --host 127.0.0.1 --port 5005
```

Откройте терминал 2 и запустите detection:

```bash
python3 object_detection.py
```

По умолчанию скрипт:

- ищет класс `person`;
- рисует bbox на preview;
- отправляет координаты на `127.0.0.1:5005`.

Пример UDP-сообщения:

```json
{
  "ts": 1710000000.123,
  "target_class": "person",
  "detections": [
    {
      "label": "person",
      "conf": 0.82,
      "bbox": {
        "x": 120,
        "y": 80,
        "w": 64,
        "h": 180
      },
      "center": {
        "x": 152,
        "y": 170
      }
    }
  ]
}
```

Если цели нет, отправляется пустой список:

```json
{
  "ts": 1710000000.456,
  "target_class": "person",
  "detections": []
}
```

## Полезные параметры object_detection.py

Показать только другой класс:

```bash
python3 object_detection.py --target-class car
```

Показать и отправлять все классы:

```bash
python3 object_detection.py --target-class all
```

Изменить threshold:

```bash
python3 object_detection.py --threshold 0.65
```

Изменить UDP destination для bbox:

```bash
python3 object_detection.py --udp-host 127.0.0.1 --udp-port 5005
```

Отключить bbox UDP:

```bash
python3 object_detection.py --no-udp
```

Отключить локальное preview окно, например для запуска из `systemd`:

```bash
python3 object_detection.py --no-preview
```

Отключить отрисовку bbox поверх кадра, полезно для диагностики video encoder:

```bash
python3 object_detection.py --no-overlay
```

Печатать detections в stdout:

```bash
python3 object_detection.py --print-detections
```

Использовать другую модель:

```bash
python3 object_detection.py --model /path/to/model.rpk
```

## Запуск video UDP

Видео по UDP включается отдельным `lores` YUV420 stream. Это безопаснее, чем кодировать `main`, потому что `main` используется для IMX500 demo-style overlay.

```bash
python3 object_detection.py --video-udp --video-stream lores --no-preview --no-overlay
```

`--video-stream lores` не содержит OpenCV overlay. Это режим для проверки стабильного video UDP.

Чтобы попробовать видео с overlay, можно отдельно протестировать:

```bash
python3 object_detection.py --video-udp --video-stream main --no-preview
```

Если при `main` снова появляются ошибки V4L2/CFE buffer queue, нужно оставить `lores` и рисовать bbox уже в web dashboard поверх видео по координатам из UDP.

Пример приема через ffplay:

```bash
ffplay udp://127.0.0.1:5006
```

Если `ffplay` не показывает видео, проверьте:

- установлен ли `ffmpeg`;
- доступен ли H.264 encoder;
- не занят ли порт `5006`;
- принимает ли клиент именно MPEG-TS over UDP.

## Рекомендуемая схема запуска

Для проверки координат:

```bash
python3 udp_bbox_receiver.py --host 127.0.0.1 --port 5005
python3 object_detection.py
```

Для проверки координат и видео:

```bash
python3 udp_bbox_receiver.py --host 127.0.0.1 --port 5005
ffplay udp://127.0.0.1:5006
python3 object_detection.py --video-udp
```

Каждую команду удобнее запускать в отдельном терминале.

## Перенос проекта на Raspberry Pi

Для синхронизации проекта на Raspberry Pi `192.168.1.108`:

```bash
./scripts/sync_to_pi.sh
```

По умолчанию используется:

```text
host: 192.168.1.108
user: pi
remote dir: /home/pi/tool_for_imx
```

Если пользователь другой:

```bash
PI_USER=qwerty ./scripts/sync_to_pi.sh
```

Если нужно сразу установить `systemd` сервисы после переноса:

```bash
./scripts/sync_to_pi.sh --install-services
```

На шаге установки сервисов удаленный `sudo` может запросить пароль пользователя Raspberry Pi. Для этого скрипт использует интерактивный SSH TTY.

Сервисы запускают Python из virtualenv:

```text
/home/<user>/venv/bin/python
```

Для пользователя `qwerty` это:

```text
/home/qwerty/venv/bin/python
```

Если virtualenv находится в другом месте:

```bash
PI_USER=qwerty PI_VENV_DIR=/path/to/venv ./scripts/sync_to_pi.sh --install-services
```

Если `.rpk` модель находится не по стандартному пути:

```bash
PI_USER=qwerty PI_MODEL_PATH=/path/to/model.rpk ./scripts/sync_to_pi.sh --install-services
```

Если labels находятся в другом месте:

```bash
PI_USER=qwerty PI_LABELS_PATH=/path/to/labels.txt ./scripts/sync_to_pi.sh --install-services
```

Если нужно перенести код и перезапустить уже активные сервисы:

```bash
./scripts/sync_to_pi.sh --restart-services
```

Можно совместить:

```bash
./scripts/sync_to_pi.sh --install-services --restart-services
```

## Запуск web dashboard

Dashboard показывает видео и координаты на одной странице.

Терминал 1:

```bash
python3 web_dashboard/server.py --host 0.0.0.0 --port 8080 --bbox-host 127.0.0.1 --bbox-port 5005 --video-host 127.0.0.1 --video-port 5006
```

Терминал 2:

```bash
python3 object_detection.py --video-udp --no-preview
```

Открыть в браузере:

```text
http://127.0.0.1:8080
```

Если браузер открыт с другого компьютера:

```text
http://<raspberry-pi-ip>:8080
```

Важно: браузер не читает UDP напрямую. `web_dashboard/server.py` принимает UDP и преобразует данные в форматы, которые понимает браузер:

```text
bbox UDP -> Server-Sent Events
video UDP -> ffmpeg -> HLS
```

Для воспроизведения HLS в Chrome/Firefox страница использует `hls.js` из CDN. Если Raspberry Pi работает без доступа в интернет, видео может не открыться в этих браузерах, пока `hls.js` не будет сохранен локально. Bbox-панель работает без внешних зависимостей.

Если нужно проверить только `bbox`, можно отключить video bridge:

```bash
python3 web_dashboard/server.py --no-video
```

`web_dashboard/server.py` и `udp_bbox_receiver.py` не могут одновременно слушать один и тот же `bbox` порт `5005`.

## Как работает основной цикл

Упрощенно:

```text
metadata = picam2.capture_metadata()
detections = parse_detections(metadata)
if detections_updated:
  udp_publisher.send(detections)
last_results = detections
draw_detections() draws last_results on video frame
```

Важно: UDP с координатами отправляется только когда пришел новый inference output. Это не дает старым координатам выглядеть как новые из-за свежего timestamp.

## Диагностика

Нет UDP-сообщений:

- проверьте, что `object_detection.py` запущен без `--no-udp`;
- проверьте host/port в receiver и sender;
- проверьте, что IMX500 реально возвращает detections;
- попробуйте `--target-class all`;
- попробуйте уменьшить threshold, например `--threshold 0.4`.

Есть видео, но нет bbox:

- проверьте класс через `--target-class all`;
- проверьте labels модели;
- проверьте `--threshold`;
- убедитесь, что объект находится в кадре и модель его поддерживает.

Есть bbox в preview, но нет UDP:

- запустите `udp_bbox_receiver.py`;
- проверьте `--udp-host` и `--udp-port`;
- убедитесь, что не используется `--no-udp`.

Не запускается video UDP:

- проверьте, установлен ли `ffmpeg`;
- попробуйте запустить без `--video-udp`;
- проверьте, поддерживается ли H.264 encoder в текущей системе;
- проверьте, что порт `5006` свободен.

## Что можно добавить дальше

- нормализованные координаты `bbox`;
- sequence id для каждого inference output;
- отдельный receiver для управляющего контура;
- логирование UDP-сообщений в файл;
- выбор самого уверенного `person`, если найдено несколько;
- трекинг цели между inference outputs.
