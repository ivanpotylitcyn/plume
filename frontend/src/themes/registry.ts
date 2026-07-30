// Реестр тем — ЗНАНИЕ ВЬЮ (шов, волна 21, Р8). Движок хранит и стережёт слаг, а как
// тема называется по-человечески, знает только эта таблица: в `plume` про ярлыки нет
// ни колонки, ни строки кода.
//
// Ярлыки — «Тёмная» / «Светлая», без «2026». Родословная («значения взяты из Dark 2026 /
// Light 2026, дефолтных тем VS Code») — документация, её место в UI_GUIDE §10, а не в
// кнопке выбора: VS Code выпустит следующий дефолт, и версия в подписи соврёт.
//
// Порядок = порядок дропдауна.
import type { ThemeSlug } from '../core/theme'

export const THEMES: { slug: ThemeSlug; label: string }[] = [
  { slug: 'dark', label: 'Тёмная' },
  { slug: 'light', label: 'Светлая' },
]

export const THEME_LABEL =
  Object.fromEntries(THEMES.map(t => [t.slug, t.label])) as Record<ThemeSlug, string>
