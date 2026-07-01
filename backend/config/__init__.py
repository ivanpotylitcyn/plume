# Локально используем чистый Python-драйвер PyMySQL вместо C-расширения
# mysqlclient (не требует сборки на macOS/Apple Silicon). Сама СУБД — настоящий
# MySQL 8.0.25 в Docker, поэтому паритет по констрейнтам/типам сохраняется.
import pymysql

# Спуфинг версии: Django-бэкенд mysql на старте требует минимальную версию mysqlclient
# (Django 6.0 подняла планку до 2.2.1; было 1.4.3 на 4.2/5.2). PyMySQL 1.2.0 внутренне
# уже сообщает version_info=(2,2,8) — прикидываемся ею явно, детерминированно проходя
# проверку 6.0. install_as_MySQLdb() выдаёт PyMySQL за MySQLdb (чистый Python, без сборки).
pymysql.version_info = (2, 2, 8, "final", 0)
pymysql.install_as_MySQLdb()
