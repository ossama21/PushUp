import tkinter as tk
import time
import threading
from typing import Optional
import psutil
from win10toast import ToastNotifier
import random
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
import ttkbootstrap as ttk
from PIL import Image, ImageTk
from datetime import datetime
from tkinter import messagebox
from tkinter import simpledialog
import pystray
import win32com.client
import pythoncom
import requests
import sys
from packaging import version  # Add this import
import winreg  # Add this import at the top

App_Version = "Pushup Reminder Pro v1.9"

# Valid themes for ttkbootstrap
class Theme(Enum):
    DARKLY = "darkly"
    SOLAR = "solar"
    SUPERHERO = "superhero"
    COSMO = "cosmo"
    FLATLY = "flatly"
    LITERA = "litera"
    MINTY = "minty"
    PULSE = "pulse"

@dataclass
class AppSettings:
    pushups: int = 10
    interval_hours: int = 0
    interval_minutes: int = 45
    interval_seconds: int = 0
    theme: str = "darkly"
    auto_start: bool = False
    minimize_to_tray: bool = True
    show_progress: bool = True
    daily_goal: int = 100
    rest_duration: int = 60
    pushup_animation: bool = True
    auto_update: bool = True
    start_with_windows: bool = False  # Add this field

    @classmethod
    def load(cls) -> 'AppSettings':
        config_path = Path.home() / '.pushup_reminder' / 'config.json'
        if config_path.exists():
            with open(config_path, 'r') as f:
                data = json.load(f)
                # Remove old sound-related settings if they exist
                data.pop('notification_sound', None)
                data.pop('custom_sound_path', None)
                # Only keep known settings
                valid_fields = cls.__dataclass_fields__.keys()
                filtered_data = {k: v for k, v in data.items() if k in valid_fields}
                return cls(**filtered_data)
        return cls()
    
    def save(self):
        config_path = Path.home() / '.pushup_reminder' / 'config.json'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(self.__dict__, f)

