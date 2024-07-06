from flask import Flask, request, jsonify
from flask_uploads import UploadSet, configure_uploads, ALL
import os
import stripe
import secrets
import requests
import time
from datetime import datetime, timedelta

app = Flask(__name__)

# Configure Stripe
stripe.api_key = 'your_stripe_secret_key'

# Configure the upload set
files = UploadSet('files', ALL)
app.config['UPLOADED_FILES_DEST'] = 'uploads'
configure_uploads(app, files)

# In-memory storage for tokens and usage (in a real application, use a database)
tokens = {}
rate_limits = {}
api_url = 'http://your-deletion-api-endpoint'

# Helper Functions
def generate_token():
    return secrets.token_urlsafe(32)

def create_token(amount):
    user_token = generate_token()
    tokens[user_token] = {'amount': amount, 'used': 0, 'expiry': datetime.now() + timedelta(hours=24)}
    return user_token

def validate_token(token):
    if token in tokens:
        if datetime.now() < tokens[token]['expiry']:
            return tokens[token]['amount'] > 0
        else:
            del tokens[token]
    return False

def rate_limited(token):
    current_time = time.time()
    if token not in rate_limits:
        rate_limits[token] = current_time
        return False
    if current_time - rate_limits[token] < 60:
        return True
    rate_limits[token] = current_time
    return False

# Endpoints
@app.route('/purchase_tokens', methods=['POST'])
def purchase_tokens():
    data = request.json
    amount = data.get('amount')
    token = data.get('stripe_token')
    
    try:
        charge = stripe.Charge.create(
            amount=amount,
            currency='usd',
            source=token,
            description='File management service tokens'
        )
        user_token = create_token(amount / 2.5)  # $2.50 per 1000 photos/images
        return jsonify({'user_token': user_token}), 200
    except stripe.error.StripeError as e:
        return jsonify({'error': str(e)}), 400

@app.route('/check_balance', methods=['POST'])
def check_balance():
    data = request.json
    user_token = data.get('user_token')
    if user_token in tokens:
        return jsonify({'balance': tokens[user_token]['amount']}), 200
    else:
        return jsonify({'error': 'Invalid token'}), 400

@app.route('/upload', methods=['POST'])
def upload_file():
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token) or rate_limited(user_token):
        return jsonify({'error': 'Invalid or expired token, or rate limit exceeded'}), 400

    if 'files' in request.files:
        uploaded_files = request.files.getlist('files')
        file_paths = []
        for file in uploaded_files:
            filename = files.save(file)
            file_paths.append(filename)
        # Process each file through the API
        decisions = []
        for file_path in file_paths:
            with open(os.path.join(app.config['UPLOADED_FILES_DEST'], file_path), 'rb') as f:
                response = requests.post(api_url, files={'file': f})
                decision = response.json().get('decision')
                decisions.append({'file': file_path, 'decision': decision})
                if decision == 'delete':
                    os.remove(os.path.join(app.config['UPLOADED_FILES_DEST'], file_path))
        # Deduct usage (assume each API call costs 1 unit)
        tokens[user_token]['amount'] -= len(file_paths)
        return jsonify({'decisions': decisions, 'remaining_balance': tokens[user_token]['amount']}), 200
    else:
        return jsonify({'error': 'No files found'}), 400

@app.route('/delete_files', methods=['POST'])
def delete_files():
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token) or rate_limited(user_token):
        return jsonify({'error': 'Invalid or expired token, or rate limit exceeded'}), 400

    data = request.json
    file_paths = data.get('file_paths', [])
    deleted_files = []
    for file_path in file_paths:
        full_path = os.path.join(app.config['UPLOADED_FILES_DEST'], file_path)
        if os.path.exists(full_path):
            os.remove(full_path)
            deleted_files.append(file_path)
    # Deduct usage (assume each deletion costs 0.5 units)
    tokens[user_token]['amount'] -= 0.5 * len(deleted_files)
    return jsonify({'deleted_files': deleted_files, 'remaining_balance': tokens[user_token]['amount']}), 200

@app.route('/purchase_tier', methods=['POST'])
def purchase_tier():
    data = request.json
    tier = data.get('tier')
    token = data.get('stripe_token')
    
    tier_pricing = {
        'basic': 1250,  # $12.50
        'standard': 2500,  # $25.00
        'premium': 5000,  # $50.00
    }
    if tier not in tier_pricing:
        return jsonify({'error': 'Invalid tier selected'}), 400
    
    amount = tier_pricing[tier]
    
    try:
        charge = stripe.Charge.create(
            amount=amount,
            currency='usd',
            source=token,
            description=f'File management service {tier} tier'
        )
        user_token = create_token(amount / 2.5)  # $2.50 per 1000 photos/images
        return jsonify({'user_token': user_token, 'tier': tier}), 200
    except stripe.error.StripeError as e:
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True)
