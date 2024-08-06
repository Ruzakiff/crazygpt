import os
import asyncio
from PyQt6.QtCore import QThread, pyqtSignal

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