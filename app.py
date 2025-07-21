from flask import Flask, request, jsonify, session, render_template
from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from datetime import datetime, timedelta
from bson import ObjectId
from flask_mail import Mail, Message
import random
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

import os

load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app, origins=["http://127.0.0.1:5500"], supports_credentials=True)
app.secret_key = os.getenv("SECRET_KEY")

app.permanent_session_lifetime = timedelta(days=1)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER






app.config["MONGO_URI"] = os.environ.get("MONGO_URI")
print("Mongo URI in use:", app.config["MONGO_URI"])

mongo = PyMongo(app)
users_collection = mongo.db.user
complaints_collection = mongo.db.complaints
print("MAIL_USERNAME:", os.environ.get("MAIL_USERNAME"))
print("MAIL_PASSWORD:", os.environ.get("MAIL_PASSWORD"))
# Mail Config
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
mail = Mail(app)


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    role = data.get("role", "student")
    if users_collection.find_one({"username": username}):
        return jsonify({"message": "User already exists"}), 409
    hashed_password = generate_password_hash(password)
    users_collection.insert_one({"username": username, "password": hashed_password, "role": role})
    return jsonify({"message": "Registration successful"}), 201

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    selected_role = data.get("role")  # ⬅️ role sent from frontend

    user = users_collection.find_one({"username": username})
    if user and check_password_hash(user["password"], password):
        actual_role = user.get("role", "student")
        if actual_role != selected_role:
            return jsonify({"message": "Invalid credentials (role mismatch)"}), 401

        # ✅ Roles match
        session["username"] = username
        session["role"] = actual_role
        redirect = "/warden.html" if actual_role in ["admin", "warden"] else "/dashboard.html"
        return jsonify({"message": "Login successful", "role": actual_role, "redirect": redirect}), 200

    return jsonify({"message": "Invalid credentials"}), 401

# Add this import at the top if not already present


# Update Flask config to allow file uploads
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # Optional: 5MB max file size

