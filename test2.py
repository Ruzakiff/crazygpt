import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
import time
from mock_server import app, tokens, batch_jobs, create_token, validate_token, rate_limited, create_batch_job, process_batch

class TestMockServer(unittest.TestCase):

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_root(self):
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"message": "Mock server is running"})

    def test_purchase_tokens(self):
        response = self.app.post('/purchase_tokens', json={'amount': 1000})
        self.assertEqual(response.status_code, 200)
        self.assertIn('user_token', response.json)

    def test_check_balance(self):
        token = create_token(1000)
        response = self.app.post('/check_balance', json={'user_token': token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['balance'], 1000)

    def test_upload_file(self):
        token = create_token(1000)
        response = self.app.post('/upload', 
                                 headers={'User-Token': token},
                                 json={'file_paths': ['file1.txt', 'file2.txt']})
        self.assertEqual(response.status_code, 202)
        self.assertIn('batches', response.json)
        self.assertEqual(len(response.json['batches']), 1)
        self.assertIn('batch_id', response.json['batches'][0])
        self.assertEqual(response.json['status'], 'validating')
        self.assertEqual(response.json['remaining_balance'], 998)
        self.assertEqual(response.json['total_files_processed'], 2)
        self.assertEqual(response.json['num_batches_created'], 1)

    @patch('mock_server.datetime')
    def test_get_batch_status(self, mock_datetime):
        base_time = datetime(2023, 1, 1, 12, 0, 0)
        mock_datetime.now.return_value = base_time
        mock_datetime.fromtimestamp.side_effect = lambda x: datetime.fromtimestamp(x)

        token = create_token(1000)
        batch_id, _ = create_batch_job(token, ['file1.txt', 'file2.txt'])
        
        # Test validating status
        response = self.app.get(f'/batches/{batch_id}', headers={'User-Token': token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'validating')

        # Test in_progress status
        mock_datetime.now.return_value = base_time + timedelta(seconds=15)
        response = self.app.get(f'/batches/{batch_id}', headers={'User-Token': token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'in_progress')

        # Test completed status
        mock_datetime.now.return_value = base_time + timedelta(seconds=35)
        response = self.app.get(f'/batches/{batch_id}', headers={'User-Token': token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'completed')
        self.assertIn('decisions', response.json)

    def test_set_batch_size(self):
        response = self.app.post('/set_batch_size', json={'batch_size': 500})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['message'], 'Batch size set to 500')

    def test_purchase_tier(self):
        response = self.app.post('/purchase_tier', json={'tier': 'standard'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('user_token', response.json)
        self.assertEqual(response.json['tier'], 'standard')

    def test_validate_token(self):
        token = create_token(1000)
        self.assertTrue(validate_token(token))
        
        # Test expired token
        tokens[token]['expiry'] = datetime.now() - timedelta(hours=1)
        self.assertFalse(validate_token(token))

    def test_rate_limited(self):
        token = create_token(1000)
        for _ in range(5):
            self.assertFalse(rate_limited(token))
        self.assertTrue(rate_limited(token))

    def test_purchase_tokens_invalid_amount(self):
        response = self.app.post('/purchase_tokens', json={'amount': -100})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json)

    def test_check_balance_invalid_token(self):
        response = self.app.post('/check_balance', json={'user_token': 'invalid_token'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json)

    def test_upload_file_insufficient_balance(self):
        token = create_token(1)
        response = self.app.post('/upload', 
                                 headers={'User-Token': token},
                                 json={'file_paths': ['file1.txt', 'file2.txt']})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json)

    def test_get_batch_status_invalid_batch(self):
        token = create_token(1000)
        response = self.app.get('/batches/invalid_batch_id', headers={'User-Token': token})
        self.assertEqual(response.status_code, 404)
        self.assertIn('error', response.json)

    def test_set_batch_size_invalid_size(self):
        response = self.app.post('/set_batch_size', json={'batch_size': -1})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json)

    def test_purchase_tier_invalid_tier(self):
        response = self.app.post('/purchase_tier', json={'tier': 'invalid_tier'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json)

    @patch('mock_server.datetime')
    def test_token_expiration(self, mock_datetime):
        base_time = datetime.now()
        mock_datetime.now.return_value = base_time
        token = create_token(1000)
        
        # Check valid token
        self.assertTrue(validate_token(token))
        
        # Check expired token
        mock_datetime.now.return_value = base_time + timedelta(hours=25)
        self.assertFalse(validate_token(token))

    @patch('mock_server.time.time')
    def test_rate_limit_reset(self, mock_time):
        base_time = 1000000  # Use a fixed integer value
        mock_time.return_value = base_time
        token = create_token(1000)
        
        # Use up the rate limit
        for _ in range(5):
            self.assertFalse(rate_limited(token))
        self.assertTrue(rate_limited(token))
        
        # Simulate waiting for rate limit to reset
        mock_time.return_value = base_time + 60
        
        # Should be able to make a request again
        self.assertFalse(rate_limited(token))

    @patch('mock_server.time.time')
    def test_batch_processing_performance(self, mock_time):
        base_time = int(time.time())
        mock_time.return_value = base_time
        token = create_token(1000)
        
        start_time = time.time()
        batch_id, _ = create_batch_job(token, ['file1.txt'] * 1000)
        end_time = time.time()
        
        self.assertLess(end_time - start_time, 1.0)  # Assert that batch creation takes less than 1 second

    @patch('mock_server.time.time')
    def test_concurrent_requests(self, mock_time):
        base_time = 1000000  # Use a fixed integer value
        mock_time.return_value = base_time
        token = create_token(1000)
        
        import threading
        def make_request():
            response = self.app.post('/upload', headers={'User-Token': token}, json={'file_paths': ['file1.txt']})
            if response.status_code == 429:
                # If rate limited, wait and try again
                mock_time.return_value += 60
                response = self.app.post('/upload', headers={'User-Token': token}, json={'file_paths': ['file1.txt']})
            self.assertEqual(response.status_code, 202)

        threads = [threading.Thread(target=make_request) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Check that all requests were processed
        self.assertEqual(tokens[token]['amount'], 990)

if __name__ == '__main__':
    unittest.main()