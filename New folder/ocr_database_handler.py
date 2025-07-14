import sqlite3
import datetime
from threading import Lock


class OCRDatabase:
    def __init__(self, db_path="anprTest.db"):
        self.db_path = db_path
        self.lock = Lock()
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._create_tables()
        self._ensure_column_exists()

    def _create_tables(self):
        with self.lock:
            with self.connection:
                cursor = self.connection.cursor()

                # Create ANPR table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS ANPR (
                        videoId INTEGER PRIMARY KEY AUTOINCREMENT,
                        cameraId TEXT NOT NULL,
                        creation_date TEXT NOT NULL,
                        created_time TEXT NOT NULL,
                        total_ocr_results INTEGER DEFAULT 0
                    )
                """)

                # Unique constraint for cameraId + creation_date
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_camera_date_unique
                    ON ANPR (cameraId, creation_date)
                """)

                # Create OCRResults table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS OCRResults (
                        resultId INTEGER PRIMARY KEY AUTOINCREMENT,
                        videoId INTEGER NOT NULL,
                        cameraId TEXT,
                        image TEXT NOT NULL,
                        ocr_result TEXT NOT NULL,
                        is_blacklistNumberPlate INTEGER DEFAULT 0,
                        detected_date TEXT,
                        detected_time TEXT,
                        FOREIGN KEY (videoId) REFERENCES ANPR (videoId)
                    )
                """)

                # Create blacklist table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS blacklistNumberPlate (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        plate_number TEXT UNIQUE NOT NULL
                    )
                """)

    def _ensure_column_exists(self):
        with self.lock:
            cursor = self.connection.cursor()

            # Check OCRResults table for new columns
            cursor.execute("PRAGMA table_info(OCRResults);")
            ocr_columns = [row["name"] for row in cursor.fetchall()]
            if "is_blacklistNumberPlate" not in ocr_columns:
                cursor.execute("ALTER TABLE OCRResults ADD COLUMN is_blacklistNumberPlate INTEGER DEFAULT 0;")
            if "detected_date" not in ocr_columns:
                cursor.execute("ALTER TABLE OCRResults ADD COLUMN detected_date TEXT;")
            if "detected_time" not in ocr_columns:
                cursor.execute("ALTER TABLE OCRResults ADD COLUMN detected_time TEXT;")
            if "cameraId" not in ocr_columns:
                cursor.execute("ALTER TABLE OCRResults ADD COLUMN cameraId TEXT;")

            # Check ANPR table for new columns
            cursor.execute("PRAGMA table_info(ANPR);")
            anpr_columns = [row["name"] for row in cursor.fetchall()]
            if "created_time" not in anpr_columns:
                cursor.execute("ALTER TABLE ANPR ADD COLUMN created_time TEXT;")
            if "cameraId" not in anpr_columns:
                cursor.execute("ALTER TABLE ANPR ADD COLUMN cameraId TEXT;")

            self.connection.commit()

    def insert_video(self, camera_id):
        now = datetime.datetime.now()
        creation_date = now.strftime("%Y-%m-%d")
        created_time = now.strftime("%H:%M:%S")

        with self.lock:
            with self.connection:
                cursor = self.connection.cursor()

                # Check for existing record for same cameraId + date
                cursor.execute("""
                    SELECT videoId FROM ANPR
                    WHERE cameraId = ? AND creation_date = ?
                """, (camera_id, creation_date))
                row = cursor.fetchone()

                if row:
                    return row["videoId"]

                # Insert new record
                cursor.execute("""
                    INSERT INTO ANPR (cameraId, creation_date, created_time)
                    VALUES (?, ?, ?)
                """, (camera_id, creation_date, created_time))

                return cursor.lastrowid

    def insert_or_update_ocr_result(self, cameraId, image, ocr_result, is_blacklistNumberPlate):
        now = datetime.datetime.now()
        detected_date = now.strftime("%Y-%m-%d")
        detected_time = now.strftime("%H:%M:%S")

        with self.lock:
            with self.connection:
                cursor = self.connection.cursor()

                # Get videoId for this cameraId and today's date
                cursor.execute("""
                    SELECT videoId FROM ANPR
                    WHERE cameraId = ? AND creation_date = ?
                """, (cameraId, detected_date))
                row = cursor.fetchone()

                if not row:
                    # Create new video entry if not exists
                    videoId = self.insert_video(cameraId)
                else:
                    videoId = row["videoId"]

                # Check if result already exists
                cursor.execute("""
                    SELECT resultId FROM OCRResults
                    WHERE ocr_result = ? AND videoId = ?
                """, (ocr_result, videoId))
                existing = cursor.fetchone()

                if existing:
                    # Update timestamps if record exists
                    cursor.execute("""
                        UPDATE OCRResults 
                        SET detected_date = ?, detected_time = ?, is_blacklistNumberPlate = ?
                        WHERE resultId = ?
                    """, (detected_date, detected_time, is_blacklistNumberPlate, existing["resultId"]))
                else:
                    # Insert new OCR result
                    cursor.execute("""
                        INSERT INTO OCRResults 
                        (videoId, cameraId, image, ocr_result, detected_date, detected_time, is_blacklistNumberPlate)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (videoId, cameraId, image, ocr_result, detected_date, detected_time, is_blacklistNumberPlate))

                    # Update result count in ANPR
                    cursor.execute("""
                        UPDATE ANPR
                        SET total_ocr_results = total_ocr_results + 1
                        WHERE videoId = ?
                    """, (videoId,))


    def get_ocr_results(self, videoId):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM OCRResults WHERE videoId = ?", (videoId,))
            return [dict(row) for row in cursor.fetchall()]

    def get_ocr_results_by_camera_and_date(self, camera_id, date):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT ocr.videoId, ocr.cameraId, ocr.ocr_result, ocr.detected_date, ocr.detected_time, ocr.is_blacklistNumberPlate
                FROM OCRResults ocr
                JOIN ANPR a ON a.videoId = ocr.videoId
                WHERE ocr.cameraId = ? AND ocr.detected_date = ?
            """, (camera_id, date))
            return [dict(row) for row in cursor.fetchall()]

    def add_blacklist_plate(self, plate_number):
        try:
            with self.lock:
                with self.connection:
                    cursor = self.connection.cursor()
                    cursor.execute("INSERT INTO blacklistNumberPlate (plate_number) VALUES (?)", (plate_number,))
            return True
        except sqlite3.IntegrityError:
            return False

    def is_plate_blacklisted(self, plate_number):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1 FROM blacklistNumberPlate WHERE plate_number = ?", (plate_number,))
            return cursor.fetchone() is not None

    def get_blacklisted_plates(self):
        try:
            with self.lock:
                cursor = self.connection.cursor()
                cursor.execute("SELECT plate_number FROM blacklistNumberPlate")
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error fetching blacklist: {e}")
            return []

    def _delete_plate_from_db(self, plate_number):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM blacklistNumberPlate WHERE plate_number = ?", (plate_number,))
            self.connection.commit()
            return cursor.rowcount > 0

    def is_already_plate_blacklisted(self, plate_number):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM blacklistNumberPlate WHERE plate_number = ?", (plate_number,))
            return cursor.fetchone()[0] > 0

    def close(self):
        with self.lock:
            self.connection.close()






