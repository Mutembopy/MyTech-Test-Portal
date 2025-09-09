from flask import Flask, render_template, request, redirect, session, url_for, jsonify, flash, Response
from flask_socketio import SocketIO, emit, join_room, leave_room
import sqlite3, os, uuid
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from xhtml2pdf import pisa
from io import BytesIO
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from fpdf import FPDF
import smtplib
from email.message import EmailMessage

# --- Config ---
DATABASE = 'technicians.db'
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
SERVICE_ACCOUNT_FILE = "path/to/your/service_account.json"

app = Flask(__name__)
app.secret_key = '831'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
socketio = SocketIO(app)

# --- DB Setup ---
DATABASE = 'chat.db'

def init_db():
    need_init = not os.path.exists(DATABASE)
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Enable foreign key support
    c.execute("PRAGMA foreign_keys = ON")

    # Create technicians table
    c.execute('''CREATE TABLE IF NOT EXISTS technicians (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    role TEXT,
                    contact TEXT,
                    email TEXT UNIQUE,
                    password TEXT,
                    photo TEXT
                )''')

    # Create groups table
    c.execute('''CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    creator_id INTEGER,
                    created_at TEXT,
                    FOREIGN KEY (creator_id) REFERENCES technicians(id) ON DELETE SET NULL
                )''')

    # Create group_members table
    c.execute('''CREATE TABLE IF NOT EXISTS group_members (
                    group_id INTEGER,
                    technician_id INTEGER,
                    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
                    FOREIGN KEY (technician_id) REFERENCES technicians(id) ON DELETE CASCADE,
                    PRIMARY KEY (group_id, technician_id)
                )''')

    # Create messages table
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER,
                    sender_name TEXT,
                    recipient_id INTEGER,
                    group_id INTEGER,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (sender_id) REFERENCES technicians(id) ON DELETE SET NULL,
                    FOREIGN KEY (recipient_id) REFERENCES technicians(id) ON DELETE SET NULL,
                    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
                )''')

    # Create reports table
    c.execute('''CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_number TEXT,
                    technician_id INTEGER,
                    technician_name TEXT,
                    progress INTEGER,
                    challenges TEXT,
                    comments TEXT,
                    observations TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    duration TEXT,
                    team TEXT,
                    files TEXT,
                    created_at TEXT,
                    job_id TEXT,
                    FOREIGN KEY (technician_id) REFERENCES technicians(id) ON DELETE SET NULL
                )''')

    if need_init:
        # Insert initial technicians
        c.executemany(
            "INSERT OR IGNORE INTO technicians (name, role, contact, email, password, photo) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ('Alice Mwansa', 'Network Engineer', '0977001122', 'alice@techcorp.com', generate_password_hash('password123'), ''),
                ('Brian Zulu', 'Systems Analyst', '0977012233', 'brian@techcorp.com', generate_password_hash('password123'), ''),
                ('Chipo Banda', 'IoT Specialist', '0977023344', 'chipo@techcorp.com', generate_password_hash('password123'), ''),
                ('Derrick Phiri', 'Cybersecurity Expert', '0977034455', 'derrick@techcorp.com', generate_password_hash('password123'), '')
            ]
        )
        conn.commit()  # Commit technicians before inserting groups

        # Insert initial groups
        c.executemany(
            "INSERT OR IGNORE INTO groups (name, creator_id, created_at) VALUES (?, ?, ?)",
            [
                ('Network Team', 1, datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                ('Security Group', 4, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            ]
        )
        conn.commit()  # Commit groups before inserting group_members

        # Insert initial group members
        c.executemany(
            "INSERT OR IGNORE INTO group_members (group_id, technician_id) VALUES (?, ?)",
            [
                (1, 1),  # Alice in Network Team
                (1, 2),  # Brian in Network Team
                (2, 4),  # Derrick in Security Group
                (2, 3)   # Chipo in Security Group
            ]
        )
        conn.commit()  # Commit group_members before inserting messages

        # Insert initial messages
        c.executemany(
            "INSERT OR IGNORE INTO messages (sender_id, sender_name, message, timestamp, group_id, recipient_id) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (0, 'System', 'Welcome to TechCorp Technician Portal.', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), None, None),
                (1, 'Alice Mwansa', 'Network upgrade completed.', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 1, None),
                (4, 'Derrick Phiri', 'Security audit in progress.', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 2, None)
            ]
        )
        conn.commit()  # Commit messages before inserting reports

        # Insert initial reports
        c.executemany(
            '''INSERT OR IGNORE INTO reports 
               (job_number, technician_id, technician_name, progress, challenges, comments,
                observations, start_time, end_time, duration, team, files, created_at, job_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            [
                ('TC-JB-1001', 1, 'Alice Mwansa', 100, 'No issues', 'Replaced old router and reconfigured firewall rules.', 'System running optimally.', '2025-08-01 09:00', '2025-08-01 12:30', '3.5h', 'Brian Zulu', '', '2025-08-01 13:00', str(uuid.uuid4())),
                ('TC-JB-1002', 2, 'Brian Zulu', 75, 'Slow performance due to outdated patches', 'Initiated patch upgrade.', 'System upgrade partially complete.', '2025-08-02 10:00', '2025-08-02 13:00', '3h', 'Alice Mwansa, Chipo Banda', '', '2025-08-02 13:15', str(uuid.uuid4())),
                ('TC-JB-1003', 3, 'Chipo Banda', 60, 'Sensor connectivity drops', 'Deployed IoT base station extension.', 'Awaiting test results.', '2025-08-03 08:30', '2025-08-03 11:00', '2.5h', 'Brian Zulu', '', '2025-08-03 11:15', str(uuid.uuid4())),
                ('TC-JB-1004', 4, 'Derrick Phiri', 90, 'Firewall logs showing brute-force attempts', 'Blocked IPs and updated access rules.', 'Security status improved.', '2025-08-03 13:00', '2025-08-03 16:30', '3.5h', 'Alice Mwansa', '', '2025-08-03 16:45', str(uuid.uuid4()))
            ]
        )
        conn.commit()

    conn.close()

