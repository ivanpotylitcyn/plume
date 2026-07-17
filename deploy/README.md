# Деплой plume на reg.ru shared hosting

Рантбук выкатки. **Проект открытый — в этих файлах и в коммитах нет и не должно
быть секретов, доменов, логинов, IP.** Всё чувствительное передаётся аргументами
`deploy_local.sh` и лежит в `backend/.env` только на сервере.

**Стек:** Python 3.14 + Django 6.0 + DRF 3.17, MySQL, Phusion Passenger, статика через
WhiteNoise; фронт — React/Vite (Django отдаёт SPA + `/admin` + `/api` с одного origin).

**Локальные требования** (на машине, откуда деплоишь): `lftp` (`brew install lftp` —
rsync на reg.ru не работает), **Node ≥ 22.12** под nvm (текущий LTS v24; иначе Vite 8
ругается), локальный Python 3.14 для валидации (`pyenv install 3.14`).

## Что где

| Файл | Где исполняется | Роль |
|------|-----------------|------|
| `deploy_local.sh` | твоя машина | сборка фронта + заливка (lftp/SFTP) + запуск серверного скрипта |
| `deploy.sh` | сервер (корень сайта) | venv, зависимости, миграции, `collectstatic`, рестарт Passenger |
| `passenger_wsgi.py` | сервер (корень сайта) | точка входа Passenger; кладёт `backend/` и venv в `sys.path` |

## Раскладка на сервере (docroot сайта)

```
SITE_ROOT/                 <- корень сайта в ISPmanager
  passenger_wsgi.py        (заливается)
  deploy.sh                (заливается)
  venv/                    (создаётся на сервере при --init)
  tmp/restart.txt          (создаётся; touch = рестарт Passenger)
  backend/                 (config/, plume/, manage.py, requirements.txt, .env, staticfiles/)
  frontend/dist/           (собранный React, заливается с локальной машины)
```

## Разовая подготовка

1. **ISPmanager → Сайты:** сайт уже создан, включить обработчик **Python 3.14**
   (стек — Django 6.0, требует Python ≥ 3.12).
2. **ISPmanager → Базы данных:** БД + пользователь уже созданы (запомни имя/пароль
   — они пойдут в серверный `.env`, не в репозиторий).
3. **SSH-ключ:** приватный ключ у тебя локально, публичный — на хостинге (готово).
4. **Серверный `backend/.env`:** создать вручную ОДИН раз (в репозиторий не попадает).
   Образец — `backend/.env.example`. Прод-значения: `DJANGO_DEBUG=0`, реальный
   `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, доступ к БД.
   Проще всего: залить первый раз кодом (шаг ниже), затем на сервере
   `cp backend/.env.example backend/.env` и отредактировать.

## Первый деплой (три фазы — из-за курицы-яйца с `.env`)

`.env` кладётся в `backend/` на сервере, а `backend/` появляется только после первой
заливки. Поэтому первый раз делаем в три захода.

**Фаза 1 — залить код + создать venv** (упадёт на `migrate` — `.env` ещё нет, это ОК):
```bash
bash deploy/deploy_local.sh \
  --server ПОЛЬЗОВАТЕЛЬ@ХОСТ \
  --remote-dir '~/www/твой-сайт' \      # одинарные кавычки обязательны (тильда)
  --key ~/.ssh/твой_приватный_ключ \
  --init
```

**Фаза 2 — создать `.env` на сервере** (по SSH или в файловом менеджере ISPmanager):
```bash
cd ~/www/твой-сайт/backend && cp .env.example .env && nano .env
```
Заполнить: `DJANGO_DEBUG=0`, свежий `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` (домены
без схемы), `DJANGO_CSRF_TRUSTED_ORIGINS` (домены СО схемой `https://`), доступ к БД
(`DB_HOST=localhost`, `DB_PORT=3306`). `CORS_ALLOWED_ORIGINS` можно оставить пустым.

**Фаза 3 — миграции + сид + статика** (venv уже есть, `--init` не нужен):
```bash
bash deploy/deploy_local.sh \
  --server ПОЛЬЗОВАТЕЛЬ@ХОСТ --remote-dir '~/www/твой-сайт' \
  --key ~/.ssh/твой_приватный_ключ --seed
```

После этого (один раз) — суперюзер (`deploy.sh` его не создаёт):
```bash
ssh -i ~/.ssh/твой_приватный_ключ ПОЛЬЗОВАТЕЛЬ@ХОСТ
cd ~/www/твой-сайт && source venv/bin/activate && cd backend
python manage.py createsuperuser
```

