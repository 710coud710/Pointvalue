from flask import Flask, request, render_template, redirect, url_for, send_file
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import pandas as pd
from fuzzywuzzy import fuzz
from flask_pymongo import PyMongo
from pymongo import DESCENDING
from bson import ObjectId
from datetime import datetime, timedelta

app = Flask(__name__)

app.config["MONGO_URI"] = "mongodb://localhost:27017/thuctap"
app.secret_key = 'Hello9876541312'
mongo = PyMongo(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id):
        self.id = id
        
users = {'admin': {'password': 'adminpass'}}

def is_similar(keyword1, keyword2, threshold=90):
    return fuzz.ratio(keyword1.lower(), keyword2.lower()) >= threshold

def duplicate_keywords(data):
    unique_keywords = []
    added_keywords = set()  

    for idx1, row1 in data.iterrows():
        keyword1 = row1['Keyword']
        if keyword1 in added_keywords:
            continue  
        
        similar_found = False

        for unique_row in unique_keywords:
            keyword_unique = unique_row['Keyword']
            if is_similar(keyword1, keyword_unique):          
                if are_values_equal(row1, unique_row):
                    similar_found = True
                    added_keywords.add(keyword1)
                    break
        if not similar_found:
            unique_keywords.append(row1)
            added_keywords.add(keyword1)

    return pd.DataFrame(unique_keywords)

def are_values_equal(row1, row2):
    return (row1['Search Volume (Global)'] == row2['Search Volume (Global)'] and
            row1['CPC (Global)'] == row2['CPC (Global)'] and
            row1['Competition (Global)'] == row2['Competition (Global)'])

def calculate_percentile(data, column_name):
    sorted_data = sorted(data[column_name])
    n = len(sorted_data)
    percentiles = []
    for value in data[column_name]:
        r = sorted_data.index(value) + 1  
        k = ((r-0.5) / n) * 100
        percentiles.append(k)
    return percentiles

def ensure_string_keys(doc):
    new_doc = {}
    for key, value in doc.items():
        new_key = str(key) if not isinstance(key, str) else key
        new_doc[new_key] = value
    return new_doc

def ensure_timestamp_keys(doc):
    new_doc = {}
    for key, value in doc.items():
        if isinstance(key, datetime):
            new_key = str(int(key.timestamp()))
        else:
            new_key = str(key) if not isinstance(key, str) else key
        new_doc[new_key] = value
    return new_doc

def calculate_point_value(data):
    search_value = data['Search Volume Percentile'] * 1
    cpc_value = 100 - (data['CPC Percentile'] * 1)
    competition_value = 100 - (data['Competition Percentile'] * 1)
    data['Point Value'] = (search_value + cpc_value + competition_value) / 3
    return data

def search_keyword(data, keyword, threshold=40):
    results = []
    for idx, row in data.iterrows():
        if is_similar(row['Keyword'], keyword, threshold):
            results.append(row)
    return pd.DataFrame(results)

def convert_datetime_string(data):
    new_doc = {}
    for key in data.keys():
        try:
            new_key = datetime.strptime(key, '%Y-%m-%d')
        except ValueError:
            new_key = key
        new_doc[new_key] = data[key]
    return new_doc

def convert_string_datetime(data):
    new_doc = {}
    for key, value in data.items():
        try:
            new_key = datetime.strptime(key, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                new_key = datetime.strptime(key, '%Y-%m-%d')
            except ValueError:
                new_key = key
        new_doc[new_key] = value
    
    return new_doc

def three_nearest_months(data):
    converted_data = convert_string_datetime(data)

    date_columns = [key for key in converted_data.keys() if isinstance(key, datetime)]
    if not date_columns:
        print("Không tìm thấy")

    sorted_date_columns = sorted(date_columns, key=lambda x: abs(x - datetime.now()))

    nearest_date_columns = sorted_date_columns[:3]
    
    return [col.strftime('%Y-%m-%d %H:%M:%S') for col in nearest_date_columns]

def is_date_string(column_name):
    try:
        pd.to_datetime(column_name, format='%Y-%m-%d', errors='raise')
        return True
    except (ValueError, TypeError):
        return False

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and users[username]['password'] == password:
            user = User(id=username)
            login_user(user)
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/calculate', methods=['GET', 'POST'])
def calculate_view():
    message=None
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            return redirect(request.url)

        if file:
            data = pd.read_excel(file)
            
            data['Search Volume Percentile'] = calculate_percentile(data, 'Search Volume (Global)')
            data['CPC Percentile'] = calculate_percentile(data, 'CPC (Global)')
            data['Competition Percentile'] = calculate_percentile(data, 'Competition (Global)')

            final_data = calculate_point_value(data)
            final_data = final_data.drop(columns=['Search Volume Percentile', 'CPC Percentile', 'Competition Percentile'])          
            final_data = duplicate_keywords(final_data)
            #final_data = convert_datetime_to_string(final_data)
            #s
            records = final_data.to_dict(orient='records')
            records = [ensure_string_keys(record) for record in records]
            #MongoDB
            collection_name = f"Data_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            mongo.db[collection_name].insert_many(records)

            return redirect(url_for('calculate_view', collection=collection_name))

    elif request.method == 'GET':
        collection_name = request.args.get('collection', None)
        if not collection_name:
            message = "Không tìm thấy dữ liệu"
            return render_template('result.html', tables='', message=message)
        
        sort_column = request.args.get('sort_column', 'Point Value')
        order = request.args.get('order', 'desc')
        keyword = request.args.get('search_keyword', '').strip()

        filtered_data = list(mongo.db[collection_name].find())        
        display_data = pd.DataFrame( filtered_data)
        
        three_months = three_nearest_months(mongo.db[collection_name].find_one())
        # print("ba cột gần nhất là:",  three_months)
        
        if keyword:
            display_data = search_keyword(pd.DataFrame(list(mongo.db[collection_name].find())), keyword, threshold=50)
            if display_data.empty:
                message = f"Không tìm thấy kết quả của: '{keyword}'."
                return render_template('result.html', tables='', message=message, search_keyword=keyword)

        if sort_column in display_data.columns:
            ascending = True if order == 'asc' else False
            display_data = display_data.sort_values(by=sort_column, ascending=ascending)
        
        display_data = display_data[['Keyword', 'Point Value', 'Search Volume (Global)', 'CPC (Global)', 'Competition (Global)', 'Trending %'] + three_months]
        table_html = display_data.to_html(classes='data', index=False)
        return render_template('result.html', tables=table_html, message=message, search_keyword=keyword, sort_column=sort_column, order=order)

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/search', methods=['POST'])
@login_required
def search_view():
    keyword = request.form.get('search_keyword', '').strip()
    if keyword:
        return redirect(url_for('calculate_view', search_keyword=keyword))
    return redirect(url_for('calculate_view'))

@app.route('/download', methods=['GET'])
@login_required
def download_file():
    collection_name = request.args.get('collection', None)
    if not collection_name:
        return redirect(url_for('calculate_view'))
    
    keyword_limit = request.args.get('keyword_limit_select', 'all')  
    data = pd.DataFrame(list(mongo.db[collection_name].find()))

    if keyword_limit != 'all':
        keyword_limit = int(keyword_limit)
        data = data.head(keyword_limit)

    limited_filepath = f'calculated_data_{keyword_limit}.xlsx'
    data.to_excel(limited_filepath, index=False)

    return send_file(limited_filepath, as_attachment=True, download_name=limited_filepath)

if __name__ == '__main__':
    app.run(debug=True)