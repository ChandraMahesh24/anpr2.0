from concurrent.futures import ThreadPoolExecutor
import json
import os
import queue
import datetime
import shutil
import threading
import time
import cv2
import re
import base64
from pathlib import Path
import numpy as np
from paddleocr import PaddleOCR
from sklearn import logger
from ultralytics import YOLO
import yaml
from ocr_database_handler import OCRDatabase
from PIL import Image, ImageTk

class VideoCaptureBuffer:
    def __init__(self, source=0, buffer_size=5, skip_rate=1):
        self.source = source
        self.buffer = queue.Queue(maxsize=buffer_size)
        self.skip_rate = skip_rate
        self.reading = False
        self.thread = None
        self.is_file = isinstance(source, str) and Path(source).suffix.lower() in ['.mp4', '.avi', '.mov', '.mkv']

    def start(self):
        self.cap = cv2.VideoCapture(self.source)
        if not self.cap.isOpened():
            print(f"Error: Unable to open video source: {self.source}")
            return

        self.reading = True
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def stop(self):
        self.reading = False
        if self.thread and self.thread.is_alive():
            self.thread.join()
        if self.cap:
            self.cap.release()

    def _reader(self):
        frame_index = 0
        while self.reading and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                print("End of video file or read failure.")
                break

            if frame_index % self.skip_rate == 0:
                if self.buffer.full():
                    try:
                        self.buffer.get_nowait()
                    except queue.Empty:
                        pass
                self.buffer.put_nowait(frame)

            frame_index += 1

            # For video files, simulate real-time processing (optional)
            if self.is_file:
                fps = self.cap.get(cv2.CAP_PROP_FPS)
                time.sleep(0.4 / fps if fps > 0 else 0.01)

        self.reading = False
        self.cap.release()
        print("Stopped video reading.")

    def get_frame(self):
        try:
            return self.buffer.get_nowait()
        except queue.Empty:
            return None

