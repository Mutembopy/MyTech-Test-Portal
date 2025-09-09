import sqlite3

conn = sqlite3.connect('technicians.db')
try:
    conn.execute("ALTER TABLE reports ADD COLUMN technician_id INTEGER;")
except sqlite3.OperationalError:
    pass  # Column already exists
conn.commit()
conn.close()
