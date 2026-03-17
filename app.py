from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from dataclasses import asdict, is_dataclass
from enum import Enum
import secrets
import string
import requests
import json
import os
import hashlib
import time
import threading

try:
    import esd
    ESD_AVAILABLE = True
    ESD_IMPORT_ERROR = None
except Exception as esd_error:
    esd = None
    ESD_AVAILABLE = False
    ESD_IMPORT_ERROR = str(esd_error)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
APP_STARTED_AT = time.time()
SELF_PING_STARTED = False

# Create database directory if it doesn't exist
database_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database')
if not os.path.exists(database_dir):
    os.makedirs(database_dir)
    print(f"Created database directory: {database_dir}")

# Set database URI from environment for production, fallback to local sqlite.
default_sqlite_path = os.path.join(database_dir, 'users.db')
render_disk_path = '/var/data/users.db'
db_path = render_disk_path if os.path.isdir('/var/data') else default_sqlite_path
database_url = os.environ.get('DATABASE_URL', '').strip()
if database_url:
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    if os.environ.get('RENDER') == 'true' and not os.path.isdir('/var/data'):
        print('WARNING: Running on Render without DATABASE_URL or persistent disk; data will reset on restart.')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# API URLs
app.config['PRIMEODDS_URL'] = "https://primeoddstips.com"
app.config['VVIP_API_URL'] = "https://api.oddsonpoint.com/public/api"

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    login_key = db.Column(db.String(100), unique=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    notifications_enabled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def generate_login_key(self):
        # Generate a complex, non-guessable login key
        alphabet = string.ascii_letters + string.digits + '!@#$%'
        key = ''.join(secrets.choice(alphabet) for _ in range(32))
        
        # Add user-specific data to make it unique
        user_data = f"{self.username}_{datetime.utcnow().timestamp()}_{secrets.token_hex(8)}"
        hash_part = hashlib.sha256(user_data.encode()).hexdigest()[:16]
        
        self.login_key = f"VIP_{key}_{hash_part}"
        return self.login_key

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200))
    message = db.Column(db.Text)
    type = db.Column(db.String(50))
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class GameHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_type = db.Column(db.String(50))
    game_data = db.Column(db.Text)
    date = db.Column(db.String(20))
    hash_value = db.Column(db.String(100), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def to_serializable(value):
    if is_dataclass(value):
        return to_serializable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: to_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_serializable(item) for item in value]
    return value

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Initialize database
def init_db():
    with app.app_context():
        try:
            db.create_all()
            print("✅ Database tables created successfully")
            
            # Create admin user if not exists
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                admin = User(username='admin', is_admin=True)
                admin.set_password('Admin@123')  # Change this on first login
                admin.generate_login_key()
                db.session.add(admin)
                db.session.commit()
                print(f"✅ Admin created successfully!")
                print(f"🔑 Admin Login Key: {admin.login_key}")
                print("⚠️  IMPORTANT: Save this key and change password on first login!")
            else:
                print(f"✅ Admin user already exists with key: {admin.login_key}")
                
        except Exception as e:
            print(f"❌ Database initialization error: {e}")
            print("Creating database with absolute path...")
            # Alternative: Create database with absolute path
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database', 'users.db')
            app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
            db.create_all()
            print(f"✅ Database created at: {db_path}")


def is_truthy(value):
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def resolve_self_ping_url():
    env_url = os.environ.get('SELF_PING_URL', '').strip()
    if env_url:
        return env_url
    render_url = os.environ.get('RENDER_EXTERNAL_URL', '').strip()
    if render_url:
        return render_url
    return ''


def self_ping_worker(base_url, interval_seconds):
    health_url = f"{base_url.rstrip('/')}/healthz"
    while True:
        try:
            requests.get(health_url, timeout=10)
        except Exception as ping_err:
            print(f"Self-ping warning: {ping_err}")
        time.sleep(interval_seconds)


