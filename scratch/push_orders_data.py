import csv
import os
import urllib.parse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
env_path = Path(__file__).resolve().parent.parent / "backend" / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# Database Configuration
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "Nithin@12")
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
TARGET_DB = "sample_test"

# Directory paths
ORDERS_DIR = Path(__file__).resolve().parent / "orders"
RESTAURANTS_CSV = ORDERS_DIR / "restaurants.csv"
CUSTOMERS_CSV = ORDERS_DIR / "customers_medium.csv"
MENU_ITEMS_CSV = ORDERS_DIR / "menu_items.csv"
ORDERS_CSV = ORDERS_DIR / "orders_medium.csv"
ORDER_ITEMS_CSV = ORDERS_DIR / "order_items.csv"

# Encode password
encoded_password = urllib.parse.quote_plus(PG_PASSWORD)
MAINTENANCE_DB_URL = f"postgresql+psycopg2://{PG_USER}:{encoded_password}@{PG_HOST}:{PG_PORT}/postgres"
SAMPLE_TEST_DB_URL = f"postgresql+psycopg2://{PG_USER}:{encoded_password}@{PG_HOST}:{PG_PORT}/{TARGET_DB}"


def ensure_target_database():
    """Ensure the target database exists."""
    try:
        maintenance_engine = create_engine(MAINTENANCE_DB_URL, isolation_level="AUTOCOMMIT")
        with maintenance_engine.connect() as conn:
            check_db_sql = text("SELECT 1 FROM pg_database WHERE datname = :db_name;")
            exists = conn.execute(check_db_sql, {"db_name": TARGET_DB}).scalar()
            if not exists:
                print(f"[*] Database '{TARGET_DB}' does not exist. Creating it...")
                conn.execute(text(f'CREATE DATABASE "{TARGET_DB}";'))
                print(f"[+] Database '{TARGET_DB}' created successfully.")
    except Exception as e:
        print(f"[!] Warning checking/creating database '{TARGET_DB}': {e}")


