import cv2
import json
import os
import tkinter as tk
from tkinter import messagebox

# Global variables
points = []
frame = None
save_prompt_shown = False

def click_event(event, x, y, flags, param):
    """Handles mouse click events."""
    global points, frame, save_prompt_shown

    if event == cv2.EVENT_LBUTTONDOWN and len(points) < 2:
        points.append((x, y))
        cv2.circle(frame, (x, y), 5, (0, 0, 255), -1)

        if len(points) == 2:
            cv2.line(frame, points[0], points[1], (0, 255, 0), 2)
            cv2.imshow("Frame", frame)

            #add dealy to show the line before closing
            cv2.waitKey(3000)  # Show the line for 1 second

            # Immediately show save prompt
            show_save_dialog(param["config_path"], param["camera_name"], points)
            save_prompt_shown = True
            delay = 4000  # Delay to show the line before closing
            cv2.waitKey(delay)
            cv2.destroyAllWindows()


def show_save_dialog(config_path, camera_name, coordinates):
    """Show confirmation dialog and save if user agrees."""
    root = tk.Tk()
    root.withdraw()

    msg = f"Camera: {camera_name}\nLOI Points: {coordinates}\n\nDo you want to save these points?"
    if messagebox.askyesno("Save LOI Points", msg):
        save_coordinates_to_config(config_path, camera_name, coordinates)
        messagebox.showinfo("Saved", "LOI points saved successfully.")
    else:
        messagebox.showinfo("Not Saved", "LOI points were not saved.")
    root.destroy()

def save_coordinates_to_config(config_path, camera_name, coordinates):
    """Save coordinates to config.json as x1, y1, x2, y2 instead of a list."""
    if os.path.exists(config_path):
        with open(config_path, "r") as file:
            config = json.load(file)
    else:
        config = {"cameras": {}}

    if "cameras" not in config:
        config["cameras"] = {}

    # Unpack coordinates
    if len(coordinates) == 2:
        (x1, y1), (x2, y2) = coordinates
    else:
        print("Invalid coordinates format.")
        return

    if camera_name in config["cameras"]:
        config["cameras"][camera_name]["loi_point"] = {
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2
        }
    else:
        config["cameras"][camera_name] = {
            "rtsp": "",
            "loi_point": {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2
            }
        }

    with open(config_path, "w") as file:
        json.dump(config, file, indent=4)

    print(f"Coordinates saved for camera '{camera_name}': ({x1}, {y1}), ({x2}, {y2})")

    
    
    
    
    # Save the coordinates in the config under the camera nam
    # if camera_name in config["cameras"]:
    #     config["cameras"][camera_name]["loi_point"] = coordinates
    # else:
    #     config["cameras"][camera_name] = {
    #         "rtsp": "",
    #         "loi_point": coordinates
    #     }

    

def draw_line_of_interest(rtsp_link, camera_name, config_path, resize_frame=True, resize_width=1024, resize_height=480):
    """Open video, capture frame, and allow user to draw line of interest."""
    global frame, points, save_prompt_shown
    points = []
    save_prompt_shown = False

    cap = cv2.VideoCapture(rtsp_link)
    if not cap.isOpened():
        print("Error: Cannot open video.")
        return

    ret, frame = cap.read()
    cap.release()

    if not ret:
        print("Error: Cannot read frame.")
        return

    if resize_frame and resize_width and resize_height:
        frame = cv2.resize(frame, (resize_width, resize_height))

    cv2.namedWindow("Frame", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("Frame", click_event, param={
        "camera_name": camera_name,
        "config_path": config_path
    })
    cv2.imshow("Frame", frame)

    # Wait until window is closed
    while True:
        key = cv2.waitKey(1)
        if cv2.getWindowProperty("Frame", cv2.WND_PROP_VISIBLE) < 1:
            break

    cv2.destroyAllWindows()

    # Ask to save if window closed after two points and prompt wasn't shown yet
    if len(points) == 2 and not save_prompt_shown:
        show_save_dialog(config_path, camera_name, points)