> Альтернатива фазам 1–2: заранее создать `backend/.env` в файловом менеджере
> ISPmanager, тогда сразу `--init --seed` одной командой.

## Обновление

```bash
bash deploy/deploy_local.sh \
  --server ПОЛЬЗОВАТЕЛЬ@ХОСТ \
  --remote-dir '~/www/твой-сайт' \
  --key ~/.ssh/твой_приватный_ключ
```

`--skip-build` — залить уже собранный `frontend/dist` без пересборки.

## Эксплуатация (после деплоя)

- **Вход в админку:** заходи по прямой ссылке `/admin/login/`. На `/admin/` reg.ru
  вешает анти-бот challenge (страница `<meta refresh>` + cookie `RCPC`) — браузер
  проходит его сам и попадает на Django-админку; `curl` на нём «залипает» (не исполняет
  meta-refresh). Если в обычной вкладке `/admin/` показал витрину — это кэш/клиентская
  навигация SPA: жёсткий релоад (Cmd+Shift+R) или инкогнито.
- **Удаление сид-пользователя (`admin/admin`):** напрямую не удаляется — на него
  ссылаются документы (`on_delete=PROTECT`, авторство на документах). Сначала переназначь
  авторство на реального суперюзера, потом удаляй:
  ```bash
  python manage.py shell -c "
  from django.contrib.auth import get_user_model
  U=get_user_model(); a=U.objects.get(username='admin'); t=U.objects.get(username='ТВОЙ_СУПЕРЮЗЕР')
  for rel in a._meta.related_objects:
      f=rel.field
      if f.many_to_many: continue
      rel.related_model.objects.filter(**{f.name:a}).update(**{f.name:t})
  a.delete()"
  ```
- **Чистый прод без демо** (когда понадобится): флаш демо-данных + ввод реальных —
  отдельный шаг, здесь не автоматизирован.

## Пойманные грабли (унаследованы от соседнего проекта на том же хостинге)

- **rsync на reg.ru shared не работает** — только `lftp` по `sftp://`.
- **`python3.X` не в PATH** — venv через полный путь `/opt/python/python-3.14/bin/python`
  (`deploy.sh` дефолтит на 3.14; переопределяется `--python`).
- **lftp `--exclude` — regex, не glob** — везде `--exclude-glob=`.
- **`~` в `--remote-dir` раскрывается локально** — передавать в одинарных кавычках.
- **PyMySQL и «mysqlclient ≥ 2.2.1»** — Django 6.0 поднял планку; `backend/config/__init__.py`
  спуфит `version_info` до (2,2,8), иначе старт падает `ImproperlyConfigured`.
- **`cryptography` обязателен** — MySQL 8 по умолчанию `caching_sha2_password`, для него
  PyMySQL требует пакет `cryptography` (`RuntimeError: 'cryptography' package is required…`).
  Он в `requirements.txt` (ставится готовым abi3-wheel, без сборки Rust). Локально мог не
  проявляться из-за fast-path кэша caching_sha2 в docker-MySQL.
- **Фронт собираем локально, заливаем готовый `dist`** — осознанный выбор (так проще
  и воспроизводимее). Node на сервере reg.ru есть (`/usr/bin/node`), так что при желании
  сборку можно перенести на сервер, но мы этого не делаем.
- **WhiteNoise + Manifest-хранилище** — НЕ используем: у ассетов Vite свои хэши;
  Manifest перехэшировал бы их и падал на `url(...)` в CSS-комментариях. Берём
  `CompressedStaticFilesStorage` (без манифеста).
- **`createsuperuser`** — ручной разовый шаг, в `deploy.sh` его нет.
- **Прод-`.env` живёт только на сервере** — `deploy_local.sh` его не заливает и не
  удаляет (основной mirror без `--delete`).
- **Каталог миграций — единственное исключение: заливается С `--delete`.** Он обязан
  ТОЧНО совпадать с репо. Иначе стухшие после сквоша файлы (напр. `0002_transfer_posted`
  после «Сквош миграций») остаются на сервере и дают `CommandError: multiple leaf nodes
  in the migration graph` на `migrate`. В каталоге нет серверных файлов, удаление
  безопасно. Разовая ручная чистка стухших миграций на сервере:
  `rm backend/plume/migrations/0002_transfer_posted.py` + `rm -rf` его `__pycache__`.
