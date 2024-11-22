
# Import all the required packages 
import os
from flask import Flask, jsonify, request, make_response, Response
from flask_cors import CORS
import json
from dateutil.relativedelta import relativedelta
from dateutil import *
from datetime import datetime, date  # Corrected import
import pandas as pd
import requests
import time

# Initilize flask app
app = Flask(__name__)
# Handles CORS (cross-origin resource sharing)
CORS(app)

# Add response headers to accept all types of  requests
def build_preflight_response():
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type")
    response.headers.add("Access-Control-Allow-Methods",
                         "PUT, GET, POST, DELETE, OPTIONS")
    return response

# Modify response headers when returning to the origin
def build_actual_response(response):
    response.headers.set("Access-Control-Allow-Origin", "*")
    response.headers.set("Access-Control-Allow-Methods",
                         "PUT, GET, POST, DELETE, OPTIONS")
    return response

 # Add your own GitHub Token to run it local
token = os.environ.get('AUTH_TOKEN', 'your GitHub Token')
'''
API route path is  "/api/forecast"
This API will accept only POST request
'''
GITHUB_API_URL = "https://api.github.com"
GITHUB_SEARCH_API_URL = "https://api.github.com/search/issues"

def subtract_months(dt, months):
    year, month = dt.year, dt.month
    for _ in range(months):
        month -= 1
        if month < 1:
            month = 12
            year -= 1
    return dt.replace(year=year, month=month, day=1)

# List of repositories
repositories = [
    "langchain-ai/langchain",
    "langchain-ai/langgraph",
    "microsoft/autogen",
    "openai/openai-cookbook",
    "elastic/elasticsearch",
    "milvus-io/pymilvus"
]

def fetch_repo_issues(repo_name, since, until, token, issue_state):
    headers = {"Authorization": f"token {token}"}
    all_issues = []
    page = 1
    per_page = 100
    retries = 0  # For exponential backoff in case of secondary rate limit

    while True:
        query = f"repo:{repo_name} type:issue state:{issue_state} created:{since}..{until}&per_page={per_page}&page={page}"
        search_issues_url = f"{GITHUB_SEARCH_API_URL}?q={query}"
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

def fetch_repo_details(repo_name, token):
    headers = {"Authorization": f"token {token}"}
    repo_url = f"{GITHUB_API_URL}/repos/{repo_name}"
    response = requests.get(repo_url, headers=headers)
    return response.json() if response.status_code == 200 else {}


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

        # Function to format date from YYYY-MM to 'Month YYYY'
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

        # Total and weekly stats for created issues
        if not created_issues_df.empty:
            created_issues_df['created_at'] = pd.to_datetime(created_issues_df['created_at']).dt.to_period('W').astype(str)
            weekly_created_issues = created_issues_df['created_at'].value_counts().to_dict()
            total_created_issues = len(created_issues_df)
        else:
            weekly_created_issues = {}
            total_created_issues = 0

        # Total and weekly stats for closed issues
        if not closed_issues_df.empty:
            closed_issues_df['closed_at'] = pd.to_datetime(closed_issues_df['closed_at']).dt.to_period('W').astype(str)
            weekly_closed_issues = closed_issues_df['closed_at'].value_counts().to_dict()
            total_closed_issues = len(closed_issues_df)
        else:
            weekly_closed_issues = {}
            total_closed_issues = 0

        all_repo_data[repo] = {
            "monthly_created_issues": monthly_created_issues,
            "monthly_closed_issues": monthly_closed_issues,
            "total_created_issues": total_created_issues,
            "weekly_created_issues": weekly_created_issues,
            "total_closed_issues": total_closed_issues,
            "weekly_closed_issues": weekly_closed_issues,
            "total_stars": repo_details.get("stargazers_count", 0),
            "total_forks": repo_details.get("forks_count", 0)
        }

    return jsonify(all_repo_data)

def fetch_repo_data(repo_name, endpoint, token, params=None):
    headers = {"Authorization": f"token {token}"}
    url = f"{GITHUB_API_URL}/repos/{repo_name}/{endpoint}"
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else []

