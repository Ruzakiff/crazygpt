import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from mock_server import app, tokens, batch_jobs

class TestMockServerIntegration(unittest.TestCase):

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    @patch('mock_server.datetime')
    def test_full_workflow(self, mock_datetime):
        base_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_datetime.now.return_value = base_time
        mock_datetime.fromtimestamp.side_effect = lambda x: datetime.fromtimestamp(x)

        # Step 1: Purchase tokens
        response = self.app.post('/purchase_tokens', json={'amount': 1000})
        self.assertEqual(response.status_code, 200)
        user_token = response.json['user_token']

        # Step 2: Check balance
        response = self.app.post('/check_balance', json={'user_token': user_token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['balance'], 1000)

        # Step 3: Upload files and create a batch
        file_paths = ['file1.txt', 'file2.txt', 'file3.txt']
        response = self.app.post('/upload', 
                                 headers={'User-Token': user_token},
                                 json={'file_paths': file_paths})
        self.assertEqual(response.status_code, 202)
        batch_id = response.json['batches'][0]['batch_id']
        self.assertEqual(response.json['status'], 'validating')
        self.assertEqual(response.json['remaining_balance'], 997)

        # Step 4: Check batch status (validating)
        response = self.app.get(f'/batches/{batch_id}', headers={'User-Token': user_token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'validating')

        # Step 5: Wait for batch to be in progress
        mock_datetime.now.return_value = base_time + timedelta(seconds=15)
        response = self.app.get(f'/batches/{batch_id}', headers={'User-Token': user_token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'in_progress')

        # Step 6: Wait for batch to complete
        mock_datetime.now.return_value = base_time + timedelta(seconds=35)
        response = self.app.get(f'/batches/{batch_id}', headers={'User-Token': user_token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'completed')
        self.assertIsNotNone(response.json['decisions'])
        self.assertEqual(len(response.json['decisions']), 3)

        # Step 7: Verify final balance
        response = self.app.post('/check_balance', json={'user_token': user_token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['balance'], 994)  # 1000 - 3 (initial) - 3 (final)

        # Step 8: Attempt to use an expired token
        mock_datetime.now.return_value = base_time + timedelta(hours=25)  # 25 hours later
        response = self.app.post('/upload', 
                                 headers={'User-Token': user_token},
                                 json={'file_paths': ['file4.txt']})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Invalid or expired token', response.json['error'])

    def test_multiple_batches(self):
        response = self.app.post('/purchase_tokens', json={'amount': 1000000})
        self.assertEqual(response.status_code, 200)
        user_token = response.json['user_token']

        # Test creating multiple batches due to request limit
        large_file_list = [f'file{i}.txt' for i in range(60000)]
        response = self.app.post('/upload', 
                                 headers={'User-Token': user_token},
                                 json={'file_paths': large_file_list})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json['total_files_processed'], 60000)
        self.assertEqual(response.json['num_batches_created'], 2)
        self.assertEqual(len(response.json['batches']), 2)
        self.assertEqual(response.json['batches'][0]['num_files'], 50000)
        self.assertEqual(response.json['batches'][1]['num_files'], 10000)

        # Test creating multiple batches due to file size limit (simulated)
        very_large_file_list = [f'large_file{i}.txt' for i in range(150000)]  # Simulates >100 MB
        response = self.app.post('/upload', 
                                 headers={'User-Token': user_token},
                                 json={'file_paths': very_large_file_list})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json['total_files_processed'], 150000)
        self.assertEqual(response.json['num_batches_created'], 3)
        self.assertEqual(len(response.json['batches']), 3)

        self.assertIn('Successfully created', response.json['message'])
        self.assertIn('batch(es) to process all files', response.json['message'])

    def test_rate_limiting(self):
        response = self.app.post('/purchase_tokens', json={'amount': 1000})
        self.assertEqual(response.status_code, 200)
        user_token = response.json['user_token']

        # Make 5 requests (should succeed)
        for _ in range(5):
            response = self.app.post('/upload', 
                                     headers={'User-Token': user_token},
                                     json={'file_paths': ['file.txt']})
            self.assertEqual(response.status_code, 202)

        # 6th request should be rate limited
        response = self.app.post('/upload', 
                                 headers={'User-Token': user_token},
                                 json={'file_paths': ['file.txt']})
        self.assertEqual(response.status_code, 429)
        self.assertIn('Rate limit exceeded', response.json['error'])

    def test_insufficient_balance(self):
        response = self.app.post('/purchase_tokens', json={'amount': 5})
        self.assertEqual(response.status_code, 200)
        user_token = response.json['user_token']

        # Attempt to upload more files than the balance allows
        response = self.app.post('/upload', 
                                 headers={'User-Token': user_token},
                                 json={'file_paths': ['file1.txt', 'file2.txt', 'file3.txt', 'file4.txt', 'file5.txt', 'file6.txt']})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Insufficient balance', response.json['error'])

if __name__ == '__main__':
    unittest.main()