# import re
# import sqlite3
# import datetime
# from threading import Lock

# class OCRDatabase:
#     def __init__(self, db_path="anprTest13.db"):
#         """Initialize the database connection and thread-safe lock."""
#         self.db_path = db_path
#         self.lock = Lock()
#         self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
#         self.connection.row_factory = sqlite3.Row
#         self._create_tables()
#         self._ensure_column_exists()

#     def _create_tables(self):
#         """Create necessary tables if they do not exist."""
#         with self.lock:
#             with self.connection:
#                 cursor = self.connection.cursor()

#                 cursor.execute("""
#                     CREATE TABLE IF NOT EXISTS ANPR (
#                         videoId INTEGER PRIMARY KEY AUTOINCREMENT,
#                         fileName TEXT NOT NULL,
#                         creation_date TEXT NOT NULL,
#                         total_ocr_results INTEGER DEFAULT 0
#                     )
#                 """)

#                 cursor.execute("""
#                     CREATE TABLE IF NOT EXISTS OCRResults (
#                         resultId INTEGER PRIMARY KEY AUTOINCREMENT,
#                         videoId INTEGER NOT NULL,
#                         image TEXT NOT NULL,
#                         detected_time TEXT NOT NULL,
#                         detected_data TEXT NOT NULL,
#                         ocr_result TEXT NOT NULL,
#                         is_blacklistNumberPlate INTEGER DEFAULT 0,
#                         FOREIGN KEY (videoId) REFERENCES ANPR (videoId)
#                     )
#                 """)

#                 cursor.execute("""
#                     CREATE TABLE IF NOT EXISTS blacklistNumberPlate (
#                         id INTEGER PRIMARY KEY AUTOINCREMENT,
#                         plate_number TEXT UNIQUE NOT NULL
#                     )
#                 """)

