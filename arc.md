
Примерная архитектура разделенная на 2 выхода:
видео + координаты для управления
```
IMX500 camera
↓
кадр + inference metadata
↓
parse detections
├── 1) bbox coordinates → guidance/control loop
└── 2) video frame + bbox overlay → запись / просмотр / отладка
```
