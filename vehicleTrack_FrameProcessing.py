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
from collections import defaultdict

import cv2
import threading
import queue
import time
import numpy as np
from pathlib import Path
from ultralytics import YOLO
from paddleocr import PaddleOCR
from collections import defaultdict
import re

class VideoCaptureBuffer:
    def __init__(self, source=0, buffer_size=5, skip_rate=1):
        self.source = source
        self.buffer = queue.Queue(maxsize=buffer_size)
        self.skip_rate = skip_rate
        self.reading = False
        self.thread = None
        self.is_file = isinstance(source, str) and Path(source).suffix.lower() in ['.mp4', '.avi', '.mov', '.mkv']
        self.track_history = defaultdict(list)

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
                break

            if frame_index % self.skip_rate == 0:
                if self.buffer.full():
                    try:
                        self.buffer.get_nowait()
                    except queue.Empty:
                        pass
                self.buffer.put_nowait(frame)

            frame_index += 1

            if self.is_file:
                fps = self.cap.get(cv2.CAP_PROP_FPS)
                time.sleep(0.8 / fps if fps > 0 else 0.01)

        self.reading = False
        self.cap.release()

    def get_frame(self):
        try:
            return self.buffer.get_nowait()
        except queue.Empty:
            return None


class VehicleNumberPlateProcessor:
    def __init__(self, video_path, target_fps=10, buffer_size=30):
        self.video_path = video_path
        self.target_fps = target_fps
        self.model = YOLO("vehicle(n).pt")
        self.model.fuse()
        self.ocr = PaddleOCR(use_angle_cls=True)
        self.frame_buffer = VideoCaptureBuffer(video_path, buffer_size=buffer_size, skip_rate=1)
        self.frame_queue = queue.Queue(maxsize=buffer_size)
        self.is_processing = False
        self.is_paused = False
        self.pause_event = threading.Event()
        self.processing_thread = None
        self.track_history = defaultdict(list)
        self.processed_tracks = set()

    def start_processing(self):
        if self.is_processing:
            return
        self.is_processing = True
        self.is_paused = False
        self.pause_event.set()
        self.frame_buffer.start()
        self.processing_thread = threading.Thread(target=self._process_frames, daemon=True)
        self.processing_thread.start()

    def stop_processing(self):
        self.is_processing = False
        self.frame_buffer.stop()
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join()

    def pause_processing(self):
        self.is_paused = True
        self.pause_event.clear()

    def resume_processing(self):
        self.is_paused = False
        self.pause_event.set()

    def get_processed_frame(self):
        if not self.frame_queue.empty():
            return self.frame_queue.get()
        return None

    def _process_frames(self):
        while self.is_processing:
            self.pause_event.wait()
            frame = self.frame_buffer.get_frame()
            if frame is None:
                time.sleep(0.01)
                continue
            self._process_frame(frame)

 
    # def _process_frame(self, frame):
    #     results = self.model.track(frame, persist=True)
    #     boxes = results[0].boxes

    #     if boxes and boxes.is_track:
    #         track_ids = boxes.id.int().cpu().tolist()
    #         boxes_xyxy = boxes.xyxy.cpu().numpy()
    #         class_ids = boxes.cls.int().cpu().tolist()
    #         class_names = [self.model.names[class_id] for class_id in class_ids]

    #         for i in range(len(track_ids)):
    #             track_id = track_ids[i]
    #             x1, y1, x2, y2 = map(int, boxes_xyxy[i])
    #             class_name = class_names[i]
    #             label = f"{class_name} ID: {track_id}"

    #             # Draw box
    #             cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 3)

    #             # Draw label with background
    #             font = cv2.FONT_HERSHEY_SIMPLEX
    #             font_scale = 1.2
    #             font_thickness = 2
    #             (w, h), _ = cv2.getTextSize(label, font, font_scale, font_thickness)
    #             cv2.rectangle(frame, (x1, y1 - h - 12), (x1 + w + 10, y1), (0, 0, 0), -1)
    #             cv2.putText(frame, label, (x1 + 5, y1 - 5), font, font_scale, (0, 255, 255), font_thickness)

    #             # Draw track trail
    #             center = ((x1 + x2) // 2, (y1 + y2) // 2)
    #             self.track_history[track_id].append(center)
    #             if len(self.track_history[track_id]) > 30:
    #                 self.track_history[track_id].pop(0)

    #             points = np.array(self.track_history[track_id]).reshape((-1, 1, 2))
    #             cv2.polylines(frame, [points], False, (255, 255, 0), 2)
    def _process_frame(self, frame):
        results = self.model.track(frame, persist=True)
        boxes = results[0].boxes

        if boxes and boxes.is_track:
            track_ids = boxes.id.int().cpu().tolist()
            boxes_xyxy = boxes.xyxy.cpu().numpy()
            class_ids = boxes.cls.int().cpu().tolist()
            class_names = [self.model.names[class_id] for class_id in class_ids]

            for i in range(len(track_ids)):
                track_id = track_ids[i]
                x1, y1, x2, y2 = map(int, boxes_xyxy[i])
                class_name = class_names[i]
                label = f"{class_name} ID: {track_id}"

                # Draw box
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 3)

                # Draw label with background
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 1.2
                font_thickness = 2
                (w, h), _ = cv2.getTextSize(label, font, font_scale, font_thickness)
                cv2.rectangle(frame, (x1, y1 - h - 12), (x1 + w + 10, y1), (0, 0, 0), -1)
                cv2.putText(frame, label, (x1 + 5, y1 - 5), font, font_scale, (0, 255, 255), font_thickness)

                # Draw track trail
                center = ((x1 + x2) // 2, (y1 + y2) // 2)
                self.track_history[track_id].append(center)
                if len(self.track_history[track_id]) > 30:
                    self.track_history[track_id].pop(0)

                points = np.array(self.track_history[track_id]).reshape((-1, 1, 2))
                cv2.polylines(frame, [points], False, (255, 255, 0), 2)

        if not self.frame_queue.full():
            self.frame_queue.put(frame)


    def _process_ocr(self, track_id, cropped, ocr_image, x1, y1):
        try:
            ocr_results = self.ocr.ocr(ocr_image, cls=True)
            if not ocr_results or not ocr_results[0]:
                return
            combined_text = self._extract_text_from_ocr(ocr_results)
            formatted_plate = self._is_valid_indian_vehicle_number_plate(combined_text)
            if formatted_plate:
                self._annotate_frame_with_text(cropped, formatted_plate, x1, y1)
        except Exception as e:
            print(f"Error during OCR for track {track_id}: {e}")

    def _extract_text_from_ocr(self, ocr_results):
        return " ".join([result[1][0].strip() for result in ocr_results[0]]).strip()

    def _is_valid_indian_vehicle_number_plate(self, text):
        corrections = {'O': '0', 'o': '0', 'S': '5', 's': '5', 'I': '1', 'i': '1'}
        if not text:
            return None
        text = ''.join(corrections.get(c, c) for c in text)
        sanitized = re.sub(r"[^A-Za-z0-9]", "", text).upper()
        return sanitized if re.match(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$", sanitized) else None

    def _annotate_frame_with_text(self, frame, text, x1, y1):
        font_scale = 1
        font_thickness = 2
        padding = 10
        margin = 15
        color = (255, 0, 0)
        text_width, text_height = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thickness)[0]
        text_x = x1
        text_y = max(y1 - text_height - padding - margin, 20)
        cv2.rectangle(frame, (text_x, text_y - text_height - padding),
                      (text_x + text_width + padding, text_y), color, -1)
        cv2.putText(frame, text, (text_x, text_y - padding), cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale, (255, 255, 255), font_thickness)
