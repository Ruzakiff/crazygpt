from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                             QMessageBox, QInputDialog)
from PyQt6.QtCore import pyqtSignal
import requests

class TokenWidget(QWidget):
    token_updated = pyqtSignal(str)  # Signal to emit when token is updated

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server_url = "http://localhost:5000"  # Assuming the real server is running locally
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(5, 5, 5, 5)

        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Enter token")
        layout.addWidget(self.token_input)

        self.balance_label = QLabel("Balance: Unknown")
        layout.addWidget(self.balance_label)

        self.update_token_button = QPushButton("Update")
        self.update_token_button.clicked.connect(self.update_token)
        layout.addWidget(self.update_token_button)

        self.buy_button = QPushButton("Buy")
        self.buy_button.clicked.connect(self.buy_tokens)
        layout.addWidget(self.buy_button)

    def update_token(self):
        token = self.token_input.text()
        if token:
            self.token_updated.emit(token)
            self.check_balance(token)
        else:
            QMessageBox.warning(self, "Invalid Token", "Please enter a valid token.")

    def check_balance(self, token):
        try:
            response = requests.post(f"{self.server_url}/check_balance", 
                                     json={"user_token": token},
                                     headers={"User-Token": token})
            if response.status_code == 200:
                balance = response.json()["balance"]
                self.balance_label.setText(f"Balance: {balance}")
            else:
                QMessageBox.warning(self, "Balance Check Failed", f"Failed to check balance. Status code: {response.status_code}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"An error occurred: {str(e)}")

    def buy_tokens(self):
        amount, ok = QInputDialog.getInt(self, "Buy Tokens", "Enter amount:", 1, 1)
        if ok:
            try:
                amount = int(amount)
                response = requests.post(f"{self.server_url}/purchase_tokens", 
                                         json={"amount": amount})
                if response.status_code == 200:
                    new_token = response.json()["user_token"]
                    self.token_input.setText(new_token)
                    self.token_updated.emit(new_token)
                    QMessageBox.information(self, "Success", f"Successfully purchased {amount} tokens. Your new token has been set.")
                    self.check_balance(new_token)
                else:
                    QMessageBox.warning(self, "Purchase Failed", f"Failed to purchase tokens. Status code: {response.status_code}")
            except ValueError:
                QMessageBox.warning(self, "Invalid Amount", "Please enter a valid number for the amount.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"An error occurred: {str(e)}")
