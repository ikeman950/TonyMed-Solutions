from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta  # One line for both
from sqlalchemy import func 
from flask import send_from_directory
from werkzeug.utils import secure_filename
import webbrowser
from threading import Timer
import sys
import os
import time
from datetime import datetime




# Create the app
app = Flask(__name__)

# IMPORTANT: Force instance_path to writable location on Vercel
app.instance_path = '/tmp'  # ← This line fixes the error


app.config['SECRET_KEY'] = 'ghana_my_pharmacy_2025_super_secure_key_!@#456'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pharmacy.db'  # Vercel creates it
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Connect SQLAlchemy to our app
db = SQLAlchemy(app)


from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlite3 import dbapi2 as sqlite

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")  # Better for concurrent access
    cursor.execute("PRAGMA busy_timeout = 5000")  # Wait 5 seconds if locked
    cursor.close()


@app.context_processor
def inject_settings():
    setting = Settings.query.first()
    if not setting:
        setting = Settings()  # fallback
    logo_url = setting.logo_url if setting.logo_url else None
    return dict(
        setting=setting,
        LOGO_URL=logo_url,
        PHARMACY_NAME=setting.pharmacy_name,
        PHARMACY_PHONE=setting.pharmacy_phone,
        PHARMACY_LOCATION=setting.pharmacy_location,
        CURRENCY_SYMBOL=setting.currency_symbol,
        LOW_STOCK_THRESHOLD=setting.low_stock_threshold
    )


# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Please log in to access the system."
login_manager.login_message_category = "info"

# Auto-create tables on first request (Vercel safe)
@app.before_request
def ensure_tables():
    if not hasattr(app, 'tables_created'):
        with app.app_context():
            db.create_all()
            app.tables_created = True  # Only run once per deployment
            print("Tables created on first request!")

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# Custom filter to calculate days between expiry and today
@app.template_filter('date_diff')
def date_diff(expiry_str, today_str):
    if not expiry_str:
        return None
    try:
        expiry = datetime.strptime(expiry_str, "%Y-%m-%d")
        today = datetime.strptime(today_str, "%Y-%m-%d")
        delta = expiry - today
        return delta.days
    except:
        return None

# Define the Medicine model (this creates a table in the database)
class Medicine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    batch = db.Column(db.String(50))
    expiry = db.Column(db.String(20))  # Format: YYYY-MM-DD
    quantity = db.Column(db.Integer, nullable=False)
    buy_price = db.Column(db.Float, nullable=False)
    sell_price = db.Column(db.Float, nullable=False)

    # New model for Sales records
class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    customer_name = db.Column(db.String(100), nullable=True)
    customer_phone = db.Column(db.String(20), nullable=True)
    
    # Relationship to sale items (we'll add items next)

class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'))
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicine.id'))
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)  # Sell price at time of sale
    subtotal = db.Column(db.Float, nullable=False)


class Expenditure(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), nullable=False)  # YYYY-MM-DD
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)


class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pharmacy_name = db.Column(db.String(200), default="My Pharmacy")
    pharmacy_phone = db.Column(db.String(50), default="")
    pharmacy_location = db.Column(db.String(200), default="")
    currency_symbol = db.Column(db.String(10), default="GH₵")
    low_stock_threshold = db.Column(db.Integer, default=10)
    logo_url = db.Column(db.String(500), default="")  # URL instead of filename


# User model for login
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)  # Hashed password
    is_owner = db.Column(db.Boolean, default=False)  # NEW: Marks the main owner

    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)




    def __repr__(self):
        return f"<Medicine {self.name}>"

# Home page
@app.route('/')
def index():
    # If user is already logged in → straight to dashboard/home
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    # Otherwise → always show login page (default landing page)
    # Even for brand new users — they will see the "Sign up" link
    return redirect(url_for('login'))

@app.route('/home')
@login_required
def home():
    return render_template('home.html')

@app.route('/inventory')
@login_required
def inventory():
    medicines = Medicine.query.all()
    today = datetime.now().strftime("%Y-%m-%d")
    
     # Calculate real stock value (quantity × price)
    total_buy = sum((med.quantity or 0) * (med.buy_price or 0) for med in medicines)
    total_sell = sum((med.quantity or 0) * (med.sell_price or 0) for med in medicines)
    total_profit = total_sell - total_buy

    # Get low stock threshold from Settings
    setting = Settings.query.first()
    low_threshold = setting.low_stock_threshold if setting else 10
    
    return render_template('inventory.html', 
                           medicines=medicines, 
                           today=today,
                           low_threshold=low_threshold,
                           total_buy=total_buy,
                           total_sell=total_sell,
                           total_profit=total_profit)



