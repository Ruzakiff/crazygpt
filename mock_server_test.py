import requests
import time
import json
import unittest

BASE_URL = "http://localhost:5000"

def upload_file(file_content):
    try:
        files = {'file': ('input.jsonl', file_content, 'application/json')}
        data = {'purpose': 'batch'}
        response = requests.post(f"{BASE_URL}/v1/files", files=files, data=data)
        response.raise_for_status()
        return response.json()['id']
    except requests.exceptions.RequestException as e:
        print(f"Error uploading file: {e}")
        return None

def create_batch(file_id):
    try:
        data = {
            "input_file_id": file_id,
            "endpoint": "/v1/chat/completions",
            "completion_window": "24h",
            "metadata": {"description": "test batch"}
        }
        response = requests.post(f"{BASE_URL}/v1/batches", json=data)
        response.raise_for_status()
        return response.json()['id']
    except requests.exceptions.RequestException as e:
        print(f"Error creating batch: {e}")
        return None

def check_batch_status(batch_id):
    try:
        response = requests.get(f"{BASE_URL}/v1/batches/{batch_id}")
        response.raise_for_status()
        return response.json()  # Return the full batch data
    except requests.exceptions.RequestException as e:
        print(f"Error checking batch status: {e}")
        return None


def get_batch_results(file_id):
    try:
        response = requests.get(f"{BASE_URL}/v1/files/{file_id}/content")
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error getting batch results: {e}")
        return None

def test_batch_processing(num_requests=100):
    print(f"\nTesting batch processing with {num_requests} requests...")

    # Prepare input file content
    input_content = ""
    for i in range(num_requests):
        request = {
            "custom_id": f"request-{i}",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "gpt-3.5-turbo-0125",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": f"Hello world {i}!"}
                ],
                "max_tokens": 1000
            }
        }
        input_content += json.dumps(request) + "\n"

    # Step 1: Upload file
    file_id = upload_file(input_content)
    if not file_id:
        print("File upload failed. Aborting test.")
        return

    print(f"File uploaded successfully. File ID: {file_id}")

    # Step 2: Create batch
    batch_id = create_batch(file_id)
    if not batch_id:
        print("Batch creation failed. Aborting test.")
        return

    print(f"Batch created successfully. Batch ID: {batch_id}")

    # Step 3: Check batch status
    while True:
        batch_data = check_batch_status(batch_id)
        if not batch_data:
            print("Failed to retrieve batch status. Aborting test.")
            return
        
        status = batch_data['status']
        print(f"Batch status: {status}")
        if status == 'completed':
            break
        elif status in ['failed', 'expired', 'cancelled']:
            print("Batch processing failed. Aborting test.")
            return
        time.sleep(5)  # Wait 5 seconds before checking again

    # Step 4: Retrieve results
    output_file_id = batch_data.get('output_file_id')
    if not output_file_id:
        print("No output file ID found. Aborting test.")
        return

    results = get_batch_results(output_file_id)
    if results:
        print("Batch results retrieved successfully.")
        print(f"First few results: {results[:500]}...")  # Print first 500 characters
    else:
        print("Failed to retrieve batch results.")

class MockServerTests(unittest.TestCase):
    def setUp(self):
        self.headers = {"User-Token": None}

    def test_server_availability(self):
        response = requests.get(BASE_URL)
        self.assertEqual(response.status_code, 200)

    def test_purchase_tokens(self):
        response = requests.post(f"{BASE_URL}/purchase_tokens", json={"amount": 1000})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("user_token", data)
        self.headers["User-Token"] = data["user_token"]

    def test_check_balance(self):
        response = requests.post(f"{BASE_URL}/check_balance", json={"user_token": self.headers["User-Token"]})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("balance", data)
        self.assertEqual(data["balance"], 1000)

    def test_invalid_token(self):
        invalid_headers = {"User-Token": "invalid_token"}
        response = requests.post(f"{BASE_URL}/upload", headers=invalid_headers, json={"file_paths": ["test.txt"]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid or expired token", response.json()["error"])

    def test_rate_limit(self):
        for _ in range(6):  # Exceed rate limit
            requests.post(f"{BASE_URL}/upload", headers=self.headers, json={"file_paths": ["test.txt"]})
        response = requests.post(f"{BASE_URL}/upload", headers=self.headers, json={"file_paths": ["test.txt"]})
        self.assertEqual(response.status_code, 429)
        self.assertIn("Rate limit exceeded", response.json()["error"])

    def test_insufficient_balance(self):
        # Use up all tokens
        requests.post(f"{BASE_URL}/upload", headers=self.headers, json={"file_paths": ["test.txt"] * 1000})
        response = requests.post(f"{BASE_URL}/upload", headers=self.headers, json={"file_paths": ["test.txt"]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Insufficient balance", response.json()["error"])

    def test_set_batch_size(self):
        response = requests.post(f"{BASE_URL}/set_batch_size", json={"batch_size": 500})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Batch size set to 500", response.json()["message"])

    def test_invalid_batch_size(self):
        response = requests.post(f"{BASE_URL}/set_batch_size", json={"batch_size": -1})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid batch size", response.json()["error"])

    def test_purchase_tier(self):
        response = requests.post(f"{BASE_URL}/purchase_tier", json={"tier": "premium"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("user_token", data)
        self.assertEqual(data["tier"], "premium")

    def test_invalid_tier(self):
        response = requests.post(f"{BASE_URL}/purchase_tier", json={"tier": "ultra"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid tier", response.json()["error"])

    def test_batch_processing(self):
        # Create a batch with 10 requests
        file_paths = [f"test{i}.txt" for i in range(10)]
        response = requests.post(f"{BASE_URL}/upload", headers=self.headers, json={"file_paths": file_paths})
        self.assertEqual(response.status_code, 202)
        batch_id = response.json()["batch_id"]

        # Check batch status until completed
        while True:
            response = requests.get(f"{BASE_URL}/batches/{batch_id}", headers=self.headers)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            if data["status"] == "completed":
                break
            time.sleep(1)

        # Verify results
        self.assertIsNotNone(data["decisions"])
        self.assertEqual(len(data["decisions"]), 10)

    def test_unauthorized_batch_access(self):
        # Create a batch
        response = requests.post(f"{BASE_URL}/upload", headers=self.headers, json={"file_paths": ["test.txt"]})
        batch_id = response.json()["batch_id"]

        # Try to access with a different token
        new_token = requests.post(f"{BASE_URL}/purchase_tokens", json={"amount": 100}).json()["user_token"]
        response = requests.get(f"{BASE_URL}/batches/{batch_id}", headers={"User-Token": new_token})
        self.assertEqual(response.status_code, 403)
        self.assertIn("Unauthorized access to batch", response.json()["error"])

    def test_nonexistent_batch(self):
        response = requests.get(f"{BASE_URL}/batches/nonexistent", headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertIn("Batch not found", response.json()["error"])

def main():
    unittest.main()

if __name__ == "__main__":
    main()
