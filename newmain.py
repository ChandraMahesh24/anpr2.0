import ast
import json
import cv2
import time
import numpy as np
import pandas as pd
from ultralytics import YOLO
from tkinter import Tk, Button, Label, Canvas, Frame
from PIL import Image, ImageTk
import threading
from datetime import datetime
# from database_handler import DatabaseHandler
import schedule
from logger import logger
import requests

# Load the YOLO model with ByteTrack enabled
model = YOLO( r"c:\Users\Admin\Downloads\Mobliebest.pt")

class VideoCaptureBuffer:   # For resolving frame p 
    def __init__(self, video_source):
        self.video_source = video_source
        self.cap = cv2.VideoCapture(video_source)
        self.buffer_frame = None
        self.stopped = False
        self.lock = threading.Lock()
        self.is_rtsp = isinstance(video_source, str) and video_source.startswith("rtsp")

        # Start the frame updating thread
        self.thread = threading.Thread(target=self.update_frames, daemon=True)
        self.thread.start()

    def update_frames(self):
        while not self.stopped:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.buffer_frame = frame
                time.sleep(0.01)  # Small delay to prevent CPU overuse and allow frame loading
            else:
                if self.is_rtsp:
                    logger.error("Failed to capture frame from RTSP, retrying...")
                    time.sleep(1)  # Short delay before retrying RTSP
                else:
                    logger.error("Failed to capture frame from MP4. Reinitializing...")
                    # Release and reopen for MP4 to handle buffering issue
                    self.cap.release()
                    self.cap = cv2.VideoCapture(self.video_source)
                    time.sleep(1)  # Short delay to stabilize

    def read(self):
        with self.lock:
            frame = self.buffer_frame
        return frame is not None, frame

    def release(self):
        self.stopped = True
        self.thread.join()
        self.cap.release()

