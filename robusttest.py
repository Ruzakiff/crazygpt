import unittest
import json
import os
import tempfile
import time
from flask_testing import TestCase
from real_server import app, init_db, db_delete_token, db_delete_batch_job
import sqlite3
import requests
from unittest.mock import patch, MagicMock
import concurrent.futures

class RealServerTestCase(TestCase):
    def create_app(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        return app

    def setUp(self):
        self.db_fd, app.config['DATABASE'] = tempfile.mkstemp()
        self.app = app.test_client()
        init_db()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(app.config['DATABASE'])

    def test_root_endpoint(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"message": "Real server is running"})

    def test_purchase_tokens(self):
        response = self.client.post('/purchase_tokens', json={'amount': 1000})
        self.assertEqual(response.status_code, 200)
        self.assertIn('user_token', response.json)

    def test_purchase_tokens_invalid_amount(self):
        response = self.client.post('/purchase_tokens', json={'amount': -100})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json)

    def test_check_balance(self):
        # First, purchase tokens
        purchase_response = self.client.post('/purchase_tokens', json={'amount': 1000})
        user_token = purchase_response.json['user_token']

        # Then, check balance
        response = self.client.post('/check_balance', json={'user_token': user_token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['balance'], 1000)

    def test_check_balance_invalid_token(self):
        response = self.client.post('/check_balance', json={'user_token': 'invalid_token'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json)

    def test_upload_jsonl(self):
        # First, purchase tokens
        purchase_response = self.client.post('/purchase_tokens', json={'amount': 1000})
        user_token = purchase_response.json['user_token']

        # Create a test JSONL file
        test_jsonl = tempfile.NamedTemporaryFile(mode='w+', suffix='.jsonl', delete=False)
        test_jsonl.write('{"test": "data"}\n')
        test_jsonl.close()

        # Mock the OpenAI API calls
        with patch('real_server.upload_file_to_openai') as mock_upload, \
             patch('real_server.create_openai_batch') as mock_create_batch:
            
            mock_upload.return_value = {'id': 'test_file_id'}
            mock_create_batch.return_value = {'id': 'test_batch_id', 'status': 'processing'}

            with open(test_jsonl.name, 'rb') as f:
                response = self.client.post('/upload_jsonl', 
                                            data={'file': (f, 'test.jsonl')},
                                            headers={'User-Token': user_token},
                                            content_type='multipart/form-data')

        self.assertEqual(response.status_code, 202)
        self.assertIn('batch_id', response.json)
        self.assertIn('status', response.json)
        self.assertIn('remaining_balance', response.json)

        # Clean up
        os.unlink(test_jsonl.name)

    def test_upload_jsonl_invalid_token(self):
        test_jsonl = tempfile.NamedTemporaryFile(mode='w+', suffix='.jsonl', delete=False)
        test_jsonl.write('{"test": "data"}\n')
        test_jsonl.close()

        with open(test_jsonl.name, 'rb') as f:
            response = self.client.post('/upload_jsonl', 
                                        data={'file': (f, 'test.jsonl')},
                                        headers={'User-Token': 'invalid_token'},
                                        content_type='multipart/form-data')

        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json)

        # Clean up
        os.unlink(test_jsonl.name)

    def test_get_batch_status(self):
        # First, purchase tokens and create a batch
        purchase_response = self.client.post('/purchase_tokens', json={'amount': 1000})
        user_token = purchase_response.json['user_token']

        # Mock batch creation
        with patch('real_server.upload_file_to_openai'), \
             patch('real_server.create_openai_batch') as mock_create_batch:
            
            mock_create_batch.return_value = {'id': 'test_batch_id', 'status': 'processing'}

            # Create a test batch
            test_jsonl = tempfile.NamedTemporaryFile(mode='w+', suffix='.jsonl', delete=False)
            test_jsonl.write('{"test": "data"}\n')
            test_jsonl.close()

            with open(test_jsonl.name, 'rb') as f:
                self.client.post('/upload_jsonl', 
                                 data={'file': (f, 'test.jsonl')},
                                 headers={'User-Token': user_token},
                                 content_type='multipart/form-data')

        # Mock OpenAI batch retrieval
        with patch('real_server.OpenAI') as mock_openai:
            mock_openai.return_value.batches.retrieve.return_value = {
                'id': 'test_batch_id',
                'status': 'completed'
            }

            response = self.client.get('/batches/test_batch_id', headers={'User-Token': user_token})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'completed')

        # Clean up
        os.unlink(test_jsonl.name)

    def test_get_batch_status_invalid_token(self):
        response = self.client.get('/batches/test_batch_id', headers={'User-Token': 'invalid_token'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json)

    def test_purchase_tier(self):
        response = self.client.post('/purchase_tier', json={'tier': 'standard'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('user_token', response.json)
        self.assertEqual(response.json['tier'], 'standard')

    def test_purchase_tier_invalid(self):
        response = self.client.post('/purchase_tier', json={'tier': 'invalid_tier'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json)

    def test_get_user_batch_jobs(self):
        # First, purchase tokens and create a batch
        purchase_response = self.client.post('/purchase_tokens', json={'amount': 1000})
        user_token = purchase_response.json['user_token']

        # Mock batch creation
        with patch('real_server.upload_file_to_openai'), \
             patch('real_server.create_openai_batch') as mock_create_batch:
            
            mock_create_batch.return_value = {'id': 'test_batch_id', 'status': 'processing'}

            # Create a test batch
            test_jsonl = tempfile.NamedTemporaryFile(mode='w+', suffix='.jsonl', delete=False)
            test_jsonl.write('{"test": "data"}\n')
            test_jsonl.close()

            with open(test_jsonl.name, 'rb') as f:
                self.client.post('/upload_jsonl', 
                                 data={'file': (f, 'test.jsonl')},
                                 headers={'User-Token': user_token},
                                 content_type='multipart/form-data')

        response = self.client.get('/user/batch_jobs', headers={'User-Token': user_token})
        self.assertEqual(response.status_code, 200)
        self.assertIn('batch_jobs', response.json)
        self.assertGreater(len(response.json['batch_jobs']), 0)

        # Clean up
        os.unlink(test_jsonl.name)

    def test_get_user_file_ids(self):
        # First, purchase tokens and create a batch
        purchase_response = self.client.post('/purchase_tokens', json={'amount': 1000})
        user_token = purchase_response.json['user_token']

        # Mock batch creation
        with patch('real_server.upload_file_to_openai'), \
             patch('real_server.create_openai_batch') as mock_create_batch:
            
            mock_create_batch.return_value = {'id': 'test_batch_id', 'status': 'processing'}

            # Create a test batch
            test_jsonl = tempfile.NamedTemporaryFile(mode='w+', suffix='.jsonl', delete=False)
            test_jsonl.write('{"test": "data"}\n')
            test_jsonl.close()

            with open(test_jsonl.name, 'rb') as f:
                self.client.post('/upload_jsonl', 
                                 data={'file': (f, 'test.jsonl')},
                                 headers={'User-Token': user_token},
                                 content_type='multipart/form-data')

        response = self.client.get('/user/file_ids', headers={'User-Token': user_token})
        self.assertEqual(response.status_code, 200)
        self.assertIn('file_ids', response.json)
        self.assertGreater(len(response.json['file_ids']), 0)

        # Clean up
        os.unlink(test_jsonl.name)

    def test_delete_batch_files(self):
        # First, purchase tokens and create a batch
        purchase_response = self.client.post('/purchase_tokens', json={'amount': 1000})
        user_token = purchase_response.json['user_token']

        # Mock batch creation
        with patch('real_server.upload_file_to_openai'), \
             patch('real_server.create_openai_batch') as mock_create_batch:
            
            mock_create_batch.return_value = {'id': 'test_batch_id', 'status': 'processing'}

            # Create a test batch
            test_jsonl = tempfile.NamedTemporaryFile(mode='w+', suffix='.jsonl', delete=False)
            test_jsonl.write('{"test": "data"}\n')
            test_jsonl.close()

            with open(test_jsonl.name, 'rb') as f:
                self.client.post('/upload_jsonl', 
                                 data={'file': (f, 'test.jsonl')},
                                 headers={'User-Token': user_token},
                                 content_type='multipart/form-data')

        # Mock file deletion
        with patch('real_server.delete_file') as mock_delete_file:
            mock_delete_file.return_value = {'deleted': True}

            response = self.client.delete('/delete_batch_files/test_batch_id', headers={'User-Token': user_token})

        self.assertEqual(response.status_code, 200)

if __name__ == '__main__':
    unittest.main()
