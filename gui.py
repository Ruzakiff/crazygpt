import sys
import os
import uuid
import json
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QTextEdit, QProgressBar, QStackedWidget, 
                             QTableWidget, QTableWidgetItem, QHeaderView, QListWidget,
                             QComboBox, QFileDialog, QFrame)
from PyQt6.QtCore import Qt, QTimer, QSize, QThread
from PyQt6.QtGui import QIcon

from deskclient import DeskClient
from worker_thread import WorkerThread
from batch_status_thread import BatchStatusThread
from batch_poll_worker import BatchPollWorker
from drag_drop_area import DragDropArea
from completed_tab import CompletedBatchResultsWidget  # Add this import
from token_widget import TokenWidget  # Import the TokenWidget
from schedule_widget import ScheduleWidget  # Import the ScheduleWidget

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DeskClient GUI")
        self.setGeometry(100, 100, 1000, 600)

        # Initialize with a placeholder token
        self.client = DeskClient("https://organizeme-04efee729c26.herokuapp.com", user_token="PLACEHOLDER")

        # Initialize prompt_options as a dictionary
        self.prompt_options = {
            "Print-worthy photos": "Analyze this image for a personal photo collection and determine if it should be printed. Output KEEP if the image is worth printing, or DELETE if it's not suitable for printing. Consider factors such as image quality, visual appeal, and personal significance when making your decision.",
            "Images with text": "Output KEEP for images containing text, DELETE otherwise.",
            "Architecture photos": "Output KEEP for images of buildings or architecture, DELETE otherwise.",
            "Images without people": "Output KEEP for images without people, DELETE otherwise.",
            "Vibrant color images": "Output KEEP for images with vibrant colors, DELETE otherwise.",
        }

        self.setup_ui()
        self.poll_incomplete_jobs()

        # Set up timer to update batch status every 30 seconds
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_batch_status)
        self.status_timer.start(30000)  # 30 seconds

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Add TokenWidget at the top
        self.token_widget = TokenWidget()
        self.token_widget.token_updated.connect(self.update_token)
        main_layout.addWidget(self.token_widget)
        
        # Add a line separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(line)
        
        # Create horizontal layout for sidebar and main content
        content_layout = QHBoxLayout()
        main_layout.addLayout(content_layout)
        
        # Create sidebar
        sidebar_layout = QVBoxLayout()
        self.create_sidebar(sidebar_layout)
        
        # Add sidebar to content layout
        sidebar_widget = QWidget()
        sidebar_widget.setLayout(sidebar_layout)
        sidebar_widget.setFixedWidth(80)  # Reduced width for icon-only sidebar
        content_layout.addWidget(sidebar_widget)
        
        # Create stacked widget for main content
        self.stacked_widget = QStackedWidget()
        content_layout.addWidget(self.stacked_widget)

        # Create and add pages
        self.create_upload_page()
        self.create_batch_status_page()
        self.create_batch_details_page()  # Keep this, but don't add it to the main navigation
        self.create_completed_results_page()
        self.create_schedule_page()

        # Set a minimum width for the window to ensure all elements are visible
        self.setMinimumWidth(800)

    def update_token(self, token):
        # Update the token in the DeskClient
        self.client.user_token = token
        print(f"Token updated: {token}")
        self.check_balance()
        self.update_batch_status()  # Refresh batch status when token is updated

    def create_sidebar(self, layout):
        self.create_sidebar_button("Upload", "upload.png", 0, layout)
        self.create_sidebar_button("Batch Status", "batch_status.webp", 1, layout)
        self.create_sidebar_button("Completed Results", "decisions.webp", 3, layout)
        self.create_sidebar_button("Schedule", "schedule.png", 4, layout)
        layout.addStretch()  # This pushes the buttons to the top

    def create_sidebar_button(self, tooltip, icon_name, page_index, layout):
        button = QPushButton()
        icon_path = os.path.join("icons", icon_name)
        button.setIcon(QIcon(icon_path))
        button.setIconSize(QSize(40, 40))
        button.setFixedSize(60, 60)
        button.setToolTip(tooltip)
        button.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 10px;
                background-color: #2C2C2C;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #3C3C3C;
            }
            QPushButton:pressed {
                background-color: #4C4C4C;
            }
        """)
        button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(page_index))
        layout.addWidget(button)

    def create_upload_page(self):
        upload_widget = QWidget()
        layout = QVBoxLayout(upload_widget)

        # Add file selection options
        file_selection_layout = QHBoxLayout()
        
        self.select_files_button = QPushButton("Select Files")
        self.select_files_button.clicked.connect(self.select_files)
        file_selection_layout.addWidget(self.select_files_button)
        
        self.select_folder_button = QPushButton("Select Folder")
        self.select_folder_button.clicked.connect(self.select_folder)
        file_selection_layout.addWidget(self.select_folder_button)
        
        layout.addLayout(file_selection_layout)

        # Existing drag and drop area
        self.drag_drop_area = DragDropArea(self)
        layout.addWidget(self.drag_drop_area)

        # Add custom prompt section
        prompt_layout = QHBoxLayout()
        self.custom_prompt_label = QLabel("Custom Prompt:")
        prompt_layout.addWidget(self.custom_prompt_label)

        self.prompt_dropdown = QComboBox()
        self.prompt_dropdown.addItem("Select a prompt type...")
        self.prompt_dropdown.addItems(self.prompt_options.keys())
        self.prompt_dropdown.currentIndexChanged.connect(self.update_custom_prompt)
        prompt_layout.addWidget(self.prompt_dropdown)

        layout.addLayout(prompt_layout)

        self.custom_prompt_text = QTextEdit()
        self.custom_prompt_text.setPlaceholderText("Enter your custom prompt here...")
        self.custom_prompt_text.setMaximumHeight(100)
        layout.addWidget(self.custom_prompt_text)

        # Set default prompt
        default_prompt = "Output DELETE for images containing women, girls, or animals. Output DELETE for images that may seem controversial or disrespectful. Output KEEP for all other images."
        self.custom_prompt_text.setPlainText(default_prompt)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.upload_button = QPushButton("Upload and Process Files")
        self.upload_button.clicked.connect(self.upload_and_process_files)
        layout.addWidget(self.upload_button)

        self.stacked_widget.addWidget(upload_widget)

    def update_custom_prompt(self, index):
        if index > 0:  # Ignore the "Select a prompt type..." option
            selected_description = self.prompt_dropdown.currentText()
            selected_prompt = self.prompt_options[selected_description]
            self.custom_prompt_text.setPlainText(selected_prompt)

    def create_batch_status_page(self):
        status_widget = QWidget()
        layout = QVBoxLayout(status_widget)

        self.status_table = QTableWidget()
        self.status_table.setColumnCount(4)
        self.status_table.setHorizontalHeaderLabels(["Batch ID", "Status", "Created At", "Completed At"])
        self.status_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # Make table non-editable
        self.status_table.itemDoubleClicked.connect(self.show_batch_details)
        layout.addWidget(self.status_table)

        refresh_button = QPushButton("Refresh Status")
        refresh_button.clicked.connect(self.update_batch_status)
        layout.addWidget(refresh_button)

        self.stacked_widget.addWidget(status_widget)

    def create_batch_details_page(self):
        self.batch_details_widget = QWidget()
        layout = QVBoxLayout(self.batch_details_widget)

        self.batch_id_label = QLabel()
        layout.addWidget(self.batch_id_label)

        self.file_list = QListWidget()
        layout.addWidget(self.file_list)

        back_button = QPushButton("Back to Batch Status")
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))  # Assuming Batch Status is index 1
        layout.addWidget(back_button)

        self.stacked_widget.addWidget(self.batch_details_widget)

    def show_batch_details(self, item):
        row = item.row()
        batch_id = self.status_table.item(row, 0).text()
        
        self.batch_id_label.setText(f"Batch ID: {batch_id}")
        self.load_file_paths(batch_id)
        self.stacked_widget.setCurrentWidget(self.batch_details_widget)

    def load_file_paths(self, batch_id):
        self.file_list.clear()
        file_path = f"pending_batches/{batch_id}.jsonl"
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                for line in f:
                    data = json.loads(line)
                    file_path = data.get('custom_id', 'Unknown file path')
                    self.file_list.addItem(file_path)
        else:
            self.file_list.addItem("No file paths found for this batch.")

    def update_batch_status(self):
        self.batch_status_thread = BatchStatusThread(self.client)
        self.batch_status_thread.update_signal.connect(self.display_batch_status)
        self.batch_status_thread.error_signal.connect(self.handle_batch_status_error)
        self.batch_status_thread.start()

    def handle_batch_status_error(self, error_message):
        self.log(f"Batch status error: {error_message}")
        # Clear the status table when there's an error
        self.status_table.setRowCount(0)

    def display_batch_status(self, batch_jobs):
        if not batch_jobs:
            self.log("No batch jobs found.")
            self.status_table.setRowCount(0)
            return

        self.status_table.setRowCount(len(batch_jobs))
        for row, job in enumerate(batch_jobs):
            self.status_table.setItem(row, 0, QTableWidgetItem(job['id']))
            self.status_table.setItem(row, 1, QTableWidgetItem(job['status']))
            self.status_table.setItem(row, 2, QTableWidgetItem(job['created_at']))
            self.status_table.setItem(row, 3, QTableWidgetItem(job.get('completed_at', 'N/A')))

    def check_balance(self):
        try:
            balance = self.client.check_balance()
            if balance is not None:
                self.log(f"Current token balance: {balance}")
            else:
                self.log("Failed to retrieve balance. Token may be invalid.")
        except Exception as e:
            self.log(f"Error checking balance: {str(e)}")

    def process_file(self, file_path):
        self.log(f"Processing file: {file_path}")
        custom_prompt = self.custom_prompt_text.toPlainText()
        if self.client.is_image(file_path):
            self.client.process_image(file_path, custom_prompt)
            self.log("File added to queue")
        else:
            self.log("Not a valid image file")

    def process_folder(self, folder_path):
        self.log(f"Processing folder: {folder_path}")
        custom_prompt = self.custom_prompt_text.toPlainText()
        if self.client.process_folder(folder_path, custom_prompt):
            self.log("Folder processed successfully")
        else:
            self.log("Failed to process folder")

    def upload_and_process_files(self):
        self.upload_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress

        run_id = uuid.uuid4().hex[:8]
        self.worker = WorkerThread(self.client, run_id)
        self.worker.update_signal.connect(self.log)
        self.worker.finished_signal.connect(self.on_worker_finished)
        self.worker.start()

    def on_worker_finished(self):
        self.upload_button.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.log("All operations completed")
        self.update_batch_status()

    def log(self, message):
        self.log_area.append(message)

    def poll_incomplete_jobs(self):
        self.poll_thread = QThread()
        self.poll_worker = BatchPollWorker(self.client)
        self.poll_worker.moveToThread(self.poll_thread)
        self.poll_thread.started.connect(self.poll_worker.run)
        self.poll_worker.update_signal.connect(self.log)
        self.poll_worker.finished_signal.connect(self.on_poll_finished)
        self.poll_worker.error_signal.connect(self.handle_poll_error)
        self.poll_thread.start()

    def handle_poll_error(self, error_message):
        self.log(f"Error in batch poll: {error_message}")

    def on_poll_finished(self):
        self.poll_thread.quit()
        self.poll_thread.wait()
        self.update_batch_status()

    def create_completed_results_page(self):
        self.completed_results_widget = CompletedBatchResultsWidget()
        self.stacked_widget.addWidget(self.completed_results_widget)

    def create_schedule_page(self):
        self.schedule_widget = ScheduleWidget()
        self.stacked_widget.addWidget(self.schedule_widget)

    def select_files(self):
        file_dialog = QFileDialog()
        files, _ = file_dialog.getOpenFileNames(self, "Select Files", "", "Image Files (*.png *.jpg *.jpeg *.gif *.bmp)")
        if files:
            for file in files:
                self.process_file(file)

    def select_folder(self):
        folder_dialog = QFileDialog()
        folder = folder_dialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.process_folder(folder)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())