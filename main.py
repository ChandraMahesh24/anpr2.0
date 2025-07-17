import base64
from collections import deque
from io import BytesIO
import json
import logging
import logging.config
import os
import re
from turtle import pd
import cv2
import time
from PIL import Image
# import pytesseract
import numpy as np
# import openpyxl
import requests
# import telebot
from ultralytics import YOLO
from pathlib import Path
from tkinter import Entry, Label, Toplevel, filedialog, Tk, messagebox
from PIL import Image, ImageTk
import threading
import customtkinter as ctk
import yaml
from ocr_database_handler import OCRDatabase # Assuming OCRDatabase is in ocr_database.py
from loi_points import draw_line_of_interest
from tkcalendar import DateEntry
import pandas as pd

from anprFrameProcessing import VehicleNumberPlateProcessor

# from anprFrameProcessing import VehicleNumberPlateProcessor
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
ctk.set_appearance_mode("System")  # Modes: system (default), light, dark
ctk.set_default_color_theme("dark-blue") # Themes: blue (default), dark-blue, green


class ANPRApp:
    CANVAS_WIDTH =  1024  # 1024 × 480 ,960 x540
    CANVAS_HEIGHT = 480
    BG_COLOR = "#424242"

    def __init__(self, root):
        self.root = root
        self.root.title("ANPR Video Processor")
        self.root.geometry("1000x700")
        self.root.configure(bg=self.BG_COLOR)
        self.db = OCRDatabase()
        self.processor = None
        self.video_path = None
        self.is_running = False
        self.thread = None
        self.alert_textP = None
        self.canvas_image = None
        self.recent_alerts = deque(maxlen=15)
        self.recent_alerts_numberPlate = deque(maxlen=10)
        self._setup_logger()
        self._setup_ui()
        self.API_KEY = os.getenv('TELEGRAM_API_KEY')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.camLink=""
        self.update_job = None
        self.logger = logging.getLogger(__name__)
        self.update_interval = 100
        self.video_name = None
        # self.bot = telebot.TeleBot(self.API_KEY)
        # self.recent_alerts = [] 
        # self.video_path = None  # Initialize with no video selected
        self.webcam_running = False
        self.webcam_thread = None


    def _setup_ui(self):
        self._setup_navbar()
        self._setup_left_sidebar()
        self._setup_middle_frame()
        self._setup_bottom_frame()

        # Initialize files and camera storage
        self.json_file = "config.json"
        self._ensure_json_file()

        self.yaml_file = "cameras.yaml"  # Optional if still using YAML for something
        self.cameras = {}
        self.form_window = None

        self._right_sidebar()
        self._load_cameras()

    # def _setup_ui(self):
    #     self._setup_navbar()
    #     self._setup_left_sidebar()
    #     self._setup_middle_frame()
    #     self._setup_bottom_frame()
    #     self.yaml_file = "cameras.yaml"
    #     self.cameras = {}  # Store camera toggle buttons
    #     self.form_window = None  # Track form window
    #     self._right_sidebar()
    #     self._load_cameras()
    #     self.json_file = "config.json"
    #     self._ensure_json_file(self)

    def _ensure_json_file(self):
        if not os.path.exists(self.json_file):
            with open(self.json_file, "w") as f:
                json.dump({}, f, indent=4)
    # step 1: setup the navigation bar
    def _setup_navbar(self):
        self.navbar_frame = ctk.CTkFrame(self.root, height=5, bg_color="#1F2A23")
        self.navbar_frame.pack(fill="x", side="top", pady=5)
        self.navbar_label = ctk.CTkLabel(self.navbar_frame, text="ANPR Video Processor", font=("Arial", 15))
        self.navbar_label.pack(pady=(2))
    
    # step 2: setup the left sidebar
    def _setup_left_sidebar(self):
        self.left_sidebar_frame = ctk.CTkFrame(self.root, width=350, bg_color=self.BG_COLOR, border_width=4)
        self.left_sidebar_frame.pack(side="left", fill="y",  pady=40,padx=10)

         # Define button dimensions and label width
        button_width = 110
        button_height = 40
        max_label_width = 130
        
        # Add Video Button
        # self.add_video_btn = ctk.CTkButton(self.left_sidebar_frame, text="Add Video", command=lambda: self._open_video, width=button_width, height=button_height, font=("Arial", 13))
        self.add_video_btn = ctk.CTkButton(self.left_sidebar_frame, text="Add Video", command=self._open_video, width=button_width, height=button_height, font=("Arial", 13))
        self.add_video_btn.pack(pady=(60, 20), padx=10)
        # self.webcam_bnt = ctk.CTkButton(self.left_sidebar_frame, text="webcam_bnt", command=self._start_webcam_processing, width=button_width, height=button_height, font=("Arial", 13))
        # self.webcam_bnt.pack(pady=(10, 20), padx=10)
       
        self.start_button = ctk.CTkButton(self.left_sidebar_frame, text="Start Processing", command=self._toggle_video_processing, fg_color="green", width=button_width, height=button_height, font=("Arial", 13))
        self.start_button.pack(pady=(10, 20), padx=10)

        self.pause_button = ctk.CTkButton(self.left_sidebar_frame, text="Pause/Resume", command=self._toggle_pause, width=button_width, height=button_height, font=("Arial", 13))
        self.pause_button.pack(pady=(10, 20), padx=10)

        self.video_label = ctk.CTkLabel(self.left_sidebar_frame, text="No video selected", font=("Arial", 15), width=max_label_width, anchor="w", wraplength=max_label_width)
        self.video_label.pack(pady=(10, 20), padx=10)

        self.delete_btn = ctk.CTkButton(self.left_sidebar_frame, text="Delete", command=self.open_toplevel)
        self.delete_btn.pack(pady=(10, 20), padx=10)
        self.toplevel_window = None 

        self.loi_pointbtn = ctk.CTkButton(self.left_sidebar_frame, text="Draw loi points", command=self.open_loi_point, width=button_width, height=button_height, font=("Arial", 13))
        self.loi_pointbtn.pack(pady=(10, 20), padx=10)

        self.get_excel_file = ctk.CTkButton(self.left_sidebar_frame, text="Excel", command=self.get_excel_data, width=button_width, height=button_height, font=("Arial", 13))
        self.get_excel_file.pack(pady=(10, 20), padx=10)

    def get_excel_data(self):
        """Opens a window to input camera ID and select date, then exports matching data to Excel."""
        popup = Toplevel()
        popup.title("Export OCR Data")
        popup.geometry("400x300")
        popup.resizable(False, False)

        # Label
        ctk.CTkLabel(popup, text="Enter Camera ID:", font=("Arial", 14)).pack(pady=(20, 5))

        # Camera ID textbox
        camera_textbox = ctk.CTkTextbox(popup, height=30, width=250)
        camera_textbox.pack()

        # Date picker
        ctk.CTkLabel(popup, text="Select Date:", font=("Arial", 14)).pack(pady=(20, 5))
        date_entry = DateEntry(popup, date_pattern="yyyy-mm-dd")
        date_entry.pack()

        def fetch_and_export():
            camera_id = camera_textbox.get("1.0", "end").strip()
            selected_date = date_entry.get_date().strftime('%Y-%m-%d')

            if not camera_id:
                print(" Camera ID is empty.")
                return

            try:
                # Fetch from DB
                results = self.db.get_ocr_results_by_camera_and_date(camera_id, selected_date)
            except Exception as e:
                print(f" DB Error: {e}")
                return

            if results:
                try:
                    df = pd.DataFrame(results)
                    filename = f"ocr_results_{camera_id}_{selected_date}.xlsx"
                    df.to_excel(filename, index=False)
                    print(f" Data exported to: {filename}")
                except Exception as e:
                    print(f" Error writing to Excel: {e}")
            else:
                print(" No data found for this Camera ID and Date.")

            popup.destroy()

        ctk.CTkButton(popup, text="Export to Excel", command=fetch_and_export).pack(pady=20)






    def open_loi_point(self):
        if not self.camLink or not self.active_camera_name:
            messagebox.showwarning("No Camera Selected", "Please select a camera first to draw LOI.")
            return

        print("Opening LOI drawing window...")
        print(f"RTSP Link: {self.camLink}, Camera Name: {self.active_camera_name}, Config Path: {self.json_file}")  
        draw_line_of_interest(rtsp_link=self.camLink, camera_name=self.active_camera_name, config_path=self.json_file)


    # Create a new Toplevel window  for delete
    def open_toplevel(self):
    # Check if toplevel_window is None or destroyed
        print("Opening Toplevel Window")
        if self.toplevel_window is None or not self.toplevel_window.winfo_exists():
            self.toplevel_window = ToplevelWindow(self)  # Create a new window if None or destroyed
            # print("Creating new Toplevel Window")
            
        else:
            self.toplevel_window.focus()  # Focus the existing window
    
    def _setup_logger(self):
        logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
        self.logger = logging.getLogger("ANPRApp")

    # step 3: Open video file dialog
    def _open_video(self):
        """Open a video file using file dialog."""
        try:
            self.video_path = filedialog.askopenfilename(
                filetypes=[("Video files", "*.mp4 *.avi *.mkv *.ts *.webm")]
            )
            if self.video_path and os.path.exists(self.video_path):
                self.video_label.configure(text=f"Selected: {Path(self.video_path).name}")
                self.logger.info(f"Video selected: {self.video_path}")
                self.camLink = None
                # self._reset_camera_toggles()
            else:
                self.video_path = None
                self.video_label.configure(text="No source selected")
                self.logger.info("No video file selected.")
        except Exception as e:
            print(f"Error in _open_video: {e}")
            self.logger.error(f"Error in _open_video: {e}")
            
    def _toggle_video_processing(self):
        if self.is_running:
            self._stop_processing()
        else:
            self._start_processing()

    # Initializes and starts video processing from a file or RTSP stream in a separate thread. 
    def _start_processing(self):
        """Start processing the selected video file or RTSP stream."""
        self.logger.debug(f"CamLink: {self.camLink}")
        if not self.video_path and self.camLink:
            self.video_path = self.camLink

        if not self.video_path:
            self.logger.error("No valid video source selected.")
            self._update_status("Error: No video source selected", "red")
            return

        self.logger.debug(f"Starting processing with source: {self.video_path}")
        try:
            # self.video_name = self.video_path
            # self.video_name = Path(self.video_path).stem if self.video_path != "0" else "webcam" 
            self.logger.debug(f"Set video_name: {self.video_name} ,  video name  {self.video_path}")
            print(f"Set video_name: {self.video_name} ,  video name  {self.video_path}")
            self.processor = VehicleNumberPlateProcessor(self.video_path, target_fps=10, buffer_size=30)
        except FileNotFoundError:
            self.logger.error(f"Video file not found: {self.video_path}")
            self._update_status("Error: Video file not found", "red")
            return
        except ValueError as e:
            self.logger.error(f"Invalid video source: {e}")
            self._update_status("Error: Invalid video source", "red")
            return
        except Exception as e:
            self.logger.error(f"Unexpected error initializing processor: {e}")
            self._update_status("Error: Processor initialization failed", "red")
            return

        self.is_running = True
        self.start_button.configure(text="Stop Video", fg_color="red")
        source_type = "camera" if self.video_path.startswith("rtsp://") else "video"
        self._update_status(f"Processing {source_type}...", "green")
        self.logger.info(f"Processing started for source: {self.video_path}")

        self.thread = threading.Thread(target=self.processor.start_processing, daemon=True)
        self.thread.start()
        self._poll_frames()    

    # Polls and displays the latest processed video frame on the canvas at regular intervals.
    def _poll_frames(self):
        if not self.is_running:
            self.logger.debug("Polling stopped: is_running is False")
            return
        try:
            frame = self.processor.get_processed_frame()
            if frame is not None:
                self.logger.debug("Frame retrieved from queue")
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame = cv2.resize(frame, (self.CANVAS_WIDTH, self.CANVAS_HEIGHT))
                image = Image.fromarray(frame)
                self.show_blacklist_alert()
                self.show_number_plate()
                self.canvas_image = ImageTk.PhotoImage(image=image)
                self.canvas.create_image(0, 0, anchor="nw", image=self.canvas_image)
                self.canvas.update()  # Force canvas update
                self.logger.debug("Frame displayed on canvas")
            else:
                self.logger.debug("No frame available in queue")
        except Exception as e:
            self.logger.error(f"Error updating frame: {e}")

        self.update_job = self.root.after(self.update_interval, self._poll_frames)