class SackbagDetectorApp:
    def __init__(self, video_path, conf_threshold, iou_threshold, image_size):
        self.video_path = video_path
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.image_size = image_size
        self.cap = VideoCaptureBuffer(video_path)

        # Detection and tracking parameters
        self.counter_left_to_right = 0
        self.counter_right_to_left = 0
        self.tracked_positions = {}
        self.counted_ids = set()
        self.direction_state = {}
        self.last_seen = {}
        self.current_id = 1
        self.is_running = False
        self.start_time = None
        self.csv_filename = "sackbag_detection_log.csv"
        # Line coordinates
        # 398, 2), (641, 588
        # self.line_x1 = 414
        # self.line_y1 = 2
        # self.line_x2 = 484
        # self.line_y2 = 617
        # self.min_movement_threshold = 2
        # self.distance_threshold = 120
        # self.max_inactive_frames = 3
        # self.frame_skip_interval = 1


        #  self.line_x1 = 485                  # X-coordinate of the first point of a line
        # self.line_y1 = 201                    # Y-coordinate of the first point of a line
        # self.line_x2 = 1069                  # X-coordinate of the second point of a line
        # self.line_y2 = 320 
        # (401, 88), (981, 583
        with open('config.json', 'r') as f:
            config = json.load(f)
            
        loi_point_str  = config['loi']['SB01']
        loi_points = ast.literal_eval(loi_point_str) 
        (x1, y1), (x2, y2) = loi_points
        self.line_x1 = x1
        self.line_y1 = y1
        self.line_x2 = x2
        self.line_y2 = y2
        # self.line_x1 = 401                  # X-coordinate of the first point of a line
        # self.line_y1 = 88                    # Y-coordinate of the first point of a line
        # self.line_x2 = 981                  # X-coordinate of the second point of a line
        # self.line_y2 = 583                      # Y-coordinate of the second point of a line
        self.min_movement_threshold = 2     # Minimum movement (in pixels?) required to consider something as "moved"
        self.distance_threshold = 120       # Maximum distance between detections to consider them the same object
        self.max_inactive_frames = 3        # Maximum number of frames an object can be inactive before being discarded
        self.frame_skip_interval = 1        # Number of frames to skip between processing (1 means no skipping)


        self.db_handler = DatabaseHandler()

        # Scheduler thread
        self.scheduler_thread = threading.Thread(target=self.run_scheduler, daemon=True)
        self.scheduler_thread.start()

        # Thread for posting to status API every 15 minutes
        self.status_api_url = "http://d.d.in/test"
        self.status_thread = threading.Thread(target=self.post_status_periodically, daemon=True)
        self.status_thread.start()


        self.frame_count = 0

        self.init_gui()
    def save_points(self, point1, point2):
        self.line_x1, self.line_y1 = point1
        self.line_x2, self.line_y2 = point2

    def post_status_periodically(self):
        """Post status to the API every 15 minutes."""
        while True:
            self.post_status_to_api()
            time.sleep(900)  # Sleep for 15 minutes (900 seconds)

    def post_status_to_api(self):
        """Send a POST request to the status API."""
        try:
            # Prepare the data to send, here we assume the API needs the 'IN' and 'OUT' counts
            payload = {
                'booth_code': "sackbags",
                'status': True,
                'dateandtime': datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            }
            
            # Send the POST request to the API
            response = requests.post(self.status_api_url, json=payload)
            
            if response.status_code == 200:
                print("Status posted successfully to the STATUS API.")
            else:
                logger.error(f"Failed to post status to the API. Status code: {response.status_code}")

        except Exception as e:
            logger.error(f"Error posting status to STATUS API: {e}")


    def init_gui(self):
        """Initialize the GUI with Start and Stop buttons, and Canvas for video."""
        self.window = Tk()
        self.window.title("Sackbag Detection Control Panel")
        # self.window.configure(bg="orange")  # Set window background to black

        # Create a horizontal frame for the controls
        control_frame = Frame(self.window)
        control_frame.pack(side="bottom", fill="x", pady=10)

        # Start Button
        self.start_button = Button(control_frame, text="Start", command=self.start_detection,
                                   font=("Helvetica", 15, "bold"), bg="#4CAF50", fg="white",
                                   relief="raised", padx=20, pady=10)
        self.start_button.pack(side="left", padx=10)

        # Start Time Label
        self.start_time_label = Label(control_frame, text="00:00:00",
                                      font=("Helvetica", 15, "bold"), fg="#4CAF50")
        self.start_time_label.pack(side="left", padx=5)

        # Stop Button
        self.stop_button = Button(control_frame, text="Stop", command=self.stop_detection,
                                  font=("Helvetica", 15, "bold"), bg="#F44336", fg="white",
                                  relief="raised", padx=20, pady=10)
        self.stop_button.pack(side="right", padx=10)

        # Stop Time Label
        self.stop_time_label = Label(control_frame, text="00:00:00",
                                     font=("Helvetica", 15, "bold"), fg="#F44336")
        self.stop_time_label.pack(side="right", padx=5)

        # Labels for counters

        # Frame for the counter box
        counter_box = Frame(control_frame, borderwidth=2, relief="solid", padx=5, pady=5)
        counter_box.pack(side="bottom", padx=20, pady=10, anchor="center")

        # Counter Label inside the box
        self.counter_label = Label(counter_box, text="IN: 0   OUT: 0",
                                font=("Helvetica", 20, "bold"), fg="#000000",
                                padx=10, pady=5)
        self.counter_label.pack()

        # Canvas for video display
        self.canvas = Canvas(self.window, width=1200, height=640, bg="black")
        self.canvas.pack(expand=True, anchor="center")  # Center the canvas in the window

        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.mainloop()

    def start_detection(self):
        """Start the sackbag detection."""
        self.is_running = True
        self.start_time = datetime.now()
        self.counter_left_to_right = 0
        self.counter_right_to_left = 0
        self.tracked_positions = {}
        self.counted_ids = set()
        self.direction_state = {}
        self.last_seen = {}
        self.current_id = 1
        self.frame_count = 0

        self.start_time_label.config(text=f"{self.start_time.strftime('%H:%M:%S')}")
        self.stop_time_label.config(text="00:00:00")
    
        self.update_frame()

        # Disable the Start button
        self.start_button.config(state="disabled")
        # Enable the Stop button
        self.stop_button.config(state="normal")

    def stop_detection(self):
        """Stop the sackbag detection and save results to CSV."""
        if self.is_running:
            self.is_running = False
            stop_time = datetime.now()
            # self.save_to_csv(self.start_time, stop_time)

            self.stop_time_label.config(text=f"{stop_time.strftime('%H:%M:%S')}")
            self.start_time_label.config(text=f"{self.start_time.strftime('%H:%M:%S')}")  # Keep the start time label

            self.counter_label.config(text=f"IN: {self.counter_left_to_right}   OUT: {self.counter_right_to_left}")

            # Re-enable the Start button
            self.start_button.config(state="normal")
            # Disable the Stop button
            self.stop_button.config(state="disabled")
            
    def save_to_csv(self, start_time, stop_time):
        """Save the detection results to a CSV file."""
        date = start_time.date()
        data = {
            "Start Time": [start_time.strftime("%H:%M:%S")],
            "Stop Time": [stop_time.strftime("%H:%M:%S")],
            "Date": [date],
            "IN": [self.counter_left_to_right],
            "OUT": [self.counter_right_to_left]
        }
        df = pd.DataFrame(data)

        try:
            df.to_csv(self.csv_filename, mode='a', header=not pd.io.common.file_exists(self.csv_filename), index=False)
            # print(f"Results saved to {self.csv_filename}")
        except Exception as e:
            logger.error(f"Failed to save results to CSV: {e}")




    def point_side(self, x1, y1, x2, y2, px, py):
        return (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)


    def update_frame(self):
        """Continuously capture frames and update the Canvas in the Tkinter window."""
        if not self.is_running:
            return

        # Frame skipping
        if self.frame_count % self.frame_skip_interval != 0:
            self.frame_count += 1
            self.window.after(33, self.update_frame)
            return

        # Capture frame
        ret, frame = self.cap.read()
        if not ret:
            logger.error("Waiting for frame...")
            return

        frame = cv2.resize(frame, (1200, 640))
        self.frame_count += 1

        results = model.track(
            source=frame,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            imgsz=self.image_size,
            tracker="bytetrack.yaml",
            verbose=False
        )

        # ROI (optional, tweak as needed)
        # roi_left = min(self.line_x1, self.line_x2) - 1000
        # roi_right = max(self.line_x1, self.line_x2) + 500
        # roi_top = min(self.line_y1, self.line_y2)
        # roi_bottom = max(self.line_y1, self.line_y2)


        roi_left = min(self.line_x1, self.line_x2) - 200
        roi_right = max(self.line_x1, self.line_x2) + 0
        roi_top = min(self.line_y1, self.line_y2) - 1000
        roi_bottom = max(self.line_y1, self.line_y2) + 500

        for r in results:
            for box in r.boxes:
                if box.id is None:
                    continue

                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

                if not (roi_left <= cx <= roi_right and roi_top <= cy <= roi_bottom):
                    continue

                # Compute distance from known positions
                distances = [
                    np.linalg.norm(np.array((cx, cy)) - np.array((prev_cx, prev_cy)))
                    for prev_cx, prev_cy in self.tracked_positions.values()
                ]

                if distances and min(distances) < self.distance_threshold:
                    obj_id = next(
                        id_ for id_, (prev_cx, prev_cy) in self.tracked_positions.items()
                        if np.linalg.norm(np.array((cx, cy)) - np.array((prev_cx, prev_cy))) < self.distance_threshold
                    )
                else:
                    obj_id = self.current_id
                    self.current_id += 1

                if obj_id in self.counted_ids:
                    continue

                # Draw box and ID
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
                cv2.circle(frame, (cx, cy), 5, (255, 0, 0), -1)
                cv2.putText(frame, f"ID: {obj_id}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                # Track crossings using tilted line logic
                if obj_id in self.tracked_positions:
                    prev_cx, prev_cy = self.tracked_positions[obj_id]
                    self.last_seen[obj_id] = self.frame_count

                    prev_side = self.point_side(self.line_x1, self.line_y1, self.line_x2, self.line_y2, prev_cx, prev_cy)
                    curr_side = self.point_side(self.line_x1, self.line_y1, self.line_x2, self.line_y2, cx, cy)

                    if prev_side * curr_side < 0 and abs(cx - prev_cx) > self.min_movement_threshold:
                        # Object crossed the tilted line
                        if cx > prev_cx:
                            self.counter_left_to_right += 1
                            self.direction_state[obj_id] = "left_to_right"
                            self.db_handler.insert_crossing(in_count=True, out_count=False)
                        else:
                            self.counter_right_to_left += 1
                            self.direction_state[obj_id] = "right_to_left"
                            self.db_handler.insert_crossing(in_count=False, out_count=True)
                else:
                    self.last_seen[obj_id] = self.frame_count

                self.tracked_positions[obj_id] = (cx, cy)

        # Clean up old IDs
        inactive_ids = [
            id_ for id_, last_seen in self.last_seen.items()
            if self.frame_count - last_seen > self.max_inactive_frames
        ]
        for id_ in inactive_ids:
            self.tracked_positions.pop(id_, None)
            self.last_seen.pop(id_, None)
            self.direction_state.pop(id_, None)

        # Display stats and visual lines
        self.counter_label.config(text=f"IN: {self.counter_left_to_right}   OUT: {self.counter_right_to_left}")
        cv2.line(frame, (self.line_x1, self.line_y1), (self.line_x2, self.line_y2), (0, 255, 0), 2)
        cv2.rectangle(frame, (roi_left, roi_top), (roi_right, roi_bottom), (255, 0, 0), 2)

        # Update UI
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)
        imgtk = ImageTk.PhotoImage(image=img)
        self.canvas.create_image(0, 0, anchor="nw", image=imgtk)
        self.canvas.image = imgtk

        if self.is_running:
            self.window.after(33, self.update_frame)

    def close(self):
        """Cleanly exit the application."""
        self.is_running = False
        self.cap.release()
        cv2.destroyAllWindows()
        self.window.destroy()

    def run_scheduler(self):
        """Runs the scheduler to post pending entries every 15 minutes."""
        # schedule.every(1).minutes.do(self.post_pending_entries) #UNCOMMWNT IN REAL USE
        while True:
            # schedule.run_pending()  #UNCOMMWNT IN REAL USE
            time.sleep(1)

    def post_pending_entries(self):
        """Fetch and post pending entries to the API and update their status."""
        self.db_handler.post_pending_entries()

if __name__ == "__main__":
    # video_path = "rtsp://admin:admin%23123@192.168.0.110:554/cam/realmonitor?channel=1&subtype=0"  # Path to the video file
    
    # video_path = r"D:\kmg\kgm_ch1_20250701142051_20250701143251.mp4"
    # conf_threshold = 0.2
    # iou_threshold = 0.3
    # image_size = 640
    # app = SackbagDetectorApp(video_path, conf_threshold, iou_threshold, image_size)
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    video_path = config['rtsp']['SB01']
    conf_threshold = config['detection']['conf_threshold']
    iou_threshold = config['detection']['iou_threshold']
    image_size = config['detection']['image_size']
    
    app = SackbagDetectorApp(video_path, conf_threshold, iou_threshold, image_size)
