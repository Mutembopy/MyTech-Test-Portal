from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
    role = db.Column(db.String(50))
    contact = db.Column(db.String(100))
    password = db.Column(db.String(200))
    photo = db.Column(db.String(200))

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_number = db.Column(db.String(100))
    technician_name = db.Column(db.String(100))
    progress = db.Column(db.Integer)
    challenges = db.Column(db.Text)
    comments = db.Column(db.Text)
    observations = db.Column(db.Text)
    start_time = db.Column(db.String(100))
    end_time = db.Column(db.String(100))
    duration = db.Column(db.String(100))
    team = db.Column(db.String(200))
    files = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    job_id = db.Column(db.String(100))

    def serialize(self):
        return {
            'job_number': self.job_number,
            'progress': self.progress,
            'created_at': self.created_at.strftime('%Y-%m-%d')
        }
