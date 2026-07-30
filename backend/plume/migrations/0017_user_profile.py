"""Волна 21, Ф1 — `UserProfile`: настройки интерфейса пользователя (пока одна, тема).

**Приставка, а не расширение `User`.** Кастомную модель пользователя вводить поздно и
незачем — ДНК Django остаётся нетронутой, наше висит сбоку через `OneToOne`. Это первая
таблица приложения `plume`, прицепленная к чужой сущности (комментарий ER-диаграммы
README «своей таблицы в `plume` нет» этой миграцией стал ложным и правится в том же
изменении).

Почему таблица, а не `localStorage`: тема — свойство ЧЕЛОВЕКА, она едет за ним между
машинами и браузерами, и форма про человека обязана показывать то, что действительно
про человека. `localStorage` хранит состояние вью (какой таб открыт), а не свойства
сущности. Почему не key/value-таблица настроек: это ровно тот запас на будущее, который
продукт отвергает, — одна настройка = одна колонка.

**`CheckConstraint` на `theme` не ставим сознательно** (при том что применимость
`choices` продукт обычно стережёт в БД): каждая новая тема — набор ФАЙЛОВ ВЬЮ, и
требовать под неё миграцию значит вписать вью в схему. Валидация — в движке
(`engine.set_theme`), там же, где живут остальные правила.

Профили рождаются **лениво** (`engine.profile_of`, `get_or_create`), сигналом на
`post_save` пользователя — намеренно нет: сигнал это магия на расстоянии ради экономии
одной строки, и он ломает `loaddata` (снимки прода, `deploy/pull_prod.sh`). Поэтому
данные здесь не мигрируются: у существующих пользователей профиль появится при первом
`me()`, с темой по умолчанию.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plume', '0016_counterparty_no_roles'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('theme', models.CharField(default='dark', max_length=32, verbose_name='тема интерфейса')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='profile', to=settings.AUTH_USER_MODEL, verbose_name='пользователь')),
            ],
            options={
                'verbose_name': 'профиль пользователя',
                'verbose_name_plural': 'профили пользователей',
            },
        ),
    ]