class Statistics:
    def __init__(self):
        self.today_pushups = 0
        self.total_pushups = 0
        self.streak_days = 0
        self.last_completion = None
        self.load_stats()
    
    def add_pushups(self, count: int):
        """Record completed pushups"""
        self.today_pushups += count
        self.total_pushups += count
        self.last_completion = datetime.now()
        self.save_stats()
    
    def reset_daily(self):
        """Reset daily statistics"""
        self.today_pushups = 0
        self.save_stats()
    
    def load_stats(self):
        """Load statistics from file"""
        stats_path = Path.home() / '.pushup_reminder' / 'stats.json'
        if stats_path.exists():
            try:
                with open(stats_path, 'r') as f:
                    data = json.load(f)
                    self.today_pushups = data.get('today_pushups', 0)
                    self.total_pushups = data.get('total_pushups', 0)
                    self.streak_days = data.get('streak_days', 0)
                    last_completion = data.get('last_completion')
                    if last_completion:
                        self.last_completion = datetime.fromisoformat(last_completion)
            except Exception as e:
                print(f"Failed to load statistics: {e}")
    
    def save_stats(self):
        """Save statistics to file"""
        stats_path = Path.home() / '.pushup_reminder' / 'stats.json'
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = {
                'today_pushups': self.today_pushups,
                'total_pushups': self.total_pushups,
                'streak_days': self.streak_days,
                'last_completion': self.last_completion.isoformat() if self.last_completion else None
            }
            with open(stats_path, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Failed to save statistics: {e}")

    def reset_all(self):
        """Reset all statistics"""
        self.today_pushups = 0
        self.total_pushups = 0
        self.streak_days = 0
        self.last_completion = None
        self.save_stats()

class NotificationService:
    def __init__(self, settings: AppSettings, stats: Statistics, root: ttk.Window, update_callback):
        self.settings = settings
        self.stats = stats
        self.root = root
        self.toaster = ToastNotifier()
        self.update_callback = update_callback
        pythoncom.CoInitialize()
    
    def notify_minimize(self, title: str, message: str):
        """Send notification without completion dialog"""
        try:
            icon_path = str(Path(__file__).parent / 'assets' / 'icons' / 'logo.ico')
            if not Path(icon_path).exists():
                icon_path = str(Path(__file__).parent / 'assets' / 'icons' / 'logo.png')
            
            # Try shell popup first
            try:
                pythoncom.CoInitialize()
                shell = win32com.client.Dispatch("WScript.Shell")
                shell.Popup(message, 0, title, 64)
                pythoncom.CoUninitialize()
            except:
                # Fallback to win10toast
                self.toaster.show_toast(
                    title,
                    message,
                    icon_path=icon_path if Path(icon_path).exists() else None,
                    duration=5,
                    threaded=True
                )
            
        except Exception as e:
            print(f"Failed to send minimize notification: {e}")

    def notify(self, title: str, message: str):
        """Send a Windows notification and show completion dialog"""
        try:
            icon_path = str(Path(__file__).parent / 'assets' / 'icons' / 'logo.ico')
            if not Path(icon_path).exists():
                icon_path = str(Path(__file__).parent / 'assets' / 'icons' / 'logo.png')
            
            # Play our custom notification sound first
            self.toaster.show_toast(
                title,
                message,
                icon_path=icon_path if Path(icon_path).exists() else None,
                duration=5,
                threaded=True
            )
            # Show completion dialog after notification
            self.root.after(5000, lambda: CompletionDialog(
                self.root,
                self.settings.pushups,
                self.stats,
                self.update_callback
            ))
        except Exception as e:
            print(f"Failed to send notification: {e}")
            # Attempt to reinitialize COM and retry once
            try:
                pythoncom.CoInitialize()
                self.toaster.show_toast(
                    title,
                    message,
                    icon_path=None,
                    duration=5,
                    threaded=True
                )
            except Exception as retry_error:
                print(f"Retry failed: {retry_error}")

class ReminderService:
    def __init__(self, settings: AppSettings, notification_service: NotificationService):
        self.settings = settings
        self.notification_service = notification_service
        self.running = False
        self.thread = None
        self.last_reminder = None
        self.notification_shown = False
    
    def _reminder_loop(self):
        """Main reminder loop"""
        while self.running:
            total_seconds = (self.settings.interval_hours * 3600 +
                           self.settings.interval_minutes * 60 +
                           self.settings.interval_seconds)
            
            # Check if it's time for notification
            current_time = time.time()
            if self.last_reminder is None or (current_time - self.last_reminder) >= total_seconds:
                if not self.notification_shown:  # Only show if not already shown
                    self.last_reminder = current_time
                    self.notification_shown = True
                    self.notification_service.notify(
                        "Time for Push-ups!",
                        f"Do {self.settings.pushups} push-ups now!"
                    )
            # Reset notification_shown flag when the interval is complete
            elif self.notification_shown and (current_time - self.last_reminder) < total_seconds * 0.1:  # Reset in first 10% of new interval
                self.notification_shown = False
            
            time.sleep(1)  # Check every second instead of waiting full interval
    
    def start(self):
        """Start the reminder service"""
        self.running = True
        self.notification_shown = False  # Reset flag when starting
        self.last_reminder = time.time()  # Initialize last reminder time
        self.thread = threading.Thread(target=self._reminder_loop, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Stop the reminder service"""
        self.running = False
        self.notification_shown = False  # Reset flag when stopping
        if self.thread:
            self.thread.join(timeout=1.0)
    
    def get_remaining_time(self) -> int:
        """Get remaining time until next reminder in seconds"""
        if not self.running or not self.last_reminder:
            return 0
        interval = (self.settings.interval_hours * 3600 +
                   self.settings.interval_minutes * 60 +
                   self.settings.interval_seconds)
        elapsed = time.time() - self.last_reminder
        remaining = max(0, interval - int(elapsed))
        return remaining

class UpdateService:
    def __init__(self, current_version: str):
        # Clean up version string to keep only numbers and dots
        self.current_version = ''.join(c for c in current_version if c.isdigit() or c == '.')
        self.github_repo = "ossama21/PushUps_Reminder"
        self.github_api = f"https://api.github.com/repos/{self.github_repo}/releases/latest"
        
    def check_for_updates(self) -> tuple[bool, Optional[str], Optional[str]]:
        """Check if updates are available
        Returns: (update_available, version, download_url)"""
        try:
            headers = {'Accept': 'application/vnd.github.v3+json'}
            response = requests.get(self.github_api, headers=headers, timeout=10)
            response.raise_for_status()
            
            release_data = response.json()
            # Clean up version string from tag name
            latest_version = ''.join(
                c for c in release_data['tag_name'] 
                if c.isdigit() or c == '.'
            )
            download_url = None
            
            # Find the appropriate asset
            for asset in release_data.get('assets', []):
                if asset['name'].endswith('.exe'):
                    download_url = asset['browser_download_url']
                    break
            
            try:
                has_update = version.parse(latest_version) > version.parse(self.current_version)
            except version.InvalidVersion:
                print(f"Invalid version format: current={self.current_version}, latest={latest_version}")
                raise ValueError("Invalid version format")
            
            return has_update, latest_version, download_url
            
        except requests.RequestException as e:
            print(f"Network error checking for updates: {e}")
            raise ConnectionError("Failed to connect to update server")
        except Exception as e:
            print(f"Error checking for updates: {e}")
            raise

class ModernPushupApp:
    def __init__(self):
        self.settings = AppSettings.load()
        # Add UpdateService initialization before creating main window
        self.update_service = UpdateService(App_Version.split()[-1])
        
        # Create the main window with ttkbootstrap
        self.root = ttk.Window(
            title="Pushup Reminder Pro",
            themename=self.settings.theme,
            size=(800, 500)
        )
        
        # Set window icon
        try:
            icon_path = Path(__file__).parent / 'assets' / 'icons' / 'logo.ico'
            if not icon_path.exists():
                icon_path = Path(__file__).parent / 'assets' / 'icons' / 'logo.png'
            if icon_path.exists():
                self.root.iconbitmap(str(icon_path))
        except Exception as e:
            print(f"Failed to set window icon: {e}")
            
        self.root.position_center()
        
        # Initialize statistics first
        self.stats = Statistics()
        
        # Setup all required variables and resources first
        self.setup_variables()
        self.setup_placeholder_images()
        self.setup_animations()
        
        # Initialize services with stats
        self.notification_service = NotificationService(self.settings, self.stats, self.root, self.update_statistics)
        self.reminder_service = ReminderService(self.settings, self.notification_service)
        
        # Create GUI after all resources are initialized
        self.create_gui()
        
        # Bind the close button event
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Setup system tray icon
        self.setup_tray_icon()
        
    def setup_tray_icon(self):
        """Setup system tray icon and menu"""
        # Create tray icon image
        icon_path = Path(__file__).parent / 'assets' / 'icons' / 'logo.png'
        if icon_path.exists():
            icon_image = Image.open(icon_path)
        else:
            # Create a simple colored square if icon doesn't exist
            icon_image = Image.new('RGB', (64, 64), '#4CAF50')
        
        def restore_window(icon, item):
            self.root.deiconify()  # Restore the window
            self.root.lift()  # Bring to front
        
        def exit_app(icon, item):
            icon.stop()  # Stop the tray icon
            self.reminder_service.stop()  # Stop reminders
            self.root.destroy()  # Close the app
        
        # Create tray icon menu
        menu = (
            pystray.MenuItem("Open", restore_window),
            pystray.MenuItem("Exit", exit_app)
        )
        
        self.tray_icon = pystray.Icon(
            "PushupReminder",
            icon_image,
            "Pushup Reminder",
            menu
        )
        # Run tray icon in separate thread
        threading.Thread(target=self.tray_icon.run, daemon=True).start()
        
    def on_closing(self):
        """Handle window close button click"""
        response = messagebox.askyesno(
            "Close Application",
            "Would you like to minimize to tray instead of closing?",
            icon='question'
        )
        # Stop any running reminders
        if response:  # Yes clicked - minimize
            self.root.withdraw()  # Hide the window
            # Show notification that app is minimized WITHOUT showing completion dialog
            self.notification_service.notify_minimize(
                "Pushup Reminder",
                "Application minimized to tray. Still running!"
            )
        else:  # No clicked - exit
            if messagebox.askokcancel("Confirm Exit", "Are you sure you want to exit?"):
                self.reminder_service.stop()  # Stop any running reminders
                if hasattr(self, 'tray_icon'):
                    self.tray_icon.stop()  # Stop the tray icon if it exists
                self.root.destroy()  # Close the application
        
    def setup_variables(self):
        self.pushups_var = tk.IntVar(value=self.settings.pushups)
        self.progress_var = tk.DoubleVar(value=0)
        self.daily_goal_var = tk.IntVar(value=self.settings.daily_goal)
        self.is_running = False
        
    def setup_placeholder_images(self):
        """Load images from assets folder"""
        self.images = {}
        assets_path = Path(__file__).parent / 'assets' / 'icons'
        assets_path.mkdir(parents=True, exist_ok=True)  # Create directory if it doesn't exist
        
        # Define image paths
        image_files = {
            "logo": "logo.png",
            "pushup": "pushup.png",
            "settings": "settings.png",
            "stats": "stats.png"
        }
        
        # Try to load images from files, create placeholders if not found
        for name, filename in image_files.items():
            img_path = assets_path / filename
            try:
                if (img_path.exists()):
                    # Open and convert to RGBA to ensure alpha channel support
                    img = Image.open(img_path).convert('RGBA')
                    # Resize image if needed
                    size = (64, 64) if name == "logo" else (24, 24)
                    img = img.resize(size, Image.Resampling.LANCZOS)
                else:
                    # Create placeholder with transparency
                    size = (64, 64) if name == "logo" else (24, 24)
                    colors = {
                        "logo": "#4CAF50",
                        "pushup": "#2196F3",
                        "settings": "#FFC107",
                        "stats": "#9C27B0"
                    }
                    img = Image.new('RGBA', size, colors[name])
                
                # Convert to PhotoImage
                self.images[name] = ImageTk.PhotoImage(img)
            except Exception as e:
                print(f"Failed to load image {filename}: {e}")
                # Create placeholder on error
                size = (64, 64) if name == "logo" else (24, 24)
                img = Image.new('RGBA', size, "#808080")  # Gray placeholder with alpha
                self.images[name] = ImageTk.PhotoImage(img)
        
    def create_gui(self):
        # Create main container with padding
        self.main_container = ttk.Frame(self.root, padding="20")
        self.main_container.pack(fill=tk.BOTH, expand=True)
        
        self.create_header()
        self.create_main_content()
        self.create_footer()
        
    def create_header(self):
        header = ttk.Frame(self.main_container)
        header.pack(fill=tk.X, pady=(0, 20))
        
        # Logo and title
        logo_label = ttk.Label(header, image=self.images["logo"])
        logo_label.pack(side=tk.LEFT)
        
        title = ttk.Label(
            header,
            text="Pushup Reminder Pro",
            font=("Segoe UI", 24, "bold")
        )
        title.pack(side=tk.LEFT, padx=10)
        
        # Settings button
        settings_btn = ttk.Button(
            header,
            image=self.images["settings"],
            command=self.open_settings,
            style="Outline.TButton"
        )
        settings_btn.pack(side=tk.RIGHT)
        
    def create_main_content(self):
        content = ttk.Frame(self.main_container)
        content.pack(fill=tk.BOTH, expand=True)
        
        # Left panel - Main controls
        self.create_left_panel(content)
        
        # Right panel - Statistics
        self.right_panel = ttk.Frame(content)
        self.right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        # Statistics header
        ttk.Label(
            self.right_panel,
            text="Statistics",
            font=("Segoe UI", 16, "bold")
        ).pack(anchor=tk.W, pady=(0, 10))
        
        # Stats container
        stats_frame = ttk.Frame(self.right_panel)
        stats_frame.pack(fill=tk.X)
        
        # Today's pushups
        self.today_pushups_label = ttk.Label(
            stats_frame,
            text=f"Today's Pushups: {self.stats.today_pushups}",
            font=("Segoe UI", 12)
        )
        self.today_pushups_label.pack(anchor=tk.W, pady=5)
        
        # Progress bar and label
        self.progress_label = ttk.Label(
            stats_frame,
            text="Daily Goal Progress: 0%",
            font=("Segoe UI", 12)
        )
        self.progress_label.pack(anchor=tk.W, pady=5)
        
        self.progress_bar = ttk.Progressbar(
            stats_frame,
            length=200,
            mode='determinate',
            value=0
        )
        self.progress_bar.pack(anchor=tk.W, pady=(0, 10))
        
        # Total pushups
        self.total_pushups_label = ttk.Label(
            stats_frame,
            text=f"Total Pushups: {self.stats.total_pushups}",
            font=("Segoe UI", 12)
        )
        self.total_pushups_label.pack(anchor=tk.W, pady=5)
        
        # Streak
        self.streak_label = ttk.Label(
            stats_frame,
            text=f"Current Streak: {self.stats.streak_days} days",
            font=("Segoe UI", 12)
        )
        self.streak_label.pack(anchor=tk.W, pady=5)
        
        # Last completion
        self.last_completion_label = ttk.Label(
            stats_frame,
            text="Last Completed: Never",
            font=("Segoe UI", 12)
        )
        self.last_completion_label.pack(anchor=tk.W, pady=5)
        
        # After all statistics labels, add reset button
        reset_frame = ttk.Frame(stats_frame)
        reset_frame.pack(fill=tk.X, pady=(20, 0))
        
        def reset_stats():
            if messagebox.askyesno(
                "Reset Statistics",
                "Are you sure you want to reset all statistics?\nThis cannot be undone.",
                icon='warning'
            ):
                self.stats.reset_all()
                self.update_statistics()
                messagebox.showinfo(
                    "Statistics Reset",
                    "All statistics have been reset successfully."
                )
        
        ttk.Button(
            reset_frame,
            text="Reset Statistics",
            style="danger.TButton",
            command=reset_stats
        ).pack(side=tk.RIGHT)
        
    def create_footer(self):
        footer = ttk.Frame(self.main_container)
        footer.pack(fill=tk.X, pady=(20, 0))
        
        # Add credits frame
        credits_frame = ttk.Frame(footer)
        credits_frame.pack(fill=tk.X)
        
        # Status message
        self.status_label = ttk.Label(
            credits_frame,
            text="Ready to start",
            font=("Segoe UI", 10)
        )
        self.status_label.pack(side=tk.LEFT)
        
        # Credits
        ttk.Label(
            credits_frame,
            text="Created by oussamahattan@gmail.com",
            font=("Segoe UI", 10, "italic"),
            foreground="#666666"  # Subtle gray color
        ).pack(side=tk.RIGHT, padx=(0, 10))
        
        # Version below credits
        ttk.Label(
            footer,
            text=App_Version,
            font=("Segoe UI", 10)
        ).pack(side=tk.RIGHT)
        
    def setup_animations(self):
        self.animation_running = False
        
    def toggle_reminder(self):
        if not self.is_running:
            try:
                pushups = self.pushups_var.get()
                if pushups <= 0:
                    messagebox.showerror("Error", "Number of pushups must be greater than 0!")
                    return
                self.reminder_service.start()
                self.is_running = True
                self.toggle_btn.configure(
                    text="Stop Reminder",
                    style="danger.TButton"
                )
                self.status_label.configure(text="Reminder is running...")
            except ValueError:
                messagebox.showerror("Error", "Please enter valid numbers!")
        else:
            self.reminder_service.stop()
            self.is_running = False
            self.toggle_btn.configure(
                text="Start Reminder",
                style="success.TButton"
            )
            self.status_label.configure(text="Reminder stopped")
            
    def open_settings(self):
        # Pass self instead of self.root to provide access to update_service
        SettingsWindow(self, self.settings)
        
    def run(self):
        self.root.mainloop()
        
    def update_statistics(self):
        """Update statistics display"""
        stats_frame = self.right_panel  # Store right_panel as instance variable
        
        # Update today's pushups
        self.today_pushups_label.configure(
            text=f"Today's Pushups: {self.stats.today_pushups}"
        )
        
        # Update progress
        progress = (self.stats.today_pushups / self.settings.daily_goal * 100)
        progress = min(progress, 100)  # Cap at 100%
        
        self.progress_label.configure(
            text=f"Daily Goal Progress: {progress:.1f}%"
        )
        self.progress_bar.configure(value=progress)
        
        # Update total pushups
        self.total_pushups_label.configure(
            text=f"Total Pushups: {self.stats.total_pushups}"
        )
        
        # Update streak
        self.streak_label.configure(
            text=f"Current Streak: {self.stats.streak_days} days"
        )
        
        # Update last completion
        if self.stats.last_completion:
            last_time = self.stats.last_completion.strftime("%I:%M %p")
            self.last_completion_label.configure(
                text=f"Last Completed: {last_time}"
            )

    def create_left_panel(self, content):
        left_panel = ttk.Frame(content)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # Pushup counter
        counter_frame = ttk.Frame(left_panel)
        counter_frame.pack(fill=tk.X, pady=20)
        
        ttk.Label(
            counter_frame,
            text="Pushups per set:",
            font=("Segoe UI", 12)
        ).pack()
        
        pushup_entry = ttk.Entry(
            counter_frame,
            textvariable=self.pushups_var,
            width=10,
            font=("Segoe UI", 32),
            justify="center"
        )
        pushup_entry.pack(pady=10)
        
        # Start/Stop button
        self.toggle_btn = ttk.Button(
            left_panel,
            text="Start Reminder",
            style="success.TButton",
            command=self.toggle_reminder,
            width=20
        )
        self.toggle_btn.pack(pady=20)
        
        # Add countdown timer label under start button
        self.countdown_label = ttk.Label(
            left_panel,
            text="Next reminder in: --:--:--",
            font=("Segoe UI", 10)
        )
        self.countdown_label.pack(pady=(5, 0))
        
        self.update_countdown()
        
    def update_countdown(self):
        """Update the countdown timer"""
        if hasattr(self, 'reminder_service') and self.reminder_service.running:
            remaining = self.reminder_service.get_remaining_time()
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            seconds = remaining % 60
            self.countdown_label.configure(
                text=f"Next reminder in: {hours:02d}:{minutes:02d}:{seconds:02d}"
            )
        else:
            self.countdown_label.configure(text="Next reminder in: --:--:--")
        
        # Update every second
        self.root.after(1000, self.update_countdown)

class SettingsWindow:
    def __init__(self, parent, settings: AppSettings):
        self.parent = parent  # parent is now ModernPushupApp instance
        self.settings = settings
        self.window = ttk.Toplevel(parent.root)  # Use parent.root for the window parent
        self.window.title("Settings")
        self.window.geometry("400x750")
        self.window.resizable(False, False)
        self.preview_style = ttk.Style()
        self.create_settings_form()
        
    def create_settings_form(self):
        container = ttk.Frame(self.window, padding="20")
        container.pack(fill=tk.BOTH, expand=True)
        
        # Theme selection with live preview
        ttk.Label(container, text="Theme", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(0, 10))
        theme_var = tk.StringVar(value=self.settings.theme)
        
        # Create preview frame
        preview_frame = ttk.LabelFrame(container, text="Theme Preview", padding=10)
        preview_frame.pack(fill=tk.X, pady=(0, 20))
        
        # Update theme preview when radio button is selected
        def on_theme_change():
            self.preview_style.theme_use(theme_var.get())
        
        # Create radio buttons for each theme
        for theme in Theme:
            ttk.Radiobutton(
                container,
                text=theme.value.capitalize(),
                value=theme.value,
                variable=theme_var,
                command=on_theme_change,
                style="TRadiobutton"
            ).pack(anchor=tk.W, pady=2)

        # Interval settings
        ttk.Label(container, text="Reminder Interval", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(0, 10))
        
        interval_frame = ttk.Frame(container)
        interval_frame.pack(fill=tk.X, pady=(0, 20))
        
        # Hours
        hours_frame = ttk.Frame(interval_frame)
        hours_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(hours_frame, text="Hours").pack()
        hours_var = tk.IntVar(value=self.settings.interval_hours)
        ttk.Entry(hours_frame, textvariable=hours_var, width=5).pack()
        
        # Minutes
        minutes_frame = ttk.Frame(interval_frame)
        minutes_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(minutes_frame, text="Minutes").pack()
        minutes_var = tk.IntVar(value=self.settings.interval_minutes)
        ttk.Entry(minutes_frame, textvariable=minutes_var, width=5).pack()
        
        # Daily goal
        ttk.Label(container, text="Daily Goal", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(20, 10))
        goal_var = tk.IntVar(value=self.settings.daily_goal)
        ttk.Entry(container, textvariable=goal_var).pack(fill=tk.X)
        
        # Add auto-update toggle before buttons
        ttk.Label(
            container,
            text="Updates",
            font=("Segoe UI", 12, "bold")
        ).pack(anchor=tk.W, pady=(20, 10))
        
        auto_update_var = tk.BooleanVar(value=self.settings.auto_update)
        ttk.Checkbutton(
            container,
            text="Check for updates automatically",
            variable=auto_update_var
        ).pack(anchor=tk.W)
        
        # Updates section with check now button
        updates_frame = ttk.LabelFrame(container, text="Updates", padding=10)
        updates_frame.pack(fill=tk.X, pady=(20, 10))
        
        auto_update_var = tk.BooleanVar(value=self.settings.auto_update)
        ttk.Checkbutton(
            updates_frame,
            text="Check for updates automatically",
            variable=auto_update_var
        ).pack(anchor=tk.W)
        
        def check_updates_now():
            check_btn.configure(state="disabled", text="Checking...")
            self.window.update()
            
            def perform_check():
                try:
                    # Now we can access update_service through parent
                    has_update, new_version, download_url = self.parent.update_service.check_for_updates()
                    if has_update:
                        if messagebox.askyesno(
                            "Update Available",
                            f"Version {new_version} is available!\n\n"
                            "Would you like to download and install it now?",
                            parent=self.window
                        ):
                            # Handle update installation
                            pass
                    else:
                        messagebox.showinfo(
                            "No Updates",
                            "You are running the latest version!",
                            parent=self.window
                        )
                except ConnectionError:
                    messagebox.showerror(
                        "Update Check Failed",
                        "Failed to check for updates.\n"
                        "Please check your internet connection.",
                        parent=self.window
                    )
                except Exception as e:
                    messagebox.showerror(
                        "Update Check Failed",
                        f"An error occurred: {str(e)}",
                        parent=self.window
                    )
                finally:
                    self.window.after(0, lambda: check_btn.configure(
                        state="normal",
                        text="Check for Updates Now"
                    ))
            
            threading.Thread(target=perform_check, daemon=True).start()
        
        check_btn = ttk.Button(
            updates_frame,
            text="Check for Updates Now",
            style="info.TButton",
            command=check_updates_now
        )
        check_btn.pack(pady=(5, 0))

        # Add startup option before updates section
        startup_frame = ttk.Frame(container)
        startup_frame.pack(fill=tk.X, pady=(20, 10))
        
        startup_var = tk.BooleanVar(value=self.settings.start_with_windows)
        ttk.Checkbutton(
            startup_frame,
            text="Start with Windows",
            variable=startup_var
        ).pack(anchor=tk.W)
        
        # Button frame at the bottom (move this to the end)
        button_frame = ttk.Frame(container)
        button_frame.pack(fill=tk.X, pady=(20, 0))
        
        # Cancel button
        ttk.Button(
            button_frame,
            text="Cancel",
            style="secondary.TButton",
            command=self.close_window
        ).pack(side=tk.LEFT, padx=5)
        
        # Save button
        ttk.Button(
            button_frame,
            text="Save Changes",
            style="primary.TButton",
            command=lambda: self.save_settings(
                hours_var.get(),
                minutes_var.get(),
                theme_var.get(),
                goal_var.get(),
                auto_update_var.get(),
                startup_var.get()  # Add startup setting
            )
        ).pack(side=tk.RIGHT, padx=5)
        
    def save_settings(self, hours, minutes, theme, goal, auto_update, start_with_windows):
        """Save settings handler"""
        try:
            old_theme = self.settings.theme
            
            # Update settings
            self.settings.interval_hours = hours
            self.settings.interval_minutes = minutes
            self.settings.theme = theme
            self.settings.daily_goal = goal
            self.settings.auto_update = auto_update  # Save auto_update setting
            self.settings.start_with_windows = start_with_windows
            self.settings.save()
            self.update_startup_registry(start_with_windows)
            theme_changed = old_theme != theme
            if theme_changed:
                if messagebox.askyesno(
                    "Restart Required",
                    "Theme changes require a restart. Would you like to restart now?"
                ):
                    self.window.destroy()
                    self.parent.destroy()
                    self.parent.after_idle(main)
                else:
                    self.window.destroy()
                    messagebox.showinfo(
                        "Settings Saved",
                        "Changes will take effect after restart."
                    )
            else:
                self.window.destroy()
                messagebox.showinfo("Success", "Settings saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {e}")

    def update_startup_registry(self, enable: bool):
        """Update Windows startup registry"""
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            app_name = "PushupReminder"
            exe_path = str(Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve())
            
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                
                if enable:
                    winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}"')
                else:
                    try:
                        winreg.DeleteValue(key, app_name)
                    except WindowsError:
                        # Key doesn't exist, which is fine when disabling
                        pass
                        
                winreg.CloseKey(key)
            except WindowsError as e:
                raise Exception(f"Failed to update startup registry: {e}")
                
        except Exception as e:
            print(f"Error updating startup registry: {e}")
            raise

    def close_window(self):
        """Handle window close"""
        self.window.destroy()

class CompletionDialog:
    def __init__(self, parent, pushups: int, stats: Statistics, update_callback):
        self.window = ttk.Toplevel(parent)
        self.window.title("Pushup Completion")
        self.window.geometry("300x400")
        self.window.resizable(False, False)
        self.window.lift()  # Bring window to front
        
        self.pushups = pushups
        self.stats = stats
        self.update_callback = update_callback  # Add callback for updates
        self.create_dialog()
        
    def create_dialog(self):
        container = ttk.Frame(self.window, padding="20")
        container.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(
            container,
            text="Did you complete your pushups?",
            font=("Segoe UI", 14, "bold"),
            wraplength=250
        ).pack(pady=(0, 20))
        
        # Pushup count
        ttk.Label(
            container,
            text=f"{self.pushups} Pushups",
            font=("Segoe UI", 24)
        ).pack(pady=(0, 20))
        
        # Buttons
        ttk.Button(
            container,
            text="Did All Pushups",
            style="success.TButton",
            command=lambda: self.complete_pushups(self.pushups)
        ).pack(fill=tk.X, pady=5)
        
        ttk.Button(
            container,
            text="Did Half",
            style="info.TButton",
            command=lambda: self.complete_pushups(self.pushups // 2)
        ).pack(fill=tk.X, pady=5)
        
        ttk.Button(
            container,
            text="Did Some",
            style="TButton",
            command=self.custom_amount
        ).pack(fill=tk.X, pady=5)
        
        ttk.Button(
            container,
            text="Skip This Time",
            style="danger.TButton",
            command=self.window.destroy
        ).pack(fill=tk.X, pady=5)
        
    def custom_amount(self):
        amount = tk.simpledialog.askinteger(
            "Custom Amount",
            "How many pushups did you complete?",
            parent=self.window,
            minvalue=1,
            maxvalue=self.pushups
        )
        if amount:
            self.complete_pushups(amount)
    
    def complete_pushups(self, count: int):
        self.stats.add_pushups(count)
        self.update_callback()  # Call the update function
        self.window.destroy()

def main():
    app = ModernPushupApp()
    app.run()

if __name__ == "__main__":
    main()