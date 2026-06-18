import pymysql
from .db_config import DB_HOST,DB_USER,DB_PASSWORD,DB_NAME
class DBManager:

    def __init__(self):
        # 数据库配置
        self.config = {
            'host': DB_HOST,
            'user': DB_USER,
            'password': DB_PASSWORD,
            'database': DB_NAME,
            'charset': 'utf8mb4',
            'cursorclass': pymysql.cursors.DictCursor
        }
        self.conn = None

    def connect(self):
        """建立数据库链接"""
        try:
            self.conn = pymysql.connect(**self.config)
            return self.conn
        except pymysql.MySQLError as e:
            print(f"数据库链接失败{e}")
            raise

    def close(self):
        """关闭数据库链接"""
        if self.conn and self.conn.open:
            self.conn.close()


if __name__ == '__main__':
    conn = DBManager().connect()
    if conn:
        print("数据库链接正常")
        conn.close()
