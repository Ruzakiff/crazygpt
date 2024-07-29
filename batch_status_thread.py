from PyQt6.QtCore import QThread, pyqtSignal

class BatchStatusThread(QThread):
    update_signal = pyqtSignal(list)

    def __init__(self, client):
        super().__init__()
        self.client = client

    def run(self):
        batch_jobs = self.client.get_batch_jobs()
        self.update_signal.emit(batch_jobs)