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
from pygame import mixer
import pygame
from tkinter import filedialog
import win32com.client
import pythoncom

App_Version = "Pushup Reminder Pro v1.5"

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
    theme: str = "darkly"  # Changed from 'dark' to 'darkly'
    notification_sound: str = "default"  # Changed from bool to str
    custom_sound_path: Optional[str] = None
    auto_start: bool = False
    minimize_to_tray: bool = True
    show_progress: bool = True
    daily_goal: int = 100
    rest_duration: int = 60
    pushup_animation: bool = True
    
    # Add validation for sound files
    MAX_SOUND_SIZE = 1024 * 1024  # 1MB limit
    ALLOWED_EXTENSIONS = {'.wav', '.mp3'}
    
    @classmethod
    def load(cls) -> 'AppSettings':
        config_path = Path.home() / '.pushup_reminder' / 'config.json'
        if config_path.exists():
            with open(config_path, 'r') as f:
                return cls(**json.load(f))
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

    def check_daily_goal(self, goal: int) -> bool:
        """Check if daily goal is reached"""
        return self.today_pushups >= goal

class NotificationService:
    def __init__(self, settings: AppSettings, stats: Statistics, root: ttk.Window, update_callback):
        self.settings = settings
        self.stats = stats
        self.root = root
        self.toaster = ToastNotifier()
        self.update_callback = update_callback
        pygame.mixer.init()
        # Initialize COM for this thread
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
            
            # Play notification sound
            self.play_notification_sound()
            
        except Exception as e:
            print(f"Failed to send minimize notification: {e}")

    def notify(self, title: str, message: str):
        """Send a Windows notification and show completion dialog"""
        try:
            icon_path = str(Path(__file__).parent / 'assets' / 'icons' / 'logo.ico')
            if not Path(icon_path).exists():
                icon_path = str(Path(__file__).parent / 'assets' / 'icons' / 'logo.png')
            
            # Play notification sound first
            self.play_notification_sound()
            
            # Show the toast notification without Windows sound
            try:
                # Create shell object in the same thread
                pythoncom.CoInitialize()
                shell = win32com.client.Dispatch("WScript.Shell")
                shell.Popup(
                    message,
                    0,  # Wait time (0 = don't wait)
                    title,
                    64  # Information icon
                )
                pythoncom.CoUninitialize()
            except:
                # Fallback to win10toast if shell popup fails
                self.toaster.show_toast(
                    title,
                    message,
                    icon_path=icon_path if Path(icon_path).exists() else None,
                    duration=5,
                    threaded=True
                )
            
            # Show completion dialog after notification
            self.root.after(2000, lambda: CompletionDialog(
                self.root,
                self.settings.pushups,
                self.stats,
                self.update_callback
            ))
            
        except Exception as e:
            print(f"Failed to send notification: {e}")
            # Final fallback - just show the completion dialog
            self.root.after(1000, lambda: CompletionDialog(
                self.root,
                self.settings.pushups,
                self.stats,
                self.update_callback
            ))

    def play_notification_sound(self):
        """Play the selected notification sound"""
        try:
            sounds_dir, default_sounds = setup_sounds_directory()
            if self.settings.notification_sound == "custom" and self.settings.custom_sound_path:
                sound_path = Path(self.settings.custom_sound_path)
            else:
                sound_path = sounds_dir / default_sounds[self.settings.notification_sound]
                
            if sound_path.exists():
                pygame.mixer.music.load(str(sound_path))
                pygame.mixer.music.play()
        except Exception as e:
            print(f"Failed to play notification sound: {e}")

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