# step 6: Stop processing the video or RTSP stream
    def _stop_processing(self):
        if self.is_running:
            self.is_running = False
            self.video_path = ""
            self.start_button.configure(text="Start Video", fg_color="green")

            if self.processor:
                self.processor.stop_processing()
            if self.thread and self.thread.is_alive():
                self.thread.join()

            # Reset UI elements
            self.canvas.delete("all")
            self.video_label.configure(text="Processing stopped. No video selected.")
            self._update_status("Stopped. Ready.", "orange")
            self.logger.info("Video processing stopped.")

            #  Clear the YAML data
            try:
                with open('NumberPlate_data.yaml', 'w') as yaml_file:
                    yaml.dump([], yaml_file)
                print(" NumberPlate_data.yaml has been cleared.")
            except Exception as e:
                print(f" Failed to clear YAML: {e}")

            # Clear number plate UI widgets
            try:
                for widget in self.scrollable_frame.winfo_children():
                    widget.destroy()
                print(" UI number plate display cleared.")
            except Exception as e:
                print(f" Failed to clear number plate UI: {e}")

            # Clear tracking variables
            self.recent_alerts_numberPlate.clear()
            self.row = 0
            self.col = 0
            self.image_refs.clear()


# step 7: Toggle pause/resume processing
    def _toggle_pause(self):
        if self.is_running and self.processor:
            if self.processor.is_paused:
                self.processor.resume_processing()
                self._update_status("Processing resumed.", "green")
            else:
                self.processor.pause_processing()
                self._update_status("Processing paused.", "orange")