# Ensure uploads folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
init_db()

# --- Helpers ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.context_processor
def inject_globals():
    return {'request': request, 'current_year': datetime.now().year}

@app.context_processor
def inject_user():
    return dict(user={
        'id': session.get('user_id'),
        'name': session.get('user_name'),
        'email': session.get('user_email'),
        'role': session.get('user_role'),
        'photo': session.get('user_photo')
    })

# --- Routes ---
@app.route("/")
def home():
    return render_template("landing.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        if username == 'admin' and password == 'admin123':
            session.clear()
            session['admin'] = True
            session['user_id'] = 'admin'
            session['user_role'] = 'Admin'
            session['user_name'] = 'Admin'
            session['user_email'] = 'admin@example.com'
            session['user_photo'] = None
            return redirect(url_for('dashboard'))

        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("SELECT id, name, email, role, password, photo FROM technicians WHERE name=?", (username,))
        tech = c.fetchone()
        conn.close()

        if tech and check_password_hash(tech[4], password):
            session.clear()
            session['technician'] = True
            session['user_id'] = tech[0]
            session['user_role'] = tech[3]
            session['user_name'] = tech[1]
            session['user_email'] = tech[2]
            session['user_photo'] = tech[5]
            return redirect(url_for('tech_dashboard'))

        return render_template('login.html', error="Invalid credentials")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    if 'admin' not in session:
        return redirect(url_for('home'))

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Enables dict-like access
    c = conn.cursor()
    c.execute("SELECT id, name, role, contact, email FROM technicians")
    rows = c.fetchall()
    conn.close()

    technicians = [dict(row) for row in rows]  # Convert to list of dicts

    user = {
        'name': 'Admin',
        'email': 'admin@example.com',
        'role': 'Administrator',
        'photo': None
    }

    return render_template('dashboard.html', user=user, technicians=technicians)


@app.route('/add_technician', methods=['GET', 'POST'])
def add_technician():
    if 'admin' not in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        role = request.form.get('role', '').strip()
        contact = request.form.get('contact', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        # Basic validation
        if not all([name, role, contact, email, password]):
            flash("⚠️ All fields are required.", "error")
            return redirect(url_for('add_technician'))

        hashed_password = generate_password_hash(password)

        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()

        # 🔍 Check for existing email
        c.execute("SELECT id FROM technicians WHERE email = ?", (email,))
        existing = c.fetchone()

        if existing:
            conn.close()
            flash("⚠️ A technician with this email already exists.", "error")
            return redirect(url_for('add_technician'))

        # ✅ Insert new technician
        c.execute("""
            INSERT INTO technicians (name, role, contact, email, password)
            VALUES (?, ?, ?, ?, ?)
        """, (name, role, contact, email, hashed_password))
        conn.commit()
        conn.close()

        flash("✅ Technician added successfully.", "success")
        return redirect(url_for('dashboard'))

    return render_template('add_technician.html')


@app.route('/delete_technician/<int:id>')
def delete_technician(id):
    if 'admin' not in session:
        return redirect(url_for('home'))
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("DELETE FROM technicians WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/tech_dashboard')
def tech_dashboard():
    if 'technician' not in session:
        return redirect(url_for('home'))

    tech_id = session['user_id']
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Fetch technician details
    c.execute("SELECT name, email, role, photo FROM technicians WHERE id=?", (tech_id,))
    tech = c.fetchone() or ('Unknown', 'unknown@techcorp.com', 'Unknown', None)

    # Fetch report statistics
    c.execute("SELECT COUNT(*) FROM reports WHERE technician_id=?", (tech_id,))
    total_reports = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM reports WHERE technician_id=? AND progress = 100", (tech_id,))
    completed = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM reports WHERE technician_id=? AND progress < 100 AND progress > 0", (tech_id,))
    in_progress = c.fetchone()[0]

    # Fetch latest message
    c.execute("""
        SELECT sender_name, message 
        FROM messages 
        WHERE recipient_id=? OR group_id IN (SELECT group_id FROM group_members WHERE technician_id=?) 
        ORDER BY timestamp DESC LIMIT 1
    """, (tech_id, tech_id))
    latest_msg = c.fetchone() or ('No messages', 'No recent messages available.')

    # Fetch chart data
    c.execute("""
        SELECT substr(created_at, 1, 7) AS month, COUNT(*)
        FROM reports
        WHERE technician_id=? AND progress = 100
        GROUP BY month
        ORDER BY month ASC
    """, (tech_id,))
    rows = c.fetchall()

    conn.close()

    user = {
        'id': tech_id,  # Added for chat compatibility
        'name': tech[0],
        'email': tech[1],
        'role': tech[2],
        'photo': tech[3]
    }
    chart = {'labels': [r[0] for r in rows], 'data': [r[1] for r in rows]}

    return render_template('tech_dashboard.html',
                           user=user,
                           total_reports=total_reports,
                           in_progress=in_progress,
                           completed=completed,
                           latest_msg=latest_msg,
                           recent_jobs=[],
                           chart=chart)

@app.route('/tech_summary')
def tech_summary():
    if 'technician' not in session:
        return redirect(url_for('home'))

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''SELECT job_number, progress, challenges, comments, start_time, end_time, created_at
                 FROM reports
                 WHERE technician_name=? AND created_at >= date('now','-7 day')''',
              (session.get('user_name'),))
    reports = c.fetchall()
    conn.close()

    suggestions = []
    if reports:
        valid_progress = [int(r[1]) for r in reports if r[1] is not None]
        avg_progress = sum(valid_progress) // len(valid_progress) if valid_progress else 0
        if avg_progress < 80:
            suggestions.append("Consider allocating more resources to improve progress.")
        challenge_count = sum(1 for r in reports if r[2] and r[2].strip())
        if challenge_count > 2:
            suggestions.append("Frequent challenges reported. Review site conditions or provide additional support.")
        if not suggestions:
            suggestions.append("Good progress and minimal challenges. Keep up the good work!")
    else:
        suggestions.append("No reports found for this week.")

    session['last_summary'] = {'reports': reports, 'suggestions': suggestions}
    return render_template('tech_summary.html', reports=reports, suggestions=suggestions)

@app.route('/export_summary_pdf')
def export_summary_pdf():
    if 'technician' not in session:
        flash("Please log in to access the summary.", "error")
        return redirect(url_for('home'))

    data = session.get('last_summary', {'reports': [], 'suggestions': ["No data to export"]})
    user = {
        'name': session.get('user_name', 'Unknown'),
        'email': session.get('user_email', ''),
        'role': session.get('user_role', ''),
        'photo': session.get('user_photo', '')
    }
    html = render_template('tech_summary_pdf.html', reports=data['reports'], suggestions=data['suggestions'], user=user)

    pdf = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=pdf)
    if pisa_status.err:
        flash("PDF generation failed.", "error")
        return redirect(url_for('tech_summary'))

    pdf.seek(0)
    return Response(pdf.read(), mimetype='application/pdf',
                    headers={'Content-Disposition': 'attachment;filename=weekly_summary.pdf'})

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'technician' not in session:
        return redirect(url_for('home'))

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    if request.method == 'POST':
        if 'file' in request.files:
            file = request.files['file']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                c.execute("UPDATE technicians SET photo=? WHERE name=?", (filename, session['user_name']))
                conn.commit()

    c.execute("SELECT name, role, contact, email, photo FROM technicians WHERE name=?", (session['user_name'],))
    user = c.fetchone()

    c.execute("SELECT COUNT(*) FROM reports WHERE technician_name=?", (session['user_name'],))
    job_count = c.fetchone()[0] or 0

    c.execute("SELECT AVG(progress) FROM reports WHERE technician_name=?", (session['user_name'],))
    avg_progress = c.fetchone()[0] or 0

    conn.close()

    return render_template(
        'profile.html',
        user=user,
        job_count=job_count,
        avg_progress=avg_progress
    )

@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'technician' not in session:
        return redirect(url_for('home'))

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    if request.method == 'POST':
        email = request.form.get('email')
        contact = request.form.get('contact')
        role = request.form.get('role')
        photo = None

        if 'file' in request.files:
            file = request.files['file']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                photo = filename

        update_fields, update_values = [], []
        if email:   update_fields.append("email=?");    update_values.append(email)
        if contact: update_fields.append("contact=?");  update_values.append(contact)
        if role:    update_fields.append("role=?");     update_values.append(role)
        if photo:   update_fields.append("photo=?");    update_values.append(photo)

        if update_fields:
            update_values.append(session['user_name'])
            query = f"UPDATE technicians SET {', '.join(update_fields)} WHERE name=?"
            c.execute(query, update_values)
            conn.commit()

        flash("Profile updated successfully.")
        conn.close()
        return redirect(url_for('profile'))

    c.execute("SELECT name, role, contact, email, photo FROM technicians WHERE name=?", (session['user_name'],))
    user = c.fetchone()
    conn.close()
    return render_template('edit_profile.html', user=user)

@app.route('/chat')
def chat():
    if 'technician' not in session:
        return redirect(url_for('home'))

    tech_id = session['user_id']
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Fetch technician details
    c.execute("SELECT name FROM technicians WHERE id=?", (tech_id,))
    tech = c.fetchone() or ('Unknown',)

    # Fetch all technicians for the group form
    c.execute("SELECT id, name FROM technicians")
    technicians = c.fetchall()

    # Fetch groups for the current technician
    c.execute("SELECT g.id, g.name FROM groups g JOIN group_members gm ON g.id = gm.group_id WHERE gm.technician_id = ?", (tech_id,))
    groups = c.fetchall()

    # Fetch all relevant messages
    c.execute("""
        SELECT id, sender_id, sender_name, message, recipient_id, group_id, timestamp
        FROM messages 
        WHERE recipient_id = ? OR group_id IN (SELECT group_id FROM group_members WHERE technician_id = ?) 
        ORDER BY timestamp DESC
    """, (tech_id, tech_id))
    messages = c.fetchall()

    conn.close()

    user = {'id': tech_id, 'name': tech[0]}

    return render_template('index.html',
                           user=user,
                           messages=messages,
                           technicians=technicians,
                           groups=groups)

@app.route('/create_group', methods=['POST'])
def create_group():
    if 'technician' not in session:
        return redirect(url_for('home'))

    group_name = request.form.get('group_name')
    member_ids = request.form.getlist('members')
    if not group_name or not member_ids:
        flash("Group name and at least one member are required.")
        return redirect(url_for('chat'))

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("INSERT INTO groups (name, creator_id, created_at) VALUES (?, ?, ?)",
              (group_name, session['user_id'], created_at))
    group_id = c.lastrowid

    # Add creator to the group
    c.execute("INSERT INTO group_members (group_id, technician_id) VALUES (?, ?)", (group_id, session['user_id']))
    # Add selected members
    for member_id in member_ids:
        c.execute("INSERT INTO group_members (group_id, technician_id) VALUES (?, ?)", (group_id, int(member_id)))
    conn.commit()
    conn.close()

    flash(f"Group '{group_name}' created successfully.")
    return redirect(url_for('chat'))

@socketio.on('join')
def handle_join(data):
    room = data['room']
    join_room(room)
    emit('message', {
        'sender_id': 0,
        'sender_name': 'System',
        'message': f"{data['user_name']} joined the chat",
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }, room=room)

@socketio.on('leave')
def handle_leave(data):
    room = data['room']
    leave_room(room)
    emit('message', {
        'sender_id': 0,
        'sender_name': 'System',
        'message': f"{data['user_name']} left the chat",
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }, room=room)

@socketio.on('message')
def handle_message(data):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender_id, sender_name, recipient_id, group_id, message, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
              (data['sender_id'], data['sender_name'], data.get('recipient_id'), data.get('group_id'), data['message'], data['timestamp']))
    conn.commit()
    conn.close()
    emit('message', data, room=data['room'])

@socketio.on('typing')
def handle_typing(data):
    emit('typing', data, room=data['room'], broadcast=True)

@app.route('/tech_logout')
def tech_logout():
    session.pop('technician', None)
    for k in ['user_id','user_name','user_role','user_email','user_photo']:
        session.pop(k, None)
    return redirect(url_for('home'))

@app.route('/api/reports', methods=['GET'])
def api_reports():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM reports")
    reports = c.fetchall()
    conn.close()
    return jsonify(reports)

@app.route('/report', methods=['GET', 'POST'])
def report():
    if 'technician' not in session:
        return redirect(url_for('home'))

    tech_id = session.get('user_id')
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    if request.method == 'POST':
        job_number = request.form.get('job_number')
        technician_name = session.get('user_name')
        progress = request.form.get('progress')
        challenges = request.form.get('challenges')
        comments = request.form.get('comments')
        observations = request.form.get('observations')
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        duration = request.form.get('duration')
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Handle file upload
        files = request.files.get('files')
        filename = ''
        if files and allowed_file(files.filename):
            filename = secure_filename(files.filename)
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
            files.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        # Handle selected team members
        selected_team = request.form.getlist('team_members')  # returns list of names
        team_str = ', '.join(selected_team)  # store as comma-separated string

        job_id = str(uuid.uuid4())

        c.execute('''INSERT INTO reports (
                        job_number, technician_id, technician_name, progress,
                        challenges, comments, observations, start_time, end_time,
                        duration, team, files, created_at, job_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (job_number, tech_id, technician_name, progress, challenges, comments,
                   observations, start_time, end_time, duration, team_str, filename, created_at, job_id))
        conn.commit()
        conn.close()
        flash("Report submitted successfully.")
        return redirect(url_for('tech_dashboard'))

    # GET request: fetch all team members for the dropdown
    c.execute("SELECT name, role, contact FROM technicians")
    team = c.fetchall()
    conn.close()

    user = {
        'name': session.get('user_name'),
        'email': session.get('user_email'),
        'role': session.get('user_role'),
        'photo': session.get('user_photo')
    }

    return render_template('report.html', team=team, user=user)

@app.route('/report_pdf/<job_id>')
def report_pdf(job_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM reports WHERE job_id=?", (job_id,))
    report = c.fetchone()
    conn.close()

    if not report:
        return "Report not found", 404

    html = render_template('report_pdf.html', report=report)
    pdf = BytesIO()
    pisa.CreatePDF(html, dest=pdf)
    pdf.seek(0)

    return Response(pdf.read(), mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment;filename=report_{job_id}.pdf'})

def upload_to_drive(file_path, file_name, mimetype='application/pdf'):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/drive']
    )
    service = build('drive', 'v3', credentials=creds)
    file_metadata = {'name': file_name}
    media = MediaFileUpload(file_path, mimetype=mimetype)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    print(f"Uploaded file ID: {file.get('id')}")

def generate_pdf(filename='report.pdf'):
    conn = sqlite3.connect('technicians.db')
    c = conn.cursor()
    c.execute("SELECT job_number, technician_name, progress, comments FROM reports")
    rows = c.fetchall()
    conn.close()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Technician Report Summary", ln=True, align='C')

    for row in rows:
        line = f"Job: {row[0]}, Tech: {row[1]}, Progress: {row[2]}%, Comments: {row[3]}"
        pdf.multi_cell(0, 10, line)

    pdf.output(filename)

def send_email_with_pdf(to_email, pdf_path):
    msg = EmailMessage()
    msg['Subject'] = 'MyTech Report Backup'
    msg['From'] = 'mutembo831@gmail.com'
    msg['To'] = to_email
    msg.set_content('Attached is your technician report backup.')

    with open(pdf_path, 'rb') as f:
        file_data = f.read()
        msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=pdf_path)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login('mutembo831@gmail.com', 'Bethelmb')
        smtp.send_message(msg)

@app.route('/send_backup', methods=['POST'])
def send_backup():
    generate_pdf('backup.pdf')
    send_email_with_pdf('mutembo831@gmail.com', 'backup.pdf')
    flash('PDF backup sent to your Gmail.')
    return redirect(url_for('index.html'))

if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)