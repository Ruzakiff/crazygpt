import json
import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QPushButton, QLabel, QSplitter)
from PyQt6.QtCore import Qt, pyqtSignal, QFileSystemWatcher
from PyQt6.QtGui import QColor

class CompletedBatchResultsWidget(QWidget):
    decision_made = pyqtSignal(str, str, str)  # custom_id, content, decision
    batch_decision_made = pyqtSignal(str, str)  # batch_id, decision (APPROVE or DENY)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.current_batch_id = None
        self.setup_file_watcher()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)

        # Batch selection area
        batch_widget = QWidget()
        batch_layout = QVBoxLayout(batch_widget)
        batch_layout.addWidget(QLabel("Select a batch:"))
        self.batch_table = QTableWidget()
        self.batch_table.setColumnCount(2)
        self.batch_table.setHorizontalHeaderLabels(["Batch ID", "Timestamp"])
        self.batch_table.horizontalHeader().setStretchLastSection(True)
        self.batch_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.batch_table.itemClicked.connect(self.load_batch_results)
        batch_layout.addWidget(self.batch_table)

        # Batch action button
        self.approve_all_button = QPushButton("Approve All")
        self.approve_all_button.clicked.connect(self.approve_all)
        batch_layout.addWidget(self.approve_all_button)

        splitter.addWidget(batch_widget)

        # Results review area
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_layout.addWidget(QLabel("Review suggestions:"))
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels(["Custom ID", "Suggestion", "Decision"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        results_layout.addWidget(self.results_table)

        # Individual action buttons
        button_layout = QHBoxLayout()
        self.keep_button = QPushButton("Keep")
        self.keep_button.clicked.connect(lambda: self.make_decision("KEEP"))
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(lambda: self.make_decision("DELETE"))
        button_layout.addWidget(self.keep_button)
        button_layout.addWidget(self.delete_button)
        results_layout.addLayout(button_layout)

        splitter.addWidget(results_widget)

        # Load batch files
        self.load_batch_files()

    def setup_file_watcher(self):
        self.file_watcher = QFileSystemWatcher(self)
        self.file_watcher.addPath("completed_results")
        self.file_watcher.directoryChanged.connect(self.refresh_batch_files)

    def refresh_batch_files(self):
        self.batch_table.setRowCount(0)  # Clear existing rows
        self.load_batch_files()
        if self.current_batch_id:
            self.load_batch_results(self.current_batch_id)

    def load_batch_files(self):
        results_dir = "completed_results"
        try:
            for filename in os.listdir(results_dir):
                if filename.endswith(".jsonl"):
                    batch_id = filename.split("_")[-1].split(".")[0]
                    timestamp = os.path.getmtime(os.path.join(results_dir, filename))
                    self.add_batch_to_table(batch_id, timestamp)
        except FileNotFoundError:
            print(f"Directory not found: {results_dir}")

    def add_batch_to_table(self, batch_id, timestamp):
        row_position = self.batch_table.rowCount()
        self.batch_table.insertRow(row_position)
        self.batch_table.setItem(row_position, 0, QTableWidgetItem(batch_id))
        self.batch_table.setItem(row_position, 1, QTableWidgetItem(str(timestamp)))

    def load_batch_results(self, item):
        if isinstance(item, QTableWidgetItem):
            self.current_batch_id = item.text()
        else:
            self.current_batch_id = item
        file_path = f"completed_results/completed_batch_{self.current_batch_id}.jsonl"
        self.results_table.setRowCount(0)  # Clear previous results
        try:
            with open(file_path, 'r') as file:
                for line in file:
                    data = json.loads(line)
                    custom_id = data.get('custom_id', '')
                    content = data.get('response', {}).get('body', {}).get('choices', [{}])[0].get('message', {}).get('content', '')
                    self.add_result_to_table(custom_id, content)
        except FileNotFoundError:
            print(f"File not found: {file_path}")
        except json.JSONDecodeError:
            print(f"Invalid JSON in file: {file_path}")

    def add_result_to_table(self, custom_id, content):
        row_position = self.results_table.rowCount()
        self.results_table.insertRow(row_position)
        self.results_table.setItem(row_position, 0, QTableWidgetItem(custom_id))
        self.results_table.setItem(row_position, 1, QTableWidgetItem(content))
        self.results_table.setItem(row_position, 2, QTableWidgetItem(""))

    def approve_all(self):
        if self.current_batch_id:
            for row in range(self.results_table.rowCount()):
                custom_id = self.results_table.item(row, 0).text()
                content = self.results_table.item(row, 1).text()
                suggestion = content  # The suggestion is the content itself
                self.apply_decision(row, suggestion)
            self.batch_decision_made.emit(self.current_batch_id, "APPROVE")

    def apply_decision(self, row, decision):
        custom_id = self.results_table.item(row, 0).text()
        content = self.results_table.item(row, 1).text()
        self.results_table.setItem(row, 2, QTableWidgetItem(decision))
        self.results_table.item(row, 2).setBackground(QColor('lightgreen' if decision == "KEEP" else 'lightcoral'))
        self.decision_made.emit(custom_id, content, decision)

    def make_decision(self, decision):
        current_row = self.results_table.currentRow()
        if current_row >= 0:
            self.apply_decision(current_row, decision)
