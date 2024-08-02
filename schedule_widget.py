from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QComboBox, QDateTimeEdit, QTableWidget, QTableWidgetItem, QHeaderView, 
                             QFileDialog, QMessageBox, QDialog, QDialogButtonBox)
from PyQt6.QtCore import QDateTime, Qt

class ScheduleWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # File/Folder selection
        file_layout = QHBoxLayout()
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("Select file or folder")
        file_layout.addWidget(self.file_input)
        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self.browse_files_or_folders)
        file_layout.addWidget(self.browse_button)
        layout.addLayout(file_layout)

        # Custom prompt
        prompt_layout = QHBoxLayout()
        prompt_layout.addWidget(QLabel("Custom Prompt:"))
        self.prompt_input = QLineEdit()
        prompt_layout.addWidget(self.prompt_input)
        layout.addLayout(prompt_layout)

        # Schedule interval
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Interval:"))
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["Daily", "Weekly", "Monthly"])
        interval_layout.addWidget(self.interval_combo)
        layout.addLayout(interval_layout)

        # Start time
        start_time_layout = QHBoxLayout()
        start_time_layout.addWidget(QLabel("Start Time:"))
        self.start_time_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.start_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        start_time_layout.addWidget(self.start_time_edit)
        layout.addLayout(start_time_layout)

        # Schedule button
        self.schedule_button = QPushButton("Schedule")
        self.schedule_button.clicked.connect(self.schedule_upload)
        layout.addWidget(self.schedule_button)

        # Scheduled tasks table
        self.tasks_table = QTableWidget()
        self.tasks_table.setColumnCount(4)
        self.tasks_table.setHorizontalHeaderLabels(["File/Folder", "Prompt", "Interval", "Start Time"])
        self.tasks_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tasks_table)

    def browse_files_or_folders(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Select File or Folder")
        dialog_layout = QVBoxLayout(dialog)

        file_button = QPushButton("Select File")
        file_button.clicked.connect(lambda: self.select_file(dialog))
        dialog_layout.addWidget(file_button)

        folder_button = QPushButton("Select Folder")
        folder_button.clicked.connect(lambda: self.select_folder(dialog))
        dialog_layout.addWidget(folder_button)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        button_box.rejected.connect(dialog.reject)
        dialog_layout.addWidget(button_box)

        dialog.exec()

    def select_file(self, dialog):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "All Files (*)")
        if file_path:
            self.file_input.setText(file_path)
        dialog.accept()

    def select_folder(self, dialog):
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder_path:
            self.file_input.setText(folder_path)
        dialog.accept()

    def schedule_upload(self):
        file_path = self.file_input.text()
        prompt = self.prompt_input.text()
        interval = self.interval_combo.currentText()
        start_time = self.start_time_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss")

        if not file_path or not prompt:
            QMessageBox.warning(self, "Input Error", "Please provide both file/folder and prompt.")
            return

        row_position = self.tasks_table.rowCount()
        self.tasks_table.insertRow(row_position)
        self.tasks_table.setItem(row_position, 0, QTableWidgetItem(file_path))
        self.tasks_table.setItem(row_position, 1, QTableWidgetItem(prompt))
        self.tasks_table.setItem(row_position, 2, QTableWidgetItem(interval))
        self.tasks_table.setItem(row_position, 3, QTableWidgetItem(start_time))

        # Here you would add the logic to actually schedule the task
        # This could involve setting up a cron job, using a task scheduler, etc.
        # For now, we'll just add it to the table as a placeholder