def start_self_ping_if_enabled():
    global SELF_PING_STARTED

    if SELF_PING_STARTED:
        return

    if not is_truthy(os.environ.get('ENABLE_SELF_PING', 'false')):
        return

    base_url = resolve_self_ping_url()
    if not base_url:
        print('Self-ping is enabled but SELF_PING_URL/RENDER_EXTERNAL_URL is not set; skipping self-ping.')
        return

    interval_seconds = int(os.environ.get('SELF_PING_INTERVAL_SECONDS', '600'))
    thread = threading.Thread(
        target=self_ping_worker,
        args=(base_url, interval_seconds),
        daemon=True
    )
    thread.start()
    SELF_PING_STARTED = True
    print(f"Self-ping started: {base_url.rstrip('/')}/healthz every {interval_seconds}s")

# Call init_db
init_db()
start_self_ping_if_enabled()

# Add a context processor to make 'now' available in templates
@app.context_processor
def utility_processor():
    def now():
        return datetime.now()
    
    def format_date(date_obj, format_string='%Y-%m-%d'):
        if isinstance(date_obj, str):
            try:
                date_obj = datetime.strptime(date_obj, '%Y-%m-%d')
            except ValueError:
                return date_obj
        if hasattr(date_obj, 'strftime'):
            return date_obj.strftime(format_string)
        return str(date_obj)
    
    return dict(now=now, format_date=format_date)

# Routes
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/healthz')
def healthz():
    uptime_seconds = int(time.time() - APP_STARTED_AT)
    return jsonify({'status': 'ok', 'uptime_seconds': uptime_seconds})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_key = request.form.get('login_key')
        
        user = User.query.filter_by(login_key=login_key).first()
        
        if user:
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user)
            
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        
        flash('Invalid login key', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)


@app.route('/predictions')
@login_required
def predictions():
    return render_template('predictions.html', user=current_user)


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_confidence(odds, game_type):
    base_by_type = {
        'vip': 83,
        'draw': 76,
        'correct_score': 69
    }
    base = base_by_type.get(game_type, 72)

    # Lower odds usually imply higher probability, so confidence is adjusted inversely.
    if odds <= 1.8:
        score = base + 9
    elif odds <= 2.2:
        score = base + 5
    elif odds <= 2.8:
        score = base + 1
    elif odds <= 4.0:
        score = base - 5
    else:
        score = base - 11

    return max(45, min(95, int(score)))


def confidence_risk(confidence):
    if confidence >= 82:
        return 'Low'
    if confidence >= 68:
        return 'Medium'
    return 'High'


@app.route('/api/predictions/daily')
@login_required
def get_daily_predictions():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    include_types = request.args.get('types', 'vip,draw,correct_score').split(',')
    include_types = [t.strip() for t in include_types if t.strip()]

    market_labels = {
        'vip': '1X2 / Main Pick',
        'draw': 'Draw Market',
        'correct_score': 'Correct Score'
    }

    items = []

    try:
        for game_type in ['vip', 'draw', 'correct_score']:
            if game_type not in include_types:
                continue

            response = requests.get(
                f"{app.config['PRIMEODDS_URL']}/api/games.php",
                params={'type': game_type, 'date': date},
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=10
            )
            games = response.json()

            if not isinstance(games, list):
                continue

            for game in games:
                odds = safe_float(game.get('odds'), 0.0)
                confidence = calculate_confidence(odds, game_type)
                items.append({
                    'match': f"{game.get('home_team', 'N/A')} vs {game.get('away_team', 'N/A')}",
                    'home_team': game.get('home_team', 'N/A'),
                    'away_team': game.get('away_team', 'N/A'),
                    'prediction': game.get('prediction', 'N/A'),
                    'market': market_labels.get(game_type, 'General'),
                    'type': game_type,
                    'odds': odds,
                    'league': game.get('league', 'N/A'),
                    'status': game.get('status', 'pending'),
                    'confidence': confidence,
                    'risk': confidence_risk(confidence)
                })

        items.sort(key=lambda item: item['confidence'], reverse=True)

        if len(items) == 0:
            return jsonify({
                'date': date,
                'total': 0,
                'average_confidence': 0,
                'low_risk_count': 0,
                'top_picks': [],
                'predictions': []
            })

        average_confidence = int(sum(item['confidence'] for item in items) / len(items))
        low_risk_count = len([item for item in items if item['risk'] == 'Low'])

        return jsonify({
            'date': date,
            'total': len(items),
            'average_confidence': average_confidence,
            'low_risk_count': low_risk_count,
            'top_picks': items[:3],
            'predictions': items
        })

    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Connection error: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Could not generate predictions: {str(e)}'}), 500