# step 8: Show blacklist alert
    def _update_status(self, message, color):
        self.status_label.configure(text=message, text_color=color)
        self.root.update_idletasks()

# ...................................................................
# step :   right side top camera box
    def _right_sidebar(self):
        self.right_slider_frame = ctk.CTkFrame(self.root, width=300, bg_color=self.BG_COLOR)
        self.right_slider_frame.pack(side="right", fill="both", expand=True, pady=40, padx=20) 
        # Call the function to populate the top part with the Add Camera button
        self.right_slider_top()
        self.loi_pointbtn1 = ctk.CTkButton(self.right_slider_frame, text="Draw loi points", command=self.open_loi_point, width=40, height=50, font=("Arial", 13))
        self.loi_pointbtn1.pack(pady=(10, 20), padx=10)

# step : Create the right sidebar with camera toggles and Add/Delete buttons
    def right_slider_top(self):
        self.right_slider_top_frame = ctk.CTkFrame(
            self.right_slider_frame,
            width=300,
            bg_color=self.BG_COLOR,
            border_width=3
        )
        self.right_slider_top_frame.pack(side="top", fill="both",  pady=40, padx=20)

        self.right_slider_top_frame.grid_columnconfigure(0, weight=1)
        self.right_slider_top_frame.grid_columnconfigure(1, weight=1)

        self.rtsp_btn = ctk.CTkButton(
            self.right_slider_top_frame, text="Add Camera", command=self._open_form,
            width=210, height=40, font=("Arial", 13)
        )
        self.rtsp_btn.grid(row=0, column=0, columnspan=2, pady=10, padx=10, sticky="ew")

        # Create the delete button (positioned later)
        self.delete_btn = ctk.CTkButton(
            self.right_slider_top_frame, text="Delete Camera", fg_color='red',command=self._open_delete_window,
            width=90, height=40, font=("Arial", 13)
        )

        self.camera_toggle_row_start = 1  # row after Add Camera
    
  # step : Open form for adding a camera
    def _open_form(self):
        if hasattr(self, 'form_window') and self.form_window is not None and self.form_window.winfo_exists():
            print("Form already open. Focusing window.")
            self.form_window.lift()
            self.form_window.focus_force()
            return  # Do not open another instance if already open
        
        # Popup form for adding a camera
        self.form_window = ctk.CTkToplevel(self.root)
        self.form_window.title("Add Camera")
        self.form_window.geometry("500x300")
        self.form_window.protocol("WM_DELETE_WINDOW", self._on_form_close)  # Handle form close event

        ctk.CTkLabel(self.form_window, text="Camera Name:").pack(pady=5)
        self.camera_name_entry = ctk.CTkEntry(self.form_window,width=440)
        self.camera_name_entry.pack(pady=5)

        ctk.CTkLabel(self.form_window, text="RTSP Link:").pack(pady=5)
        self.rtsp_link_entry = ctk.CTkEntry(self.form_window,width=440)
        self.rtsp_link_entry.pack(pady=5)

        save_btn = ctk.CTkButton(self.form_window, text="Save", command=self._save_camera)
        save_btn.pack(pady=10)
    
# step : Handle form close event
    def _on_form_close(self):
        print("Closing form....")
        self.form_window.destroy()
        self.form_window = None


    def _save_camera(self):
        camera_name = self.camera_name_entry.get().strip()
        rtsp_link = self.rtsp_link_entry.get().strip()

        if not camera_name or not rtsp_link:
            messagebox.showwarning("Missing Info", "Please provide both Camera Name and RTSP Link.")
            return

        config = {"cameras": {}, "active_camera": None}

        # Load existing config if it exists
        if os.path.exists(self.json_file):
            with open(self.json_file, "r") as f:
                try:
                    config = json.load(f)
                except json.JSONDecodeError:
                    pass

        # Warn if overwriting an existing camera
        if camera_name in config["cameras"]:
            confirm = messagebox.askyesno(
                "Duplicate Camera Name",
                f"The camera '{camera_name}' already exists.\nDo you want to replace its RTSP link?"
            )
            if not confirm:
                return

        # Save or update the camera entry
        config["cameras"][camera_name] = {
            "rtsp": rtsp_link,
            "loi_point": config["cameras"].get(camera_name, {}).get("loi_point", [])
        }

        with open(self.json_file, "w") as f:
            json.dump(config, f, indent=4)

        self._refresh_camera_list()
        self._on_form_close()



    def _refresh_camera_list(self):
        for toggle_btn in self.cameras.values():
            toggle_btn.destroy()
        self.cameras.clear()
        self._load_cameras()

# step : Load cameras from JSON file
    def _load_cameras(self):
        if os.path.exists(self.json_file):
            with open(self.json_file, "r") as f:
                try:
                    config = json.load(f)
                    cameras = config.get("cameras", {})
                    for name, data in cameras.items():
                        rtsp_link = data.get("rtsp", "")
                        self._add_camera_toggle(name, rtsp_link)
                except json.JSONDecodeError:
                    pass


