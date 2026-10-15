"""Парсер тела запроса с гигиеной текста (2026-10-15).

Единая точка, через которую проходит каждая JSON-мутация API: строки тела чистятся
`engine.clean_text` ДО того, как их увидит вьюха или движок. Ключ `code` чистится
кодовым правилом (двойники дефиса → `-`), остальное — общим. Поле формы спрашивает то
же правило заранее (`/api/hygiene/`) и даёт человеку выбор; этот слой — молчаливая
страховка для всего, что пришло мимо всплывашки (прямой запрос, строки таблиц).

Где текст священен (пароли, сам вопрос к гигиене), вьюха ставит сырой
`JSONParser` через `@parser_classes` — исключение задаётся у вьюхи, а не списком
ключей здесь: имена полей пароля (`password`/`current`/`new`) слишком общие.
"""
from rest_framework.parsers import JSONParser

from . import engine


def _clean(value, key=None):
    if isinstance(value, str):
        return engine.clean_text(value, code=(key == 'code'))
    if isinstance(value, dict):
        return {k: _clean(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


class HygieneJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        return _clean(super().parse(stream, media_type, parser_context))
