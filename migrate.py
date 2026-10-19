# 一次性迁移脚本，跑一次就行
import sqlite3
conn = sqlite3.connect("data/quiz.db")
try:
    conn.execute("ALTER TABLE wrong_book ADD COLUMN ease REAL DEFAULT 2.5")
    conn.execute("ALTER TABLE wrong_book ADD COLUMN interval_days INTEGER DEFAULT 1")
    conn.execute("ALTER TABLE wrong_book ADD COLUMN repetitions INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE wrong_book ADD COLUMN next_review TEXT")
    conn.commit()
    print("迁移完成")
except sqlite3.OperationalError as e:
    print(f"字段可能已存在：{e}")
finally:
    conn.close()