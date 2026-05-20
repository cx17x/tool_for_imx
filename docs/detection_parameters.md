# Detection parameters

Этот документ описывает параметры `object_detection.py` и страницы
`/config.html`: что они делают, что меняется при увеличении/уменьшении и с
каких значений обычно начинать.

## Detection

| Параметр | Что делает | Если увеличить | Если уменьшить | Стартовое значение |
| --- | --- | --- | --- | --- |
| `Target class` | Фильтрует detections по label. `all` показывает все классы. | Не числовой параметр. | Не числовой параметр. | `person`, `airplane` или `all` |
| `Threshold` | Минимальная confidence детекции. | Меньше ложных и слабых bbox, но выше риск пропустить объект. | Больше чувствительность, но больше лишних bbox и дублей. | `0.25-0.35` |
| `NMS IoU` / `iou` | Порог NMS для подавления пересекающихся bbox одной модели. | Больше пересекающихся bbox останется, полезно для близких объектов. | Агрессивнее убирает дубли, но может удалить соседний объект. | `0.30-0.45` |
| `Max detections` | Максимум detections после postprocess. | Можно увидеть больше объектов/дублей. | Меньше шума, но можно обрезать реальные объекты. | `3-10` |
| `BBox normalization` | Делит bbox координаты модели на размер входного тензора. | Boolean: включено/выключено. | Boolean: включено/выключено. | Обычно `on` |
| `BBox order` | Порядок координат bbox от модели: `xy` или `yx`. | Не числовой параметр. | Не числовой параметр. | Для текущей модели `xy` |
| `BBox scale` | Множитель raw bbox до нормализации/конвертации. | Все bbox становятся крупнее/смещаются сильнее от исходных координат. | Все bbox становятся меньше. | `1.0` |
| `Smoothing alpha` | EMA сглаживание bbox, когда tracker выключен. | Рамка быстрее реагирует, но сильнее дрожит. | Рамка плавнее, но сильнее запаздывает. | `0.35-0.8` |

Практика для дублей одного объекта:

```text
Threshold: повышать
NMS IoU: снижать
Max detections: снижать
BBox scale: оставить 1.0
```

Если при выключенном tracker картинка чище, сначала настрой `Threshold` и
`NMS IoU`, а tracker подключай отдельно.

## Tracker

Tracker связывает bbox между кадрами, назначает `track_id`, сглаживает движение
через Kalman filter и может кратко предсказывать объект, если модель его не
нашла.

| Параметр | Что делает | Если увеличить | Если уменьшить | Стартовое значение |
| --- | --- | --- | --- | --- |
| `Enable tracker` | Включает трекинг поверх обычных detections. | Boolean: tracker работает. | Boolean: используются detections модели без tracker. | Начинать с `off`, потом `on` |
| `Tracker IoU` | Минимальное пересечение старого track bbox и новой bbox для matching. | Matching строже: меньше риск склеить соседние объекты, но больше новых track_id. | Matching мягче: меньше пересозданий track, но выше риск склеить близкие объекты. | `0.10-0.20` |
| `Max missed frames` | Сколько кадров держать track без новой bbox от модели. | Меньше пропаданий при мигании модели, но больше ghost bbox и наложений. | Быстрее удаляет неподтвержденные bbox, меньше наслоений. | `0-1` |
| `Process noise` | Насколько Kalman filter допускает резкие изменения движения. | Tracker быстрее подстраивается к маневрам, но меньше сглаживает. | Движение плавнее, но bbox может отставать и терять быстрый объект. | `8.0-15.0` |
| `Measurement noise` | Насколько tracker доверяет текущей bbox от модели. | Больше доверия предсказанию tracker, сильнее сглаживание, больше задержка. | Больше доверия модели, bbox быстрее прыгает к новой детекции. | `10.0-30.0` |
| `Confidence decay` | Умножает confidence неподтвержденного track при missed frame. | Confidence падает медленнее, ghost track выглядит увереннее. | Confidence падает быстрее, ghost track быстрее становится слабым. | `0.6-0.85` |

Аккуратный старт без ghost bbox:

```text
Enable tracker: on
Tracker IoU: 0.10
Max missed frames: 0
Process noise: 8.0
Measurement noise: 10.0
Confidence decay: 0.85
```

Если bbox чистые, но `track_id` часто пересоздается:

```text
Max missed frames: 1
Tracker IoU: 0.05-0.10
```

Если появляются наслоения старой и новой рамки:

```text
Max missed frames: 0
Measurement noise: 10.0 или ниже
Process noise: 8.0 или выше
```

Если рядом несколько объектов и tracker их склеивает:

```text
Tracker IoU: 0.15-0.25
Max missed frames: 0
```

## Motion vector

Motion vector берется из скорости центра bbox в Kalman state. Единицы измерения
для `vx`, `vy` и `speed` - пиксели за кадр.

