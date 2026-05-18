# Object Detection Architecture

## Цель

Нужно получать координаты `bbox` для выбранного класса, например `person`, и передавать их на внутренний UDP-порт для управляющего контура. Одновременно должен оставаться видеопоток для просмотра, записи или отладки с наложенными рамками.

## Базовая схема

```text
IMX500 camera
  |
  v
Picamera2 request + inference metadata
  |
  v
parse_detections()
  |
  v
filtered detections, for example person only
  |
  +--> bbox UDP publisher --> 127.0.0.1:PORT --> guidance/control loop
  |
  +--> video frame + bbox overlay --> preview / record / debug
```

Главная идея: камера и inference работают в одном месте, а после `parse_detections()` результат разделяется на два независимых потребителя:

- координаты `bbox` для управления;
- видео с отрисовкой для оператора, записи или отладки.

## Где должна жить UDP-логика

Рекомендуемый вариант: вынести UDP-отправку в отдельный модуль, но вызывать его из текущего процесса детекции.

```text
object_detection.py
  - Picamera2 / IMX500 setup
  - parse_detections()
  - фильтр класса, например person
  - draw_detections()
  - вызов udp_publisher.send(detections)

detection_udp.py
  - UDP socket
  - сериализация bbox
  - отправка datagram на 127.0.0.1:PORT
```

Такой подход лучше, чем сразу делать отдельный процесс для отправки координат, потому что:

- `object_detection.py` уже имеет самые свежие координаты сразу после разбора metadata;
- UDP `sendto()` на localhost дешевый и не должен заметно тормозить цикл;
- код камеры не смешивается с форматом сетевого сообщения;
- позже можно заменить UDP на MAVLink, serial, shared memory, ROS или другой транспорт;
- тестировать UDP-отправку можно отдельно от камеры.

Отдельный процесс для обработки координат имеет смысл добавлять позже, если появятся тяжелая фильтрация, трекинг, логирование, несколько потребителей или отдельный lifecycle для управляющего контура.

## Два потока камеры

Для текущей задачи лучше думать не как о двух независимых камерах, а как об одной камере с двумя выходами:

```text
Picamera2 / IMX500
  |
  +--> video stream  --> overlay / preview / record
  |
  +--> metadata      --> parse_detections() --> bbox UDP
```

`bbox` нужно брать из inference metadata, а не из видеопотока. Видео и координаты должны расходиться после `parse_detections()`.

Если понадобится два видеопотока, например один крупный для записи и один маленький для preview или дополнительной обработки, можно использовать `main` и `lores` stream в Picamera2:

```python
config = picam2.create_preview_configuration(
    main={"size": (1280, 720)},
    lores={"size": (640, 360)},
    controls={"FrameRate": intrinsics.inference_rate},
    buffer_count=12,
)
```

При этом inference metadata остается основным источником координат.

## Формат UDP-сообщения

Рекомендуемый формат datagram: JSON.

Пример сообщения с найденной целью:

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

Важно отправлять и пустой результат:

```json
{
  "ts": 1710000000.456,
  "target_class": "person",
  "detections": []
}
```

Пустое сообщение позволяет управляющему контуру отличать ситуацию "цель не найдена" от ситуации "данные вообще не приходят".

## Предлагаемая структура файлов

```text
object_detection.py
detection_udp.py
udp_bbox_receiver.py
docs/
  object_detection_architecture.md
```

Назначение файлов:

- `object_detection.py` - камера, inference, фильтрация класса, отрисовка и главный цикл;
- `detection_udp.py` - UDP publisher для bbox;
- `udp_bbox_receiver.py` - простой тестовый приемник UDP, опционально;
- `docs/object_detection_architecture.md` - описание архитектуры и решений.

## Поток выполнения в основном цикле

```text
while True:
  metadata = picam2.capture_metadata()
  detections = parse_detections(metadata)
  udp_publisher.send(detections)
  last_results = detections
```

`draw_detections()` может продолжать использовать `last_results` для overlay, а UDP publisher получает тот же список детекций.

## Что важно для управляющего контура

Для управления обычно полезны не только координаты `x, y, w, h`, но и центр bbox:

```text
center_x = x + w / 2
center_y = y + h / 2
```

Если управление идет относительно центра кадра, полезно позже добавить нормализованные координаты:

```text
norm_x = center_x / frame_width
norm_y = center_y / frame_height
```

Это позволит управляющему контуру меньше зависеть от конкретного разрешения видеопотока.

## Следующий шаг реализации

1. Создать `detection_udp.py` с классом `DetectionUdpPublisher`.
2. Добавить в `object_detection.py` аргументы `--udp-host`, `--udp-port`, `--no-udp`.
3. После `parse_detections()` отправлять текущий список bbox через publisher.
4. Добавить `udp_bbox_receiver.py` для локальной проверки.