@app.route('/api/vip/games')
@login_required
def get_vip_games():
    game_type = request.args.get('type', 'vip')
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    try:
        if game_type in ['correct_score', 'draw', 'vip']:
            # PrimeOdds API
            response = requests.get(
                f"{app.config['PRIMEODDS_URL']}/api/games.php",
                params={'type': game_type, 'date': date},
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=10
            )
            return jsonify(response.json())
        
        elif game_type in ['vvip', 'vip_games']:
            # VVIP API
            endpoint = 'vvip-games-by-date' if game_type == 'vvip' else 'vip-games-by-date'
            response = requests.get(
                f"{app.config['VVIP_API_URL']}/{endpoint}",
                params={'date': date},
                timeout=10
            )
            return jsonify(response.json())
    
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Connection error: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    return jsonify([])

@app.route('/api/user/toggle-notifications', methods=['POST'])
@login_required
def toggle_notifications():
    data = request.json or {}
    current_user.notifications_enabled = bool(data.get('enabled', False))
    db.session.commit()
    return jsonify({'success': True, 'enabled': current_user.notifications_enabled})


@app.route('/api/user/notification-settings')
@login_required
def get_notification_settings():
    return jsonify({'enabled': bool(current_user.notifications_enabled)})

@app.route('/api/user/notifications')
@login_required
def get_notifications():
    notifications = Notification.query.filter_by(
        user_id=current_user.id, read=False
    ).order_by(Notification.created_at.desc()).all()
    
    return jsonify([{
        'id': n.id,
        'title': n.title,
        'message': n.message,
        'type': n.type,
        'created_at': n.created_at.strftime('%Y-%m-%d %H:%M:%S')
    } for n in notifications])

@app.route('/api/user/mark-notification-read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id == current_user.id:
        notification.read = True
        db.session.commit()
    return jsonify({'success': True})

# Admin Routes
@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    # Calculate stats
    total_users = User.query.count()
    new_today = User.query.filter(
        db.func.date(User.created_at) == datetime.now().date()
    ).count()
    active_notifications = User.query.filter_by(notifications_enabled=True).count()
    
    stats = {
        'total_users': total_users,
        'new_today': new_today,
        'active_notifications': active_notifications
    }
    
    return render_template('admin/admin_dashboard.html', stats=stats)

@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/manage_users.html', users=users)

@app.route('/admin/user/create', methods=['POST'])
@login_required
def admin_create_user():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json
    
    # Check if user exists
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username already exists'}), 400
    
    # Create new user
    user = User(
        username=data['username'],
        is_admin=data.get('is_admin', False)
    )
    user.set_password(data['password'])
    user.generate_login_key()
    
    db.session.add(user)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'login_key': user.login_key,
        'username': user.username
    })