| Параметр | Что делает | Если увеличить | Если уменьшить | Стартовое значение |
| --- | --- | --- | --- | --- |
| `Enable motion vector` | Рисует и публикует вектор движения bbox. | Boolean: стрелки включены. | Boolean: стрелки выключены. | `on` |
| `Vector mode` | Режим отображения вектора/прицела: `velocity_arrow`, `center_to_object`, `dual_crosshair`. | Не числовой параметр. | Не числовой параметр. | `velocity_arrow` |
| `Vector scale` | Масштаб длины стрелки в режиме `velocity_arrow`. | Стрелка длиннее, направление заметнее, но может мешать видео. | Стрелка короче и менее заметна. | `5.0` |
| `Min vector speed` | Минимальная скорость перед отрисовкой стрелки. | Мелкое дрожание не рисуется. | Стрелка появляется даже при слабом шуме bbox. | `0.2-1.0` |

Режимы `Vector mode`:

```text
velocity_arrow
```

Рисует стрелку от центра bbox в направлении скорости Kalman tracker. Это режим
для оценки реального движения объекта между кадрами. `Vector scale` влияет
только на этот режим.

```text
center_to_object
```

Выбирает detection с максимальной confidence и рисует синий вектор от центра
кадра к центру bbox. Центр кадра отмечается зеленой точкой, цель - красной
точкой. Дополнительно рисуются `x_delta`, `y_delta` и `distance`.

```text
dual_crosshair
```

Похож на `center_to_object`, но вместо точек рисует два прицела: зеленый в
центре кадра и красный на задетекченном объекте. Центральный прицел крупный:
три концентрических круга и крест в центре. Прицел на объекте компактный:
маленькие круги и короткие риски вокруг центра bbox. Используется, когда нужно
визуально оценивать наведение на цель.

В режимах `center_to_object` и `dual_crosshair`:

```text
x_delta = object_center_x - frame_center_x
y_delta = object_center_y - frame_center_y
distance = sqrt(x_delta^2 + y_delta^2)
```

Если detections несколько, прицел выбирает объект с максимальной confidence.
Обычные bbox при этом продолжают рисоваться для всех detections.

Если стрелки дрожат на неподвижном объекте:

```text
Min vector speed: увеличить
Measurement noise: увеличить
```

Если стрелки слишком короткие:

```text
Vector scale: увеличить
```

## Video and MJPEG

| Параметр | Что делает | Если увеличить | Если уменьшить | Стартовое значение |
| --- | --- | --- | --- | --- |
| `Main width` | Ширина основного stream, на котором рисуются bbox. | Больше детализация и нагрузка. | Меньше нагрузка, хуже детализация. | `640` |
| `Main height` | Высота основного stream. | Больше детализация и нагрузка. | Меньше нагрузка, хуже детализация. | `640` |
| `Enable MJPEG` | Включает MJPEG stream из camera process. | Boolean: поток работает. | Boolean: поток выключен. | `on` |
| `MJPEG host` | Адрес, на котором слушает MJPEG server. | Не числовой параметр. | Не числовой параметр. | `0.0.0.0` |
| `MJPEG port` | Порт MJPEG stream. | Не влияет на качество, только меняет порт. | Не влияет на качество, только меняет порт. | `8081` |
| `MJPEG quality` | JPEG quality каждого кадра. | Лучше картинка, больше трафик/CPU. | Меньше трафик/CPU, больше артефакты. | `75-90` |
| `Disable local preview` | Отключает локальное preview окно на Raspberry Pi. | Boolean: preview выключен. | Boolean: preview включен. | Для systemd `on` |
| `Disable overlay` | Отключает bbox/ROI/vector overlay на видео. | Boolean: overlay выключен. | Boolean: overlay включен. | Обычно `off` |
| `Disable bbox UDP` | Отключает отправку bbox JSON на dashboard. | Boolean: UDP выключен. | Boolean: UDP включен. | Обычно `off` |
| `BBox UDP host` | Адрес получателя bbox JSON. | Не числовой параметр. | Не числовой параметр. | `127.0.0.1` |
| `BBox UDP port` | Порт bbox JSON. | Не влияет на detection, только меняет порт. | Не влияет на detection, только меняет порт. | `5005` |

## Быстрые пресеты

Чистая картинка без tracker:

```text
Threshold: 0.30
NMS IoU: 0.40
Max detections: 10
Enable tracker: off
Smoothing alpha: 0.8
```

Осторожное включение tracker:

```text
Threshold: 0.30
NMS IoU: 0.40
Max detections: 10
Enable tracker: on
Tracker IoU: 0.10
Max missed frames: 0
Process noise: 8.0
Measurement noise: 10.0
Confidence decay: 0.85
```

Агрессивное подавление лишних bbox:

```text
Threshold: 0.35
NMS IoU: 0.25-0.30
Max detections: 3-5
Enable tracker: on
Tracker IoU: 0.10
Max missed frames: 0
Measurement noise: 10.0
```
