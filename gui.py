import sys
import os
import uuid
import asyncio
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QTextEdit, QProgressBar, QStackedWidget, 
                             QTableWidget, QTableWidgetItem, QHeaderView)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QObject
from PyQt6.QtGui import QIcon, QDragEnterEvent, QDropEvent

from deskclient import DeskClient

class WorkerThread(QThread):
    update_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, client, run_id):
        super().__init__()
        self.client = client
        self.run_id = run_id

    def run(self):
        output_base = f"batch_requests_{self.run_id}"
        self.client.create_batch_jsonl(output_base)
        
        file_index = 1
        while True:
            file_path = f"{output_base}_{file_index}.jsonl"
            if not os.path.exists(file_path):
                break
            self.update_signal.emit(f"Uploading {file_path}...")
            self.client.upload_jsonl(file_path)
            try:
                os.remove(file_path)
                self.update_signal.emit(f"Removed batch request file: {file_path}")
            except OSError as e:
                self.update_signal.emit(f"Error removing batch request file {file_path}: {e}")
            file_index += 1

        self.update_signal.emit("Upload complete")
        balance = self.client.check_balance()
        self.update_signal.emit(f"Current balance: {balance}")

        batch_jobs = self.client.get_batch_jobs()
        if batch_jobs:
            self.update_signal.emit("Processing all batch jobs concurrently...")
            asyncio.run(self.client.async_process_all_batches(batch_jobs))
        else:
            self.update_signal.emit("No batch jobs found.")

        final_balance = self.client.check_balance()
        self.update_signal.emit(f"Final balance: {final_balance}")

        self.finished_signal.emit()

class BatchStatusThread(QThread):
    update_signal = pyqtSignal(list)

    def __init__(self, client):
        super().__init__()
        self.client = client

    def run(self):
        batch_jobs = self.client.get_batch_jobs()
        self.update_signal.emit(batch_jobs)

class BatchPollWorker(QObject):
    update_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, client):
        super().__init__()
        self.client = client

    def run(self):
        batch_jobs = self.client.get_batch_jobs()
        incomplete_jobs = [job for job in batch_jobs if job['status'] != 'completed']
        
        if incomplete_jobs:
            self.update_signal.emit(f"Found {len(incomplete_jobs)} incomplete batch jobs. Processing...")
            asyncio.run(self.client.async_process_all_batches(incomplete_jobs))
            self.update_signal.emit("Finished processing incomplete batch jobs.")
        else:
            self.update_signal.emit("No incomplete batch jobs found.")
        
        self.finished_signal.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DeskClient GUI")
        self.setGeometry(100, 100, 1000, 600)

        self.client = DeskClient("http://localhost:5000", user_token='x9z0oeGLYu36GQqAjte8kg')

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # Create sidebar
        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(200)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Create stacked widget for main content
        self.stacked_widget = QStackedWidget()

        # Create and add pages
        self.create_upload_page()
        self.create_batch_status_page()

        # Create sidebar buttons
        self.create_sidebar_button("Upload", "upload_icon.png", 0)
        self.create_sidebar_button("Batch Status", "status_icon.png", 1)

        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.stacked_widget)

        self.check_balance()

        # Start polling for incomplete batch jobs
        self.poll_incomplete_jobs()

        # Set up timer to update batch status every 30 seconds
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_batch_status)
        self.status_timer.start(30000)  # 30 seconds

    def create_sidebar_button(self, text, icon_path, page_index):
        button = QPushButton(text)
        button.setIcon(QIcon(icon_path))
        button.setIconSize(QSize(24, 24))
        button.setFixedHeight(50)
        button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(page_index))
        self.sidebar_layout.addWidget(button)

    def create_upload_page(self):
        upload_widget = QWidget()
        layout = QVBoxLayout(upload_widget)

        self.drag_drop_area = DragDropArea(self)
        layout.addWidget(self.drag_drop_area)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.upload_button = QPushButton("Upload and Process Files")
        self.upload_button.clicked.connect(self.upload_and_process_files)
        layout.addWidget(self.upload_button)

        self.stacked_widget.addWidget(upload_widget)

    def create_batch_status_page(self):
        status_widget = QWidget()
        layout = QVBoxLayout(status_widget)

        self.status_table = QTableWidget()
        self.status_table.setColumnCount(4)
        self.status_table.setHorizontalHeaderLabels(["Batch ID", "Status", "Created At", "Completed At"])
        self.status_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # Make table non-editable
        layout.addWidget(self.status_table)

        refresh_button = QPushButton("Refresh Status")
        refresh_button.clicked.connect(self.update_batch_status)
        layout.addWidget(refresh_button)

        self.stacked_widget.addWidget(status_widget)

    def update_batch_status(self):
        self.batch_status_thread = BatchStatusThread(self.client)
        self.batch_status_thread.update_signal.connect(self.display_batch_status)
        self.batch_status_thread.start()

    def display_batch_status(self, batch_jobs):
        self.status_table.setRowCount(len(batch_jobs))
        for row, job in enumerate(batch_jobs):
            self.status_table.setItem(row, 0, QTableWidgetItem(job['id']))
            self.status_table.setItem(row, 1, QTableWidgetItem(job['status']))
            self.status_table.setItem(row, 2, QTableWidgetItem(job['created_at']))
            self.status_table.setItem(row, 3, QTableWidgetItem(job.get('completed_at', 'N/A')))

    def check_balance(self):
        balance = self.client.check_balance()
        if balance < 10:
            self.log("Insufficient tokens, purchasing more...")
            new_balance = self.client.purchase_tokens(100)
            self.log(f"Purchased tokens. New balance: {new_balance}")
        else:
            self.log(f"Sufficient tokens available. Current balance: {balance}")

    def process_file(self, file_path):
        self.log(f"Processing file: {file_path}")
        if self.client.is_image(file_path):
            self.client.process_image(file_path)
            self.log("File added to queue")
        else:
            self.log("Not a valid image file")

    def process_folder(self, folder_path):
        self.log(f"Processing folder: {folder_path}")
        if self.client.process_folder(folder_path):
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
        self.poll_thread.start()

    def on_poll_finished(self):
        self.poll_thread.quit()
        self.poll_thread.wait()
        self.update_batch_status()

class DragDropArea(QLabel):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("Drag and drop files or folders here")
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #aaa;
                border-radius: 5px;
                padding: 20px;
                background-color: #f0f0f0;
                color: black;
            }
        """)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                self.main_window.process_file(file_path)
            elif os.path.isdir(file_path):
                self.main_window.process_folder(file_path)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