@app.route("/submit_complaint", methods=["POST"])
def submit_complaint():
    if "username" not in session:
        return jsonify({"message": "Please login first"}), 401

    # If the request is a file upload, use request.form and request.files
    title = request.form.get("title")
    room = request.form.get("room")
    roll = request.form.get("roll")
    text = request.form.get("text")
    hostel = request.form.get("hostel")
    date = request.form.get("date")

    if not all([title, room, roll, text, hostel, date]):
        return jsonify({"message": "Missing fields"}), 400

    image_path = None
    if "image" in request.files:
        image = request.files["image"]
        if image and image.filename:
            filename = secure_filename(image.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image.save(filepath)
            image_path = filename

    complaint_data = {
        "username": session["username"],
        "roll": roll,
        "title": title,
        "text": text,
        "room": room,
        "hostel": hostel,
        "date": date,
        "status": "Open",
        "submitted_at": datetime.utcnow(),
        "image_path": image_path  # Optional
    }

    result = complaints_collection.insert_one(complaint_data)
    return jsonify({"message": "Complaint submitted", "id": str(result.inserted_id)}), 200


@app.route("/api/complaints/<complaint_id>", methods=["DELETE"])
def delete_complaint(complaint_id):
    if "username" not in session:
        return jsonify({"message": "Please login first"}), 401

    complaint = complaints_collection.find_one({"_id": ObjectId(complaint_id)})
    if not complaint:
        return jsonify({"message": "Complaint not found"}), 404

    if complaint["username"] != session["username"] and session.get("role") != "admin":
        return jsonify({"message": "Unauthorized"}), 403

    complaints_collection.delete_one({"_id": ObjectId(complaint_id)})
    return jsonify({"message": "Complaint deleted successfully"}), 200



@app.route("/logout", methods=["POST"])
def logout():
    session.clear()  # or: session.pop("username", None) and session.pop("role", None)
    return jsonify({"message": "Logged out"}), 200


@app.route("/")
def serve_index():
    return render_template("index.html")

@app.route("/dashboard.html")
def serve_dashboard():
    return render_template("dashboard.html")

@app.route("/warden.html")
def serve_warden():
    return render_template("warden.html")

@app.route("/api/complaints", methods=["GET"])
def get_complaints():
    if "username" not in session:
        return jsonify({"message": "Please login first"}), 401

    user = users_collection.find_one({"username": session["username"]})
    if not user:
        return jsonify({"message": "User not found"}), 403

    try:
        if user.get("role") in ["admin", "warden"]:
            complaints = list(complaints_collection.find())
        else:
            complaints = list(complaints_collection.find({"username": session["username"]}))

        for complaint in complaints:
            complaint["_id"] = str(complaint["_id"])
            if "status" not in complaint:
                complaint["status"] = "Open"
          
            if "image_path" in complaint and complaint["image_path"]:
                complaint["image_url"] = f"/static/uploads/{complaint['image_path']}"
            else:
                complaint["image_url"] = ""


        return jsonify(complaints), 200
    except Exception as e:
        print("Fetch Error:", e)
        return jsonify({"message": "Error fetching complaints"}), 500
    
    
@app.route("/api/complaints/<complaint_id>", methods=["PUT"])
def update_complaint_status(complaint_id):
    if "username" not in session:
        return jsonify({"message": "Please login first"}), 401

    user = users_collection.find_one({"username": session["username"]})
    if not user or user.get("role") not in ["admin", "warden"]:
        return jsonify({"message": "Access denied"}), 403

    data = request.get_json()
    new_status = data.get("status")
    if not new_status:
        return jsonify({"message": "Status is required"}), 400

    try:
        result = complaints_collection.update_one(
            {"_id": ObjectId(complaint_id)},
            {"$set": {
                "status": new_status,
                "updated_by": session["username"],
                "updated_at": datetime.now()
            }}
        )

        if result.matched_count:
            return jsonify({"message": "Status updated successfully"}), 200
        else:
            return jsonify({"message": "Complaint not found"}), 404
    except Exception as e:
        print("Update Error:", e)
        return jsonify({"message": "Error updating complaint"}), 500
    
    import random

@app.route("/request_otp", methods=["POST"])
def request_otp():
    data = request.get_json()
    email = data.get("email")
    username = data.get("username")
    password = data.get("password")
    role = data.get("role", "student")
    employee_id = data.get("employee_id") 
    print("Received employee_id:", repr(employee_id))
    print("Looking for employee_id:", employee_id)
    found_employee = mongo.db.employees.find_one({"employee_id": employee_id})
    print("Found in DB:", found_employee)

    if users_collection.find_one({"username": username}):
        return jsonify({"message": "User already exists"}), 409

    if role == "admin":
        if not employee_id:
            return jsonify({"message": "Employee ID required for admin"}), 400
        employee_id = employee_id.strip()
        found = mongo.db.employees.find_one({"employee_id": employee_id})
        print("MongoDB lookup result:", found)

        if not found:
            return jsonify({"message": "Invalid employee ID"}), 400

    otp = str(random.randint(100000, 999999))
    session['pending_user'] = {
        "username": username,
        "password": generate_password_hash(password),
        "role": role,
        "email": email,
        "otp": otp,
        "employee_id": employee_id if role == "admin" else None
    }

    try:
        msg = Message("Your OTP for HostelCare Registration",
                      sender=app.config['MAIL_USERNAME'],
                      recipients=[email])
        msg.body = f"Your OTP is {otp}"
        mail.send(msg)
        return jsonify({"message": "OTP sent to email"}), 200
    except Exception as e:
        print("Failed to send email:", e)
        return jsonify({"message": "Failed to send email", "error": str(e)}), 500


@app.route("/verify_otp", methods=["POST"])
def verify_otp():
    data = request.get_json()
    entered_otp = data.get("otp")
    pending_user = session.get("pending_user")

    if not pending_user:
        return jsonify({"message": "No pending registration"}), 400

    if pending_user["otp"] == entered_otp:
        user_data = {
            "username": pending_user["username"],
            "password": pending_user["password"],
            "role": pending_user["role"],
            "email": pending_user["email"]
        }
        if pending_user["role"] == "admin":
            user_data["employee_id"] = pending_user["employee_id"]
        users_collection.insert_one(user_data)
        session.pop("pending_user", None)
        return jsonify({"message": "Registration successful"}), 201
    else:
        return jsonify({"message": "Invalid OTP"}), 400


@app.route("/routes")
def show_routes():
    return jsonify([str(rule) for rule in app.url_map.iter_rules()])
@app.route("/test_mongo_insert")
def test_mongo_insert():
    try:
        users_collection.insert_one({"test_user": True})
        return "✅ Test insert successful"
    except Exception as e:
        return f"❌ Insert failed: {e}"


    
if __name__ == '__main__':
    app.run(debug=True, port=5500)
