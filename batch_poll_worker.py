import asyncio
from PyQt6.QtCore import QObject, pyqtSignal

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