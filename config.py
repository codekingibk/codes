import os
import secrets

class Config:
    SECRET_KEY = secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = 'sqlite:///database/users.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PRIMEODDS_URL = "https://primeoddstips.com"
    VVIP_API_URL = "https://api.oddsonpoint.com/public/api"