@app.route('/admin/user/delete/<int:user_id>', methods=['DELETE'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    user = User.query.get_or_404(user_id)
    if user.username == 'admin':  # Prevent deleting main admin
        return jsonify({'error': 'Cannot delete main admin'}), 400
    
    db.session.delete(user)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/user/reset-key/<int:user_id>', methods=['POST'])
@login_required
def admin_reset_key(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    user = User.query.get_or_404(user_id)
    user.generate_login_key()
    db.session.commit()
    
    return jsonify({
        'success': True,
        'new_key': user.login_key
    })


@app.route('/admin/notifications/broadcast', methods=['POST'])
@login_required
def admin_broadcast_notification():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.json or {}
    title = (data.get('title') or '').strip()
    message = (data.get('message') or '').strip()
    target = (data.get('target') or 'enabled').strip()

    if not title or not message:
        return jsonify({'error': 'Title and message are required'}), 400

    if target == 'all':
        users = User.query.all()
    else:
        users = User.query.filter_by(notifications_enabled=True).all()

    created = 0
    for user in users:
        notification = Notification(
            user_id=user.id,
            title=title,
            message=message,
            type='admin-broadcast',
            read=False
        )
        db.session.add(notification)
        created += 1

    db.session.commit()
    return jsonify({'success': True, 'created': created})

@app.route('/admin/games')
@login_required
def admin_games():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    return render_template('admin/view_games.html')

@app.route('/admin/games/fetch')
@login_required
def admin_fetch_games():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    game_type = request.args.get('type', 'all')
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    results = {}
    
    try:
        if game_type in ['all', 'primeodds']:
            for t in ['correct_score', 'draw', 'vip']:
                response = requests.get(
                    f"{app.config['PRIMEODDS_URL']}/api/games.php",
                    params={'type': t, 'date': date},
                    headers={'User-Agent': 'Mozilla/5.0'},
                    timeout=10
                )
                results[t] = response.json()
        
        if game_type in ['all', 'vvip_api']:
            # VVIP
            response = requests.get(
                f"{app.config['VVIP_API_URL']}/vvip-games-by-date",
                params={'date': date},
                timeout=10
            )
            results['vvip'] = response.json()
            
            # VIP from API
            response = requests.get(
                f"{app.config['VVIP_API_URL']}/vip-games-by-date",
                params={'date': date},
                timeout=10
            )
            results['vip_games'] = response.json()
    
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Connection error: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    return jsonify(results)

# API Endpoints for the scripts functionality
@app.route('/api/games/summary')
@login_required
def get_games_summary():
    today = datetime.now().strftime('%Y-%m-%d')
    summary = {}
    
    try:
        # PrimeOdds counts
        for t in ['correct_score', 'draw', 'vip']:
            response = requests.get(
                f"{app.config['PRIMEODDS_URL']}/api/games.php",
                params={'type': t, 'date': today},
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=5
            )
            data = response.json()
            summary[f"{t}_count"] = len(data) if isinstance(data, list) else 0
        
        # VVIP counts
        # VVIP packages
        response = requests.get(
            f"{app.config['VVIP_API_URL']}/vvip-games-by-date",
            params={'date': today},
            timeout=5
        )
        data = response.json()
        summary['vvip_count'] = len(data) if isinstance(data, list) else 0
        
        # VIP games from API
        response = requests.get(
            f"{app.config['VVIP_API_URL']}/vip-games-by-date",
            params={'date': today},
            timeout=5
        )
        data = response.json()
        summary['vip_api_count'] = len(data) if isinstance(data, list) else 0
    
    except Exception as e:
        print(f"Error fetching summary: {e}")
        # Return default values
        summary = {
            'correct_score_count': 0,
            'draw_count': 0,
            'vip_count': 0,
            'vvip_count': 0,
            'vip_api_count': 0
        }
    
    return jsonify(summary)

@app.route('/api/games/historical')
@login_required
def get_historical_games():
    game_type = request.args.get('type', 'vvip')
    days = int(request.args.get('days', 7))
    
    historical = []
    
    for i in range(1, days + 1):
        date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        
        try:
            if game_type in ['correct_score', 'draw', 'vip']:
                response = requests.get(
                    f"{app.config['PRIMEODDS_URL']}/api/games.php",
                    params={'type': game_type, 'date': date},
                    headers={'User-Agent': 'Mozilla/5.0'},
                    timeout=5
                )
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    historical.append({
                        'date': date,
                        'games': data
                    })
            
            elif game_type == 'vvip':
                response = requests.get(
                    f"{app.config['VVIP_API_URL']}/vvip-games-by-date",
                    params={'date': date},
                    timeout=5
                )
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    historical.append({
                        'date': date,
                        'games': data
                    })
            
            elif game_type == 'vip_games':
                response = requests.get(
                    f"{app.config['VVIP_API_URL']}/vip-games-by-date",
                    params={'date': date},
                    timeout=5
                )
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    historical.append({
                        'date': date,
                        'games': data
                    })
        
        except Exception as e:
            print(f"Error fetching historical data for {date}: {e}")
    
    return jsonify(historical)

@app.route('/api/games/winning')
@login_required
def get_winning_games():
    game_type = request.args.get('type', 'vvip')
    
    try:
        if game_type == 'vvip':
            response = requests.get(f"{app.config['VVIP_API_URL']}/vvip-games", timeout=10)
            data = response.json()
            
            winning_packages = []
            for package in data:
                if package.get('status') == 'Won':
                    winning_games = [g for g in package.get('games', []) if g.get('status') == 'Won']
                    if winning_games:
                        package['winning_games'] = winning_games
                        winning_packages.append(package)
            
            return jsonify(winning_packages)
        
        elif game_type == 'vip_games':
            response = requests.get(f"{app.config['VVIP_API_URL']}/vip-games", timeout=10)
            data = response.json()
            
            winning_games = [g for g in data if g.get('status') == 'Won']
            return jsonify(winning_games)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    return jsonify([])


@app.route('/api/soccer/live')
@login_required
def get_live_soccer_data():
    if not ESD_AVAILABLE:
        return jsonify({
            'error': f'EasySoccerData is not available: {ESD_IMPORT_ERROR}'
        }), 503

    source = request.args.get('source', 'sofascore')
    date = request.args.get('date', 'today')

    try:
        if source == 'sofascore':
            live = request.args.get('live', 'true').lower() == 'true'
            client = esd.SofascoreClient()
            events = client.get_events(date=date if date != 'today' else None, live=live)
            payload = []

            for event in events:
                payload.append({
                    'id': event.id,
                    'home_team': event.home_team.name,
                    'away_team': event.away_team.name,
                    'home_score': event.home_score.current,
                    'away_score': event.away_score.current,
                    'tournament': event.tournament.name,
                    'status': event.status.description,
                    'start_timestamp': event.start_timestamp,
                    'source': 'sofascore'
                })

            return jsonify({'source': source, 'count': len(payload), 'matches': payload})

        try:
            client = esd.PromiedosClient()
            events = client.get_events(date=date)
            payload = []

            for event in events:
                league_name = event.league.name if event.league else None
                for match in event.matches:
                    payload.append({
                        'id': match.id,
                        'home_team': match.home_team.name,
                        'away_team': match.away_team.name,
                        'home_score': match.scores.home,
                        'away_score': match.scores.away,
                        'status': match.status.name or match.time_status_to_display,
                        'display_time': match.time_to_display,
                        'start_timestamp': int(match.start_time) if match.start_time else 0,
                        'league': league_name,
                        'source': 'promiedos',
                        'odds': [
                            {'name': odd.name, 'value': odd.value, 'trend': odd.trend}
                            for odd in (match.main_odds.options or [])
                        ]
                    })

            return jsonify({'source': source, 'count': len(payload), 'matches': payload})
        except Exception:
            # Promiedos is less stable; fallback to Sofascore to keep feature available.
            client = esd.SofascoreClient()
            events = client.get_events(date=date if date != 'today' else None, live=True)
            payload = []
            for event in events:
                payload.append({
                    'id': event.id,
                    'home_team': event.home_team.name,
                    'away_team': event.away_team.name,
                    'home_score': event.home_score.current,
                    'away_score': event.away_score.current,
                    'tournament': event.tournament.name,
                    'status': event.status.description,
                    'start_timestamp': event.start_timestamp,
                    'source': 'sofascore'
                })
            return jsonify({'source': 'sofascore', 'count': len(payload), 'matches': payload})

    except Exception as e:
        return jsonify({'error': f'Failed to fetch soccer data: {str(e)}'}), 500


@app.route('/api/soccer/match/<match_id>')
@login_required
def get_match_details(match_id):
    if not ESD_AVAILABLE:
        return jsonify({
            'error': f'EasySoccerData is not available: {ESD_IMPORT_ERROR}'
        }), 503

    source = request.args.get('source', 'promiedos')

    try:
        if source == 'sofascore':
            client = esd.SofascoreClient()
            event = client.get_event(int(match_id))

            incidents = []
            stats_rows = []

            try:
                incidents = client.get_match_incidents(int(match_id))
            except Exception:
                incidents = []

            try:
                raw_stats = client.get_match_stats(int(match_id))
                groups = getattr(raw_stats, 'groups', []) or []
                for group in groups:
                    for item in getattr(group, 'stats_items', []) or []:
                        stats_rows.append({
                            'name': getattr(item, 'name', 'N/A'),
                            'home': getattr(item, 'home_value', 'N/A'),
                            'away': getattr(item, 'away_value', 'N/A')
                        })
            except Exception:
                stats_rows = []

            normalized = {
                'home_team': {'name': getattr(event.home_team, 'name', 'Home')},
                'away_team': {'name': getattr(event.away_team, 'name', 'Away')},
                'scores': {
                    'home': getattr(event.home_score, 'current', 0),
                    'away': getattr(event.away_score, 'current', 0)
                },
                'status': {'name': getattr(event.status, 'description', 'N/A')},
                'start_time': getattr(event, 'start_timestamp', 0),
                'events': {'events': to_serializable(incidents)},
                'stats': {'stats': stats_rows}
            }
            return jsonify({'match': normalized, 'source': 'sofascore'})

        client = esd.PromiedosClient()
        match = client.get_match(match_id=match_id)
        return jsonify({'match': to_serializable(match), 'source': 'promiedos'})
    except Exception as e:
        # Promiedos can intermittently fail with upstream 500; return a graceful response.
        try:
            fallback_client = esd.SofascoreClient()
            event = fallback_client.get_event(int(match_id))
            fallback = {
                'home_team': {'name': getattr(event.home_team, 'name', 'Home')},
                'away_team': {'name': getattr(event.away_team, 'name', 'Away')},
                'scores': {
                    'home': getattr(event.home_score, 'current', 0),
                    'away': getattr(event.away_score, 'current', 0)
                },
                'status': {'name': getattr(event.status, 'description', 'N/A')},
                'start_time': getattr(event, 'start_timestamp', 0),
                'events': {'events': []},
                'stats': {'stats': []}
            }
            return jsonify({
                'match': fallback,
                'source': 'sofascore',
                'warning': 'Primary provider is temporarily unavailable. Showing fallback data.'
            })
        except Exception:
            return jsonify({
                'match': None,
                'source': source,
                'warning': 'Match details are temporarily unavailable from the provider. Please try again later or switch source.'
            })

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 Starting Codes Web Application")
    print("=" * 50)
    print(f"📁 Database location: {db_path}")
    print(f"🔗 Access URL: http://127.0.0.1:5000")
    try:
        ip = requests.get('https://api.ipify.org', timeout=5).text
        print(f"📱 For other devices: http://{ip}:5000")
    except:
        print("📱 For other devices: Check your local IP address")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)