# step : Add camera toggle button
    def _add_camera_toggle(self, name, rtsp_link):
        var = ctk.StringVar(value="Off")

        index = len(self.cameras)
        row_index = self.camera_toggle_row_start + (index // 2)
        column_index = index % 2

        toggle_btn = ctk.CTkSwitch(
            self.right_slider_top_frame, text=name, variable=var,
            onvalue="On", offvalue="Off",
            command=lambda: self._toggle_camera(name, var.get(), rtsp_link)
        )
        toggle_btn.grid(row=row_index, column=column_index, padx=10, pady=5, sticky="ew")

        self.cameras[name] = toggle_btn

        max_toggle_row = self.camera_toggle_row_start + (len(self.cameras) + 1) // 2
        self.delete_btn.grid(row=max_toggle_row, column=1, padx=10, pady=10, sticky="e")

# step : Toggle camera on/off
    # def _toggle_camera(self, name, state, link):
    #     if state == "On":
    #         for camera_name, switch in self.cameras.items():
    #             if camera_name != name:
    #                 switch.deselect()
    #                 self._toggle_camera(camera_name, "Off", "")
    #         print(f"Starting stream for {name}: {link}")
    #         self.video_label.configure(text=f"Selected: {Path(name)}")
    #         self.camLink = link
    #     else:
    #         print(f"Stopping stream for {name}")
    #         self.logger.info(f"Deactivating camera {name}")
    #         self.camLink = None
    def _toggle_camera(self, name, state, link):
        if state == "On":
            for camera_name, switch in self.cameras.items():
                if camera_name != name:
                    switch.deselect()
                    self._toggle_camera(camera_name, "Off", "")
            print(f"Starting stream for {name}: {link}")
            self.video_label.configure(text=f"Selected: {Path(name)}")
            self.camLink = link
            self.active_camera_name = name  # <- Store active camera name
        else:
            print(f"Stopping stream for {name}")
            self.logger.info(f"Deactivating camera {name}")
            self.camLink = None
            self.active_camera_name = None


# step : Open delete window for camera selection
    def _open_delete_window(self):
        if hasattr(self, 'delete_window') and self.delete_window.winfo_exists():
            self.delete_window.lift()
            return

        self.delete_window = ctk.CTkToplevel(self.root)
        self.delete_window.title("Delete Cameras")
        self.delete_window.geometry("450x400")

        ctk.CTkLabel(self.delete_window, text="Select cameras to delete:", font=("Arial", 14)).pack(pady=10)
        outer_frame = ctk.CTkFrame(self.delete_window)
        outer_frame.pack(pady=10, anchor="center")

        self.delete_check_vars = {}

        for idx, name in enumerate(self.cameras.keys()):
            row = idx // 2
            col = (idx % 2) * 2

            label = ctk.CTkLabel(outer_frame, text=name)
            label.grid(row=row, column=col, sticky="w", padx=10, pady=5)

            var = ctk.BooleanVar()
            checkbox = ctk.CTkCheckBox(outer_frame, text="", variable=var)
            checkbox.grid(row=row, column=col + 1, sticky="w", padx=5, pady=5)

            self.delete_check_vars[name] = var

        btn_frame = ctk.CTkFrame(self.delete_window)
        btn_frame.pack(pady=20)

        delete_btn = ctk.CTkButton(btn_frame, text="Delete", command=self._confirm_delete_selected)
        delete_btn.pack(side="left", padx=10)

        cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", command=self.delete_window.destroy)
        cancel_btn.pack(side="left", padx=10)


# step : Confirm deletion of selected cameras
    def _confirm_delete_selected(self):
        selected_to_delete = [name for name, var in self.delete_check_vars.items() if var.get()]
        if not selected_to_delete:
            messagebox.showwarning("No Selection", "Please select at least one camera to delete.")
            return

        confirm = messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete {len(selected_to_delete)} camera(s)?")
        if not confirm:
            return

        if os.path.exists(self.json_file):
            with open(self.json_file, "r") as file:
                try:
                    config = json.load(file)
                except json.JSONDecodeError:
                    config = {"cameras": {}, "active_camera": None}
        else:
            config = {"cameras": {}, "active_camera": None}

        for name in selected_to_delete:
            config["cameras"].pop(name, None)
            if config.get("active_camera") == name:
                config["active_camera"] = None

        with open(self.json_file, "w") as file:
            json.dump(config, file, indent=4)

        self.delete_window.destroy()
        self._refresh_camera_list()
        messagebox.showinfo("Cameras Deleted", f"{len(selected_to_delete)} camera(s) deleted.")

    # step : Save camera data to YAML
#     def _save_camera(self):
#         camera_name = self.camera_name_entry.get()
#         rtsp_link = self.rtsp_link_entry.get()

#         if not camera_name or not rtsp_link:
#             messagebox.showwarning("Missing Info", "Please provide both Camera Name and RTSP Link.")
#             return

#         cameras_data = {}
#         if os.path.exists(self.yaml_file):
#             with open(self.yaml_file, "r") as file:
#                 cameras_data = yaml.safe_load(file) or {}

#         if camera_name in cameras_data:
#             confirm = messagebox.askyesno(
#                 "Duplicate Camera Name",
#                 f"The camera '{camera_name}' already exists.\nDo you want to replace its RTSP link?"
#             )
#             if not confirm:
#                 return  # Do nothing if user cancels

#         # Save or update the camera
#         cameras_data[camera_name] = rtsp_link
#         with open(self.yaml_file, "w") as file:
#             yaml.safe_dump(cameras_data, file)      

#         # Refresh the camera toggles
#         self._refresh_camera_list()
#         self._on_form_close()


#     # step : Refresh the camera list
#     def _refresh_camera_list(self):
#         # Clear old camera toggle buttons from UI
#         for toggle_btn in self.cameras.values():
#             toggle_btn.destroy()
#         # Clear the dictionary
#         self.cameras.clear()
#         # Reload from YAML
#         self._load_cameras()

#     # step : Load cameras from YAML file
#     def _load_cameras(self):
#         if os.path.exists(self.yaml_file):
#             with open(self.yaml_file, "r") as file:
#                 cameras_data = yaml.safe_load(file) or {}
#                 for name, link in cameras_data.items():
#                     self._add_camera_toggle(name, link)

#     # step : Add camera toggle button
#     def _add_camera_toggle(self, name, rtsp_link):
#         var = ctk.StringVar(value="Off")

#         index = len(self.cameras)
#         row_index = self.camera_toggle_row_start + (index // 2)
#         column_index = index % 2

#         toggle_btn = ctk.CTkSwitch(
#             self.right_slider_top_frame, text=name, variable=var,
#             onvalue="On", offvalue="Off",
#             command=lambda: self._toggle_camera(name, var.get(), rtsp_link)
#         )
#         toggle_btn.grid(row=row_index, column=column_index, padx=10, pady=5, sticky="ew")

#         self.cameras[name] = toggle_btn

#         # Move delete button to right side, below last row
#         max_toggle_row = self.camera_toggle_row_start + (len(self.cameras) + 1) // 2
#         self.delete_btn.grid(row=max_toggle_row, column=1, padx=10, pady=10, sticky="e")  #  right side


#   # step : Toggle camera on/off   
#     def _toggle_camera(self, name, state, link):
#         if state == "On":
#             # turn off all other switches
#             for camera_name, switch in self.cameras.items():
#                 if camera_name != name:
#                     # switch.set("Off")  # Turn off other cameras
#                     switch.deselect()
#                     self._toggle_camera(camera_name, "Off", "")  # Stop other cameras

#             print(f"Starting stream for {name}: {link}")
#             self.video_label.configure(text=f"Selected: {Path(name)}")
#             self.camLink = link
#         else:
#             print(f"Stopping stream for {name}")
#             self.logger.info(f"Deactivating camera {name}")
#             self.camLink = None
#             # Stop video stream logic here
    

# # step : Open delete window for camera selection
#     def _open_delete_window(self):
#         if hasattr(self, 'delete_window') and self.delete_window.winfo_exists():
#             self.delete_window.lift()
#             return

#         self.delete_window = ctk.CTkToplevel(self.root)
#         self.delete_window.title("Delete Cameras")
#         self.delete_window.geometry("450x400")

#         ctk.CTkLabel(self.delete_window, text="Select cameras to delete:", font=("Arial", 14)).pack(pady=10)

#         # Outer frame to center inner grid
#         outer_frame = ctk.CTkFrame(self.delete_window)
#         outer_frame.pack(pady=10, anchor="center")  # Center the frame

#         self.delete_check_vars = {}

#         for idx, name in enumerate(self.cameras.keys()):
#             row = idx // 2
#             col = (idx % 2) * 2  # 0 or 2

#             # Camera name label
#             label = ctk.CTkLabel(outer_frame, text=name)
#             label.grid(row=row, column=col, sticky="w", padx=10, pady=5)

#             # Corresponding checkbox
#             var = ctk.BooleanVar()
#             checkbox = ctk.CTkCheckBox(outer_frame, text="", variable=var)
#             checkbox.grid(row=row, column=col + 1, sticky="w", padx=5, pady=5)

#             self.delete_check_vars[name] = var

#         # Bottom buttons
#         btn_frame = ctk.CTkFrame(self.delete_window)
#         btn_frame.pack(pady=20)

#         delete_btn = ctk.CTkButton(btn_frame, text="Delete", command=self._confirm_delete_selected)
#         delete_btn.pack(side="left", padx=10)

#         cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", command=self.delete_window.destroy)
#         cancel_btn.pack(side="left", padx=10)

#    # step : Confirm deletion of selected cameras
#     def _confirm_delete_selected(self):
#         selected_to_delete = [name for name, var in self.delete_check_vars.items() if var.get()]

#         if not selected_to_delete:
#             messagebox.showwarning("No Selection", "Please select at least one camera to delete.")
#             return

#         confirm = messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete {len(selected_to_delete)} camera(s)?")
#         if not confirm:
#             return

#         # Load current YAML data
#         if os.path.exists(self.yaml_file):
#             with open(self.yaml_file, "r") as file:
#                 cameras_data = yaml.safe_load(file) or {}
#         else:
#             cameras_data = {}

#         # Remove selected cameras
#         for name in selected_to_delete:
#             cameras_data.pop(name, None)

#         with open(self.yaml_file, "w") as file:
#             yaml.safe_dump(cameras_data, file)

#         self.delete_window.destroy()
#         self._refresh_camera_list()
#         messagebox.showinfo("Cameras Deleted", f"{len(selected_to_delete)} camera(s) deleted.")

# ............................................................................................
# step 4: setup the middle frame
# This frame contains the video display area and status label
    def _setup_middle_frame(self):
        self.middle_frame = ctk.CTkFrame(self.root)
        self.middle_frame.pack(side="left", fill="both", expand=True, padx=20)

        self.video_frame = ctk.CTkFrame(self.middle_frame)
        self.video_frame.pack(side="top", fill="both", expand=True, padx=10, pady=10)
        
        # Video Display Canvas for displaying video frames
        self.canvas = ctk.CTkCanvas(self.video_frame, width=self.CANVAS_WIDTH, height=self.CANVAS_HEIGHT, bg="black")
        self.canvas.pack(pady=5, padx=20)

        # Status Label to display the current status of the application
        self.status_label = ctk.CTkLabel(self.video_frame, text="Ready", font=("Arial", 14), text_color="red")
        self.status_label.pack(side="left", pady=5)

    # step 4: setup the bottom frame
    def _setup_bottom_frame(self):
        # Create a tab view for the bottom frame
        self.bottom_tabview = ctk.CTkTabview(self.middle_frame, width=300)
        self.bottom_tabview.pack(side="bottom", fill="both", expand=True, padx=5, pady=5)

        # Add the main tabs: "Formatted Plate" , "Blacklisted""Search" 
        self.bottom_tabview.add("Formatted Plate")
        self.bottom_tabview.add("Blacklisted")
        self.bottom_tabview.add("Search")
      

        # Setup the actual contents of each tab
        self._setup_formatted_plate_tab()
        self._setup_tabview()
        self._setup_search_tab()

        # Set up the "Search" tab
    def _setup_search_tab(self):
        """Set up the 'Search' tab to allow searching for number plates."""
        self.search_frame = ctk.CTkFrame(self.bottom_tabview.tab("Search"))
        self.search_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Search Entry
        self.search_entry = ctk.CTkEntry(self.search_frame, placeholder_text="Enter number plate to search")
        self.search_entry.pack(pady=10, padx=20)

        # Search Button
        self.search_button = ctk.CTkButton(self.search_frame, text="Search", command=self._search_number_plate)
        self.search_button.pack(pady=10, padx=20)

        # Results Display Label
        self.search_results_label = ctk.CTkLabel(self.search_frame, text="", justify="left", wraplength=400)
        self.search_results_label.pack(pady=10, padx=20)

    def _search_number_plate(self):
        """Search for a number plate and display the results in the UI."""
        plate_number = self.search_entry.get().strip()

        if not plate_number:
            self.search_results_label.configure(text=" Please enter a number plate.")
            return

        results = self.db.search_by_number_plate(plate_number)

        if results:
            output_lines = []
            for row in results:
                output_lines.append(
                    f" Video ID: {row['videoId']}\n"
                    f" Date: {row['detected_date']}\n"
                    f" Time: {row['detected_time']}\n"
                    f" Blacklisted: {'Yes' if row['is_blacklistNumberPlate'] else 'No'}\n"
                    f"{'-'*30}"
                )
            self.search_results_label.configure(text="\n\n".join(output_lines))
        else:
            self.search_results_label.configure(text="No records found for this number plate.")



# step 5: Set up the "Formatted Plate" tab, This tab will display images with number plate data
    def _setup_formatted_plate_tab(self):
        """Set up the 'Formatted Plate' tab to display images with number plate data."""
        self.formatted_plate_frame = ctk.CTkFrame(self.bottom_tabview.tab("Formatted Plate"))
        self.formatted_plate_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Scrollable canvas
        self.formatted_plate_canvas = ctk.CTkCanvas(self.formatted_plate_frame, width=400, height=300, bg="#2A2A2A")
        self.formatted_plate_canvas.pack(side="left", fill="both", expand=True)

        # Scrollbar
        self.scrollbar = ctk.CTkScrollbar(self.formatted_plate_frame, command=self.formatted_plate_canvas.yview)
        self.scrollbar.pack(side="right", fill="y",padx=20,pady=10)

        # Configure canvas scrolling
        self.formatted_plate_canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollable_frame = ctk.CTkFrame(self.formatted_plate_canvas)
        self.formatted_plate_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        # Bind scrolling
        self.scrollable_frame.bind("<Configure>", lambda e: self.formatted_plate_canvas.configure(scrollregion=self.formatted_plate_canvas.bbox("all")))

        # Store image references to prevent garbage collection
        self.image_refs = []

        # Initialize row and column counters for grid layout
        self.row = 0
        self.col = 0

# ..........................................................
    # step 5: Set up the "Blacklisted" tab with sub-tabs
    # This tab will contain a tab view for managing blacklisted numbers
    def _setup_tabview(self):
        """ Set up the tab view for 'Blacklisted' inside the bottom tabview """
        self.blacklist_tabview = ctk.CTkTabview(self.bottom_tabview.tab("Blacklisted"), width=250)
        self.blacklist_tabview.pack(fill="both", expand=True, padx=5, pady=5)

        # Add sub-tabs inside "Blacklisted"
        self.blacklist_tabview.add("Blacklisted NumbersView")
        self.blacklist_tabview.add("Blacklisted Numbers")

        # Setup individual tabs correctly
        self._setup_blacklisted_numbers_view_tab()
        self._setup_blacklisted_numbers_tab()
  
   
    # step 6: setup the blacklisted numbers view tab
    def _setup_blacklisted_numbers_view_tab(self):
        # Set up the "Blacklisted NumbersView" tab
        self.blacklist_listbox = ctk.CTkTextbox(self.blacklist_tabview.tab("Blacklisted NumbersView"), height=300)
        self.blacklist_listbox.grid(row=1, column=0, padx=20, pady=5, sticky="nsew")
        
        self.blacklist_label = ctk.CTkLabel(self.blacklist_tabview.tab("Blacklisted NumbersView"), text="✅ Monitoring for Blacklisted Plates...", text_color="white")
        self.blacklist_label.grid(row=0, column=0, padx=20, pady=10)

        # Set the tab to expand correctly
        self.blacklist_tabview.tab("Blacklisted NumbersView").grid_rowconfigure(1, weight=1)
        self.blacklist_tabview.tab("Blacklisted NumbersView").grid_columnconfigure(0, weight=1)

    # step 7: setup the blacklisted numbers tab
    def _setup_blacklisted_numbers_tab(self):
        self.blacklist_entry = ctk.CTkEntry(self.blacklist_tabview.tab("Blacklisted Numbers"), placeholder_text="Enter license plate number")
        self.blacklist_entry.grid(row=2, column=0, padx=20, pady=20)

        self.add_blacklist_btn = ctk.CTkButton(self.blacklist_tabview.tab("Blacklisted Numbers"), text="Add to Blacklist", command=self._blacklist_number)
        self.add_blacklist_btn.grid(row=2, column=1, padx=20, pady=10)

        self.blacklist_label2 = ctk.CTkLabel(self.blacklist_tabview.tab("Blacklisted Numbers"), text="Blacklisted Numbers", font=("Arial", 14))
        self.blacklist_label2.grid(row=1, column=0, padx=20, pady=10, columnspan=2)        
        

        self.textbox_frame = ctk.CTkFrame(self.blacklist_tabview.tab("Blacklisted Numbers"))
        self.textbox = ctk.CTkTextbox(self.textbox_frame, wrap="none")
        self.textbox.pack(side="left", fill="x", expand=True)
        self.textbox.configure(height=250, width=400)

        # OptionMenu in the "Blacklisted Numbers" tab
        self.optionmenu_1 = ctk.CTkOptionMenu(self.blacklist_tabview.tab("Blacklisted Numbers"), dynamic_resizing=False,
                                              values=["Add to Blacklist", "Blacklist view"],
                                              command=self._handle_option_menu_selection)
        self.optionmenu_1.grid(row=0, column=0, padx=20, pady=10, columnspan=2, sticky="NSEW")

    def _setup_blacklist_frame(self):
        self.blacklist_frame = ctk.CTkFrame(self.bottom_frame, width=250)
        self.blacklist_frame.pack(side="left", fill="both", expand=True, padx=5)


    def _handle_option_menu_selection(self, selection):
        if selection == "Add to Blacklist":
            self.blacklist_entry.grid()
            self.blacklist_label2.grid()
            self.add_blacklist_btn.grid()
            # self.blacklist_label.grid_remove()
            self.textbox_frame.grid_remove()
        elif selection == "Blacklist view":
            # Hide the blacklist entry and button for adding new plates
            self.blacklist_entry.grid_remove()
            self.add_blacklist_btn.grid_remove()
            # Show the text box for displaying the blacklist
            self.textbox_frame.grid()
            self.blacklist_label2.grid_remove()  # Hide the label showing the status
            # Refresh and display the blacklisted plates
            self._open_plate_number_dialog()
        else:
            # Hide all elements if another option is selected
            self.blacklist_entry.grid_remove()

   
    def _open_plate_number_dialog(self):
        """Refresh and display the list of blacklisted plates."""
        # Fetch the latest blacklisted plates from the database
        blacklisted_plates = self.db.get_blacklisted_plates()
        # print(blacklisted_plates)
        self.textbox.delete("1.0", "end")
        # If no blacklisted plates are found, show a message
        if not blacklisted_plates:
            self.textbox.insert("end", "No blacklisted plates found.")
        else:
            # Insert each blacklisted plate into the textbox, formatted
            for plate in blacklisted_plates:
                self.textbox.insert("end", f"    {plate.center(30)}\n\n")  # Format each plate in the textbox

    def open_input_dialog(self):
            self.blacklist_entry = ctk.CTkEntry(self.root, placeholder_text="Enter license plate number")
            self.blacklist_entry.pack(side="left", padx=2, fill="x", expand=True)

            self.add_blacklist_btn = ctk.CTkButton(self.root, text="Add to Blacklist", command=self._blacklist_number)
            self.add_blacklist_btn.pack(side="right", padx=10)    


    # def _is_valid_license_plate(self, plate_number):
    #     """Validate the plate number format (Indian format)."""
    #     plate_regex = r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{4}$"  # Indian format regex
    #     return bool(re.match(plate_regex, plate_number))  # Check if it matches the pattern
    def _is_valid_license_plate(self, text):
        corrections = {'O': '0', 'o': '0', 'S': '5', 's': '5', 'I': '1', 'i': '1'}
        if not text:
            return None
        text = ''.join(corrections.get(c, c) for c in text)
        sanitized = re.sub(r"[^A-Za-z0-9]", "", text).upper()
        return sanitized if re.match(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$", sanitized) else None

    def _blacklist_number(self):
        plate_number = self.blacklist_entry.get().strip()  # Get the input and strip spaces

        if not plate_number:
            self.blacklist_label2.configure(text="Please enter a license plate number.", text_color="red")
            return
        
        # Remove any spaces and convert the plate number to uppercase
        plate_number = plate_number.replace(" ", "").upper()

        # Validate license plate
        if not self._is_valid_license_plate(plate_number):
            self.blacklist_label2.configure(text="Invalid license plate number.", text_color="red")
            self._reset_label_after_delay()
            return

        if self.db.is_already_plate_blacklisted(plate_number):
            self.blacklist_label2.configure(text="Number is already in DB.", text_color="red")
            self._reset_label_after_delay()
            return

        # Try adding to the database
        success = self.db.add_blacklist_plate(plate_number)
        if success:
            # Append plate number to the label text (use newline to add it as a new line)
            current_text = self.blacklist_label2.cget("text")  # Get the current text of the label
            new_text = current_text + "\n" + plate_number  # Append the new plate number
            self.blacklist_label2.configure(text=new_text, text_color="green")  # Update label with the new text
            self.blacklist_label2.configure(text="License plate added to blacklist.", text_color="green")
        else:
            self.blacklist_label2.configure(text="Error adding plate to blacklist.", text_color="red")

        # Clear input field and reset label
        self.blacklist_entry.delete(0, 'end')
        self._reset_label_after_delay()

    def _reset_label_after_delay(self):
        """Reset the blacklist label text after a few seconds."""
        # Wait for 2 seconds (2000 milliseconds) before resetting the label text
        self.blacklist_label2.after(2000, lambda: self.blacklist_label2.configure(text="Add Blacklisted Numbers", font=("Arial", 14), text_color='white'))

    
    def show_number_plate(self):
        try:
            with open('NumberPlate_data.yaml', 'r') as file:
                alert_data = yaml.safe_load(file)

            if alert_data and isinstance(alert_data, list):
                for entry in alert_data:
                    if isinstance(entry, dict) and "numberPlate" in entry:
                        number_plate = entry["numberPlate"]
                        detection_time = entry.get("numberPlate_current_dataTime", "Unknown Time")
                        image_base64 = entry.get("image", "")

                        if number_plate in self.recent_alerts_numberPlate:
                            continue  # Skip duplicate entries

                        # Append to recent alerts list
                        self.recent_alerts_numberPlate.append(number_plate)

                        # Create a frame for each car's image and plate info
                        item_frame = ctk.CTkFrame(self.scrollable_frame)
                        item_frame.grid(row=self.row, column=self.col, padx=10, pady=5, sticky="w")

                        # Insert Image (Left side)
                        if image_base64:
                            self._insert_image(item_frame, image_base64)

                        # Insert Text (Right side)
                        text_label = ctk.CTkLabel(item_frame, 
                                                text=f"Plate: {number_plate}\nTime: {detection_time}", 
                                                anchor="w", 
                                                justify="left")
                        text_label.pack(side="left", padx=10, expand=True)

                        # Move to the next column, if two items are in the row, move to the next row
                        if self.col == 2:  # Third item in the row
                            self.col = 0  # Reset column to 0
                            self.row += 1  # Move to the next row
                        else:
                            self.col += 1  # Move to the next column

        except Exception as e:
            print(f"Error: {e}")
   

    def _insert_image(self, parent, base64_string):
        try:
            # Decode Base64 image
            image_data = base64.b64decode(base64_string)
            image = Image.open(BytesIO(image_data))
            image = image.resize((100, 60))  # Resize image

            # Convert to CTk-compatible PhotoImage
            photo = ImageTk.PhotoImage(image)
            self.image_refs.append(photo)  # Store reference

            # Create Image Label (Left side)
            image_label = ctk.CTkLabel(parent, image=photo, text="")
            image_label.pack(side="left", padx=5)

        except Exception as e:
            print(f"Error displaying image: {e}")

    def send_telegram_alert(self, message):
        if not message:
            self.logger.error("Error: message text is empty")
            return
        # f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        url = f"https://api.telegram.org/bot{self.API_KEY}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message
        }
        # Debugging: Print the payload to check for any issues
        self.logger.info(f"Prepared payload for Telegram alert: {payload}")
        
        try:
            self.logger.info(f"Sending Telegram alert with payload: {payload}")
            response = requests.post(url, data=payload)
            response.raise_for_status()  # Will raise an exception for 4xx/5xx responses
            self.logger.info(f"Telegram alert sent successfully: {response.json()}")
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error sending Telegram alert: {e}")
            self.logger.error(f"Request payload: {payload}")
            self.logger.error(f"Request URL: {url}")

    def show_blacklist_alert(self):
        try:
            with open('BlackListNumberPlate_data.yaml', 'r') as file:
                alert_data = yaml.safe_load(file)

            if alert_data and isinstance(alert_data, list):  # Ensure alert_data is a list
                for entry in alert_data:
                    # Ensure the entry is a dictionary and contains the required keys
                    if isinstance(entry, dict) and "blackListNumber" in entry and "detectionTime" in entry:
                        blackListedplate_number = entry["blackListNumber"]
                        detection_time = entry["detectionTime"]
                        
                        # Check if the blackListedplate_number is already in recent_alerts
                        if blackListedplate_number in self.recent_alerts:
                            print(f"Skipping duplicate alert for blacklisted plate: {blackListedplate_number}")
                            continue  # Skip this alert if it's a duplicate
                        
                        # Add blackListedplate_number to recent_alerts
                        self.recent_alerts.append(blackListedplate_number)

                        # Format the alert message
                        formatted_alert = f"BLACKLISTED PLATE DETECTED: {blackListedplate_number},  {detection_time}"

                        # Ensure the formatted_alert is not empty before proceeding
                        if not formatted_alert.strip():
                            self.logger.error("Formatted alert is empty. Skipping Telegram alert.")
                            continue  # Skip sending the Telegram alert if the message is empty

                        self.logger.info(f"Formatted alert: {formatted_alert}")

                        # Display the alert in the listbox
                        self.blacklist_listbox.insert('end', formatted_alert + '\n')

                        # Update the label with the alert message
                        self.blacklist_label.configure(text=formatted_alert, text_color="red")
                        self.send_telegram_alert(formatted_alert)
                        # Blinking effect for urgent alert
                        def blink_label(count=5):
                            if count > 0:
                                current_color = self.blacklist_label.cget("text_color")
                                new_color = "yellow" if current_color == "red" else "red"
                                self.blacklist_label.configure(text_color=new_color)
                                self.blacklist_label.after(500, lambda: blink_label(count - 1))

                        blink_label()  # Start blinking effect

                        # Reset the label after 5 seconds
                        self.blacklist_label.after(5000, lambda: self.blacklist_label.configure(
                            text="✅ Monitoring for Blacklisted Plates...",
                            text_color="white"
                        ))

                        # Send alert message to Telegram                
        except Exception as e:
            self.logger.error(f"Error reading blacklist alert: {e}")



class ToplevelWindow(ctk.CTkToplevel):

    def __init__(self, parent, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent = parent  # This is the main window
        self.geometry("400x400")
        self.db = OCRDatabase()
        self.db_connection = self.parent.db.connection  # Use the parent's database connection
        self.yaml_file = "cameras.yaml"
        self.cameras = {}  # Dictionary to store camera data
        self.label = ctk.CTkLabel(self, text="ToplevelWindow")
        self.label.pack(padx=20, pady=20)

        password_label = ctk.CTkLabel(self, text="Enter Admin Password:")
        password_label.pack(pady=10)

        # self.password_entry = ctk.CTkEntry(self, show="*")  # Use '*' to mask the password
        # self.password_entry.pack(pady=10)
        self.password_entry = ctk.CTkEntry(self, show="*")  # Use '*' to mask the password
        self.password_entry.pack(pady=10)
        self.password_entry.bind("<Return>", lambda event: self._validate_password())  # Bind Enter key

        submit_button = ctk.CTkButton(self, text="Submit", command=self._validate_password)
        submit_button.pack(pady=10)

    def _validate_password(self):
        password = self.password_entry.get()
        with open('password.yaml', 'r') as file:
            stored_password = yaml.safe_load(file).get('password')
        if stored_password is not None and password == stored_password:
            self._ask_for_action()
        else:
            messagebox.showerror("Error", "Incorrect password!")

    def _ask_for_action(self):
        # Clear the current window
        for widget in self.winfo_children():
            widget.destroy()

        # Prompt the user to select between deleting a blacklisted plate or deleting a camera
        action_label = ctk.CTkLabel(self, text="What would you like to delete?")
        action_label.pack(pady=10)

        plate_button = ctk.CTkButton(self, text="Delete Blacklisted Plate", command=self._open_plate_number_dialog)
        plate_button.pack(pady=10)

        camera_button = ctk.CTkButton(self, text="Delete Camera", command=self._open_camera_dialog)
        camera_button.pack(pady=10)

    def _open_plate_number_dialog(self):
        # Proceed with the existing flow to delete a blacklisted plate
        for widget in self.winfo_children():
            widget.destroy()

        blacklisted_plates = self.db.get_blacklisted_plates()

        if not blacklisted_plates:
            no_plate_label = ctk.CTkLabel(self, text="No blacklisted plates found.")
            no_plate_label.pack(pady=10)
        else:
            plate_list_label = ctk.CTkLabel(self, text="Blacklisted Plates:")
            plate_list_label.pack(pady=10)

            # Create a scrollable textbox for plates
            self.textbox_frame = ctk.CTkFrame(self)
            self.textbox_frame.pack(pady=10, fill="x", expand=True)

            self.textbox = ctk.CTkTextbox(self.textbox_frame, wrap="none")
            self.textbox.pack(side="left", fill="x", expand=True)
            self.textbox.configure(height=150, width=200)        

            for plate in blacklisted_plates:
                self.textbox.insert("end", f"    {plate}\n\n") 

        plate_label = ctk.CTkLabel(self, text="Enter License Plate to Delete:")
        plate_label.pack(pady=10)

        self.plate_entry = ctk.CTkEntry(self)
        self.plate_entry.pack(pady=10)

        submit_button = ctk.CTkButton(self, text="Delete", command=self._delete_plate)
        submit_button.pack(pady=10)

        # Add a "Back" button to go back to the action screen
        back_button = ctk.CTkButton(self, text="Back", command=self._ask_for_action)
        back_button.pack(pady=10)

    def _delete_plate(self):
        plate_number = self.plate_entry.get()
        if plate_number:
            if self.db._delete_plate_from_db(plate_number):
                messagebox.showinfo("Success", f"Plate {plate_number} deleted from blacklist!")
                self._open_plate_number_dialog()  # Refresh the list of blacklisted plates
            else:
                messagebox.showerror("Error", f"Plate {plate_number} not found in the blacklist!")
        else:
            messagebox.showwarning("Input Error", "Please enter a valid plate number.")

    def _open_camera_dialog(self):
        # Clear the current widgets in the frame
        for widget in self.winfo_children():
            widget.destroy()

        cameras_data = self._load_camera()  # Load the list of cameras from cameras.yaml

        if not cameras_data:
            no_camera_label = ctk.CTkLabel(self, text="No cameras found.")
            no_camera_label.pack(pady=10)
        else:
            camera_list_label = ctk.CTkLabel(self, text="Cameras:")
            camera_list_label.pack(pady=10)

            # Create a scrollable textbox for cameras
            self.textbox_frame = ctk.CTkFrame(self)
            self.textbox_frame.pack(pady=10, fill="x", expand=True)

            self.textbox = ctk.CTkTextbox(self.textbox_frame, wrap="none")
            self.textbox.pack(side="left", fill="x", expand=True)
            self.textbox.configure(height=150, width=200)

            # Display the camera names in the textbox
            for camera_name in cameras_data.keys():
                self.textbox.insert("end", f"    {camera_name}\n\n")

        camera_label = ctk.CTkLabel(self, text="Enter Camera Name to Delete:")
        camera_label.pack(pady=10)

        self.camera_entry = ctk.CTkEntry(self)
        self.camera_entry.pack(pady=10)

        submit_button = ctk.CTkButton(self, text="Delete Camera", command=self._delete_camera)
        submit_button.pack(pady=10)

        # Add a "Back" button to go back to the action screen
        back_button = ctk.CTkButton(self, text="Back", command=self._ask_for_action)
        back_button.pack(pady=10)

    def _delete_camera(self):
        camera_name = self.camera_entry.get()
        if camera_name:
            cameras_data = self._load_camera()

            # Check if the camera exists in the loaded data
            if camera_name in cameras_data:
                # Remove from the cameras YAML file
                self.delete_camera(camera_name)

                # Refresh the list of cameras after deletion
                self._open_camera_dialog()  # Refresh UI inside ToplevelWindow

                messagebox.showinfo("Success", f"Camera '{camera_name}' deleted!")
                # Refresh the main UI in ANPRApp
                self.parent._refresh_camera_list()  # Call the function in the main app
                
            else:
                messagebox.showerror("Error", f"Camera '{camera_name}' not found!")
        else:
            messagebox.showwarning("Input Error", "Please enter a valid camera name.")

    def delete_camera(self, camera_name):
        # Try to remove the camera from the YAML file
        yaml_file = "cameras.yaml"
        try:
            if os.path.exists(yaml_file):
                with open(yaml_file, "r") as file:
                    cameras_data = yaml.safe_load(file) or {}

                if camera_name in cameras_data:
                    del cameras_data[camera_name]

                    # Save the updated data back to the YAML file
                    with open(yaml_file, "w") as file:
                        yaml.safe_dump(cameras_data, file)
                    print(f"Camera '{camera_name}' deleted from cameras.yaml.")
                    # self.parent._right_sidebar()  # Assuming this method exists in the parent class
                    # self.parent._load_cameras()  # 
                else:
                    print(f"Camera '{camera_name}' not found in YAML.")
            else:
                print("YAML file not found.")
        except Exception as e:
            print(f"Error deleting camera: {e}")

    def _load_camera(self):
        cameras_data = {}
        if os.path.exists(self.yaml_file):
            with open(self.yaml_file, "r") as file:
                cameras_data = yaml.safe_load(file) or {}
        return cameras_data

if __name__ == "__main__":
    # root = Tk()
    root = ctk.CTk()
    app = ANPRApp(root)
    root.mainloop()











