// Измеритель тесноты списка (волна 25, Ф3) — одно место на все табы всех форм.
//
// Поднимает ступень `data-fit` на `.fs-list`, пока список шире своей панели
// (`scrollWidth > clientWidth`); что прятать на каждой ступени, решает CSS по РОЛЯМ
// колонок (лестница — в `index.css` у `.fs-list`). Пороги в пикселях не годятся: списки
// разные, и скелет у каждого свой, — поэтому меряем, а не угадываем.
//
// Каждый пересчёт идёт с нуля: область могла вырасти, и спрятанное должно вернуться.
// Колбэк ResizeObserver исполняется после раскладки и до отрисовки, поэтому промежуточные
// ступени не мигают; итог равен прошлому — повторного уведомления нет, цикла тоже.
//
// Знак, а не смысл: живёт в теме рядом с `FormShell`, движок о нём не знает.
import { useLayoutEffect, type RefObject } from 'react'

const TOP = 5   // последняя ступень; дальше — страховка `overflow-x: auto`

// `key` — что меняет содержимое списка без смены его ширины (таб, сущность, замок).
export function useFit(ref: RefObject<HTMLElement | null>, key: string) {
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const fit = () => {
      delete el.dataset.fit
      for (let lv = 1; lv <= TOP && el.scrollWidth > el.clientWidth + 0.5; lv++)
        el.dataset.fit = String(lv)
      // Содержимое таба приезжает асинхронно (таблица вместо «загрузка…»): следим и за
      // детьми — их ширина растёт раньше, чем панель что-то заметит.
      for (const c of el.children) ro.observe(c)
    }
    const ro = new ResizeObserver(fit)
    ro.observe(el)
    fit()
    return () => ro.disconnect()
  }, [ref, key])
}
