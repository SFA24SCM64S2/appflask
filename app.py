import os
import json
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, make_response, render_template
from flask_cors import CORS
import pandas as pd

# Initialize Flask app
app = Flask(__name__)
# Handles CORS (cross-origin resource sharing)
CORS(app)

# Add response headers to accept all types of requests
def build_preflight_response():
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type")
    response.headers.add("Access-Control-Allow-Methods", "PUT, GET, POST, DELETE, OPTIONS")
    return response

# Modify response headers when returning to the origin
def build_actual_response(response):
    response.headers.set("Access-Control-Allow-Origin", "*")
    response.headers.set("Access-Control-Allow-Methods", "PUT, GET, POST, DELETE, OPTIONS")
    return response

# Function to subtract months from a given datetime
def subtract_months(dt, months):
    year, month = dt.year, dt.month
    for _ in range(months):
        month -= 1
        if month < 1:
            month = 12
            year -= 1
    return dt.replace(year=year, month=month, day=1)

# List of repositories to query
repositories = [
    "langchain-ai/langchain",
    "langchain-ai/langgraph",
    "microsoft/autogen",
    "openai/openai-cookbook",
    "elastic/elasticsearch",
    "milvus-io/pymilvus"
]

# Fetch issues from GitHub API
def fetch_repo_issues(repo_name, since, until, token, issue_state):
    headers = {"Authorization": f"token {token}"}
    all_issues = []
    page = 1
    per_page = 100
    retries = 0  # For exponential backoff in case of secondary rate limit

    while True:
        query = f"repo:{repo_name} type:issue state:{issue_state} created:{since}..{until}&per_page={per_page}&page={page}"
        search_issues_url = f"https://api.github.com/search/issues?q={query}"
        response = requests.get(search_issues_url, headers=headers)

        if response.status_code in [403, 429]:  # Rate limit exceeded
            if 'retry-after' in response.headers:
                sleep_duration = int(response.headers['retry-after'])
            else:
                sleep_duration = int(response.headers.get('x-ratelimit-reset', time.time())) - time.time()
                sleep_duration = max(sleep_duration, 60)  # At least 60 seconds
            time.sleep(sleep_duration)
            retries += 1
            if retries > 5:  # Max retries exceeded
                break
            continue

        if response.status_code != 200:
            break

        page_issues = response.json().get('items', [])
        if not page_issues:
            break

        all_issues.extend(page_issues)
        page += 1
        retries = 0  # Reset retries after a successful request

    return all_issues

# Fetch repository details from GitHub API
def fetch_repo_details(repo_name, token):
    headers = {"Authorization": f"token {token}"}
    repo_url = f"https://api.github.com/repos/{repo_name}"
    response = requests.get(repo_url, headers=headers)
    return response.json() if response.status_code == 200 else {}

# Route to fetch processed repository data
@app.route('/api/repo_data', methods=['GET'])
def get_processed_repo_data():
    current_datetime = datetime.now()
    since = subtract_months(current_datetime, 2).isoformat()
    until = current_datetime.isoformat()
    token = os.getenv('AUTH_TOKEN', 'your-token-here')  # Use your GitHub token

    all_repo_data = {}
    for repo in repositories:
        created_issues = fetch_repo_issues(repo, since, until, token, 'open')
        closed_issues = fetch_repo_issues(repo, since, until, token, 'closed')
        repo_details = fetch_repo_details(repo, token)

        # Process the issues
        created_issues_df = pd.DataFrame(created_issues)
        closed_issues_df = pd.DataFrame(closed_issues)

        def format_date(date):
            return datetime.strptime(date, '%Y-%m').strftime('%B %Y')

        # Monthly stats for created issues
        if not created_issues_df.empty:
            created_issues_df['created_at'] = pd.to_datetime(created_issues_df['created_at']).dt.to_period('M').astype(str)
            created_issues_df['created_at'] = created_issues_df['created_at'].apply(format_date)
            monthly_created_issues = created_issues_df['created_at'].value_counts().to_dict()
        else:
            monthly_created_issues = {}

        # Monthly stats for closed issues
        if not closed_issues_df.empty:
            closed_issues_df['closed_at'] = pd.to_datetime(closed_issues_df['closed_at']).dt.to_period('M').astype(str)
            closed_issues_df['closed_at'] = closed_issues_df['closed_at'].apply(format_date)
            monthly_closed_issues = closed_issues_df['closed_at'].value_counts().to_dict()
        else:
            monthly_closed_issues = {}

        all_repo_data[repo] = {
            "monthly_created_issues": monthly_created_issues,
            "monthly_closed_issues": monthly_closed_issues,
            "total_created_issues": len(created_issues_df),
            "total_closed_issues": len(closed_issues_df),
            "total_stars": repo_details.get("stargazers_count", 0),
            "total_forks": repo_details.get("forks_count", 0)
        }

    return jsonify(all_repo_data)

# Home route to render an HTML template
@app.route('/')
def home():
    return render_template('index.html')

# Run flask app server on port 5000
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
