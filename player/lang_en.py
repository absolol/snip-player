"""Английские надписи плеера: {русская строка из кода: английская}. Читает i18n.tr().

Ключ — точно та же строка, что в tr("…") (склеенные строки — целиком). Подстановки {n}, {name}… — те же, что
в русской строке. Нет перевода — показывается русская строка (проверка — тест в scratchpad, scan.py).
"""

EN = {
    # --- Общее -------------------------------------------------------------
    "Произошла ошибка": "Something went wrong",
    "Подробности записаны в файл:": "Details were written to the file:",
    "Произошла ошибка. Подробности записаны в файл:": "Something went wrong. Details were written to the file:",
    "Отмена": "Cancel",
    "Готово": "Done",
    "Понятно": "OK",
    "Закрыть": "Close",
    "Закрыть (Esc)": "Close (Esc)",
    "Свернуть": "Minimize",
    "Развернуть": "Maximize",
    "Свернуть в окно": "Restore down",
    "Поверх всех окон — щёлкните, чтобы выключить": "Always on top — click to turn off",
    "Щёлкните, чтобы увидеть сведения о видео": "Click to see video details",
    "Видео ({videos});;Все файлы (*)": "Videos ({videos});;All files (*)",

    # --- Окно и панель -----------------------------------------------------
    "Перетащите видео сюда или откройте файл": "Drop a video here or open a file",
    "Открыть файл": "Open file",
    "Открыть видео": "Open video",
    "Оформление…": "Appearance…",
    "Настройки…": "Settings…",
    "Горячие клавиши": "Keyboard shortcuts",
    "Воспроизведение / пауза (Пробел)": "Play / pause (Space)",
    "Стоп": "Stop",
    "Назад на 5 секунд (←)": "Back 5 seconds (←)",
    "Вперёд на 5 секунд (→)": "Forward 5 seconds (→)",
    "Назад на {n} с (←)": "Back {n} s (←)",
    "Вперёд на {n} с (→)": "Forward {n} s (→)",
    "Предыдущее видео в папке (PgUp)": "Previous video in the folder (PgUp)",
    "Следующее видео в папке (PgDn)": "Next video in the folder (PgDn)",
    "Кадр назад (,)": "Previous frame (,)",
    "Кадр вперёд (.)": "Next frame (.)",
    "Без звука (M)": "Mute (M)",
    "Громкость (↑ / ↓)": "Volume (↑ / ↓)",
    "Скриншот кадра (P) — в «Изображения» и в буфер обмена": "Screenshot of the frame (P) — to “Pictures” and the clipboard",
    "Обрезка видео (C)": "Trim video (C)",
    "Скорость, поверх всех окон, настройки": "Speed, always on top, settings",
    "Во весь экран (F)": "Full screen (F)",
    "Выйти из полноэкранного режима (F / Esc)": "Exit full screen (F / Esc)",
    "Скорость": "Speed",
    "Скорость: {rate}": "Speed: {rate}",
    "Повтор": "Repeat",
    "Поверх всех окон": "Always on top",
    "Обычное окно": "Normal window",
    "Убрать разрез": "Remove split",

    # --- Сообщения поверх видео ---------------------------------------------
    "Продолжаем с {time}": "Resuming from {time}",
    "Это первое видео в папке": "This is the first video in the folder",
    "Это последнее видео в папке": "This is the last video in the folder",
    "Не удалось создать папку для скриншотов": "Couldn't create the screenshots folder",
    "Не удалось сделать скриншот": "Couldn't take a screenshot",
    "Изображения": "Pictures",
    "Скриншот сохранён в «{where}»": "Screenshot saved to “{where}”",
    "Скриншот сохранён в «{where}» и скопирован": "Screenshot saved to “{where}” and copied",
    "Скриншот сохранён в «{where}» (буфер обмена занят)": "Screenshot saved to “{where}” (clipboard is busy)",
    "Повтор включён": "Repeat on",
    "Повтор выключен": "Repeat off",

    # --- Вопросы и ошибки ---------------------------------------------------
    "Идёт сохранение видео": "Saving the video",
    "Дождитесь окончания — потом можно будет открыть другой файл.":
        "Please wait until it finishes — then you can open another file.",
    "Если выйти сейчас, сохранение прервётся.": "If you quit now, saving will stop.",
    "Прервать и выйти": "Stop and quit",
    "Не удалось открыть файл": "Couldn't open the file",
    "Возможно, файл повреждён или это не видео.": "The file may be damaged or it isn't a video.",
    "Обрезка не сохранена": "The trim isn't saved",
    "Если продолжить, разрезы и пометки этого видео пропадут.":
        "If you continue, the splits and marks on this video will be lost.",
    "Продолжить без сохранения": "Continue without saving",
    "Перезапустить плеер?": "Restart the player?",
    "Язык сменится после перезапуска. Открытое видео продолжится с того же места.":
        "The language will change after a restart. The open video will continue from the same spot.",
    "Перезапустить": "Restart",
    "Позже": "Later",

    # --- Сохранение обрезки -------------------------------------------------
    "Сохранить как копию": "Save as copy",
    "Сохранить с удалением": "Save and replace",
    "Обрезанное видео сохраняется в новый файл — вы выберете имя и папку. Исходное видео остаётся без изменений.":
        "The trimmed video is saved to a new file — you choose the name and folder. The original video stays unchanged.",
    "Исходный файл заменяется обрезанной версией под тем же именем. Старое видео отправляется в корзину Windows — "
    "при необходимости его можно оттуда восстановить.":
        "The original file is replaced by the trimmed version under the same name. The old video goes to the "
        "Windows Recycle Bin — you can restore it from there if needed.",
    "Выбрать способ сохранения": "Choose how to save",
    "Сохранить куски отдельно": "Save segments separately",
    "Каждый выделенный кусок — в свой файл, в папку, которую вы выберете. Ничего не выделено — "
    "все оставленные куски.":
        "Each selected segment goes to its own file in a folder you choose. Nothing selected — "
        "all kept segments.",
    "Сейчас: {n} {word}.": "Now: {n} {word}.",
    "Папка для кусков": "Folder for the segments",
    "{stem} — кусок {n}": "{stem} — segment {n}",
    "Сохранено {n} {word}": "{n} {word} saved",
    "… и ещё {n}": "… and {n} more",
    "Кусок {n} из {total}: ": "Segment {n} of {total}: ",
    "Уже сохранены:": "Already saved:",
    "Сохранить с удалением?": "Save and replace?",
    "Файл «{name}» будет заменён обрезанной версией. Старое видео отправится в корзину Windows — при необходимости "
    "его можно оттуда восстановить.":
        "“{name}” will be replaced by the trimmed version. The old video will go to the Windows Recycle Bin — "
        "you can restore it from there if needed.",
    "Заменить файл": "Replace file",
    "{stem} (обрезано)": "{stem} (trimmed)",
    "Тот же формат (*{suffix});;MP4 (*.mp4);;MKV (*.mkv);;Все файлы (*)":
        "Same format (*{suffix});;MP4 (*.mp4);;MKV (*.mkv);;All files (*)",
    "Это тот же файл": "This is the same file",
    "Чтобы заменить исходное видео обрезанным, выберите «Сохранить с удалением» в меню ▾ у кнопки сохранения.":
        "To replace the original video with the trimmed one, choose “Save and replace” in the ▾ menu "
        "next to the save button.",
    "Не удалось убрать исходный файл": "Couldn't remove the original file",
    "Возможно, он занят другой программой. Обрезанное видео сохранено рядом:":
        "It may be in use by another program. The trimmed video was saved next to it:",
    "Не удалось заменить исходный файл": "Couldn't replace the original file",
    "Видео сохранено, но заменить исходный файл не удалось: {error}":
        "The video was saved, but the original file couldn't be replaced: {error}",
    "Обрезанное видео лежит здесь:": "The trimmed video is here:",
    "Видео сохранено": "Video saved",
    "Показать в папке": "Show in folder",
    "Старое видео — в корзине Windows.": "The old video is in the Windows Recycle Bin.",
    "Файл заменён обрезанной версией": "File replaced with the trimmed version",
    "Не удалось сохранить видео": "Couldn't save the video",

    # --- Редактор -----------------------------------------------------------
    "✂  Разрезать": "✂  Split",
    "Разрезать видео в текущей позиции (S)": "Split the video at the current position (S)",
    "🗑  Удалить кусок": "🗑  Delete segment",
    "🗑  Удалить куски": "🗑  Delete segments",
    "⭯  Вернуть кусок": "⭯  Restore segment",
    "⭯  Вернуть куски": "⭯  Restore segments",
    "Удалить / вернуть выделенные куски (Ctrl+X)": "Delete / restore the selected segments (Ctrl+X)",
    "Отменить (Ctrl+Z)": "Undo (Ctrl+Z)",
    "Вернуть (Ctrl+Y)": "Redo (Ctrl+Y)",
    "Сбросить": "Reset",
    "Убрать все разрезы и пометки": "Remove all splits and marks",
    "Удаляется {n} {word}": "{n} {word} removed",
    "Без потерь": "Lossless",
    "Быстро": "Fast",
    "Без потерь — разрезы точно по кадру, качество и битрейт как в исходнике:\n"
    "видео и звук копируются без перекодирования, заново кодируются только\n"
    "несколько кадров у каждой границы разреза (с почти без потерь качеством).\n\n"
    "Быстро — всё копируется, почти мгновенно, но границы сдвигаются\n"
    "к ближайшим ключевым кадрам (до ~1–2 секунд).":
        "Lossless — frame-accurate splits, same quality and bitrate as the original:\n"
        "video and audio are copied without re-encoding; only a few frames\n"
        "at each split are encoded again (at near-lossless quality).\n\n"
        "Fast — everything is copied almost instantly, but the splits move\n"
        "to the nearest keyframes (up to ~1–2 seconds).",
    "Остановить сохранение": "Stop saving",
    "Сохранение…": "Saving…",
    "Как резать видео": "How to trim a video",
    "Разрезы": "Splits",
    "Куски": "Segments",
    "Таймлайн": "Timeline",
    "Правка": "Editing",
    "разрезать здесь": "split here",
    "Тянуть маркер": "Drag marker",
    "подвинуть разрез": "move a split",
    "ПКМ по маркеру": "Right-click marker",
    "убрать разрез": "remove a split",
    "ЛКМ": "Click",
    "выделить кусок": "select a segment",
    "Ctrl + ЛКМ": "Ctrl + Click",
    "выделить несколько": "select several",
    "удалить / вернуть": "delete / restore",
    "Колесо": "Wheel",
    "увеличить / уменьшить": "zoom in / out",
    "Shift + колесо": "Shift + Wheel",
    "прокрутить": "scroll",
    "кадр назад / вперёд": "frame back / forward",
    "отменить / вернуть": "undo / redo",
    "сохранить": "save",

    # --- Звуковые дорожки (track_button.py) ---------------------------------
    "Дорожка {n}": "Track {n}",
    "Нет звука": "No audio",
    "Слушать эту дорожку в плеере": "Listen to this track in the player",
    "Какие звуковые дорожки сохранить": "Which audio tracks to save",
    "Звук в сохранённом видео": "Audio in the saved video",
    "🎧 — послушать дорожку, пока смотрите видео": "🎧 — listen to a track while you watch",
    "Без звука": "No audio",
    "Звук: {n} из {total}": "Audio: {n} of {total}",
    "Нечего сохранять: в файле нет видео, а звук не выбран.":
        "Nothing to save: the file has no video and no audio is selected.",

    # --- Сохранение: ход и итог (exporter.py) -------------------------------
    "Сохранение отменено.": "Saving canceled.",
    "видеокарта NVIDIA (NVENC)": "NVIDIA graphics card (NVENC)",
    "видеокарта Intel (Quick Sync)": "Intel graphics (Quick Sync)",
    "видеокарта AMD (AMF)": "AMD graphics card (AMF)",
    "процессор": "processor",
    "Кодирование: {who}.": "Encoding: {who}.",
    "Анализ видео…": "Analyzing the video…",
    "Быстрый режим: всё скопировано без перекодирования, границы разрезов сдвинуты к ближайшим ключевым кадрам "
    "(максимум на {n} с).":
        "Fast mode: everything was copied without re-encoding; the splits moved to the nearest keyframes "
        "(by {n} s at most).",
    "Быстрый режим: скопировано без перекодирования.": "Fast mode: copied without re-encoding.",
    "Звук сохранён без перекодирования.": "Audio saved without re-encoding.",
    "Без потерь: видео и звук скопированы без перекодирования, заново закодированы только кадры у границ разрезов "
    "({n} шт.).":
        "Lossless: video and audio were copied without re-encoding; only the frames at the splits were encoded "
        "again ({n}).",
    "умная обрезка не прошла проверку ({error})": "smart trimming failed the check ({error})",
    "для кодека {codec} умная обрезка недоступна": "smart trimming isn't available for the {codec} codec",
    "этого видео": "this video's",
    "Перекодирование с максимальным качеством…": "Re-encoding at maximum quality…",
    "Видео перекодировано с очень высоким качеством, звук скопирован без изменений ({reason}).":
        "The video was re-encoded at very high quality, the audio was copied unchanged ({reason}).",
    "Копирование без перекодирования…": "Copying without re-encoding…",
    "Кадры у границ разрезов и копирование… (перекодируется {n} с)": "Frames at the splits and copying… ({n} s to re-encode)",
    "Сборка файла…": "Putting the file together…",
    "Проверка результата…": "Checking the result…",
    "FFmpeg не найден. Установите его и перезапустите плеер.": "FFmpeg wasn't found. Install it and restart the player.",
    "Непредвиденная ошибка: {error}": "Unexpected error: {error}",
    "Не удалось определить длительность видео.": "Couldn't determine the video length.",
    "число кадров не совпало: {got} вместо {expected}": "frame count mismatch: {got} instead of {expected}",
    "длина звука {audio} с не совпадает с длиной видео {video} с":
        "audio length {audio} s doesn't match video length {video} s",
    "FFmpeg завершился с ошибкой (код {code}).": "FFmpeg failed (code {code}).",
    "Не удалось прочитать видео.": "Couldn't read the video.",
    "ошибка декодирования у стыков около {times} с": "decoding error at the joins around {times} s",

    # --- Горячие клавиши ----------------------------------------------------
    "Шаги перемотки и громкости, скорость ускорения — в Настройки → «Воспроизведение»":
        "Seek and volume steps and hold speed are in Settings → “Playback”",
    "на {n} {word}": "by {n} {word}",
    "Воспроизведение": "Playback",
    "Перемотка": "Seeking",
    "Звук и прочее": "Sound and more",
    "Редактор": "Editor",
    "Пробел": "Space",
    "пауза / воспроизведение": "pause / play",
    "Зажать пробел": "Hold Space",
    "ускорение {rate}": "speed up {rate}",
    "ЛКМ по видео": "Click video",
    "Зажать ЛКМ": "Hold click",
    "ускорение, тянуть ← → — 1×…{rate}": "speed up, drag ← → for 1×…{rate}",
    "во весь экран (и двойной щелчок)": "full screen (or double-click)",
    "выйти из полноэкранного": "exit full screen",
    "предыдущее / следующее видео": "previous / next video",
    "громкость (шаг {n} %)": "volume ({n}% step)",
    "без звука": "mute",
    "скриншот кадра": "screenshot of the frame",
    "повтор вкл / выкл": "repeat on / off",
    "открыть файл": "open file",
    "настройки": "settings",
    "выход": "quit",
    "открыть / закрыть редактор": "open / close the editor",
    "ЛКМ по куску": "Click segment",
    "масштаб шкалы": "zoom the timeline",
    "прокрутить шкалу": "scroll the timeline",

    # --- Сведения о видео ---------------------------------------------------
    "Копировать": "Copy",
    "Скопировать сведения как текст": "Copy the details as text",
    "Открыть папку": "Open folder",
    "Показать файл в Проводнике": "Show the file in File Explorer",
    "Скопировано ✓": "Copied ✓",
    "Собираю сведения…": "Gathering details…",
    "Файл": "File",
    "Видео": "Video",
    "Звук": "Audio",
    "Размер": "Size",
    "Длительность": "Duration",
    "Формат": "Format",
    "Общий битрейт": "Overall bitrate",
    "Изменён": "Modified",
    "Папка": "Folder",
    "Разрешение": "Resolution",
    "Частота кадров": "Frame rate",
    "Кодек": "Codec",
    "Битрейт": "Bitrate",
    "Частота": "Sample rate",
    "Каналы": "Channels",
    "Дорожек": "Tracks",
    "моно": "mono",
    "стерео": "stereo",
    "{n} кан.": "{n} ch.",
    "{n} ГБ": "{n} GB",
    "{n} МБ": "{n} MB",
    "{n} КБ": "{n} KB",
    "{n} Мбит/с": "{n} Mbit/s",
    "{n} кбит/с": "{n} kbit/s",
    "{n} к/с": "{n} fps",
    "{n} кГц": "{n} kHz",
    "Нет сведений: не найден ffprobe": "No details: ffprobe wasn't found",
    "нет видеодорожки": "no video track",
    "нет звуковой дорожки": "no audio track",
    "Не удалось прочитать файл: {error}": "Couldn't read the file: {error}",

    # --- Регистрация в Windows ----------------------------------------------
    "Видео ({app})": "Video ({app})",
    "Видеоплеер с обрезкой видео": "Video player with video trimming",
    "Готово: «{app}» добавлен в «Открыть с помощью» для видео.": "Done: “{app}” was added to “Open with” for videos.",
    "Команда открытия: {command}": "Open command: {command}",
    "Чтобы видео открывались в нём двойным щелчком: правой кнопкой по видео →":
        "To open videos in it with a double-click: right-click a video →",
    "«Открыть с помощью» → «Выбрать другое приложение» → «{app}» → «Всегда».":
        "“Open with” → “Choose another app” → “{app}” → “Always”.",
    "Это нужно сделать по одному разу для каждого формата (mp4, mkv, …).":
        "You need to do this once for each format (mp4, mkv, …).",
    "Готово: регистрация «{app}» в Windows удалена.": "Done: the “{app}” registration was removed from Windows.",
    "Если плеер был выбран по умолчанию, Windows при следующем открытии видео спросит, чем его открыть.":
        "If the player was the default, Windows will ask which app to use the next time you open a video.",

    # --- Настройки ----------------------------------------------------------
    "Настройки": "Settings",
    "Внешний вид": "Appearance",
    "Окно": "Window",
    "Скриншоты": "Screenshots",
    "Обрезка и сохранение": "Trimming and saving",
    "Система": "System",
    "{n} с": "{n} s",
    "{n} %": "{n}%",
    "Продолжать с места, где остановились": "Resume where you left off",
    "Для каждого видео запоминается своё место": "Each video remembers its own spot",
    "В конце видео": "At the end of a video",
    "Остановиться": "Stop",
    "Следующее в папке": "Next in folder",
    "Перемотка стрелками ← →": "Seek with arrows ← →",
    "Перемотка с Shift": "Seek with Shift",
    "Шаг громкости ↑ ↓": "Volume step ↑ ↓",
    "Ускорение при удержании": "Speed when holding",
    "Мышь на видео или пробел: сначала эта скорость…": "Mouse on the video or Space: this speed first…",
    "Предел ускорения": "Speed limit",
    "…а если потянуть мышь вправо — до этой": "…and up to this one if you drag the mouse right",
    "Сменится после перезапуска плеера": "Takes effect after the player restarts",
    "Основа": "Base",
    "Фон и текст подбираются сами — всё остаётся читаемым":
        "Background and text adjust automatically — everything stays readable",
    "Тёмная": "Dark",
    "Светлая": "Light",
    "Цвет интерфейса": "Interface color",
    "Кнопки, шкала, выделение, кнопка «закрыть»": "Buttons, timeline, selection, the close button",
    "Цвет уведомлений": "Notification color",
    "Оттенки цвета интерфейса: как он, светлее, глубже, соседние":
        "Shades of the interface color: same, lighter, deeper, neighbors",
    "Так будут выглядеть уведомления": "This is how notifications will look",
    "Свой цвет": "Custom color",
    "Свой…": "Custom…",
    "Обводка кнопок окна": "Window button outline",
    "Кружки «свернуть / развернуть / закрыть» в заголовке": "The minimize / maximize / close circles in the title bar",
    "Нет": "None",
    "Мягкая": "Soft",
    "Акцент": "Accent",
    "Кнопка «Стоп» на панели": "Stop button on the panel",
    "Уведомления поверх видео": "Notifications over the video",
    "«Скриншот сохранён», «Повтор включён» и т. п.": "“Screenshot saved”, “Repeat on” and so on",
    "Сколько держать уведомление": "How long to show a notification",
    "Открывать новые видео в том же окне": "Open new videos in the same window",
    "Двойной щелчок по видео, когда плеер уже открыт, — файл откроется в нём, а не в новом окне. "
    "Выключение подействует со следующего запуска плеера":
        "Double-click a video while the player is open, and it opens there instead of in a new window. "
        "Turning this off takes effect the next time the player starts",
    "Изменить…": "Change…",
    "Папка для скриншотов": "Screenshots folder",
    "PNG — без потерь, JPG — файлы меньше": "PNG — lossless, JPG — smaller files",
    "Копировать в буфер обмена": "Copy to the clipboard",
    "Чтобы сразу вставить скриншот в чат или документ": "To paste the screenshot into a chat or document right away",
    "Кодирование": "Encoding",
    "Видеокарта — быстрее; процессор — если с видеокартой что-то не так":
        "Graphics card is faster; use the processor if something is wrong with the graphics card",
    "Видеокарта": "Graphics card",
    "Процессор": "Processor",
    "Качество по умолчанию": "Default quality",
    "«Без потерь» — точно по кадру; «Быстро» — по ключевым кадрам":
        "“Lossless” is frame-accurate; “Fast” cuts at keyframes",
    "Способ по умолчанию": "Default method",
    "«С удалением» — старый файл уходит в корзину": "“Replace” sends the old file to the Recycle Bin",
    "Как копию": "As a copy",
    "С удалением": "Replace",
    "Плеер для видео в Windows": "Video player in Windows",
    "Добавляет «Snip Player» в «Открыть с помощью» (только для вашего пользователя). Чтобы видео открывались "
    "двойным щелчком: Открыть с помощью → Выбрать другое приложение → Snip Player → Всегда":
        "Adds “Snip Player” to “Open with” (for your user only). To open videos with a double-click: "
        "Open with → Choose another app → Snip Player → Always",
    "Сейчас": "Now",
    "Сделать плеером для видео": "Make it the video player",
    "Убрать регистрацию": "Remove registration",
    "✓ Зарегистрирован": "✓ Registered",
    "Не зарегистрирован": "Not registered",
    "Регистрация устарела — нажмите «Сделать плеером» ещё раз":
        "Registration is out of date — click “Make it the video player” again",
    "Зарегистрирован для другой папки — нажмите «Сделать плеером» ещё раз":
        "Registered for another folder — click “Make it the video player” again",
    "Не удалось сделать плеером для видео": "Couldn't make it the video player",
    "Не удалось убрать регистрацию": "Couldn't remove the registration",
    "Запись в реестр не удалась: {error}": "Writing to the registry failed: {error}",

    # --- Цвета (подсказки кружков) ------------------------------------------
    "Синий": "Blue",
    "Фиолетовый": "Purple",
    "Розовый": "Pink",
    "Красный": "Red",
    "Оранжевый": "Orange",
    "Жёлтый": "Yellow",
    "Зелёный": "Green",
    "Бирюзовый": "Teal",
    "Как интерфейс": "Same as the interface",
    "Светлее": "Lighter",
    "Глубже": "Deeper",
    "Соседний оттенок": "Neighboring hue",
    "Соседний оттенок с другой стороны": "Neighboring hue on the other side",
}
