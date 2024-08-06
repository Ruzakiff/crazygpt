from PyQt6.QtCore import QObject, pyqtSignal
import time

class BatchPollWorker(QObject):
    update_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, client):
        super().__init__()
        self.client = client

    def run(self):
        while True:
            try:
                batch_jobs = self.client.get_batch_jobs()
                if batch_jobs is None:
                    self.error_signal.emit("Failed to get batch jobs. Token may be invalid.")
                else:
                    incomplete_jobs = [job for job in batch_jobs if job['status'] != 'completed']
                    for job in incomplete_jobs:
                        self.update_signal.emit(f"Polling job {job['id']}")
                        result = self.client.poll_batch_job(job['id'])
                        if result:
                            self.update_signal.emit(f"Job {job['id']} completed")
                        else:
                            self.update_signal.emit(f"Job {job['id']} still in progress")
            except Exception as e:
                self.error_signal.emit(f"Error in batch poll: {str(e)}")

            time.sleep(60)  # Poll every 60 seconds

        self.finished_signal.emit()