class ModernPushupApp:
    def __init__(self):
        self.settings = AppSettings.load()
        # Create the main window with ttkbootstrap
        self.root = ttk.Window(
            title="Pushup Reminder Pro",
            themename=self.settings.theme,
            size=(900, 700)  # Increased window size
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
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        # Initialize statistics first
        self.stats = Statistics()
        self.setup_tray_icon()
        self.setup_variables()
        self.setup_placeholder_images()
        self.setup_animations()
        
        # Initialize services with stats
        self.notification_service = NotificationService(self.settings, self.stats, self.root, self.update_statistics)
        self.reminder_service = ReminderService(self.settings, self.notification_service)
        
        # Create GUI after all initializations
        self.create_gui()
        
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
        
        if response:  # Yes clicked - minimize
            self.root.withdraw()  # Hide the window
            # Show notification that app is minimized WITHOUT showing completion dialog
            self.notification_service.notify_minimize(  # New method
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
                if (pushups <= 0):
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
        SettingsWindow(self.root, self.settings)
        
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

        # Check if daily goal is reached
        if self.stats.check_daily_goal(self.settings.daily_goal) and self.is_running:
            self.reminder_service.stop()
            self.is_running = False
            self.toggle_btn.configure(
                text="Start Reminder",
                style="success.TButton"
            )
            self.status_label.configure(text="Daily goal reached!")
            self.show_goal_completion_dialog()

    def show_goal_completion_dialog(self):
        """Show dialog when daily goal is reached"""
        response = messagebox.askyesno(
            "Congratulations! 🎉",
            f"You've reached your daily goal of {self.settings.daily_goal} pushups!\n\n"
            "Would you like to set a new goal for today?",
            icon='info'
        )
        
        if response:  # User wants to set new goal
            new_goal = simpledialog.askinteger(
                "New Daily Goal",
                "Enter your new daily goal:",
                parent=self.root,
                minvalue=self.settings.daily_goal + 1,
                initialvalue=self.settings.daily_goal + 20
            )
            
            if new_goal:
                self.settings.daily_goal = new_goal
                self.settings.save()
                self.daily_goal_var.set(new_goal)
                
                if messagebox.askyesno(
                    "Resume Training",
                    "Would you like to resume your training with the new goal?",
                    icon='question'
                ):
                    self.toggle_reminder()  # Restart the reminder
                else:
                    messagebox.showinfo(
                        "Training Complete",
                        "Great job today! Take a rest and come back stronger tomorrow! 💪",
                        icon='info'
                    )
        else:
            messagebox.showinfo(
                "Training Complete",
                "Amazing work! You've crushed your goal for today! 🏆\n"
                "Get some rest and come back tomorrow for more gains! 💪",
                icon='info'
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
        self.parent = parent
        self.settings = settings
        self.window = ttk.Toplevel(parent)
        self.window.title("Settings")
        self.window.geometry("500x800")  # Increased window size
        self.window.resizable(True, True)  # Made resizable
        
        # Create scrollable container
        canvas = ttk.Canvas(self.window)
        scrollbar = ttk.Scrollbar(self.window, orient="vertical", command=canvas.yview)
        self.container = ttk.Frame(canvas)
        
        # Configure canvas
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Pack scrollbar and canvas
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Create window in canvas
        canvas_window = canvas.create_window((0, 0), window=self.container, anchor="nw")
        
        # Configure canvas scrolling
        def configure_scroll_region(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        def configure_window_size(event):
            canvas.itemconfig(canvas_window, width=event.width)
        
        self.container.bind("<Configure>", configure_scroll_region)
        canvas.bind("<Configure>", configure_window_size)
        
        # Add mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # Create preview frame first
        self.preview_style = ttk.Style()
        self.create_settings_form()
        
        # Initialize pygame mixer
        pygame.mixer.init()
        
    def create_settings_form(self):
        # Use self.container instead of creating a new container
        self.container.configure(padding="20")
        
        # Theme selection with live preview
        ttk.Label(self.container, text="Theme", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(0, 10))
        theme_var = tk.StringVar(value=self.settings.theme)
        
        # Create preview frame
        preview_frame = ttk.LabelFrame(self.container, text="Theme Preview", padding=10)
        preview_frame.pack(fill=tk.X, pady=(0, 20))
        
        # Update theme preview when radio button is selected
        def on_theme_change():
            self.preview_style.theme_use(theme_var.get())
        # Create radio buttons for each theme
        for theme in Theme:
            ttk.Radiobutton(
                self.container,
                text=theme.value.capitalize(),
                value=theme.value,
                variable=theme_var,
                command=on_theme_change,
                style="TRadiobutton"
            ).pack(anchor=tk.W, pady=2)

        # Interval settings
        ttk.Label(self.container, text="Reminder Interval", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(0, 10))
        interval_frame = ttk.Frame(self.container)
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
        
        # Notification sound
        ttk.Label(self.container, text="Notifications", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(0, 10))
        sound_var = tk.StringVar(value=self.settings.notification_sound)
        
        # Sound settings
        ttk.Label(self.container, text="Notification Sound", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(20, 10))
        
        sounds_frame = ttk.LabelFrame(self.container, text="Choose Sound", padding=10)
        sounds_frame.pack(fill=tk.X, pady=(0, 20))
        
        # Default sounds
        sounds_dir, default_sounds = setup_sounds_directory()
        for sound_name in default_sounds.keys():
            ttk.Radiobutton(
                sounds_frame,
                text=sound_name.replace('_', ' ').capitalize(),
                value=sound_name,
                variable=sound_var,
                command=lambda s=sound_name: self.play_sound(sounds_dir / f"{s}.wav"),
                style="TRadiobutton"
            ).pack(anchor=tk.W, pady=2)
        
        # Custom sound section
        custom_frame = ttk.Frame(sounds_frame)
        custom_frame.pack(fill=tk.X, pady=(10, 0))
        
        def browse_sound():
            file_path = filedialog.askopenfilename(
                title="Select Sound File",
                filetypes=[("Sound Files", "*.wav *.mp3")],
                initialdir=str(Path.home())
            )
            if file_path:
                try:
                    sound_path = Path(file_path)
                    # Check file size
                    if sound_path.stat().st_size > AppSettings.MAX_SOUND_SIZE:
                        messagebox.showerror("Error", "Sound file must be smaller than 1MB")
                        return
                    # Check extension
                    if sound_path.suffix.lower() not in AppSettings.ALLOWED_EXTENSIONS:
                        messagebox.showerror("Error", "Only .wav and .mp3 files are supported")
                        return
                    # Copy file to sounds directory
                    dest_path = sounds_dir / sound_path.name
                    import shutil
                    shutil.copy2(file_path, dest_path)
                    
                    self.settings.custom_sound_path = str(dest_path)
                    sound_var.set("custom")
                    self.play_sound(dest_path)
                    
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to add sound file: {e}")
        
        ttk.Button(
            custom_frame,
            text="Add Custom Sound",
            command=browse_sound,
            style="TButton"
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Radiobutton(
            custom_frame,
            text="Use Custom Sound",
            value="custom",
            variable=sound_var,
            state="disabled" if not self.settings.custom_sound_path else "normal",
            command=lambda: self.play_sound(Path(self.settings.custom_sound_path)),
            style="TRadiobutton",
        ).pack(side=tk.LEFT, padx=5)
        
        # Daily goal
        ttk.Label(self.container, text="Daily Goal", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(20, 10))
        goal_var = tk.IntVar(value=self.settings.daily_goal)
        ttk.Entry(self.container, textvariable=goal_var).pack(fill=tk.X)
        
        # Button frame at the bottom (move this to the end)
        button_frame = ttk.Frame(self.container)
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
                sound_var.get(),
                goal_var.get()
            )
        ).pack(side=tk.RIGHT, padx=5)

    def save_settings(self, hours, minutes, theme, sound, goal):
        """Save settings handler"""
        try:
            old_theme = self.settings.theme
            
            # Update settings
            self.settings.interval_hours = hours
            self.settings.interval_minutes = minutes
            self.settings.theme = theme
            self.settings.notification_sound = sound
            self.settings.daily_goal = goal
            self.settings.save()
            
            theme_changed = old_theme != theme
            if theme_changed:
                if messagebox.askyesno(
                    "Restart Required",
                    "Theme changes require a restart. Would you like to restart now?"
                ):
                    self.stop_sound()
                    self.window.destroy()
                    self.parent.destroy()
                    self.parent.after_idle(main)
                else:
                    self.stop_sound()
                    self.window.destroy()
                    messagebox.showinfo(
                        "Settings Saved",
                        "Changes will take effect after restart."
                    )
            else:
                self.stop_sound()
                self.window.destroy()
                messagebox.showinfo("Success", "Settings saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {e}")

    def play_sound(self, sound_path):
        """Play the selected sound"""
        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            pygame.mixer.music.load(str(sound_path))
            pygame.mixer.music.play()
        except Exception as e:
            print(f"Failed to play sound: {e}")
    
    def stop_sound(self):
        """Stop any playing sound"""
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()

    def close_window(self):
        """Handle window close"""
        self.stop_sound()
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

def setup_sounds_directory():
    sounds_dir = Path(__file__).parent / 'assets' / 'sounds'
    sounds_dir.mkdir(parents=True, exist_ok=True)
    # Default sounds dictionary with names and sources
    default_sounds = {
        "Default": "mixkit-software-interface-start-2574.wav",
        "Rain": "mixkit-rain-in-the-forest-2337.wav",
        "Guitar_up": "mixkit-guitar-stroke-up-slow-2338.wav",
        "Guitar_down": "mixkit-guitar-stroke-down-slow-2339.wav",
    }
    return sounds_dir, default_sounds

def main():
    app = ModernPushupApp()
    app.run()

if __name__ == "__main__":
    main()