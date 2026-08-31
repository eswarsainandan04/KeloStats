import os
import csv
import urllib.parse
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from pathlib import Path
from sqlalchemy import create_engine, text

# Configuration
PG_USER = "postgres"
PG_PASSWORD = "Nithin@12"
PG_HOST = "localhost"
PG_PORT = 5432
TARGET_DB = "sample_test"
CSV_FILE_PATH = Path(__file__).resolve().parent / "Salary Data.csv"

# Encode password to handle special characters like '@'
encoded_password = urllib.parse.quote_plus(PG_PASSWORD)

# Connection URLs
SAMPLE_TEST_DB_URL = f"postgresql+psycopg2://{PG_USER}:{encoded_password}@{PG_HOST}:{PG_PORT}/{TARGET_DB}"


def create_database_if_not_exists():
    """Connects to the default postgres database and creates sample_test if missing."""
    print(f"[*] Checking if database '{TARGET_DB}' exists...")
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            user=PG_USER,
            password=PG_PASSWORD,
            host=PG_HOST,
            port=PG_PORT
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        cur.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{TARGET_DB}'")
        exists = cur.fetchone()

        if not exists:
            cur.execute(f'CREATE DATABASE "{TARGET_DB}"')
            print(f"[+] Database '{TARGET_DB}' created successfully!")
        else:
            print(f"[+] Database '{TARGET_DB}' already exists.")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"[-] Error checking/creating database: {e}")
        raise


def create_table_and_push_csv():
    """Creates the salary_data table and pushes records from the CSV file."""
    if not CSV_FILE_PATH.exists():
        raise FileNotFoundError(f"CSV file not found at: {CSV_FILE_PATH}")

    print(f"[*] Connecting to database '{TARGET_DB}'...")
    engine = create_engine(SAMPLE_TEST_DB_URL, pool_pre_ping=True)

    create_table_sql = """
    CREATE TABLE IF NOT EXISTS salary_data (
        id SERIAL PRIMARY KEY,
        age INTEGER,
        gender VARCHAR(50),
        education_level VARCHAR(100),
        job_title VARCHAR(255),
        years_of_experience NUMERIC(5, 2),
        salary NUMERIC(12, 2)
    );
    """

    insert_sql = text("""
    INSERT INTO salary_data (
        age, gender, education_level, job_title, years_of_experience, salary
    ) VALUES (
        :age, :gender, :education_level, :job_title, :years_of_experience, :salary
    );
    """)

    with engine.connect() as conn:
        # 1. Create table
        conn.execute(text(create_table_sql))
        conn.commit()
        print("[+] Table 'salary_data' ready.")

        # 2. Read and parse CSV
        records = []
        with open(CSV_FILE_PATH, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Helper for safe numerical parsing
                def safe_int(val):
                    try:
                        return int(float(val.strip())) if val and val.strip() else None
                    except ValueError:
                        return None

                def safe_float(val):
                    try:
                        return float(val.strip()) if val and val.strip() else None
                    except ValueError:
                        return None

                def safe_str(val):
                    return val.strip() if val and val.strip() else None

                records.append({
                    "age": safe_int(row.get("Age")),
                    "gender": safe_str(row.get("Gender")),
                    "education_level": safe_str(row.get("Education Level")),
                    "job_title": safe_str(row.get("Job Title")),
                    "years_of_experience": safe_float(row.get("Years of Experience")),
                    "salary": safe_float(row.get("Salary")),
                })

        # 3. Batch insert records
        if records:
            conn.execute(insert_sql, records)
            conn.commit()
            print(f"[+] Successfully inserted {len(records)} rows into 'salary_data' table!")

        # 4. Verify count
        total_rows = conn.execute(text("SELECT COUNT(*) FROM salary_data;")).scalar()
        print(f"[✓] Verification: Total rows currently in 'salary_data': {total_rows}")


if __name__ == "__main__":
    print("==================================================")
    print("  Pushing 'Salary Data.csv' to PostgreSQL DB      ")
    print("==================================================")
    create_database_if_not_exists()
    create_table_and_push_csv()
