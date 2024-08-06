from PyQt6.QtCore import QThread, pyqtSignal

class BatchStatusThread(QThread):
    update_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, client):
        super().__init__()
        self.client = client

    def run(self):
        try:
            batch_jobs = self.client.get_batch_jobs()
            if batch_jobs is None:
                self.error_signal.emit("Failed to get batch jobs. Token may be invalid.")
            else:
                self.update_signal.emit(batch_jobs)
        except Exception as e:
            self.error_signal.emit(f"Error fetching batch status: {str(e)}")