class VehicleNumberPlateProcessor:
    def __init__(self, video_path, target_fps=10, buffer_size=30):
        self.video_path = video_path
        self.target_fps = target_fps
        self.db = OCRDatabase()
        self.model = YOLO(r"anpr(n).pt")
        self.model.fuse()
        self.ocr = PaddleOCR(use_angle_cls=True)
        self.frame_buffer = VideoCaptureBuffer(video_path, buffer_size=buffer_size, skip_rate=1)
        self.frame_queue = queue.Queue(maxsize=buffer_size)
        self.is_processing = False
        self.is_paused = False
        self.pause_event = threading.Event()
        self.processing_thread = None
        self.io_worker = IOWorker('NumberPlate_data.yaml')
        self.io_worker.start()

    def start_processing(self):
        if self.is_processing:
            print("Processing already running.")
            return
        self.is_processing = True
        self.is_paused = False
        self.pause_event.set()
        self.frame_buffer.start()
        self.processing_thread = threading.Thread(target=self._process_frames, daemon=True)
        self.processing_thread.start()

    def stop_processing(self):
        if not self.is_processing:
            print("Processing is already stopped.")
            return
        self.is_processing = False
        self.frame_buffer.stop()
        print("Stopping processing...")
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join()
        print("Processing stopped.")

    def pause_processing(self):
        if self.is_processing and not self.is_paused:
            self.is_paused = True
            self.pause_event.clear()
            print("Processing paused.")

    def resume_processing(self):
        if self.is_processing and self.is_paused:
            self.is_paused = False
            self.pause_event.set()
            print("Processing resumed.")

    def get_processed_frame(self):
        if not self.frame_queue.empty():
            return self.frame_queue.get()
        return None
    def _process_frames(self):
        video_name = Path(self.video_path).stem if self.video_path != 0 else "webcam"
        cameraId = self.db.insert_video(video_name)

        frame_index = 0
        skip_rate = 1  # <-- Now we skip frames here, not in VideoCaptureBuffer

        while self.is_processing:
            self.pause_event.wait()
            frame = self.frame_buffer.get_frame()
            if frame is None:
                time.sleep(0.01)
                continue

            if frame_index % skip_rate == 0:
                self._process_frame(frame, cameraId)

            frame_index += 1


    def _process_frame(self, frame, cameraId):
        if frame is None:
            return

        with open('NumberPlate_data.yaml', 'w') as f:
            yaml.dump([], f)
        with open('BlackListNumberPlate_data.yaml', 'w') as f:
            yaml.dump([], f)

        self.io_worker.data = []
        self.io_worker.blacklist_data = []

        results = self.model(frame)
        boxes = results[0].boxes

        for box in boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 3)

            cropped = frame[y1:y2, x1:x2]
            ocr_image = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)

            try:
                ocr_results = self.ocr.ocr(ocr_image, cls=True)
                if ocr_results is None:
                    continue

                combined_text = self._extract_text_from_ocr(ocr_results)
                current_dataTime = datetime.datetime.now().strftime("%d-%m-%y %H:%M:%S")
                current_data= datetime.datetime.now().strftime("%d-%m-%Y")
                current_time = datetime.datetime.now().strftime("%H:%M:%S")
                
                is_blacklistNumberPlate = 0

                if combined_text:
                    formatted_plate = self._is_valid_indian_vehicle_number_plate(combined_text)
                    if formatted_plate:
                        _, buffer = cv2.imencode('.jpg', cropped)
                        base64_image = base64.b64encode(buffer).decode('utf-8')

                        if self.db.is_plate_blacklisted(formatted_plate):
                            is_blacklistNumberPlate = 1
                            alert_message = f"Blacklisted vehicle detected\n{formatted_plate}"
                            for i, line in enumerate(alert_message.split("\n")):
                                self._annotate_frame_with_text(frame, line, x1, y1 + i * 30, True)
                            self.io_worker.queue.put({
                                'type': 'write_yaml_blacklist',
                                'data': {
                                    'blackListNumber': formatted_plate,
                                    'detectionTime': current_dataTime,
                                    'numberPlate': formatted_plate,
                                    'numberPlate_current_dataTime': current_dataTime,
                                    'image': base64_image,
                                    'timestamp': time.time()
                                }
                            })
                        else:
                            self._annotate_frame_with_text(frame, formatted_plate, x1, y1, False)

                        self.io_worker.queue.put({
                            'type': 'db_insert',
                            'func': self.db.insert_or_update_ocr_result,
                            'args': (cameraId, base64_image, formatted_plate, is_blacklistNumberPlate)
                        })

                        self.io_worker.queue.put({
                            'type': 'write_yaml',
                            'data': {
                                'numberPlate': formatted_plate,
                                'numberPlate_current_dataTime': current_dataTime,
                                'image': base64_image
                            }
                        })
            except Exception as e:
                print(f"Error processing frame: {e}")

        if not self.frame_queue.full():
            self.frame_queue.put(frame)


    def _extract_text_from_ocr(self, ocr_results):
        if not ocr_results:
            return None
        return " ".join([result[1][0].strip() for result in ocr_results[0]]).strip()

    def _is_valid_indian_vehicle_number_plate(self, text):
        corrections = {'O': '0', 'o': '0', 'S': '5', 's': '5', 'I': '1', 'i': '1'}
        if not text:
            return None
        text = ''.join(corrections.get(c, c) for c in text)
        sanitized = re.sub(r"[^A-Za-z0-9]", "", text).upper()
        return sanitized if re.match(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$", sanitized) else None

    def _annotate_frame_with_text(self, frame, text, x1, y1, is_blacklisted=False):
        font_scale = 1
        font_thickness = 2
        padding = 10
        margin = 15
        color = (0, 0, 255) if is_blacklisted else (255, 0, 0)
        text_width, text_height = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thickness)[0]
        text_x = x1
        text_y = max(y1 - text_height - padding - margin, 20)
        cv2.rectangle(frame, (text_x, text_y - text_height - padding), (text_x + text_width + padding, text_y), color, -1)
        cv2.putText(frame, text, (text_x, text_y - padding), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), font_thickness)


class IOWorker(threading.Thread):
    def __init__(self, yaml_path, blacklist_yaml_path="BlackListNumberPlate_data.yaml"):
        super().__init__(daemon=True)
        self.queue = queue.Queue()
        self.yaml_path = yaml_path
        self.blacklist_yaml_path = blacklist_yaml_path
        self.data = self._load_existing_data(self.yaml_path)
        self.blacklist_data = self._load_existing_data(self.blacklist_yaml_path)
        self.blacklist_lock = threading.Lock()

    def _load_existing_data(self, path):
        if os.path.exists(path):
            with open(path, 'r') as f:
                return yaml.safe_load(f) or []
        return []

    def run(self):
        while True:
            self._cleanup_expired_blacklist_entries()
            try:
                task = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if task is None:
                break

            try:
                if task['type'] == 'write_yaml':
                    self.data.append(task['data'])
                    with open(self.yaml_path, 'w') as f:
                        yaml.dump(self.data, f)
                elif task['type'] == 'write_yaml_blacklist':
                    with self.blacklist_lock:
                        self.blacklist_data.append(task['data'])
                        self._write_blacklist_yaml()
                elif task['type'] == 'db_insert':
                    task['func'](*task['args'])
            except Exception as e:
                print(f"[IOWorker Error] {e}")

    def _cleanup_expired_blacklist_entries(self):
        current_time = time.time()
        with self.blacklist_lock:
            self.blacklist_data = [entry for entry in self.blacklist_data if current_time - entry.get('timestamp', 0) < 3]
            self._write_blacklist_yaml()

    def _write_blacklist_yaml(self):
        with open(self.blacklist_yaml_path, 'w') as f:
            yaml.dump(self.blacklist_data, f)