@app.route('/api/full_repo_data/<path:repo_name>', methods=['GET'])
def get_full_repo_data(repo_name):
    token = os.getenv('AUTH_TOKEN', 'your-token-here')  # Use your GitHub token
    data = {
        'issues_open': fetch_repo_data(repo_name, 'issues', token, {'state': 'open'}),
        'issues_closed': fetch_repo_data(repo_name, 'issues', token, {'state': 'closed'}),
        'pulls': fetch_repo_data(repo_name, 'pulls', token),
        'commits': fetch_repo_data(repo_name, 'commits', token),
        'branches': fetch_repo_data(repo_name, 'branches', token),
        'contributors': fetch_repo_data(repo_name, 'contributors', token),
        'releases': fetch_repo_data(repo_name, 'releases', token)
    }

    return jsonify(data)
@app.route('/api/github/<path:repo_name>', methods=['GET'])
def github():
    body = request.get_json()
    repo_name = body['repository']
    headers = {"Authorization": f"token {token}"}

    # Dates for the past 12 months
    today = datetime.today()
    last_year = today - timedelta(days=365)

    # Pagination
    per_page = 100
    page = 1

    all_issues = []
    while True:
        search_query = f"repo:{repo_name} type:issue created:{last_year.isoformat()}..{today.isoformat()}&per_page={per_page}&page={page}"
        query_url = f"{GITHUB_API_URL}/search/issues?q={search_query}"
        response = requests.get(query_url, headers=headers)
        
        if response.status_code != 200:
            # Error handling
            break

        issues = response.json().get('items', [])
        all_issues.extend(issues)

        if len(issues) < per_page:
            break
        page += 1

    # Process the issues
    issues_response = []
    for issue in all_issues:
        issue_data = {
            'issue_number': issue['number'],
            'created_at': issue['created_at'][0:10],
            'closed_at': issue['closed_at'][0:10] if issue['closed_at'] else None,
            'labels': [label['name'] for label in issue['labels']],
            'state': issue['state'],
            'author': issue['user']['login']
        }
        issues_response.append(issue_data)

    # Convert to DataFrame for further processing
    df = pd.DataFrame(issues_response)

    # Daily Created Issues
    df_created_at = df.groupby(['created_at'], as_index=False).count()
    dataFrameCreated = df_created_at[['created_at', 'issue_number']]
    dataFrameCreated.columns = ['date', 'count']

    '''
    Monthly Created Issues
    Format the data by grouping the data by month
    ''' 
    created_at = df['created_at']
    month_issue_created = pd.to_datetime(
        pd.Series(created_at), format='%Y-%m-%d')
    month_issue_created.index = month_issue_created.dt.to_period('m')
    month_issue_created = month_issue_created.groupby(level=0).size()
    month_issue_created = month_issue_created.reindex(pd.period_range(
        month_issue_created.index.min(), month_issue_created.index.max(), freq='m'), fill_value=0)
    month_issue_created_dict = month_issue_created.to_dict()
    created_at_issues = []
    for key in month_issue_created_dict.keys():
        array = [str(key), month_issue_created_dict[key]]
        created_at_issues.append(array)

    '''
    Monthly Closed Issues
    Format the data by grouping the data by month
    ''' 
    
    closed_at = df['closed_at'].sort_values(ascending=True)
    month_issue_closed = pd.to_datetime(
        pd.Series(closed_at), format='%Y-%m-%d')
    month_issue_closed.index = month_issue_closed.dt.to_period('m')
    month_issue_closed = month_issue_closed.groupby(level=0).size()
    month_issue_closed = month_issue_closed.reindex(pd.period_range(
        month_issue_closed.index.min(), month_issue_closed.index.max(), freq='m'), fill_value=0)
    month_issue_closed_dict = month_issue_closed.to_dict()
    closed_at_issues = []
    for key in month_issue_closed_dict.keys():
        array = [str(key), month_issue_closed_dict[key]]
        closed_at_issues.append(array)

    '''
        1. Hit LSTM Microservice by passing issues_response as body
        2. LSTM Microservice will give a list of string containing image paths hosted on google cloud storage
        3. On recieving a valid response from LSTM Microservice, append the above json_response with the response from
            LSTM microservice
    '''
    created_at_body = {
        "issues": issues_reponse,
        "type": "created_at",
        "repo": repo_name.split("/")[1]
    }
    closed_at_body = {
        "issues": issues_reponse,
        "type": "closed_at",
        "repo": repo_name.split("/")[1]
    }
    LSTM_API_URL_BASE = os.environ.get('LSTM_API_URL', 'your LSTM API URL')
    # Update your Google cloud deployed LSTM app URL (NOTE: DO NOT REMOVE "/")
    LSTM_API_URL = LSTM_API_URL_BASE + "/api/forecast"

    '''
    Trigger the LSTM microservice to forecasted the created issues
    The request body consists of created issues obtained from GitHub API in JSON format
    The response body consists of Google cloud storage path of the images generated by LSTM microservice
    '''
    created_at_response = requests.post(LSTM_API_URL,
                                        json=created_at_body,
                                        headers={'content-type': 'application/json'})
    
    '''
    Trigger the LSTM microservice to forecasted the closed issues
    The request body consists of closed issues obtained from GitHub API in JSON format
    The response body consists of Google cloud storage path of the images generated by LSTM microservice
    '''    
    closed_at_response = requests.post(LSTM_API_URL,
                                       json=closed_at_body,
                                       headers={'content-type': 'application/json'})
    
    '''
    Create the final response that consists of:
        1. GitHub repository data obtained from GitHub API
        2. Google cloud image urls of created and closed issues obtained from LSTM microservice
    '''
    json_response = {
        "created": created_at_issues,
        "closed": closed_at_issues,
        "starCount": repository["stargazers_count"],
        "forkCount": repository["forks_count"],
        "createdAtImageUrls": {
            **created_at_response.json(),
        },
        "closedAtImageUrls": {
            **closed_at_response.json(),
        },
    }
    # Return the response back to client (React app)
    return jsonify(json_response)
