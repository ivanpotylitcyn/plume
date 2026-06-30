# Локально используем чистый Python-драйвер PyMySQL вместо C-расширения
# mysqlclient (не требует сборки на macOS/Apple Silicon). Сама СУБД — настоящий
# MySQL 8.0.25 в Docker, поэтому паритет по констрейнтам/типам сохраняется.
import pymysql

pymysql.install_as_MySQLdb()