#     def _ensure_column_exists(self):
#         """Ensure the is_blacklistNumberPlate column exists in OCRResults table."""
#         with self.lock:
#             cursor = self.connection.cursor()
#             cursor.execute("PRAGMA table_info(OCRResults);")
#             columns = [row["name"] for row in cursor.fetchall()]
#             if "is_blacklistNumberPlate" not in columns:
#                 cursor.execute("ALTER TABLE OCRResults ADD COLUMN is_blacklistNumberPlate INTEGER DEFAULT 0;")
#                 self.connection.commit()

#     def insert_video(self, name):
#         """Insert a new video record and return its ID."""
#         creation_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#         with self.lock:
#             with self.connection:
#                 cursor = self.connection.cursor()
#                 cursor.execute(
#                     "INSERT INTO ANPR (fileName, creation_date) VALUES (?, ?)",
#                     (name, creation_date)
#                 )
#                 return cursor.lastrowid

#     def insert_or_update_ocr_result(self, videoId, image, ocr_result, is_blacklistNumberPlate):
#         """Insert or update an OCR result with blacklist flag."""
#         detected_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#         with self.lock:
#             with self.connection:
#                 cursor = self.connection.cursor()

#                 # Check if result already exists
#                 cursor.execute("""
#                     SELECT resultId FROM OCRResults 
#                     WHERE ocr_result = ? AND videoId = ?
#                 """, (ocr_result, videoId))
#                 existing_result = cursor.fetchone()

#                 if existing_result:
#                     cursor.execute("""
#                         UPDATE OCRResults 
#                         SET detected_time = ?, is_blacklistNumberPlate = ?
#                         WHERE resultId = ?
#                     """, (detected_time, is_blacklistNumberPlate, existing_result["resultId"]))
#                     print(f"Updated existing OCR result: {ocr_result} (Blacklisted: {is_blacklistNumberPlate})")
#                 else:
#                     cursor.execute("""
#                         INSERT INTO OCRResults (videoId, image, ocr_result, detected_time, is_blacklistNumberPlate)
#                         VALUES (?, ?, ?, ?, ?)
#                     """, (videoId, image, ocr_result, detected_time, is_blacklistNumberPlate))
                    
#                     cursor.execute("""
#                         UPDATE ANPR 
#                         SET total_ocr_results = total_ocr_results + 1 
#                         WHERE videoId = ?
#                     """, (videoId,))
#                     print(f"Inserted new OCR result: {ocr_result} (Blacklisted: {is_blacklistNumberPlate})")

#     def get_ocr_results(self, videoId):
#         """Return all OCR results for a specific video."""
#         with self.lock:
#             cursor = self.connection.cursor()
#             cursor.execute("SELECT * FROM OCRResults WHERE videoId = ?", (videoId,))
#             return [dict(row) for row in cursor.fetchall()]

#     def add_blacklist_plate(self, plate_number):
#         """Add a new blacklisted plate."""
#         try:
#             with self.lock:
#                 with self.connection:
#                     cursor = self.connection.cursor()
#                     cursor.execute(
#                         "INSERT INTO blacklistNumberPlate (plate_number) VALUES (?)", 
#                         (plate_number,)
#                     )
#             return True
#         except sqlite3.IntegrityError:
#             return False

#     def is_plate_blacklisted(self, plate_number):
#         """Check if a plate is blacklisted."""
#         with self.lock:
#             cursor = self.connection.cursor()
#             cursor.execute(
#                 "SELECT 1 FROM blacklistNumberPlate WHERE plate_number = ?", 
#                 (plate_number,)
#             )
#             return cursor.fetchone() is not None

#     def get_blacklisted_plates(self):
#         """Return a list of all blacklisted plates."""
#         try:
#             with self.lock:
#                 cursor = self.connection.cursor()
#                 cursor.execute("SELECT plate_number FROM blacklistNumberPlate")
#                 result = cursor.fetchall()
#                 return [row[0] for row in result]
#         except Exception as e:
#             print(f"Error fetching blacklist: {e}")
#             return []

#     def _delete_plate_from_db(self, plate_number):
#         """Delete a plate from blacklist."""
#         with self.lock:
#             cursor = self.connection.cursor()
#             cursor.execute("DELETE FROM blacklistNumberPlate WHERE plate_number = ?", (plate_number,))
#             self.connection.commit()
#             return cursor.rowcount > 0

#     def close(self):
#         """Close the database connection."""
#         with self.lock:
#             self.connection.close()



#     def is_already_plate_blacklisted(self, plate_number):
#         """Check if a license plate is already blacklisted."""
#         with self.lock:
#             cursor = self.connection.cursor()
#             cursor.execute("SELECT COUNT(*) FROM blacklistNumberPlate WHERE plate_number = ?", (plate_number,))
#             result = cursor.fetchone()
#             return result[0] > 0  # Returns True if plate exists