@app.route('/api/repo_stats/<path:repo_name>', methods=['GET'])
def get_repo_stats(repo_name):
    # The existing token and header setup
    token = os.getenv('AUTH_TOKEN', 'your-token-here')
    
    headers = {"Authorization": f"token {token}"}

    # Fetch issues for the past year
    current_datetime = datetime.now()
    since = subtract_months(current_datetime, 12).isoformat()
    until = current_datetime.isoformat()

    # Fetch open and closed issues
    created_issues = fetch_repo_issues(repo_name, since, until, token, 'open')
    closed_issues = fetch_repo_issues(repo_name, since, until, token, 'closed')

    # Convert to DataFrames
    created_issues_df = pd.DataFrame(created_issues)
    closed_issues_df = pd.DataFrame(closed_issues)

    # Add a column for day of the week and month
    if not created_issues_df.empty:
        created_issues_df['day_of_week'] = pd.to_datetime(created_issues_df['created_at']).dt.day_name()
        created_issues_df['month'] = pd.to_datetime(created_issues_df['created_at']).dt.month_name()

    if not closed_issues_df.empty:
        closed_issues_df['day_of_week'] = pd.to_datetime(closed_issues_df['closed_at']).dt.day_name()
        closed_issues_df['month'] = pd.to_datetime(closed_issues_df['closed_at']).dt.month_name()

    # Calculate the stats
    max_created_day = created_issues_df['day_of_week'].mode()[0] if not created_issues_df.empty else None
    max_closed_day = closed_issues_df['day_of_week'].mode()[0] if not closed_issues_df.empty else None
    max_closed_month = closed_issues_df['month'].mode()[0] if not closed_issues_df.empty else None

    # Prepare the JSON response
    stats = {
        'max_created_day': max_created_day,
        'max_closed_day': max_closed_day,
        'max_closed_month': max_closed_month
    }

    return jsonify(stats)



# Run flask app server on port 5000
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