# Add medicine page
@app.route('/add_medicine', methods=['GET', 'POST'])
@login_required
def add_medicine():
    if request.method == 'POST':
        name = request.form['name'].strip().lower()  # Lowercase for comparison
        
        # Check if medicine with same name already exists
        existing = Medicine.query.filter(func.lower(Medicine.name) == name).first()
        if existing:
            flash(f'Medicine "{request.form["name"]}" already exists in inventory!', 'danger')
            return render_template('add_medicine.html')
        
        # Create new medicine if no duplicate
        new_med = Medicine(
            name=request.form['name'].strip(),
            batch=request.form['batch'].strip(),
            expiry=request.form['expiry'] or None,
            quantity=int(request.form['quantity']),
            buy_price=float(request.form['buy_price']),
            sell_price=float(request.form['sell_price'])
        )
        db.session.add(new_med)
        db.session.commit()
        flash('Medicine added successfully!', 'success')
        return redirect(url_for('inventory'))
    
    return render_template('add_medicine.html')




    # Edit medicine
@app.route('/edit_medicine/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_medicine(id):
    medicine = Medicine.query.get_or_404(id)
    
    if request.method == 'POST':
        new_name = request.form['name'].strip()
        
        # Check if another medicine has the same name (ignore case and current medicine)
        duplicate = Medicine.query.filter(
            func.lower(Medicine.name) == new_name.lower(),
            Medicine.id != medicine.id  # Exclude current medicine
        ).first()
        
        if duplicate:
            flash(f'Medicine "{new_name}" already exists in inventory!', 'danger')
            return render_template('edit_medicine.html', medicine=medicine)
        
        # Update fields if no duplicate
        medicine.name = new_name
        medicine.batch = request.form['batch'].strip()
        medicine.expiry = request.form['expiry'] or None
        medicine.quantity = int(request.form['quantity'])
        medicine.buy_price = float(request.form['buy_price'])
        medicine.sell_price = float(request.form['sell_price'])
        
        db.session.commit()
        flash('Medicine updated successfully!', 'success')
        return redirect(url_for('inventory'))
    
    return render_template('edit_medicine.html', medicine=medicine)




# Delete medicine
@app.route('/delete_medicine/<int:id>')
@login_required
def delete_medicine(id):
    medicine = Medicine.query.get_or_404(id)
    db.session.delete(medicine)
    db.session.commit()
    flash('Medicine deleted successfully!', 'danger')
    return redirect(url_for('inventory'))




# Sales page
@app.route('/sales', methods=['GET', 'POST'])
@login_required
def sales():
    if request.method == 'POST':
        if 'add_to_cart' in request.form:
            med_id = int(request.form['medicine_id'])
            qty_sold = int(request.form['quantity'])
            
            medicine = Medicine.query.get_or_404(med_id)
            
            # Extra safety: block expired medicines
            today = datetime.now().strftime("%Y-%m-%d")
            if medicine.expiry and medicine.expiry < today:
                flash(f'Cannot sell {medicine.name} — it is EXPIRED!', 'danger')
                return redirect(url_for('sales'))
            
            if qty_sold > medicine.quantity:
                flash(f'Not enough stock! Only {medicine.quantity} available.', 'danger')
                return redirect(url_for('sales'))
            
            # Add to cart
            item = {
                'id': medicine.id,
                'name': medicine.name,
                'qty': qty_sold,
                'price': medicine.sell_price,
                'subtotal': qty_sold * medicine.sell_price
            }
            if 'cart' not in session:
                session['cart'] = []
            session['cart'].append(item)
            session.modified = True
            flash(f'{medicine.name} x{qty_sold} added to cart!', 'success')
            return redirect(url_for('sales'))
        
        elif 'complete_sale' in request.form:
            if 'cart' not in session or not session['cart']:
                flash('Cart is empty!', 'danger')
                return redirect(url_for('sales'))
            
            cart = session['cart']
            total = sum(item['subtotal'] for item in cart)
            
            # Get customer info
            customer_name = request.form.get('customer_name', '').strip() 
            customer_phone = request.form.get('customer_phone', '').strip()
            if customer_phone and not customer_phone.startswith(('020','024','025','026','027','050','053','054','055','059')):
                customer_phone = None  # Invalid Ghana number
            
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Create sale record
            new_sale = Sale(
                date=today,
                total_amount=total,
                customer_name=customer_name or None,
                customer_phone=customer_phone or None
            )
            db.session.add(new_sale)
            db.session.flush()  # To get new_sale.id
            
            # Process items
            for item in cart:
                medicine = Medicine.query.get(item['id'])
                medicine.quantity -= item['qty']
                
                sale_item = SaleItem(
                    sale_id=new_sale.id,
                    medicine_id=item['id'],
                    quantity=item['qty'],
                    price=item['price'],
                    subtotal=item['subtotal']
                )
                db.session.add(sale_item)
            
            db.session.commit()
            
            # Clear cart and show receipt
            session.pop('cart', None)
            flash('Sale completed successfully!', 'success')
            
            return render_template('receipt.html',
                                   cart=cart,
                                   total=total,
                                   date=today,
                                   sale_id=new_sale.id,
                                   customer_name=customer_name or '',
                                   customer_phone=customer_phone or '')
    # GET request - load page
    cart = session.get('cart', [])
    total = sum(item['subtotal'] for item in cart)
    
    today = datetime.now().strftime("%Y-%m-%d")
    medicines = Medicine.query.filter(Medicine.quantity > 0).all()
    
    # Filter out expired medicines
    available_medicines = []
    for med in medicines:
        if med.expiry is None or med.expiry >= today:
            available_medicines.append(med)
    
    return render_template('sales.html', 
                           medicines=available_medicines, 
                           cart=cart, 
                           total=total)




@app.route('/reports', methods=['GET', 'POST'])
@login_required
def reports():
    # Default dates: last 30 days
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    if request.method == 'POST':
        start_date = request.form.get('start_date', start_date)
        end_date = request.form.get('end_date', end_date)
    
    # Get sales in date range
    sales = Sale.query.filter(Sale.date >= start_date, Sale.date <= end_date).order_by(Sale.date.desc()).all()
    
    # Calculate total earnings
    period_total = sum(sale.total_amount for sale in sales)
    
    # Get sale items with needed fields
    sale_items = (
      db.session.query(
        SaleItem.id,
        SaleItem.sale_id,
        SaleItem.medicine_id,
        SaleItem.quantity,
        SaleItem.price,
        SaleItem.subtotal,
        Sale.date.label('sale_date')
      )
       .join(Sale)
       .filter(Sale.date >= start_date, Sale.date <= end_date)
       .order_by(Sale.date.desc())
       .all()
    )
    
    # Medicine lookup
    all_medicines = Medicine.query.all()
    medicine_dict = {med.id: med.name for med in all_medicines}
    
    return render_template('reports.html',
                          sales=sales,
                          sale_items=sale_items,
                          period_total=period_total,
                          start_date=start_date,
                          end_date=end_date,
                          medicine_dict=medicine_dict)


@app.route('/expired_report')
@login_required
def expired_report():
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Get all medicines
    all_medicines = Medicine.query.all()
    
    # Filter: expired OR expiring within 30 days
    expired_medicines = []
    near_expiry_medicines = []
    
    for med in all_medicines:
        if not med.expiry:
            continue  # Skip if no expiry date
        
        try:
            expiry_date = datetime.strptime(med.expiry, "%Y-%m-%d")
            days_left = (expiry_date - datetime.now()).days
            
            if days_left < 0:
                med.status = "Expired"
                med.days_info = f"{abs(days_left)} days ago"
                expired_medicines.append(med)
            elif days_left <= 30:
                med.status = "Expiring Soon"
                med.days_info = f"{days_left} days left"
                near_expiry_medicines.append(med)
        except:
            continue  # Skip invalid dates
    
    # Combine: expired first, then near expiry
    critical_medicines = expired_medicines + near_expiry_medicines
    
    return render_template('expired_report.html',
                          critical_medicines=critical_medicines,
                          today=today,
                          expired_count=len(expired_medicines),
                          near_count=len(near_expiry_medicines))


@app.route('/login', methods=['GET', 'POST'])
def login():
    # If no users exist, go to setup
    if not User.query.first():
        return redirect(url_for('setup'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Logged in successfully! Welcome back.', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password. Try again.', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))



@app.route('/users')
@login_required
def users():
    # Only the pharmacy owner can access user management
    if not current_user.is_owner:
        flash('Only the pharmacy owner can access user management!', 'danger')
        return redirect(url_for('home'))
    
    all_users = User.query.all()
    return render_template('users.html', users=all_users)



@app.route('/add_user', methods=['GET', 'POST'])
@login_required
def add_user():
    # Only the pharmacy owner can add new staff
    if not current_user.is_owner:
        flash('Only the pharmacy owner can add new staff users!', 'danger')
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        # Validation
        if not username:
            flash('Username is required!', 'danger')
        elif User.query.filter_by(username=username).first():
            flash(f'Username "{username}" already exists!', 'danger')
        elif len(password) < 6:
            flash('Password must be at least 6 characters long!', 'danger')
        else:
            hashed_pw = generate_password_hash(password)
            new_user = User(username=username, password=hashed_pw)
            db.session.add(new_user)
            db.session.commit()
            flash(f'Staff user "{username}" added successfully!', 'success')
            return redirect(url_for('users'))
    
    return render_template('add_user.html')

@app.route('/delete_user/<int:id>')
@login_required
def delete_user(id):
    if not current_user.is_owner:
        flash('Only admin can delete users!', 'danger')
        return redirect(url_for('home'))
    
    user_to_delete = User.query.get_or_404(id)
    if user_to_delete.username == 'admin':
        flash('Cannot delete the main admin!', 'danger')
        return redirect(url_for('users'))
    
    db.session.delete(user_to_delete)
    db.session.commit()
    flash(f'User {user_to_delete.username} deleted.', 'info')
    return redirect(url_for('users'))


@app.route('/low_stock_report')
@login_required
def low_stock_report():
    setting = Settings.query.first()
    threshold = setting.low_stock_threshold if setting else 10
    
    low_stock_medicines = Medicine.query.filter(Medicine.quantity < threshold).order_by(Medicine.quantity).all()
    
    return render_template('low_stock_report.html',
                           medicines=low_stock_medicines,
                           threshold=threshold,
                           count=len(low_stock_medicines))


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if User.query.count() > 0:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        if len(password) < 6:
            flash('Password must be at least 6 characters', 'danger')
            return render_template('setup.html')
        
        hashed_pw = generate_password_hash(password)
        owner_user = User(
            username=username,
            password=hashed_pw,
            is_owner=True  # Permanent owner
        )
        db.session.add(owner_user)
        db.session.commit()
        
        # AUTO-LOGIN after setup (like Facebook/X)
        login_user(owner_user)
        
        flash(f'Welcome {username}! Your pharmacy system is ready. You have full owner rights.', 'success')
        return redirect(url_for('home'))
    
    return render_template('setup.html')


@app.route('/add_expenditure', methods=['GET', 'POST'])
@login_required
def add_expenditure():
    if request.method == 'POST':
        date = request.form['date']
        description = request.form['description'].strip()
        amount = float(request.form['amount'])
        
        new_exp = Expenditure(date=date, description=description, amount=amount)
        db.session.add(new_exp)
        db.session.commit()
        flash('Expenditure added successfully!', 'success')
        return redirect(url_for('expenditures'))
    
    # Pass today's date to template
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template('add_expenditure.html', today=today)


@app.route('/expenditures')
@login_required
def expenditures():
    # Get all expenditures ordered by date
    all_exp = Expenditure.query.order_by(Expenditure.date.desc()).all()
    
    # Calculate total
    total_exp = sum(exp.amount for exp in all_exp)
    
    return render_template('expenditures.html',
                           expenditures=all_exp,
                           total=total_exp)



@app.route('/monthly_report')
@login_required
def monthly_report():
    # Get all sales grouped by month
    sales_by_month = db.session.query(
        func.strftime('%Y-%m', Sale.date).label('month'),
        func.sum(Sale.total_amount).label('sales')
    ).group_by('month').order_by('month').all()
    
    # Get all expenditure grouped by month
    exp_by_month = db.session.query(
        func.strftime('%Y-%m', Expenditure.date).label('month'),
        func.sum(Expenditure.amount).label('expenditure')
    ).group_by('month').order_by('month').all()
    
    # Combine into dictionary for easy lookup
    sales_dict = {row.month: row.sales or 0 for row in sales_by_month}
    exp_dict = {row.month: row.expenditure or 0 for row in exp_by_month}
    
    # Get all months from both
    all_months = sorted(set(sales_dict.keys()) | set(exp_dict.keys()))
    
    # Build report data
    report = []
    grand_sales = 0
    grand_exp = 0
    grand_profit = 0
    
    for month in all_months:
        sales = sales_dict.get(month, 0)
        expenditure = exp_dict.get(month, 0)
        profit = sales - expenditure
        
        report.append({
            'month': month,
            'sales': sales,
            'expenditure': expenditure,
            'profit': profit
        })
        
        grand_sales += sales
        grand_exp += expenditure
        grand_profit += profit
    
    return render_template('monthly_report.html',
                           report=report,
                           grand_sales=grand_sales,
                           grand_exp=grand_exp,
                           grand_profit=grand_profit)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if not current_user.is_owner:
        flash('Only the pharmacy owner can access settings!', 'danger')
        return redirect(url_for('home'))
    
    # Get or create the single settings record (fallback if missing)
    setting = Settings.query.first()
    if not setting:
        setting = Settings()
        db.session.add(setting)
        db.session.commit()
    
    if request.method == 'POST':
        # Update text fields with proper stripping
        setting.pharmacy_name = request.form.get('pharmacy_name', '').strip()
        setting.pharmacy_phone = request.form.get('pharmacy_phone', '').strip()
        setting.pharmacy_location = request.form.get('pharmacy_location', '').strip()
        setting.currency_symbol = request.form.get('currency_symbol', 'GH₵').strip()
        
        # Safe integer conversion for threshold
        try:
            threshold_input = request.form.get('low_stock_threshold', '10').strip()
            setting.low_stock_threshold = int(threshold_input)
            if setting.low_stock_threshold < 1:
                setting.low_stock_threshold = 1  # Minimum 1
        except ValueError:
            setting.low_stock_threshold = 10  # Fallback
        
        # Logo URL validation (must start with http/https)
        logo_url_input = request.form.get('logo_url', '').strip()
        if logo_url_input and (logo_url_input.startswith('http://') or logo_url_input.startswith('https://')):
            setting.logo_url = logo_url_input
        else:
            setting.logo_url = ""  # Clear if invalid
        
        db.session.commit()
        flash('Settings saved successfully!', 'success')
        return redirect(url_for('settings'))
    
    # Prepare current logo URL for preview
    current_logo_url = setting.logo_url if setting.logo_url else None
    
    return render_template('settings.html', 
                           setting=setting, 
                           current_logo_url=current_logo_url)
    



@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pw = request.form['current_password']
        new_pw = request.form['new_password']
        confirm_pw = request.form['confirm_password']
        
        # Check current password
        if not check_password_hash(current_user.password, current_pw):
            flash('Current password is incorrect!', 'danger')
            return render_template('change_password.html')
        
        if new_pw != confirm_pw:
            flash('New passwords do not match!', 'danger')
            return render_template('change_password.html')
        
        if len(new_pw) < 6:
            flash('New password must be at least 6 characters!', 'danger')
            return render_template('change_password.html')
        
        # Update password
        current_user.password = generate_password_hash(new_pw)
        db.session.commit()  # ← This line is critical!
        
        flash('Password changed successfully! Please log in again.', 'success')
        logout_user()  # Force re-login with new password
        return redirect(url_for('login'))
    
    return render_template('change_password.html')





def open_browser():
    try:
        url = 'http://127.0.0.1:5000'
        if sys.platform.startswith('win'):
            # Most reliable in Windows .exe
            import os
            os.startfile(url)
        elif sys.platform.startswith('darwin'):
            os.system(f'open {url}')
        else:
            webbrowser.open_new(url)
    except Exception as e:
        print(f"Browser open failed: {e}")
        print("Open http://127.0.0.1:5000 manually")


@app.errorhandler(500)
def internal_error(error):
    return "Server error — check logs or contact support", 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("Database tables ready!")

    
    # Open browser after 3 seconds (gives time for server + backup)
    Timer(3, open_browser).start()
    
    # Run the app
    app.run(port=5000, debug=False, use_reloader=False)