def push_orders_dataset():
    ensure_target_database()
    print(f"[*] Connecting to database '{TARGET_DB}'...")
    engine = create_engine(SAMPLE_TEST_DB_URL, pool_pre_ping=True)

    with engine.connect() as conn:
        # 1. Drop existing tables
        print("[*] Dropping existing tables...")
        drop_tables_sql = """
        DROP TABLE IF EXISTS order_items CASCADE;
        DROP TABLE IF EXISTS orders CASCADE;
        DROP TABLE IF EXISTS menu_items CASCADE;
        DROP TABLE IF EXISTS products CASCADE;
        DROP TABLE IF EXISTS customers CASCADE;
        DROP TABLE IF EXISTS restaurants CASCADE;
        """
        conn.execute(text(drop_tables_sql))
        conn.commit()
        print("[+] Existing tables dropped.")

        # 2. Create tables
        print("[*] Creating new tables schema...")
        create_tables_sql = """
        CREATE TABLE restaurants (
            restaurant_id VARCHAR(50) PRIMARY KEY,
            cuisine VARCHAR(100),
            city VARCHAR(100),
            rating NUMERIC(3, 1)
        );

        CREATE TABLE customers (
            customer_id VARCHAR(50) PRIMARY KEY,
            city VARCHAR(100),
            signup_date DATE
        );

        CREATE TABLE menu_items (
            item_id VARCHAR(50) PRIMARY KEY,
            restaurant_id VARCHAR(50) REFERENCES restaurants(restaurant_id),
            price NUMERIC(10, 2)
        );

        CREATE TABLE orders (
            order_id VARCHAR(50) PRIMARY KEY,
            customer_id VARCHAR(50) REFERENCES customers(customer_id),
            restaurant_id VARCHAR(50) REFERENCES restaurants(restaurant_id),
            order_time TIMESTAMP,
            delivery_time TIMESTAMP,
            status VARCHAR(50)
        );

        CREATE TABLE order_items (
            order_id VARCHAR(50) REFERENCES orders(order_id),
            item_id VARCHAR(50) REFERENCES menu_items(item_id),
            quantity INTEGER,
            price NUMERIC(10, 2)
        );
        """
        conn.execute(text(create_tables_sql))
        conn.commit()
        print("[+] Tables created successfully.")

        # Helper functions
        def parse_int(v):
            return int(v.strip()) if v and v.strip() else None

        def parse_float(v):
            return float(v.strip()) if v and v.strip() else None

        def parse_str(v):
            return v.strip() if v and v.strip() else None

        def parse_date(v):
            if not v or not v.strip():
                return None
            val = v.strip()
            for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
                try:
                    return datetime.strptime(val, fmt).date()
                except ValueError:
                    pass
            return None

        def parse_timestamp(v):
            if not v or not v.strip():
                return None
            val = v.strip()
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y"):
                try:
                    return datetime.strptime(val, fmt)
                except ValueError:
                    pass
            return None

        # 3. Load Restaurants
        if RESTAURANTS_CSV.exists():
            print(f"[*] Loading restaurants from {RESTAURANTS_CSV.name}...")
            restaurant_records = []
            with open(RESTAURANTS_CSV, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    restaurant_records.append({
                        "restaurant_id": parse_str(row.get("restaurant_id")),
                        "cuisine": parse_str(row.get("cuisine")),
                        "city": parse_str(row.get("city")),
                        "rating": parse_float(row.get("rating")),
                    })

            insert_restaurants_sql = text("""
                INSERT INTO restaurants (restaurant_id, cuisine, city, rating)
                VALUES (:restaurant_id, :cuisine, :city, :rating);
            """)
            conn.execute(insert_restaurants_sql, restaurant_records)
            conn.commit()
            print(f"[+] Loaded {len(restaurant_records)} restaurants.")

        # 4. Load Customers
        if CUSTOMERS_CSV.exists():
            print(f"[*] Loading customers from {CUSTOMERS_CSV.name}...")
            customer_records = []
            with open(CUSTOMERS_CSV, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    customer_records.append({
                        "customer_id": parse_str(row.get("customer_id")),
                        "city": parse_str(row.get("city")),
                        "signup_date": parse_date(row.get("signup_date")),
                    })

            insert_customers_sql = text("""
                INSERT INTO customers (customer_id, city, signup_date)
                VALUES (:customer_id, :city, :signup_date);
            """)
            conn.execute(insert_customers_sql, customer_records)
            conn.commit()
            print(f"[+] Loaded {len(customer_records)} customers.")

        # 5. Load Menu Items
        if MENU_ITEMS_CSV.exists():
            print(f"[*] Loading menu_items from {MENU_ITEMS_CSV.name}...")
            menu_records = []
            with open(MENU_ITEMS_CSV, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    menu_records.append({
                        "item_id": parse_str(row.get("item_id")),
                        "restaurant_id": parse_str(row.get("restaurant_id")),
                        "price": parse_float(row.get("price")),
                    })

            insert_menu_sql = text("""
                INSERT INTO menu_items (item_id, restaurant_id, price)
                VALUES (:item_id, :restaurant_id, :price);
            """)
            conn.execute(insert_menu_sql, menu_records)
            conn.commit()
            print(f"[+] Loaded {len(menu_records)} menu items.")

        # 6. Load Orders
        if ORDERS_CSV.exists():
            print(f"[*] Loading orders from {ORDERS_CSV.name}...")
            order_records = []
            with open(ORDERS_CSV, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    order_records.append({
                        "order_id": parse_str(row.get("order_id")),
                        "customer_id": parse_str(row.get("customer_id")),
                        "restaurant_id": parse_str(row.get("restaurant_id")),
                        "order_time": parse_timestamp(row.get("order_time")),
                        "delivery_time": parse_timestamp(row.get("delivery_time")),
                        "status": parse_str(row.get("status")),
                    })

            insert_orders_sql = text("""
                INSERT INTO orders (order_id, customer_id, restaurant_id, order_time, delivery_time, status)
                VALUES (:order_id, :customer_id, :restaurant_id, :order_time, :delivery_time, :status);
            """)
            conn.execute(insert_orders_sql, order_records)
            conn.commit()
            print(f"[+] Loaded {len(order_records)} orders.")

        # 7. Load Order Items
        if ORDER_ITEMS_CSV.exists():
            print(f"[*] Loading order_items from {ORDER_ITEMS_CSV.name}...")
            order_item_records = []
            with open(ORDER_ITEMS_CSV, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    order_item_records.append({
                        "order_id": parse_str(row.get("order_id")),
                        "item_id": parse_str(row.get("item_id")),
                        "quantity": parse_int(row.get("quantity")),
                        "price": parse_float(row.get("price")),
                    })

            insert_order_items_sql = text("""
                INSERT INTO order_items (order_id, item_id, quantity, price)
                VALUES (:order_id, :item_id, :quantity, :price);
            """)
            conn.execute(insert_order_items_sql, order_item_records)
            conn.commit()
            print(f"[+] Loaded {len(order_item_records)} order items.")

        # 8. Verification Summary
        print("\n==================================================")
        print("  Database 'sample_test' Setup Complete!         ")
        print("==================================================")
        for tbl in ["restaurants", "customers", "menu_items", "orders", "order_items"]:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {tbl};")).scalar()
            print(f"  • {tbl}: {count} rows")


if __name__ == "__main__":
    push_orders_dataset()
