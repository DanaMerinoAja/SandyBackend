# app/deps.py
from services.firebase_service import FirebaseService

def get_firebase():
    return FirebaseService.instance()
