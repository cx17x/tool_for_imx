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
/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk
```

Если используется другая модель, передайте ее через `--model`.

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

Печатать detections в stdout:

```bash
python3 object_detection.py --print-detections
```

Использовать другую модель:

```bash
python3 object_detection.py --model /path/to/model.rpk
```

## Запуск video UDP

Видео по UDP выключено по умолчанию. Чтобы включить:

```bash
python3 object_detection.py --video-udp --video-udp-host 127.0.0.1 --video-udp-port 5006
```

Поток отправляется как `H.264` в контейнере `MPEG-TS`.

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
